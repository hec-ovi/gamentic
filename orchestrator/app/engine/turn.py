"""run_turn and its direct helpers: composing the player's tagged segments, the
deterministic adjudication pre-check, the narrator call, the bounded character cascade,
the private channel, and the freeform-input interpreter."""
import json
import re
from collections import deque

from .. import repo, prompts, tools, llm
from ..config import settings
from . import live, parsing


def _display(s: dict, key: str, conn=None, gid: str | None = None, item: bool = False) -> str:
    """The human name for an id carried by this segment's entity chips (refs). Chips send
    {kind, id, name}, so the readable action text never leaks raw ids to the model/player.
    When the chip refs DON'T carry the key (the give/attack picker sends a bare id with no
    refs - live: 'you give 408f0801a83d to Sera'), fall back to resolving it against the
    DB: an item key -> the pack item's stored name, a target key -> a character's name (the
    character resolver already accepts ids). The wire contract says echoes show names,
    never ids; this seam is where a bare id is caught before it reaches the public echo."""
    for r in s.get("refs") or []:
        if r.get("id") and r["id"] == key and r.get("name"):
            return r["name"]
    if conn is not None and gid is not None and key:
        if item:
            name = repo.player_item_name(conn, gid, key)
            if name:
                return name
        else:
            kind_t, row = repo.resolve_target(conn, gid, key)
            if kind_t == "character" and row and row["name"]:
                return row["name"]
    return key


def _sane_amount(v):
    """Clamp a client-stated attack amount to 1..DAMAGE_CAP at the entry seam. Nothing
    bounded the segment amount before (live audit 2026-06-11: a typed 'for 999999' is an
    adjudication-proof instakill, because default-accept applies the raw args and
    _attempt_amount back-fills them into narrator-accepted strikes). Overshoots clamp to
    the cap; junk, zero and negatives become None (the narrator's default applies)."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    if n < 1:
        return None
    return min(n, settings.DAMAGE_CAP)


def _compose(segments, conn=None, gid: str | None = None) -> tuple[str, list[dict]]:
    """Render tagged segments into a readable action string + the directed actions to apply.
    conn/gid let _display resolve a bare id (no entity chip) against the DB, so the give
    picker's {item:'<id>', target:'<name>'} echoes the item NAME, never the raw id."""
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
            parts.append(f'you say "{text}"' + (f" to {_display(s, target, conn, gid)}" if target else ""))
            if target:
                directed.append({"tool": "_address", "args": {"target": target}})
        elif t == "attack":
            # the HOW rides along (live replay: "I grab her wrist" composed to a bare
            # "you attack Mira" and the narrator invented a bloody slap - the player's
            # stated force never reached the echo or the adjudication line)
            how = f": {text}" if text else ""
            tdisp = _display(s, target, conn, gid) if target else "them"
            parts.append(f"you attack {tdisp}{how}")
            # _sane_amount HERE covers every client path at once: composer segments,
            # raw API segments, and the interpreter all flow through this compose, and
            # default-accept + _attempt_amount both read these args downstream
            directed.append({"tool": "attack", "args": {"target": target,
                                                        "amount": _sane_amount(s.get("amount"))},
                             "display": {"target": tdisp, "how": text}})
        elif t == "give":
            idisp = _display(s, item, conn, gid, item=True)
            tdisp = _display(s, target, conn, gid) if target else "them"
            parts.append(f"you give {idisp} to {tdisp}")
            directed.append({"tool": "give_item", "args": {"item": item, "target": target},
                             "display": {"item": idisp, "target": tdisp}})
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
        # article-safe phrasing: targets arrive both bare ('dragon') and with their own
        # article (live: 'There is no the lighthouse keeper here.')
        return f"You see no sign of {t_disp} here."
    if kind_t == "character" and row:
        here = repo.get_player(conn, gid)["location"]
        if not row["alive"]:
            return f"{row['name']} is already down."
        if not row["present"] or row["location"] != here:
            return f"{row['name']} is not here."
    if d["tool"] == "give_item":
        if kind_t is None:
            return f"You see no sign of {t_disp} here."
        if not repo.player_has_item(conn, gid, args.get("item") or ""):
            return f"You don't have {disp.get('item') or args.get('item') or 'that'}."
    return None


def _norm_move(s: str) -> str:
    """Lowercased, whitespace-collapsed form for movement matching."""
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _strip_article(s: str) -> str:
    """Drop one leading article from an already-normalized phrase ('the lighthouse'
    and 'lighthouse' must name the same exit)."""
    for a in ("the ", "a ", "an "):
        if s.startswith(a):
            return s[len(a):]
    return s


def _match_exit(texts, exits) -> dict | None:
    """The deterministic movement router's matcher: does a public 'do' text name a
    REVEALED exit? Case- and article-insensitive. A text matches when it equals/starts
    with 'go to <label>' (the FE exit button sends exactly that shape), or contains the
    full exit label, or contains the full target name. First match wins. Movement
    language that names no revealed exit matches NOTHING: discovering new places stays
    the narrator's call."""
    for raw in texts:
        text = _norm_move(raw)
        if not text:
            continue
        for e in exits:
            phrases = []
            for p in (_norm_move(e.get("label")), _norm_move(e.get("target"))):
                for v in (p, _strip_article(p)):
                    if v and v not in phrases:
                        phrases.append(v)
            for p in phrases:
                # lookarounds, not \b: a label may start/end with a non-word character
                if text.startswith(f"go to {p}") \
                        or re.search(rf"(?<!\w){re.escape(p)}(?!\w)", text):
                    return e
    return None


def _character_reply(conn, gid, ch, emit, private_with=None, impulse=None):
    """Run one character turn (POV + tools). Returns the reaction targets to enqueue.
    Each character agent has its OWN context; its prompt size feeds ONLY its own meter
    (state.characters[].context). The global meter tracks the narrator's story context,
    so small character calls never make the global number bounce around.

    private_with forces the WHOLE reply into one private thread (the whisper channel, and
    a gift's forced reply). impulse is a directed prompt line prepended for this call only
    (mirrors the whisper channel's directed reply): the forced gift reply hands the model
    'the player just gave you <item>' so X always has something to answer."""
    segs: list[tuple[str, str]] = []
    creply = llm.LLMReply(content="")
    live.phase(gid, "character", actor=ch["name"])
    live_c = None
    for _ in range(2):
        # one retry: a character occasionally returns nothing usable (live: spoken to,
        # no reply), and a silent addressed character reads as a bug, not a choice
        if live_c is not None:
            live_c.done()   # the retry starts a fresh live stream; clear the first
        live_c = live.LiveCharacter(gid, ch, private_with)
        creply = llm.chat(
            prompts.build_character_messages(conn, gid, ch, settings.CHAR_HISTORY_BEATS,
                                             impulse=impulse),
            tools=tools.CHARACTER_TOOLS, tool_choice="auto",
            temperature=settings.CHARACTER_TEMPERATURE, max_tokens=settings.CHARACTER_MAX_TOKENS,
            on_delta=live_c.on_delta, cancel=live.stop_event(gid),
        )
        tok = (creply.usage or {}).get("prompt_tokens", 0) or 0
        if tok:
            repo.set_character_context(conn, ch["id"], tok)
        segs, marks = parsing.parse_character_output_with_marks(creply.content)
        if segs and creply.finish_reason == "length":
            k, t, e = segs[-1]
            segs[-1] = (k, parsing.trim_to_sentence(t), e)   # never show a mid-word cut
            segs = [s for s in segs if s[1]]   # a sentence-less fragment trims to nothing
        if segs or creply.tool_calls:
            break
    for kind, txt, emotion in segs:
        # [say] -> dialogue (speech bubble); [do] -> action (a character's physical action);
        # [whisper] -> dialogue meant for the player alone (ALWAYS private, even on a public
        # turn - owner: 'characters should be able to also whisper'). A private reply with no
        # stated emotion is spoken as a whisper by nature.
        seg_private = private_with or (ch["id"] if kind == "whisper" else None)
        if kind in ("say", "whisper") and seg_private and not emotion:
            emotion = "whisper"
        emit(ch["id"], ch["name"], "dialogue" if kind in ("say", "whisper") else "action", txt,
             private_with=seg_private, emotion=emotion)
    if live_c is not None:
        live_c.done()   # after the real beats: the swap is gapless on screen
    reactions = []
    # memory marks written as text count exactly like real calls (live: the 26B
    # narrates its tool use - '{piece: "..."}' inside a [do] - instead of calling;
    # same lesson as the say/do tags: parse the intent, never demand the protocol)
    seen_marks = set()
    for name, args in marks:
        key = (name, json.dumps(args, sort_keys=True))
        if key in seen_marks:
            continue
        seen_marks.add(key)
        out = tools.apply_tool(conn, gid, name, args, actor=ch)
        if out["kind"] == "state" and out["text"]:
            emit("system", None, "system", out["text"], private_with=private_with)
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
                         temperature=0.2, max_tokens=settings.INTERPRET_MAX_TOKENS,
                         cancel=live.stop_event(gid))
    except llm.LLMCancelled:
        raise   # a stop must stop the TURN, not fall back to the raw text
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


def _image_pacing_ok(conn, gid: str, turn: int) -> bool:
    """Spontaneous narrator images stay special: allowed only when enough turns passed
    since the last image landed in the story flow. A player LOOK bypasses this."""
    last = repo.last_image_turn(conn, gid)
    return last is None or (turn - last) >= settings.IMAGE_NARRATOR_COOLDOWN_TURNS


def run_turn(conn, gid: str, action_text: str = "", segments=None,
             continue_story: bool = False, wish: str | None = None,
             echo_text: str | None = None) -> dict:
    # Claim the story's write lock BEFORE reading the turn counter: background media
    # jobs land their beats under the same lock (jobs._land_beat), so the index this
    # turn claims can never be claimed twice. Without it, an image persisting while
    # this turn ran read the committed MAX and took the SAME turn_index; sorted by
    # (turn_index, seq) on reload it re-appeared in the middle of this turn's
    # exchange, and beats?since=<last turn> (strict >) never delivered it live.
    # Guarded: a caller already inside a transaction holds the lock via its writes.
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
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
        live.publish_beat(gid, b)   # live mirror; the POST response stays the record
        return b

    # The stop flag is cleared by live.begin_turn in the route (before the interpreter),
    # NOT here: a stop landing between the interpreter and this call must still count.
    stop_ev = live.stop_event(gid)

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
    location_before = repo.get_player(conn, gid)["location"]
    location_at_pass = None   # the scene the narrator pass SAW (set at the pass; stays
    # None on whisper-only turns, which run no narrator)

    # Hybrid story clock: every turn costs a few fictional minutes automatically, so time
    # never freezes; the narrator jumps it with advance_time for rests/journeys/nightfall.
    repo.advance_time(conn, gid, settings.TURN_TIME_MINUTES)

    # The RETURNING note (set when re-entering a previously-left scene) lives for the rest
    # of the move turn plus one full turn, so the next narrator call (the one with tools)
    # gets to apply what changed while the player was away; then it expires.
    arrival_at_start = (repo.get_game(conn, gid)["arrival_note"] or "").strip()

    # ---- public turn (narrator + cascade) ----
    if has_public:
        action_text, directed = _compose(public, conn, gid) if public else (action_text, [])
        if not continue_story:
            # the player's echo is THEIR words: typed input echoes verbatim (echo_text);
            # the composed rendition is for the narrator, never put in the player's mouth.
            # EXCEPT when the input split into public + whisper segments: the verbatim
            # text carries the whispered words and this beat is witnessed by EVERYONE
            # (static-confirmed leak: the secret entered every bystander's recap), so a
            # mixed turn echoes the composed public-only rendition instead.
            emit("player", None, "action",
                 (echo_text if not whispers else "") or action_text or "...")

        # Deterministic movement router FIRST: an explicit step through a REVEALED exit
        # moves the player before anything else resolves, so a stacked composer turn like
        # "[do] go to the table, [say] hi" (the canonical owner example) addresses people
        # at the DESTINATION, not where the player stood when typing (live showcase
        # 2026-06-11: a move+say stack bounced 'not here' against the room being walked
        # into). It also runs before the narrator call, so the arrival rides the
        # NEW/RETURNING machinery (the audit's worst finding: traveling prose, no move).
        # Only public 'do' texts (or the raw typed text) can move; one move per turn;
        # movement language that names no revealed exit changes nothing.
        state_notes: list[str] = []
        moved_key = None
        if not continue_story:
            move_texts = ([(s.get("text") or "") for s in public
                           if (s.get("type") or "do").lower() == "do"]
                          if public else [action_text])
            ex = _match_exit(move_texts,
                             repo.db.loads(repo.current_scene(conn, gid)["exits"], []))
            if ex and (ex.get("target") or "").strip():
                margs = {"location": ex["target"]}
                out = tools.apply_tool(conn, gid, "move_location", margs, actor=None)
                if out["kind"] == "state":
                    if out["text"]:
                        state_notes.append(out["text"])   # 'You move to X.', in receipt order
                    # pre-seed the dedup key: the narrator restating the same move in its
                    # reply must not land a second receipt
                    moved_key = ("move_location", json.dumps(margs, sort_keys=True, default=str))

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
            if d["tool"] == "attack":
                # striking an OBJECT is not combat: a bell, a door, a jar (live
                # showcase 2026-06-11: "strike the Great Bell" was read as an attack,
                # found no character called that, and bounced "no sign of the Great
                # Bell" while the bell hung in plain sight). A target that matches a
                # visible item falls through to the narrator as plain action text.
                kt_probe, _ = repo.resolve_target(conn, gid, d["args"].get("target") or "")
                key = repo.item_key(d["args"].get("target") or "")
                if kt_probe is None and key and key in repo.visible_item_index(conn, gid):
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
                how = f' "{disp.get("how")}"' if disp.get("how") else ""
                line = f"attack {disp.get('target')}{how}" + (f" ({amt} damage)" if amt else "")
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

        # One game-row read covers every per-game dial this turn: the verbatim window
        # plus the turn-economy caps (voices cued per turn, acts per character). 0 in
        # the row = the env default. TURN_MAX_ACTOR_STEPS stays env-only on purpose:
        # it is the runaway safety ceiling, not a feel dial.
        game_row = repo.get_game(conn, gid)
        history_limit = repo.effective_history_beats(game_row)
        turn_voices = repo.effective_turn_voices(game_row)
        turn_acts = repo.effective_turn_acts(game_row)
        # Scaffold stop-sequences FIRST: at deep context the model can regress into
        # writing the worked example's SHAPE as text instead of calling tools (live,
        # turn 53: '(think: ...' then 'tools: {...}' then 'Prose:'). Halting at the
        # scaffold's first marker leaves empty/short prose, and the resolve pass then
        # voices the turn cleanly. Then impersonation stops: the model faked cast
        # dialogue as screenplay lines (live: 'Vane: "Movement. Now."'); generation
        # halts at any present character's name-colon (full name + bare first name).
        stops: list[str] = ["(think:", "\ntools:", "\nTools:", "\nProse:"]
        for c in repo.present_characters(conn, gid, repo.get_player(conn, gid)["location"]):
            if not c["alive"]:
                continue
            nm = (c["name"] or "").strip()
            if not nm:
                continue
            words = nm.split()
            for cand in [nm] + (words[:1] if len(words) > 1 else []):
                s = f"\n{cand}:"
                if s not in stops:
                    stops.append(s)
        stops = stops[:12]  # llama.cpp accepts a list; keep it bounded
        location_at_pass = repo.get_player(conn, gid)["location"]   # the scene this pass SEES
        messages = prompts.build_narrator_messages(conn, gid, narrator_action, history_limit,
                                                   settings.LORE_BUDGET,
                                                   attempts=[p["line"] for p in pending],
                                                   looking=bool(look_seg), wish=wish)
        # The failed-call note renders exactly once: consumed by the message build above,
        # cleared now; the retry pass below overwrites it with this turn's new list.
        repo.set_last_tool_errors(conn, gid, [])
        live.phase(gid, "narrator")
        live_n = live.LiveNarration(gid)
        # A stop request raises LLMCancelled (here or in any later call this turn) and
        # it PROPAGATES: the route's catch rolls the whole transaction back, so a
        # stopped turn never happened - no beats, no echo, no clock tick (owner
        # 2026-07-20: stop must take the player's own action back too).
        reply = llm.chat(
            messages,
            tools=tools.narrator_tools(adjudicating=bool(pending),
                                       images=settings.IMAGE_ENABLED),
            tool_choice="auto",
            temperature=settings.NARRATOR_TEMPERATURE, max_tokens=settings.NARRATOR_MAX_TOKENS,
            stop=stops or None, thinking=settings.NARRATOR_THINKING,
            on_delta=live_n.on_delta, cancel=stop_ev,
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

        cues: list = []   # state_notes opened above (the movement router seeds it)
        invalid_calls: list[tuple[str, dict, str]] = []  # (name, args, reason): the second chance
        seen_calls: set = {moved_key} if moved_key else set()
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
            if out["kind"] == "invalid":
                # not dropped yet: it gets ONE deterministic retry after the loop (a
                # spawn_character later in this same reply may create its target)
                invalid_calls.append((tc.name, tc.arguments or {}, out["text"] or tc.name))
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
        # A gift's reply is a private whisper from the receiving character (owner: "when i
        # give item a private whisper comes from that character... that must be forced").
        # Every give that landed (not rejected, not refused) maps the receiver to the item;
        # the public receipt stays public (a mechanical fact), but the receiver's reaction
        # is owed to the player alone. Resolved AFTER default-accept so it covers both the
        # narrator's explicit give_item and a defaulted give. A refused give never makes it
        # here (it never became a pending attempt), so it forces no private reply.
        gift_receivers: dict[str, str] = {}
        for p in pending:
            if p["family"] == "give" and not p["rejected"] and p["tid"] \
                    and p["tid"] != "player":
                gift_receivers[p["tid"]] = (p["d"].get("display", {}).get("item")
                                            or p["d"]["args"].get("item") or "it")
        # Intra-reply retry: each invalid call gets ONE deterministic second chance, in
        # order, now that the whole reply has applied (live: set_disposition fired BEFORE
        # its spawn_character in the same reply). Still-invalid reasons become the
        # narrator's next-turn note; characters' invalid calls are never fed back.
        still_invalid: list[str] = []
        for name, args, reason in invalid_calls:
            out = tools.apply_tool(conn, gid, name, args, actor=None)
            if out["kind"] == "invalid":
                still_invalid.append(out["text"] or reason)
                continue
            if out["kind"] == "spawn":
                spawned.append(out["cue"]["id"])
            if out["kind"] in ("cue", "spawn") and out["cue"]:
                cues.append(out["cue"])
            if out["kind"] in ("state", "kill", "spawn") and out["text"]:
                state_notes.append(out["text"])
            enqueue(out["reactions"])
        repo.set_last_tool_errors(conn, gid, still_invalid)
        prose = parsing.clean_prose(reply.content)
        if prose and reply.finish_reason == "length":
            prose = parsing.trim_to_sentence(prose)
        prose_emotion, prose = parsing._scrub_narration(prose)
        if prose:
            emit("narrator", "Narrator", "narration", prose, emotion=prose_emotion)
            live_n.done()
        else:
            live_n.done()
            # No prose, but state changed (move/furnish/pickup) or nothing else will speak:
            # a short resolve pass voices the outcome so the turn is never dead air.
            will_speak = bool(cues) or bool(queue)
            if state_notes or not will_speak:
                live_r = live.LiveNarration(gid)
                resolve = llm.chat(
                    prompts.build_narrator_resolve_messages(conn, gid, narrator_action, state_notes),
                    temperature=settings.NARRATOR_TEMPERATURE,
                    max_tokens=settings.NARRATOR_RESOLVE_MAX_TOKENS,
                    # same narrator voice, same defenses: the scaffold + impersonation
                    # stops above (static review: a screenplay line passed this pass
                    # verbatim because only the main call was stopped)
                    stop=stops or None,
                    on_delta=live_r.on_delta, cancel=stop_ev,
                )
                track["ctx"] = max(track["ctx"], (resolve.usage or {}).get("prompt_tokens", 0) or 0)
                rprose = parsing.clean_prose(resolve.content)
                if rprose and resolve.finish_reason == "length":
                    rprose = parsing.trim_to_sentence(rprose)   # never show a mid-word cut
                remotion, rtext = parsing._scrub_narration(rprose)
                if rtext:
                    emit("narrator", "Narrator", "narration", rtext, emotion=remotion)
                live_r.done()
        for note in state_notes:
            emit("system", None, "system", note)
        for cue in cues[:turn_voices]:
            queue.append(cue)

        location = repo.get_player(conn, gid)["location"]
        steps = 0
        while queue and steps < settings.TURN_MAX_ACTOR_STEPS:
            if stop_ev.is_set():
                raise llm.LLMCancelled()   # a stop between calls cancels the turn too
            cid = queue.popleft()["id"]
            # a gift receiver answers PRIVATELY below, never in the public cascade: their
            # whole reply this turn is owed to the player alone, so they are pulled out of
            # the open reaction loop (give_item enqueued them; this is where that is undone)
            if cid in gift_receivers:
                continue
            ch = repo.get_character(conn, cid)
            if not ch or not ch["alive"] or not ch["present"] or ch["location"] != location:
                continue
            if acted.get(cid, 0) >= turn_acts:
                continue
            acted[cid] = acted.get(cid, 0) + 1
            steps += 1
            enqueue(_character_reply(conn, gid, ch, emit))

        # The forced private reply: every gift receiver answers in the private thread,
        # GUARANTEED, even when the narrator cued nobody. The directed impulse names the
        # gift outright so the model always has the moment to answer (mirrors the whisper
        # channel's directed reply). Other characters' public reactions already ran above.
        for cid, item_name in gift_receivers.items():
            if stop_ev.is_set():
                raise llm.LLMCancelled()
            ch = repo.get_character(conn, cid)
            if not ch or not ch["alive"] or not ch["present"] or ch["location"] != location:
                continue
            _character_reply(conn, gid, ch, emit, private_with=cid,
                             impulse=f"The player just gave you {item_name}. "
                                     f"React to the gift, just to them.")

    # ---- private channel (1:1; other characters never see it) ----
    # The private modal stacks say AND do segments at one character. Consecutive private
    # segments to the SAME character form one exchange: all the player's lines land first,
    # then the character replies once (not once per line).
    location = repo.get_player(conn, gid)["location"]
    exchanges: list[tuple[dict, list[dict]]] = []   # (character row, [segments])
    for w in whispers[: settings.TURN_MAX_ACTOR_STEPS]:
        target = (w.get("target") or "").strip()
        kind_t, row = repo.resolve_target(conn, gid, target)
        # A bad whisper target BOUNCES like the public path, never swallows (live:
        # whispers to a nonexistent AND to a dead character both returned 200 with zero
        # beats - dead air with the clock ticked). An unknown name bounces publicly
        # (there is no private channel to land it in); a known-but-dead/absent character
        # bounces INTO their private thread, where the player tried to speak.
        if kind_t != "character" or not row:
            emit("system", None, "system",
                 f"There is no one called {_display(w, target) or 'that'} here.")
            continue
        if not row["alive"]:
            emit("system", None, "system", f"{row['name']} can no longer hear you.",
                 private_with=row["id"])
            continue
        if not row["present"] or row["location"] != location:
            emit("system", None, "system", f"{row['name']} is not here.",
                 private_with=row["id"])
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
                # a discreet private action (slip a note, flash a badge): only they
                # notice. The text stays the player's own first-person words, like the
                # public do echo (live: prefixing 'you ' produced 'you I slide the
                # ledger across the table')
                emit("player", None, "action",
                     f"(only {row['name']} notices) {text}", private_with=row["id"])
            else:
                emit("player", None, "action",
                     f'you whisper to {row["name"]}: "{text}"', private_with=row["id"])
        if spoke:
            if stop_ev.is_set():
                raise llm.LLMCancelled()
            _character_reply(conn, gid, row, emit, private_with=row["id"])

    if arrival_at_start:
        repo.clear_arrival_note(conn, gid)
    if track["ctx"]:
        repo.set_context_used(conn, gid, track["ctx"])
    # Death is ENGINE-owned: a turn that ends with the player at 0 life IS lost, no
    # matter what the model said (live, e2e 2026-06-11: the lethal-fall turn printed the
    # fall receipt, then a set_game_status('active') later in the SAME reply silently
    # reverted the flip - 'active' receipts are silent - so the response said 'active',
    # and the next turn dealt 3 more damage at zero and re-printed the fall). The fall
    # receipt already landed when life first hit 0; this re-assert is silent. The staged
    # rescue (heal from 0) raises life first, so it is never caught here.
    if repo.get_player(conn, gid)["life"] == 0 \
            and (repo.get_game(conn, gid)["status"] or "active") == "active":
        repo.set_game_status(conn, gid, "lost")
    # Stranded-companion net: on a turn that MOVED the player, narration that names a
    # character the state left behind is prose walking someone along without the tool
    # (live replay 2026-06-11: "Basir falls into step behind you" into the stables while
    # set_following never fired - his location stayed the common room, so he would
    # witness none of what the fiction showed him). No state is changed here: the
    # narrator gets the discrepancy through the same next-turn note as invalid calls,
    # and either set_followings them or writes them out. A mere mention of someone far
    # away costs only this harmless reminder.
    location_now = repo.get_player(conn, gid)["location"]
    if location_now != location_before:
        told = [b["text"] for b in new_beats
                if b["kind"] == "narration" and not b.get("private_with")]
        stranded = [c["name"] for c in repo.get_characters(conn, gid)
                    if c["alive"] and c["location"] != location_now and c["name"]
                    and any(c["name"].split()[0].lower() in t.lower() for t in told)]
        if stranded:
            g = repo.get_game(conn, gid)
            notes = repo.db.loads(g["last_tool_errors"], []) if "last_tool_errors" in g.keys() else []
            notes += [(f"your narration placed {n} at {location_now}, but they stayed at "
                       f"their own scene: set_following('{n}', true) if they came along, "
                       f"or keep them out of the scene's present action") for n in stranded]
            repo.set_last_tool_errors(conn, gid, notes)
    # A scene the narrator never furnishes stays "unestablished" forever if the
    # describe_scene call never comes (live: 'vault interior' showed a bare-name card,
    # no history text, and its art rendered from the name alone while the prose sat in
    # the beats). The establishing narration IS the description: when the slot is still
    # empty after a narrator pass that RAN AT this scene (it saw the NEW PLACE furnish
    # protocol and skipped describe_scene), seed it from this turn's public prose
    # (first two sentences); a later describe_scene simply overwrites it. A narrator
    # that moved the player mid-pass keeps its furnish chance next turn.
    sc_now = repo.current_scene(conn, gid)
    if location_at_pass == sc_now["name"] and not (sc_now["description"] or "").strip():
        told = [b["text"] for b in new_beats
                if b["kind"] == "narration" and not b.get("private_with") and b["text"]]
        if told:
            sentences = re.split(r"(?<=[.!?])\s+", " ".join(told[0].split()))
            seeded = " ".join(sentences[:2]).strip()[:400]
            if seeded:
                repo.set_scene_description(conn, gid, seeded)
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
