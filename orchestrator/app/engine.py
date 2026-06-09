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
import re
from collections import deque

from . import repo, prompts, tools, llm
from .config import settings

_CHAR_TAG = re.compile(r"\[(say|do)\]", re.I)
_CHAR_CLOSE = re.compile(r"\[/?(?:say|do)\]", re.I)
# Hygiene for small-model artifacts seen live: a pseudo tool call leaked as text
# ("[attack{amount:10,target: \"player\"}]") and stray tag debris ("*]", trailing "*").
_PSEUDO_TOOL = re.compile(r"\[\w+\s*\{[^\[\]]*\}\s*\]?")
_TAG_DEBRIS = re.compile(r"(\*+\]|\[+\*+|[\[\]*]+$)")


def _clean_segment(text: str) -> str:
    text = _PSEUDO_TOOL.sub("", text)
    text = _TAG_DEBRIS.sub("", text)
    return text.strip()


def parse_character_output(text: str) -> list[tuple[str, str]]:
    """Split a character's tagged reply into (kind, content) where kind is 'say' or 'do'.
    [say]...[/say] -> speech (dialogue beat); [do]...[/do] -> action (action beat).
    Tolerant: untagged text is treated as speech; text before the first tag as action."""
    text = (text or "").strip()
    if not text:
        return []
    matches = list(_CHAR_TAG.finditer(text))
    if not matches:
        cleaned = _clean_segment(text)
        return [("say", cleaned)] if cleaned else []
    segs: list[tuple[str, str]] = []
    lead = _clean_segment(text[: matches[0].start()])
    if lead:
        segs.append(("do", lead))
    for i, m in enumerate(matches):
        kind = m.group(1).lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = _clean_segment(_CHAR_CLOSE.sub("", text[start:end]))
        if content:
            segs.append((kind, content))
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
    """Run one character turn (POV + tools). Returns the reaction targets to enqueue."""
    creply = llm.chat(
        prompts.build_character_messages(conn, gid, ch, settings.SCENE_BEATS),
        tools=tools.CHARACTER_TOOLS, tool_choice="auto",
        temperature=settings.CHARACTER_TEMPERATURE, max_tokens=settings.CHARACTER_MAX_TOKENS,
    )
    for kind, txt in parse_character_output(creply.content):
        # [say] -> dialogue (speech bubble); [do] -> action (a character's physical action)
        emit(ch["id"], ch["name"], "dialogue" if kind == "say" else "action", txt,
             private_with=private_with)
    reactions = []
    for tc in creply.tool_calls:
        out = tools.apply_tool(conn, gid, tc.name, tc.arguments, actor=ch)
        if out["kind"] == "state" and out["text"]:
            emit("system", None, "system", out["text"], private_with=private_with)
        reactions += out["reactions"]
    return reactions


def run_turn(conn, gid: str, action_text: str = "", segments=None) -> dict:
    turn = repo.next_turn_index(conn, gid)
    seq = 0
    new_beats: list[dict] = []
    spawned: list[str] = []
    ctx_used = 0  # max prompt tokens seen this turn -> the context-usage meter

    def emit(speaker, name, kind, text, private_with=None):
        nonlocal seq
        loc = repo.get_player(conn, gid)["location"]
        b = repo.add_beat(conn, gid, speaker, name, kind, text, loc,
                          turn_index=turn, seq=seq, private_with=private_with)
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
    has_public = bool(public) or bool(action_text)

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
        emit("player", None, "action", action_text or "...")

        # Impossible attempts are rejected deterministically with a friendly in-world beat,
        # BEFORE anything is applied, and the narrator is told they failed (so its prose
        # cannot claim a transfer or a hit that state forbids).
        failures: list[str] = []
        pending: list[dict] = []
        for d in directed:
            if d["tool"] == "_address":
                kind_t, row = repo.resolve_target(conn, gid, d["args"].get("target", ""))
                if kind_t == "character" and row:
                    enqueue([row["id"]])
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

        narrator_action = action_text
        if failures:
            narrator_action = f"{action_text} (failed: {' '.join(failures)})"

        reply = llm.chat(
            prompts.build_narrator_messages(conn, gid, narrator_action, settings.HISTORY_BEATS,
                                            settings.LORE_BUDGET,
                                            attempts=[p["line"] for p in pending]),
            tools=tools.NARRATOR_TOOLS, tool_choice="auto",
            temperature=settings.NARRATOR_TEMPERATURE, max_tokens=settings.NARRATOR_MAX_TOKENS,
        )
        ctx_used = max(ctx_used, (reply.usage or {}).get("prompt_tokens", 0) or 0)

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

        cues, state_notes = [], []
        for tc in reply.tool_calls:
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
        if reply.content:
            emit("narrator", "Narrator", "narration", reply.content)
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
                ctx_used = max(ctx_used, (resolve.usage or {}).get("prompt_tokens", 0) or 0)
                if resolve.content:
                    emit("narrator", "Narrator", "narration", resolve.content)
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

    # ---- private whispers (1:1 asides; other characters never see them) ----
    location = repo.get_player(conn, gid)["location"]
    for w in whispers[: settings.TURN_MAX_ACTOR_STEPS]:
        kind_t, row = repo.resolve_target(conn, gid, (w.get("target") or ""))
        if kind_t != "character" or not row or not row["alive"] or row["location"] != location:
            continue
        text = (w.get("text") or "").strip()
        emit("player", None, "action", f'you whisper to {row["name"]}: "{text}"', private_with=row["id"])
        _character_reply(conn, gid, row, emit, private_with=row["id"])

    if arrival_at_start:
        repo.clear_arrival_note(conn, gid)
    if ctx_used:
        repo.set_context_used(conn, gid, ctx_used)
    return {"beats": new_beats, "state": repo.game_state(conn, gid), "spawned": spawned}
