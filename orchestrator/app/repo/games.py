"""Game rows: creation, lookup, lifecycle, and game-level fields (goal, memory,
status, settings, the context meter)."""
import json

from ..models import WorldSheet
from . import beats, scenes
from .base import _id, norm_name


def create_game(conn, sheet: WorldSheet) -> str:
    gid = _id()
    start = norm_name(sheet.start_location)
    conn.execute(
        "INSERT INTO games (id, title, setting, tone, art_style, narrator_voice_id, "
        "narrator_persona, opening_scenario) VALUES (?,?,?,?,?,?,?,?)",
        (gid, sheet.title, sheet.setting, sheet.tone, sheet.art_style,
         sheet.narrator_voice_id, sheet.narrator_persona, sheet.opening_scenario),
    )
    conn.execute(
        "INSERT INTO player_state (game_id, life, max_life, location) VALUES (?,?,?,?)",
        (gid, sheet.player_life, sheet.player_life, start),
    )
    from . import characters as _chars
    for c in sheet.characters:
        # gender is decided ONCE here (explicit field, else inferred from the sheet) and
        # stored, so the portrait, the narrator's pronouns and the voice always agree
        gender = (c.gender or "").strip().lower()
        if gender not in ("female", "male"):
            gender = _chars.gender_hint(c.appearance, c.description, c.persona, c.name)
        conn.execute(
            "INSERT INTO characters (id, game_id, name, persona, description, knowledge, appearance, "
            "voice_id, color, talkativeness, location, life, max_life, disposition, following, "
            "gender, origin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_id(), gid, c.name, c.persona, c.description, c.knowledge, c.appearance,
             c.voice_id, c.color, c.talkativeness, start, c.life, c.max_life,
             c.disposition, 1 if c.following else 0, gender, c.origin),
        )
    for q in sheet.quests:
        qid = _id()
        conn.execute(
            "INSERT INTO quests (id, game_id, title, description) VALUES (?,?,?,?)",
            (qid, gid, q.title, q.description),
        )
        for text in q.objectives:
            conn.execute(
                "INSERT INTO objectives (id, quest_id, text) VALUES (?,?,?)",
                (_id(), qid, text),
            )
    for lo in sheet.lore:
        conn.execute(
            "INSERT INTO lore (id, game_id, keys, content, constant, priority) VALUES (?,?,?,?,?,?)",
            (_id(), gid, json.dumps(lo.keys), lo.content, int(lo.constant), lo.priority),
        )
    # Seed the opening scene from the OPENING SCENARIO (the actual place and moment),
    # not the setting: the setting is the whole world's cosmology ("a multiverse of
    # dying worlds"), and seeding it here made the opening scene art depict the
    # universe instead of the place the player is standing in (live-found).
    scenes.get_or_create_scene(conn, gid, start, sheet.opening_scenario or sheet.setting)
    # Seed an opening goal so the player always has a current purpose from turn 0
    # (the narrator updates it as the story turns). Prefer the first quest's first objective.
    if sheet.quests:
        q0 = sheet.quests[0]
        goal = (q0.objectives[0] if q0.objectives else "") or q0.title
        if goal:
            conn.execute("UPDATE games SET current_goal=? WHERE id=?", (goal, gid))
    if sheet.opening_scenario:
        beats.add_beat(conn, gid, "narrator", "Narrator", "narration",
                       sheet.opening_scenario, start)
    return gid


def get_game(conn, gid: str):
    return conn.execute("SELECT * FROM games WHERE id=?", (gid,)).fetchone()


def list_games(conn):
    return conn.execute("SELECT id, title, status, created_at FROM games ORDER BY created_at DESC").fetchall()


def delete_game(conn, gid: str) -> bool:
    """Wipe an entire game session and everything attached to it."""
    if not get_game(conn, gid):
        return False
    qids = [r["id"] for r in conn.execute("SELECT id FROM quests WHERE game_id=?", (gid,)).fetchall()]
    for qid in qids:
        conn.execute("DELETE FROM objectives WHERE quest_id=?", (qid,))
    for tbl in ("beats", "characters", "scenes", "quests", "lore", "player_state"):
        conn.execute(f"DELETE FROM {tbl} WHERE game_id=?", (gid,))
    conn.execute("DELETE FROM games WHERE id=?", (gid,))
    return True


def append_memory(conn, gid: str, note: str) -> None:
    row = get_game(conn, gid)
    memory = (row["memory"] or "")
    memory = (memory + "\n- " + note).strip()
    conn.execute("UPDATE games SET memory=? WHERE id=?", (memory, gid))


def clear_arrival_note(conn, gid: str) -> None:
    conn.execute("UPDATE games SET arrival_note='' WHERE id=?", (gid,))


def set_game_status(conn, gid: str, status: str) -> None:
    conn.execute("UPDATE games SET status=? WHERE id=?", (status, gid))


def set_goal(conn, gid: str, goal: str) -> None:
    conn.execute("UPDATE games SET current_goal=? WHERE id=?", (goal, gid))


def set_difficulty(conn, gid: str, difficulty: str) -> None:
    conn.execute("UPDATE games SET difficulty=? WHERE id=?", (difficulty, gid))


def set_narrator_gender(conn, gid: str, gender: str) -> None:
    conn.execute("UPDATE games SET narrator_gender=? WHERE id=?", (gender, gid))


def set_narrator_voice(conn, gid: str, voice_id: str) -> None:
    conn.execute("UPDATE games SET narrator_voice_id=? WHERE id=?", (voice_id, gid))


def set_context_used(conn, gid: str, used: int) -> None:
    """Record the last turn's prompt-token count for the context-usage meter."""
    conn.execute("UPDATE games SET context_used=? WHERE id=?", (int(used or 0), gid))


def set_story_summary(conn, gid: str, text: str, through_turn: int) -> None:
    """Store the updated rolling recap and the turn it covers through."""
    conn.execute("UPDATE games SET story_summary=?, summarized_through=? WHERE id=?",
                 (text, int(through_turn), gid))


def set_history_beats(conn, gid: str, beats: int) -> None:
    """Per-game verbatim-window override (0 = the settings default)."""
    conn.execute("UPDATE games SET history_beats=? WHERE id=?", (int(beats), gid))


def effective_history_beats(g) -> int:
    from ..config import settings
    stored = (g["history_beats"] or 0) if "history_beats" in g.keys() else 0
    return stored or settings.HISTORY_BEATS
