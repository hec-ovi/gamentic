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


def parse_character_output(text: str) -> list[tuple[str, str]]:
    """Split a character's tagged reply into (kind, content) where kind is 'say' or 'do'.
    [say]...[/say] -> speech (dialogue beat); [do]...[/do] -> action (action beat).
    Tolerant: untagged text is treated as speech; text before the first tag as action."""
    text = (text or "").strip()
    if not text:
        return []
    matches = list(_CHAR_TAG.finditer(text))
    if not matches:
        return [("say", text)]
    segs: list[tuple[str, str]] = []
    lead = text[: matches[0].start()].strip()
    if lead:
        segs.append(("do", lead))
    for i, m in enumerate(matches):
        kind = m.group(1).lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = _CHAR_CLOSE.sub("", text[start:end]).strip()
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
            directed.append({"tool": "attack", "args": {"target": target, "amount": s.get("amount")}})
        elif t == "give":
            parts.append(f"you give {_display(s, item)} to {_display(s, target) if target else 'them'}")
            directed.append({"tool": "give_item", "args": {"item": item, "target": target}})
        else:  # do
            parts.append(text or "you wait")
    return "; ".join(p for p in parts if p), directed


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

    # ---- public turn (narrator + cascade) ----
    if has_public:
        action_text, directed = _compose(public) if public else (action_text, [])
        emit("player", None, "action", action_text or "...")

        for d in directed:
            if d["tool"] == "_address":
                kind_t, row = repo.resolve_target(conn, gid, d["args"].get("target", ""))
                if kind_t == "character" and row:
                    enqueue([row["id"]])
                continue
            out = tools.apply_tool(conn, gid, d["tool"], d["args"], actor=None)
            if out["kind"] == "state" and out["text"]:
                emit("system", None, "system", out["text"])
            enqueue(out["reactions"])

        reply = llm.chat(
            prompts.build_narrator_messages(conn, gid, action_text, settings.HISTORY_BEATS, settings.LORE_BUDGET),
            tools=tools.NARRATOR_TOOLS, tool_choice="auto",
            temperature=settings.NARRATOR_TEMPERATURE, max_tokens=settings.NARRATOR_MAX_TOKENS,
        )
        ctx_used = max(ctx_used, (reply.usage or {}).get("prompt_tokens", 0) or 0)
        cues, state_notes = [], []
        for tc in reply.tool_calls:
            out = tools.apply_tool(conn, gid, tc.name, tc.arguments, actor=None)
            if out["kind"] == "cue" and out["cue"]:
                cues.append(out["cue"])
            elif out["kind"] == "spawn":
                spawned.append(out["cue"]["id"])
                if out["text"]:
                    state_notes.append(out["text"])
                cues.append(out["cue"])
            elif out["kind"] in ("state", "kill") and out["text"]:
                state_notes.append(out["text"])
        if reply.content:
            emit("narrator", "Narrator", "narration", reply.content)
        else:
            # No prose, but state changed (move/furnish/pickup) or nothing else will speak:
            # a short resolve pass voices the outcome so the turn is never dead air.
            will_speak = bool(cues) or bool(queue)
            if state_notes or not will_speak:
                resolve = llm.chat(
                    prompts.build_narrator_resolve_messages(conn, gid, action_text, state_notes),
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

    if ctx_used:
        repo.set_context_used(conn, gid, ctx_used)
    return {"beats": new_beats, "state": repo.game_state(conn, gid), "spawned": spawned}
