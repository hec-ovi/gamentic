"""Prompt assembly. This is workstream G.

The prose lives in editable markdown templates under orchestrator/prompts/ (so it
is easy to review and tune without touching code). This module loads them fresh
each call and fills {{placeholders}}; it computes the dynamic sub-blocks (state,
lore, scene transcript) and owns the tool schemas (those are structured, not prose).

Single model, different message stacks:
  - Narrator: omniscient. Full world state, recent history, matched lore. Directs the scene.
  - Character: local POV. Only its persona, private knowledge, and what happens at its location.

Keep prompts lean. Q4 degrades on long context, so history and lore are budgeted hard.
"""
import os

from . import repo, constants

PROMPT_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")


def _load(template: str) -> str:
    # Read fresh every call: editing a .md takes effect on the next turn, no restart.
    with open(os.path.join(PROMPT_DIR, template), encoding="utf-8") as f:
        return f.read()


def render(template: str, **kw) -> str:
    text = _load(template)
    for k, v in kw.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text.strip()


# ---------- shared rendering helpers ----------

def _render_beat(b) -> str:
    speaker = b["speaker"]
    priv = " (privately)" if (b["private_with"] if "private_with" in b.keys() else None) else ""
    if speaker == "narrator":
        return b["text"]
    if speaker == "player":
        return f"PLAYER{priv}: {b['text']}"
    if speaker == "system":
        return f"[{b['text']}]"
    return f"{b['speaker_name']}{priv}: {b['text']}"


def _transcript(beats) -> str:
    return "\n".join(_render_beat(b) for b in beats) if beats else "(the story has not begun)"


def _state_block(conn, gid: str) -> str:
    g = repo.get_game(conn, gid)
    pd = repo.player_dict(repo.get_player(conn, gid))
    inv = ", ".join(f"{i['name']} x{i.get('qty', 1)}" for i in pd["inventory"]) or "empty"

    qlines = []
    for q in repo.get_quests(conn, gid):
        if q["status"] != "active":
            continue
        objs = repo.get_objectives(conn, q["id"])
        ob = "; ".join(f"[{'x' if o['done'] else ' '}] {o['text']} (id={o['id']})" for o in objs)
        qlines.append(f"- {q['title']} (id={q['id']}): {q['description']} {ob}".strip())
    quest_text = "\n".join(qlines) or "none active"

    sc = repo.current_scene(conn, gid)

    def _char_line(c):
        held = ", ".join(i["name"] for i in repo.visible_items(c["inventory"]))
        carry = f", holding {held}" if held else ""
        return (f"{c['name']} ({c['disposition']}{', following you' if c['following'] else ''}, "
                f"{c['life']}/{c['max_life']} hp{carry})")

    present = repo.present_characters(conn, gid, pd["location"])
    pchars = "; ".join(_char_line(c) for c in present) or "no one else"
    # Characters who are alive but NOT in this scene (e.g. a companion left behind, or someone
    # waiting elsewhere). The narrator needs this to stay consistent and to set_following.
    elsewhere = [c for c in repo.get_characters(conn, gid)
                 if c["alive"] and c["location"] != pd["location"]]
    elsewhere_text = "; ".join(f"{c['name']} (at {c['location']}"
                              f"{', following you' if c['following'] else ''})" for c in elsewhere)

    exits = repo.db.loads(sc["exits"], [])
    exit_text = ", ".join(f"{e['label']} -> {e['target']}" for e in exits) or "none yet"
    scene_items = repo.narrator_items(sc["items"]) or "nothing in view"
    new_flag = "" if repo.scene_is_established(sc) else "   <- NEW PLACE"

    t = repo.game_time(conn, gid)
    lines = [
        f"CURRENT GOAL: {g['current_goal'] or 'none yet'}",
        f"TIME: {t['label']}",
        f"LOCATION: {pd['location']}  (scene mood: {sc['status']}){new_flag}",
        f"SCENE DESCRIPTION: {sc['description'] or '(not described yet)'}",
        f"PLAYER LIFE: {pd['life']}/{pd['max_life']}    POINTS: {pd['points']}",
        f"INVENTORY: {inv}",
        f"EXITS: {exit_text}",
        f"ITEMS IN SCENE: {scene_items}",
        f"CHARACTERS PRESENT: {pchars}",
    ]
    if elsewhere_text:
        lines.append(f"CHARACTERS ELSEWHERE: {elsewhere_text}")
    if (g["arrival_note"] or "").strip():
        lines.append(f"RETURNING: {g['arrival_note']}")
    lines.append(f"ACTIVE QUESTS:\n{quest_text}")
    # The narrator is omniscient: it knows each character's secret so it can honor planted
    # facts (a hidden key, a chip under a table) and reveal them when the player earns it.
    # Characters themselves never see another's knowledge; this block is narrator-only.
    secrets = [f"- {c['name']}: {c['knowledge']}" for c in repo.get_characters(conn, gid)
               if c["alive"] and (c["knowledge"] or "").strip()]
    if secrets:
        lines.append("SECRETS (only you know these; let them surface when the player earns it):\n"
                     + "\n".join(secrets))
    if g["memory"]:
        lines.append(f"REMEMBERED FACTS:{g['memory']}")
    return "\n".join(lines)


def _lore_block(conn, gid: str, focus_text: str, budget: int) -> str:
    entries = repo.match_lore(conn, gid, focus_text, budget)
    if not entries:
        return ""
    body = "\n".join(f"- {e['content']}" for e in entries)
    return f"\n\nRELEVANT WORLD FACTS:\n{body}"


# ---------- message builders ----------

def _situation_blocks(conn, gid: str) -> str:
    """Resolver-style dispatch: detailed protocol blocks are injected ONLY when the current
    state triggers them (new place to furnish, a return after absence). The core system
    prompt stays lean; the model reads furnish/returning guidance only on the turns it
    actually applies, which is what a small model can follow."""
    g = repo.get_game(conn, gid)
    sc = repo.current_scene(conn, gid)
    blocks = []
    if not repo.scene_is_established(sc):
        blocks.append(render("narrator.newplace.md"))
    if (g["arrival_note"] or "").strip():
        blocks.append(render("narrator.returning.md"))
    return ("\n\n" + "\n\n".join(blocks)) if blocks else ""


def build_narrator_messages(conn, gid: str, action: str, history_limit: int, lore_budget: int,
                            attempts: list[str] | None = None,
                            looking: bool = False) -> list[dict]:
    g = repo.get_game(conn, gid)
    history = repo.recent_beats(conn, gid, history_limit)
    focus = action + " " + " ".join(_render_beat(b) for b in history[-4:])

    situation = _situation_blocks(conn, gid)
    if looking:
        # the player is LOOKING this turn: inject the looking protocol (describe what a
        # look would find, reveal/discover plausibly, render the view via show_image)
        situation += "\n\n" + render("narrator.looking.md")
    system = render(
        "narrator.system.md",
        narrator_persona=g["narrator_persona"] or "",
        setting=g["setting"] or "unspecified",
        tone=g["tone"] or "cinematic",
        situation=situation,
        world_rules=constants.world_rules(),
        state=_state_block(conn, gid),
        lore=_lore_block(conn, gid, focus, lore_budget),
    )
    # The player's mechanical attempts (attack/give), numbered for adjudication. Only
    # rendered when there are any; the engine default-accepts whatever goes unaddressed.
    attempts_block = ""
    if attempts:
        lines = "\n".join(f"{i + 1}. {a}" for i, a in enumerate(attempts))
        attempts_block = "\n" + render("narrator.attempts.md", attempts=lines) + "\n"
    user = render("narrator.user.md", transcript=_transcript(history), action=action,
                  attempts_block=attempts_block)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_narrator_resolve_messages(conn, gid: str, action: str, changes: list[str]) -> list[dict]:
    """Second narrator pass: when the first call changed state via tools but wrote no prose,
    ask ONLY for a short line of narration that voices what just happened. No tools, no
    dialogue (characters speak for themselves). This is what kills dead-air turns."""
    g = repo.get_game(conn, gid)
    system = render(
        "narrator.resolve.md",
        narrator_persona=g["narrator_persona"] or "",
        setting=g["setting"] or "unspecified",
        tone=g["tone"] or "cinematic",
        state=_state_block(conn, gid),
    )
    change_text = "\n".join(f"- {c}" for c in changes) or "- (no mechanical change)"
    user = render("narrator.resolve.user.md", action=action, changes=change_text)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_character_messages(conn, gid: str, character, scene_limit: int) -> list[dict]:
    location = repo.get_player(conn, gid)["location"]
    scene = repo.scene_beats_for_character(conn, gid, location, character["id"], scene_limit)
    knowledge_block = (
        f"\nWHAT YOU PRIVATELY KNOW: {character['knowledge']}" if character["knowledge"] else ""
    )
    system = render(
        "character.system.md",
        name=character["name"],
        persona=character["persona"],
        knowledge_block=knowledge_block,
    )
    user = render("character.user.md", location=location, scene=_transcript(scene), name=character["name"])
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ---------- 'ask what this is' (tap-to-explain) ----------

def _explain_facts(conn, gid: str, kind: str, key: str, beat_id: str | None) -> str | None:
    """PLAYER-VISIBLE facts about the tapped thing, or None if nothing visible matches.
    Spoiler-safe by construction: only revealed items, public bios, known state. Never
    character knowledge/persona, never hidden items."""
    pd = repo.player_dict(repo.get_player(conn, gid))
    sc = repo.current_scene(conn, gid)
    if kind == "item":
        places = [("in your pack", pd["inventory"]),
                  ("here in the scene", repo.visible_items(sc["items"]))]
        for c in repo.present_characters(conn, gid, pd["location"]):
            places.append((f"carried by {c['name']}", repo.visible_items(c["inventory"])))
        for where, items in places:
            for it in items:
                if repo._item_matches(it, key):
                    qty = it.get("qty", 1)
                    fixed = " It is part of the place and cannot be carried." if it.get("fixed") else ""
                    return (f"- {it['name']}{f' x{qty}' if qty and qty > 1 else ''}, {where}: "
                            f"{it.get('description') or 'nothing more is known about it yet'}.{fixed}")
        return None
    if kind == "character":
        kt, row = repo.resolve_target(conn, gid, key)
        if kt != "character" or not row:
            return None
        held = ", ".join(i["name"] for i in repo.visible_items(row["inventory"])) or "nothing you have seen"
        here = "here with you" if row["present"] and row["location"] == pd["location"] \
            else f"elsewhere (at {row['location']})"
        return (f"- {row['name']}: {row['description'] or 'no public description yet'}\n"
                f"- toward you: {row['disposition']}; "
                f"{'traveling with you' if row['following'] else 'not following you'}; {here}\n"
                f"- life: {row['life']}/{row['max_life']}{'' if row['alive'] else ' (dead)'}\n"
                f"- visibly carrying: {held}")
    if kind == "scene":
        items = ", ".join(i["name"] for i in repo.visible_items(sc["items"])) or "nothing in view"
        exits = ", ".join(e["label"] for e in repo.db.loads(sc["exits"], [])) or "no way out revealed"
        t = repo.game_time(conn, gid)
        return (f"- {sc['name']} (mood: {sc['status']}), {t['label']}\n"
                f"- {sc['description'] or 'not yet described'}\n"
                f"- in view: {items}\n- ways out: {exits}")
    if kind in ("quest", "objective"):
        for q in repo.get_quests(conn, gid):
            qd = repo.quest_dict(conn, q)
            ids = {q["id"], (q["title"] or "").lower()} | {o["id"] for o in qd["objectives"]}
            if key and key.lower() not in {i.lower() if isinstance(i, str) else i for i in ids}:
                continue
            obs = "\n".join(f"  - [{'x' if o['done'] else ' '}] {o['text']}"
                            + (f" ({o['progress']})" if o.get("progress") else "")
                            for o in qd["objectives"])
            return f"- quest: {q['title']} ({qd['status']}): {q['description']}\n{obs}"
        return None
    if kind == "goal":
        g = repo.get_game(conn, gid)
        return f"- your current goal: {g['current_goal'] or 'none set yet'}"
    if kind == "beat":
        row = conn.execute("SELECT * FROM beats WHERE id=? AND game_id=?",
                           (beat_id or key, gid)).fetchone()
        if not row:
            return None
        around = conn.execute(
            "SELECT * FROM beats WHERE game_id=? AND private_with IS NULL "
            "AND turn_index BETWEEN ? AND ? ORDER BY turn_index, seq",
            (gid, row["turn_index"] - 1, row["turn_index"])).fetchall()
        ctx = "\n".join(_render_beat(b) for b in around[-8:])
        return (f"- the moment they tapped: \"{row['text']}\"\n"
                f"- what was happening around it:\n{ctx}")
    return None


def build_explain_messages(conn, gid: str, kind: str, key: str | None = None,
                           beat_id: str | None = None) -> list[dict] | None:
    facts = _explain_facts(conn, gid, (kind or "").strip().lower(), (key or "").strip(), beat_id)
    if not facts:
        return None
    return [
        {"role": "system", "content": render("explain.system.md")},
        {"role": "user", "content": render("explain.user.md", kind=kind, facts=facts)},
    ]


# ---------- agentic input interpreter ----------

INTERPRET_TOOL = [{
    "type": "function",
    "function": {
        "name": "submit_segments",
        "description": "Submit the player's message as ordered action segments.",
        "parameters": {
            "type": "object",
            "properties": {
                "segments": {"type": "array", "items": {"type": "object", "properties": {
                    "type": {"type": "string",
                             "enum": ["say", "do", "attack", "give", "whisper", "look"]},
                    "text": {"type": "string"},
                    "target": {"type": "string", "description": "Character name, when directed."},
                    "item": {"type": "string", "description": "For give: the item handed over."},
                    "amount": {"type": "integer", "description": "For attack: only if force is named."},
                    "mode": {"type": "string", "enum": ["say", "do"],
                             "description": "For whisper: words or a discreet act."},
                }, "required": ["type"]}},
            },
            "required": ["segments"],
        },
    },
}]


def build_interpret_messages(conn, gid: str, message: str) -> list[dict]:
    """The interpreter 'skill' is loaded ONLY for this one call (resolver doctrine):
    parse a freeform typed action into structured segments, grounded in who is present
    and what the player carries so names resolve."""
    pd = repo.get_player(conn, gid)
    chars = ", ".join(c["name"] for c in repo.present_characters(conn, gid, pd["location"])) or "no one"
    inv = ", ".join(i["name"] for i in repo.db.loads(pd["inventory"], [])) or "nothing"
    return [
        {"role": "system", "content": render("interpret.system.md")},
        {"role": "user", "content": render("interpret.user.md", characters=chars,
                                           inventory=inv, message=message)},
    ]


# ---------- agentic image prompts ----------

def build_image_prompt_messages(context: str) -> list[dict]:
    """The image-prompt 'skill': loaded ONLY for this one call (the FLUX recipe + a worked
    example), never present in any story context. See integrate._agentic_prompt."""
    return [
        {"role": "system", "content": render("imageprompt.system.md")},
        {"role": "user", "content": render("imageprompt.user.md", context=context)},
    ]


# ---------- story creator ----------

def build_creator_messages(history: list[dict], message: str) -> list[dict]:
    msgs = [{"role": "system", "content": render("creator.system.md")}]
    msgs.extend(history)
    msgs.append({"role": "user", "content": message})
    return msgs


def build_finalize_messages(history: list[dict]) -> list[dict]:
    convo = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in history)
    return [
        {"role": "system", "content": render("finalize.system.md")},
        {"role": "user", "content": render("finalize.user.md", convo=convo)},
    ]


# ---------- tool schema (structured, stays in code) ----------

FINALIZE_TOOL = [{
    "type": "function",
    "function": {
        "name": "save_world",
        "description": "Persist the designed world as a structured WorldSheet to start the game.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "setting": {"type": "string"},
                "tone": {"type": "string"},
                "art_style": {"type": "string",
                              "description": "Visual art style/theme applied to all generated images."},
                "narrator_persona": {"type": "string",
                                     "description": "Voice/style guidance for the Narrator."},
                "opening_scenario": {"type": "string",
                                     "description": "The opening narration shown to the player."},
                "start_location": {"type": "string"},
                "player_life": {"type": "integer"},
                "characters": {"type": "array", "items": {"type": "object", "properties": {
                    "name": {"type": "string"},
                    "persona": {"type": "string", "description": "Who they are and how they behave (agent context)."},
                    "description": {"type": "string", "description": "One short public line shown in the UI."},
                    "knowledge": {"type": "string"},
                    "appearance": {"type": "string",
                                   "description": "Visual description for the character reference images. "
                                                  "Start with explicit sex and rough age ('a young woman "
                                                  "with...', 'a grizzled old man...') and keep every feature "
                                                  "unmistakably matching it. Looks only (face, build, hair, "
                                                  "clothing); never include words, signs or symbols to draw."},
                    "disposition": {"type": "string", "enum": list(constants.DISPOSITIONS),
                                    "description": "How they feel toward the player to start."},
                }, "required": ["name", "persona", "description"]}},
                "quests": {"type": "array", "items": {"type": "object", "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "objectives": {"type": "array", "items": {"type": "string"}},
                }, "required": ["title"]}},
                "lore": {"type": "array", "items": {"type": "object", "properties": {
                    "keys": {"type": "array", "items": {"type": "string"}},
                    "content": {"type": "string"},
                    "constant": {"type": "boolean"},
                }, "required": ["content"]}},
            },
            "required": ["title", "opening_scenario", "characters", "quests"],
        },
    },
}]
