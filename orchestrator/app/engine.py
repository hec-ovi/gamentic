"""The turn loop: a bounded multi-actor event loop over one model, many contexts.

One POST = one fully-resolved turn:
  1. record the player's action (tagged segments: say / do / attack / give)
  2. apply the player's DIRECTED actions (attack/give) -> may queue a target to react
  3. narrator call (world/scene + tools): narration, state changes, cues, spawn/kill
  4. process an ACTOR QUEUE (cued + targeted characters), each with its own POV + tools;
     a character's directed action (attack/give) queues ITS target to react -> cascade,
     bounded by a step cap and a per-character cap for pacing
  5. return new beats + updated state

Directed actions route deterministically to the targeted agent, so the narrator never has
to (and shouldn't) speak for characters.
"""
import json
import re
from collections import deque

from . import db, repo, prompts, tools, llm
from .config import settings

_CHAR_TAG = re.compile(r"\[(say|do)\]", re.I)
_CHAR_CLOSE = re.compile(r"\[/?(?:say|do)\]", re.I)
# Hygiene for small-model artifacts seen live: a pseudo tool call leaked as text
# ("[attack{amount:10,target: \"player\"}]") and stray tag debris ("*]", trailing "*").
_PSEUDO_TOOL = re.compile(r"\[\w+\s*\{[^\[\]]*\}\s*\]?")
_TAG_DEBRIS = re.compile(r"(\*+\]|\[+\*+|[\[\]*]+$)")
# Tool-call shapes leaked AS PROSE (live: the model occasionally printed call syntax like
# move_location("the docks") instead of calling the tool). Any line carrying a known tool
# name followed by ( or { is junk, as is a bare JSON-object line or a fenced code block.
_TOOL_NAMES = sorted({t["function"]["name"] for t in tools.NARRATOR_TOOLS + tools.CHARACTER_TOOLS}
                     | {"reject_attempt", "submit_segments", "save_world"})
_TOOL_CALL = re.compile(r"\b(?:%s)\s*[({]" % "|".join(_TOOL_NAMES))
_JSON_LINE = re.compile(r"^\s*[\[{].*[\]}]\s*,?\s*$")
_FENCE = re.compile(r"```.*?(?:```|$)", re.S)


def trim_to_sentence(text: str) -> str:
    """A generation that hit the token ceiling ends mid-word (live: 'we do not linger
    for <'); cut back to the last completed sentence so truncation is never visible."""
    cut = max(text.rfind(p) for p in (". ", "! ", "? ", ".\n", "!\n", "?\n"))
    last = max(text.rfind(p) for p in (".", "!", "?", "…"))
    if last == len(text) - 1:
        return text                      # already ends cleanly
    return text[: cut + 1].rstrip() if cut > 0 else text


def clean_prose(text: str) -> str:
    """Scrub model leakage from prose shown to the player: fenced code blocks, bare JSON
    lines, lines written in tool-call syntax, and inline pseudo tool calls."""
    text = _FENCE.sub("", text or "")
    lines = [ln for ln in text.splitlines()
             if not _TOOL_CALL.search(ln) and not _JSON_LINE.match(ln)]
    text = _PSEUDO_TOOL.sub("", "\n".join(lines))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _clean_segment(text: str) -> str:
    text = _PSEUDO_TOOL.sub("", text)
    text = "\n".join(ln for ln in text.splitlines() if not _TOOL_CALL.search(ln))
    text = _TAG_DEBRIS.sub("", text)
    return text.strip()


def _unquote(text: str) -> str:
    """Strip WRAPPING quotation marks from a speech segment: the model writes
    [say]"Far enough."[/say], but a dialogue bubble supplies its own framing, so the
    quotes read as artifacts on screen. Partial/inner quotes are left alone."""
    if len(text) >= 2 and text[0] in '"“' and text[-1] in '"”':
        return text[1:-1].strip()
    return text


# Maya1 emotion vocabulary (natives + the aliases the voice-api maps itself). A speech
# segment may OPEN with one tag; it becomes the beat's base tone for the voice and is
# stripped from the display text. Unknown leading tags are scrubbed as artifacts.
EMOTIONS = {"laugh", "giggle", "chuckle", "sigh", "whisper", "angry", "gasp", "cry",
            "scream", "excited", "sad", "shout", "yell", "sob", "happy", "scared",
            "furious", "calm", "nervous", "tired"}
_EMOTION_TAG = re.compile(r"^\[(\w+)\]\s*")
_ANY_TAG = re.compile(r"\[\w+\]\s*")


def _extract_emotion(text: str) -> tuple[str, str]:
    """(emotion, clean_text): a leading known [tag] becomes the line's tone; remaining
    bracketed single-word tags anywhere are scrubbed so they never show on screen."""
    emotion = ""
    m = _EMOTION_TAG.match(text)
    while m and m.group(1).lower() in EMOTIONS:
        emotion = emotion or m.group(1).lower()   # first tag wins; extras are scrubbed
        text = text[m.end():]
        m = _EMOTION_TAG.match(text)
    return emotion, _ANY_TAG.sub("", text).strip()


def _reclassify_do(content: str) -> tuple[str, str, str]:
    """A 'do' segment that is emotion tags + a fully quoted span IS speech the model
    mis-tagged (live: [do][sigh] [whisper] "Do not waste your breath..."[/do] rendered
    as an italic action, tags visible, never voiced). Judged by SHAPE, not wording."""
    emotion, cleaned = _extract_emotion(content)
    if len(cleaned) >= 2 and cleaned[0] in '"“' and cleaned[-1] in '"”':
        return "say", _unquote(cleaned), emotion
    return "do", cleaned, ""   # genuine action: tags scrubbed, no tone (actions aren't spoken)


def parse_character_output(text: str) -> list[tuple[str, str, str]]:
    """Split a character's tagged reply into (kind, content, emotion) where kind is
    'say' or 'do'. [say]...[/say] -> speech (dialogue beat); [do]...[/do] -> action.
    A speech segment may OPEN with a Maya1 emotion tag ([angry] You dare?), extracted
    into the beat's tone for the voice and stripped from the display text.
    Tolerant: untagged text is treated as speech; text before the first tag as action."""
    text = (text or "").strip()
    if not text:
        return []
    matches = list(_CHAR_TAG.finditer(text))
    if not matches:
        emotion, cleaned = _extract_emotion(_unquote(_clean_segment(text)))
        return [("say", cleaned, emotion)] if cleaned else []
    segs: list[tuple[str, str, str]] = []
    lead = _clean_segment(text[: matches[0].start()])
    if lead:
        segs.append(_reclassify_do(lead))
    for i, m in enumerate(matches):
        kind = m.group(1).lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = _clean_segment(_CHAR_CLOSE.sub("", text[start:end]))
        emotion = ""
        if kind == "say":
            # the tag may sit inside or outside the quotes: unquote, extract, unquote
            content = _unquote(content)
            emotion, content = _extract_emotion(content)
            content = _unquote(content)
            # the model sometimes writes stage directions as a leading (parenthetical)
            # inside the speech (live: '(She looks at the stone...) "A whetstone..."');
            # those are ACTIONS: split them into their own do beat so they are never
            # spoken aloud or shown inside a speech bubble
            while content.startswith("(") and ")" in content:
                inner, _, rest = content[1:].partition(")")
                if inner.strip():
                    segs.append(("do", inner.strip(), ""))
                content = _unquote(rest.strip())
        elif kind == "do":
            kind, content, emotion = _reclassify_do(content)
        if content:
            segs.append((kind, content, emotion))
    return segs


def _display(s: dict, key: str) -> str:
    """The human name for an id carried by this segment's entity chips (refs). Chips send
    {kind, id, name}, so the readable action text never leaks raw ids to the model/player."""
    for r in s.get("refs") or []:
        if r.get("id") and r["id"] == key and r.get("name"):
            return r["name"]
    return key


def _compose(segments) -> tuple[str, list[dict]]:
    """Render tagged segments into a readable action string + the directed actions to apply."""
    parts, directed = [], []
    for s in segments:
        t = (s.get("type") or "do").lower()
        text = (s.get("text") or "").strip()
        target = (s.get("target") or "").strip()
        item = (s.get("item") or "").strip()
        if t == "say":
            # A character chip inside the text IS the addressing: tagging someone in a say
            # directs the line at them even without an explicit target.
            if not target:
                chip = next((r for r in s.get("refs") or []
                             if (r.get("kind") or "") == "character" and (r.get("id") or r.get("name"))),
                            None)
                if chip:
                    target = chip.get("id") or chip.get("name")
            parts.append(f'you say "{text}"' + (f" to {_display(s, target)}" if target else ""))
            if target:
                directed.append({"tool": "_address", "args": {"target": target}})
        elif t == "attack":
            parts.append(f"you attack {_display(s, target) if target else 'them'}")
            directed.append({"tool": "attack", "args": {"target": target, "amount": s.get("amount")},
                             "display": {"target": _display(s, target) if target else "them"}})
        elif t == "give":
            parts.append(f"you give {_display(s, item)} to {_display(s, target) if target else 'them'}")
            directed.append({"tool": "give_item", "args": {"item": item, "target": target},
                             "display": {"item": _display(s, item),
                                         "target": _display(s, target) if target else "them"}})
        elif t == "look":
            # a look IS a story action (it can trigger reactions and discoveries), not
            # just an image request; the narrator decides whether the view earns a picture
            if text:
                low = text.lower()
                pre = "" if low.startswith(("at ", "for ", "around", "toward", "into ",
                                            "behind ", "under ", "where ", "out ")) else "at "
                parts.append(f"you look {pre}{text}")
            else:
                parts.append("you look around")
        else:  # do
            parts.append(text or "you wait")
    return "; ".join(p for p in parts if p), directed


def _why_impossible(conn, gid, d) -> str | None:
    """Deterministic pre-check of a mechanical attempt (attack/give). Returns a friendly,
    in-world reason when the attempt is impossible against current state, else None.
    Impossible attempts never reach the world (and the narrator is told they failed),
    so prose can never claim a transfer or a hit that state forbids."""
    args, disp = d["args"], d.get("display", {})
    t_disp = disp.get("target") or args.get("target") or "them"
    kind_t, row = repo.resolve_target(conn, gid, args.get("target") or "")
    if d["tool"] == "attack" and kind_t is None:
        return f"There is no {t_disp} here."
    if kind_t == "character" and row:
        here = repo.get_player(conn, gid)["location"]
        if not row["alive"]:
            return f"{row['name']} is already down."
        if not row["present"] or row["location"] != here:
            return f"{row['name']} is not here."
    if d["tool"] == "give_item":
        if kind_t is None:
            return f"There is no {t_disp} here."
        if not repo.player_has_item(conn, gid, args.get("item") or ""):
            return f"You don't have {disp.get('item') or args.get('item') or 'that'}."
    return None


def _character_reply(conn, gid, ch, emit, private_with=None):
    """Run one character turn (POV + tools). Returns the reaction targets to enqueue.
    Each character agent has its OWN context; its prompt size feeds ONLY its own meter
    (state.characters[].context). The global meter tracks the narrator's story context,
    so small character calls never make the global number bounce around."""
    segs: list[tuple[str, str]] = []
    creply = llm.LLMReply(content="")
    for _ in range(2):
        # one retry: a character occasionally returns nothing usable (live: spoken to,
        # no reply), and a silent addressed character reads as a bug, not a choice
        creply = llm.chat(
            prompts.build_character_messages(conn, gid, ch, settings.SCENE_BEATS),
            tools=tools.CHARACTER_TOOLS, tool_choice="auto",
            temperature=settings.CHARACTER_TEMPERATURE, max_tokens=settings.CHARACTER_MAX_TOKENS,
        )
        tok = (creply.usage or {}).get("prompt_tokens", 0) or 0
        if tok:
            repo.set_character_context(conn, ch["id"], tok)
        segs = parse_character_output(creply.content)
        if segs and creply.finish_reason == "length":
            k, t, e = segs[-1]
            segs[-1] = (k, trim_to_sentence(t), e)   # never show a mid-word cut
        if segs or creply.tool_calls:
            break
    for kind, txt, emotion in segs:
        # [say] -> dialogue (speech bubble); [do] -> action (a character's physical action).
        # A private reply with no stated emotion is spoken as a whisper by nature.
        if kind == "say" and private_with and not emotion:
            emotion = "whisper"
        emit(ch["id"], ch["name"], "dialogue" if kind == "say" else "action", txt,
             private_with=private_with, emotion=emotion)
    reactions = []
    for tc in creply.tool_calls:
        out = tools.apply_tool(conn, gid, tc.name, tc.arguments, actor=ch)
        if out["kind"] == "state" and out["text"]:
            emit("system", None, "system", out["text"], private_with=private_with)
        reactions += out["reactions"]
    return reactions


_SEGMENT_TYPES = {"say", "do", "attack", "give", "whisper", "look"}
# tools where firing twice with identical args may be intentional; everything else dedupes
_DEDUP_EXEMPT = {"apply_damage", "attack", "heal", "cue_character", "advance_time",
                 "spawn_character", "reject_attempt"}


def interpret_action(conn, gid: str, text: str) -> list[dict] | None:
    """Agentic input interpreter: parse a freeform typed action into structured segments
    (one small LLM call, the 'skill' loaded only for this call), so typing freely gets
    the same directed routing and adjudication as the composer buttons. Returns validated
    segments, or None on any failure (the caller falls back to the raw text)."""
    if not settings.INTERPRET_FREE_TEXT:
        return None
    try:
        reply = llm.chat(prompts.build_interpret_messages(conn, gid, text),
                         tools=prompts.INTERPRET_TOOL, tool_choice="auto",
                         temperature=0.2, max_tokens=settings.INTERPRET_MAX_TOKENS)
    except Exception:
        return None
    call = next((tc for tc in reply.tool_calls if tc.name == "submit_segments"), None)
    raw = (call.arguments or {}).get("segments") if call else None
    if not isinstance(raw, list):
        return None
    segs = []
    for s in raw[:6]:                                  # bounded, like the composer
        if not isinstance(s, dict) or (s.get("type") or "").lower() not in _SEGMENT_TYPES:
            continue
        t = s["type"].lower()
        seg = {"type": t, "text": (s.get("text") or "").strip(),
               "target": (s.get("target") or "").strip() or None,
               "item": (s.get("item") or "").strip() or None,
               "amount": s.get("amount"), "mode": (s.get("mode") or "").strip() or None}
        if t in ("say", "do") and not seg["text"]:
            continue
        if t == "attack" and not seg["target"]:
            continue
        if t == "give" and not (seg["item"] and seg["target"]):
            continue
        if t == "whisper" and not (seg["target"] and seg["text"]):
            continue
        segs.append(seg)
    return segs or None


CONTINUE_IMPULSE = ("(no player input; the player watches and waits. Continue the story: "
                    "advance the scene yourself - let the world shift, a character act, or "
                    "something new surface - then leave the player room to respond.)")


def maybe_update_summary(gid: str) -> None:
    """Background (scheduled after turns): fold story older than the newest turns into
    the rolling facts-only recap, so the narrator always knows the WHOLE story at a
    bounded token cost. One LLM call per fold; failures keep the previous recap and
    retry on a later turn. Characters are NEVER summarized (their small scene windows
    are by design; their long memory is the trait/origin/profile machinery)."""
    if not settings.SUMMARY_ENABLED:
        return
    with db.get_conn() as conn:
        g = repo.get_game(conn, gid)
        if not g:
            return
        latest = repo.next_turn_index(conn, gid) - 1
        done_through = g["summarized_through"] or 0
        target = latest - settings.SUMMARY_KEEP_TURNS
        if target - done_through < repo.effective_summary_every(g):
            return
        rows = repo.beats_between(conn, gid, done_through, target)
        if not rows:
            return
        prev = (g["story_summary"] or "").strip()
        transcript = "\n".join(prompts._render_beat(b) for b in rows)
    try:
        reply = llm.chat(prompts.build_summary_messages(prev, transcript),
                         temperature=0.3, max_tokens=settings.SUMMARY_MAX_TOKENS)
    except Exception:
        return
    text = clean_prose(reply.content or "")   # drift safety: junk never becomes memory
    if not text:
        return
    with db.get_conn() as conn:
        g = repo.get_game(conn, gid)
        # the window must not have moved while the LLM ran: a concurrent fold or a
        # history reset makes this result stale (it covers beats that no longer follow
        # the stored recap); skip and let a later turn fold fresh
        if g and (g["summarized_through"] or 0) == done_through:
            repo.set_story_summary(conn, gid, text, target)


def _image_pacing_ok(conn, gid: str, turn: int) -> bool:
    """Spontaneous narrator images stay special: allowed only when enough turns passed
    since the last image landed in the story flow. A player LOOK bypasses this."""
    last = repo.last_image_turn(conn, gid)
    return last is None or (turn - last) >= settings.IMAGE_NARRATOR_COOLDOWN_TURNS


def run_turn(conn, gid: str, action_text: str = "", segments=None,
             continue_story: bool = False, wish: str | None = None,
             echo_text: str | None = None) -> dict:
    turn = repo.next_turn_index(conn, gid)
    seq = 0
    new_beats: list[dict] = []
    spawned: list[str] = []
    image_request: str | None = None   # a show_image description the narrator fired
    # The global context meter: the NARRATOR's story context only (its biggest prompt this
    # turn). Character agents have their own per-character meters; folding them in here made
    # the global number bounce (a whisper turn would drop it to the character's small prompt).
    # A turn with no narrator call leaves the global meter at its last narrator value.
    track = {"ctx": 0}

    def emit(speaker, name, kind, text, private_with=None, emotion=""):
        nonlocal seq
        loc = repo.get_player(conn, gid)["location"]
        b = repo.add_beat(conn, gid, speaker, name, kind, text, loc,
                          turn_index=turn, seq=seq, private_with=private_with,
                          emotion=emotion)
        seq += 1
        new_beats.append(b)
        return b

    queue: deque = deque()
    acted: dict[str, int] = {}

    def enqueue(reactions):
        for cid in reactions or []:
            queue.append({"id": cid})

    segments = segments or []
    whispers = [s for s in segments if (s.get("type") or "").lower() == "whisper"]
    public = [s for s in segments if (s.get("type") or "").lower() != "whisper"]
    has_public = bool(public) or bool(action_text) or continue_story
    look_seg = next((s for s in public if (s.get("type") or "").lower() == "look"), None)

    # Snapshot what the player can SEE before the turn; the after-diff finds newly
    # unlocked items (each gets a small unlock image, rendered in the background).
    items_before = set(repo.visible_item_index(conn, gid))

    # Hybrid story clock: every turn costs a few fictional minutes automatically, so time
    # never freezes; the narrator jumps it with advance_time for rests/journeys/nightfall.
    repo.advance_time(conn, gid, settings.TURN_TIME_MINUTES)

    # The RETURNING note (set when re-entering a previously-left scene) lives for the rest
    # of the move turn plus one full turn, so the next narrator call (the one with tools)
    # gets to apply what changed while the player was away; then it expires.
    arrival_at_start = (repo.get_game(conn, gid)["arrival_note"] or "").strip()

    # ---- public turn (narrator + cascade) ----
    if has_public:
        action_text, directed = _compose(public) if public else (action_text, [])
        if not continue_story:
            # the player's echo is THEIR words: typed input echoes verbatim (echo_text);
            # the composed rendition is for the narrator, never put in the player's mouth
            emit("player", None, "action", echo_text or action_text or "...")

        # Impossible attempts are rejected deterministically with a friendly in-world beat,
        # BEFORE anything is applied, and the narrator is told they failed (so its prose
        # cannot claim a transfer or a hit that state forbids).
        failures: list[str] = []
        pending: list[dict] = []
        for d in directed:
            if d["tool"] == "_address":
                # speech routes only to characters ACTUALLY here; addressing someone
                # absent gets the same friendly deterministic bounce as attack/give
                # (live: the narrator wrote an 'elsewhere' character into the scene
                # because a missed say failed silently)
                kind_t, row = repo.resolve_target(conn, gid, d["args"].get("target", ""))
                if kind_t == "character" and row:
                    here = repo.get_player(conn, gid)["location"]
                    if row["alive"] and row["present"] and row["location"] == here:
                        enqueue([row["id"]])
                    else:
                        why = (f"{row['name']} is gone." if not row["alive"]
                               else f"{row['name']} is not here.")
                        failures.append(why)
                        emit("system", None, "system", why)
                continue
            why = _why_impossible(conn, gid, d)
            if why:
                failures.append(why)
                emit("system", None, "system", why)
                continue
            # Valid mechanical attempt: NOT applied yet. The narrator adjudicates it
            # (accept via the matching tool / veto via reject_attempt); anything it leaves
            # untouched is default-applied after the reply, so nothing is silently lost.
            kind_t, row = repo.resolve_target(conn, gid, d["args"].get("target") or "")
            disp = d.get("display", {})
            if d["tool"] == "attack":
                amt = d["args"].get("amount")
                line = f"attack {disp.get('target')}" + (f" ({amt} damage)" if amt else "")
                family = "attack"
            else:
                line = f"give {disp.get('item')} to {disp.get('target')}"
                family = "give"
            pending.append({"d": d, "family": family, "line": line,
                            "tid": "player" if kind_t == "player" else (row["id"] if row else None),
                            "handled": False, "rejected": False})

        narrator_action = CONTINUE_IMPULSE if continue_story else action_text
        if failures:
            narrator_action = f"{action_text} (failed: {' '.join(failures)})"

        history_limit = repo.effective_history_beats(repo.get_game(conn, gid))
        reply = llm.chat(
            prompts.build_narrator_messages(conn, gid, narrator_action, history_limit,
                                            settings.LORE_BUDGET,
                                            attempts=[p["line"] for p in pending],
                                            looking=bool(look_seg), wish=wish),
            tools=tools.narrator_tools(adjudicating=bool(pending),
                                       images=settings.IMAGE_ENABLED),
            tool_choice="auto",
            temperature=settings.NARRATOR_TEMPERATURE, max_tokens=settings.NARRATOR_MAX_TOKENS,
        )
        track["ctx"] = max(track["ctx"], (reply.usage or {}).get("prompt_tokens", 0) or 0)

        def _mark_handled(name, args):
            """An accepting tool call (apply_damage/attack/give_item) covers the matching
            pending attempt: same family, same resolved target."""
            fam = "give" if name == "give_item" else "attack"
            tname = (args or {}).get("target") or ("" if name == "give_item" else "player")
            kt, rw = repo.resolve_target(conn, gid, tname)
            tid = "player" if kt == "player" else (rw["id"] if rw else None)
            for p in pending:
                if not p["handled"] and not p["rejected"] and p["family"] == fam and p["tid"] == tid:
                    p["handled"] = True
                    return

        def _attempt_amount(args):
            """The player's stated force for the attempt this accepting call covers.
            When the narrator approves a strike WITHOUT naming its own amount, the
            player's amount wins (live: 'attack for 12' was accepted as a default-3 hit
            because the model rarely fills the amount field)."""
            tname = (args or {}).get("target") or "player"
            kt, rw = repo.resolve_target(conn, gid, tname)
            tid = "player" if kt == "player" else (rw["id"] if rw else None)
            for p in pending:
                if (not p["handled"] and not p["rejected"] and p["family"] == "attack"
                        and p["tid"] == tid):
                    return p["d"]["args"].get("amount")
            return None

        cues, state_notes = [], []
        seen_calls: set = set()
        for tc in reply.tool_calls:
            if tc.name in ("apply_damage", "attack") and pending \
                    and not (tc.arguments or {}).get("amount"):
                amt = _attempt_amount(tc.arguments)
                if amt:
                    tc.arguments = dict(tc.arguments or {}, amount=amt)
            # the model sometimes over-fires the SAME call twice in one reply (live:
            # add_item("scanner device") x2 doubled the item). Suppress exact repeats,
            # except for tools where repetition can be meant (damage, heal, cues, time).
            if tc.name not in _DEDUP_EXEMPT:
                key = (tc.name, json.dumps(tc.arguments, sort_keys=True, default=str))
                if key in seen_calls:
                    continue
                seen_calls.add(key)
            out = tools.apply_tool(conn, gid, tc.name, tc.arguments, actor=None)
            if tc.name in ("apply_damage", "attack", "give_item") and out["kind"] == "state":
                _mark_handled(tc.name, tc.arguments)
            if out["kind"] == "cue" and out["cue"]:
                cues.append(out["cue"])
            elif out["kind"] == "spawn":
                spawned.append(out["cue"]["id"])
                if out["text"]:
                    state_notes.append(out["text"])
                cues.append(out["cue"])
            elif out["kind"] == "reject":
                n = (out["cue"] or {}).get("attempt")
                victim = (pending[n - 1] if isinstance(n, int) and 1 <= n <= len(pending)
                          else next((p for p in pending if not p["handled"] and not p["rejected"]), None))
                if victim and not victim["handled"]:
                    victim["rejected"] = True
                    state_notes.append(out["text"])
            elif out["kind"] == "image":
                # the narrator wants this moment rendered; a player look always earns it,
                # a spontaneous one only when images have not landed too recently
                if image_request is None and (look_seg or _image_pacing_ok(conn, gid, turn)):
                    image_request = out["text"]
            elif out["kind"] in ("state", "kill") and out["text"]:
                state_notes.append(out["text"])
            enqueue(out["reactions"])

        # Default-accept: anything the narrator neither applied nor vetoed happens as attempted.
        for p in pending:
            if p["handled"] or p["rejected"]:
                continue
            out = tools.apply_tool(conn, gid, p["d"]["tool"], p["d"]["args"], actor=None)
            if out["kind"] == "state" and out["text"]:
                state_notes.append(out["text"])
            enqueue(out["reactions"])
        prose = clean_prose(reply.content)
        if prose and reply.finish_reason == "length":
            prose = trim_to_sentence(prose)
        if prose:
            emit("narrator", "Narrator", "narration", prose)
        else:
            # No prose, but state changed (move/furnish/pickup) or nothing else will speak:
            # a short resolve pass voices the outcome so the turn is never dead air.
            will_speak = bool(cues) or bool(queue)
            if state_notes or not will_speak:
                resolve = llm.chat(
                    prompts.build_narrator_resolve_messages(conn, gid, narrator_action, state_notes),
                    temperature=settings.NARRATOR_TEMPERATURE,
                    max_tokens=settings.NARRATOR_RESOLVE_MAX_TOKENS,
                )
                track["ctx"] = max(track["ctx"], (resolve.usage or {}).get("prompt_tokens", 0) or 0)
                rtext = clean_prose(resolve.content)
                if rtext:
                    emit("narrator", "Narrator", "narration", rtext)
        for note in state_notes:
            emit("system", None, "system", note)
        for cue in cues[: settings.MAX_CHARACTER_REACTIONS]:
            queue.append(cue)

        location = repo.get_player(conn, gid)["location"]
        steps = 0
        while queue and steps < settings.TURN_MAX_ACTOR_STEPS:
            cid = queue.popleft()["id"]
            ch = repo.get_character(conn, cid)
            if not ch or not ch["alive"] or not ch["present"] or ch["location"] != location:
                continue
            if acted.get(cid, 0) >= settings.TURN_MAX_PER_CHARACTER:
                continue
            acted[cid] = acted.get(cid, 0) + 1
            steps += 1
            enqueue(_character_reply(conn, gid, ch, emit))

    # ---- private channel (1:1; other characters never see it) ----
    # The private modal stacks say AND do segments at one character. Consecutive private
    # segments to the SAME character form one exchange: all the player's lines land first,
    # then the character replies once (not once per line).
    location = repo.get_player(conn, gid)["location"]
    exchanges: list[tuple[dict, list[dict]]] = []   # (character row, [segments])
    for w in whispers[: settings.TURN_MAX_ACTOR_STEPS]:
        kind_t, row = repo.resolve_target(conn, gid, (w.get("target") or ""))
        if kind_t != "character" or not row or not row["alive"] or row["location"] != location:
            continue
        if exchanges and exchanges[-1][0]["id"] == row["id"]:
            exchanges[-1][1].append(w)
        else:
            exchanges.append((row, [w]))
    private_looks: list[tuple[str, str]] = []   # (character id, focus) -> private snapshots
    for row, segs in exchanges:
        spoke = False
        for w in segs:
            text = (w.get("text") or "").strip()
            mode = (w.get("mode") or "say").lower()
            if mode == "look":
                # a quiet study of the character from the private panel: the snapshot
                # lands IN the private thread (owner spec); no reply is owed to a gaze
                emit("player", None, "action",
                     f"you quietly study {row['name']}" + (f": {text}" if text else ""),
                     private_with=row["id"])
                private_looks.append((row["id"], text or f"at {row['name']}"))
                continue
            spoke = True
            if mode == "do":
                # a discreet private action (slip a note, flash a badge): only they notice
                emit("player", None, "action",
                     f"(only {row['name']} notices) you {text}", private_with=row["id"])
            else:
                emit("player", None, "action",
                     f'you whisper to {row["name"]}: "{text}"', private_with=row["id"])
        if spoke:
            _character_reply(conn, gid, row, emit, private_with=row["id"])

    if arrival_at_start:
        repo.clear_arrival_note(conn, gid)
    if track["ctx"]:
        repo.set_context_used(conn, gid, track["ctx"])
    result = {"beats": new_beats, "state": repo.game_state(conn, gid), "spawned": spawned}
    if image_request:
        # caller schedules the slow render in the background; the look's text becomes
        # the image beat's caption (matches the See-with-focus behavior)
        result["image_request"] = {"description": image_request,
                                   "caption": ((look_seg or {}).get("text") or "").strip()}
    elif look_seg:
        # owner decision: a LOOK always earns an image. The narrator's show_image
        # description wins when it fired; otherwise fall back to the deterministic
        # state-grounded snapshot with the look's focus.
        result["view_fallback"] = ((look_seg or {}).get("text") or "").strip()
    if private_looks:
        result["private_looks"] = private_looks   # snapshots bound to the private thread
    new_items = [v for k, v in repo.visible_item_index(conn, gid).items()
                 if k not in items_before and not v.get("image_url")]
    if new_items:
        result["new_items"] = new_items   # caller renders their small unlock images
    return result
