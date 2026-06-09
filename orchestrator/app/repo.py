"""Data access. Plain SQL helpers over the connection from db.get_conn().

Functions take an open sqlite3.Connection so the engine controls the
transaction boundary (one turn = one commit).
"""
import json
import uuid

from . import db
from .config import settings
from .models import WorldSheet


def visible_items(value) -> list[dict]:
    """Revealed items only, shaped for the UI. Hidden items are omitted entirely.
    `fixed` marks scenery (an altar, a lever) the player can see but cannot pocket."""
    out = []
    for it in db.loads(value, []):
        if it.get("hidden"):
            continue
        out.append({"id": it.get("id"), "name": it["name"],
                    "description": it.get("description", ""), "image_url": it.get("image_url"),
                    "fixed": bool(it.get("fixed", False))})
    return out


def narrator_items(value) -> str:
    """A compact item listing for the NARRATOR's state block: includes hidden and fixed
    items (marked), so the narrator can reason about what is here and reveal it logically.
    The player UI never sees this; it uses visible_items()."""
    parts = []
    for it in db.loads(value, []):
        tags = []
        if it.get("hidden"):
            tags.append("hidden")
        if it.get("fixed"):
            tags.append("fixed")
        suffix = f" [{', '.join(tags)}]" if tags else ""
        parts.append(it["name"] + suffix)
    return ", ".join(parts)


def _id() -> str:
    return uuid.uuid4().hex[:12]


# ---------- creation ----------

def create_game(conn, sheet: WorldSheet) -> str:
    gid = _id()
    conn.execute(
        "INSERT INTO games (id, title, setting, tone, art_style, narrator_voice_id, "
        "narrator_persona, opening_scenario) VALUES (?,?,?,?,?,?,?,?)",
        (gid, sheet.title, sheet.setting, sheet.tone, sheet.art_style,
         sheet.narrator_voice_id, sheet.narrator_persona, sheet.opening_scenario),
    )
    conn.execute(
        "INSERT INTO player_state (game_id, life, max_life, location) VALUES (?,?,?,?)",
        (gid, sheet.player_life, sheet.player_life, sheet.start_location),
    )
    for c in sheet.characters:
        conn.execute(
            "INSERT INTO characters (id, game_id, name, persona, description, knowledge, appearance, "
            "voice_id, color, talkativeness, location, life, max_life, disposition, following) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_id(), gid, c.name, c.persona, c.description, c.knowledge, c.appearance,
             c.voice_id, c.color, c.talkativeness, sheet.start_location, c.life, c.max_life,
             c.disposition, 1 if c.following else 0),
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
    get_or_create_scene(conn, gid, sheet.start_location, sheet.setting or sheet.opening_scenario)
    # Seed an opening goal so the player always has a current purpose from turn 0
    # (the narrator updates it as the story turns). Prefer the first quest's first objective.
    if sheet.quests:
        q0 = sheet.quests[0]
        goal = (q0.objectives[0] if q0.objectives else "") or q0.title
        if goal:
            conn.execute("UPDATE games SET current_goal=? WHERE id=?", (goal, gid))
    if sheet.opening_scenario:
        add_beat(conn, gid, "narrator", "Narrator", "narration",
                 sheet.opening_scenario, sheet.start_location)
    return gid


def scene_is_established(sc) -> bool:
    """A scene is 'established' once the narrator has furnished it (given it a description).
    A fresh scene the player just entered has an empty description; the state block flags it
    NEW so the narrator knows to describe it, set its mood, and reveal a way onward."""
    return bool((sc["description"] or "").strip())


# ---------- games ----------

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


def clear_beats(conn, gid: str) -> None:
    """Clear the story log (history) of a game, keeping its current state."""
    conn.execute("DELETE FROM beats WHERE game_id=?", (gid,))


def append_memory(conn, gid: str, note: str) -> None:
    row = get_game(conn, gid)
    memory = (row["memory"] or "")
    memory = (memory + "\n- " + note).strip()
    conn.execute("UPDATE games SET memory=? WHERE id=?", (memory, gid))


# ---------- player state ----------

def get_player(conn, gid: str):
    return conn.execute("SELECT * FROM player_state WHERE game_id=?", (gid,)).fetchone()


def player_dict(row) -> dict:
    return {
        "life": row["life"],
        "max_life": row["max_life"],
        "points": row["points"],
        "location": row["location"],
        "inventory": db.loads(row["inventory"], []),
        "flags": db.loads(row["flags"], {}),
    }


def set_life(conn, gid: str, delta: int) -> int:
    p = get_player(conn, gid)
    new = max(0, min(p["max_life"], p["life"] + delta))
    conn.execute("UPDATE player_state SET life=? WHERE game_id=?", (new, gid))
    return new


def add_points(conn, gid: str, amount: int) -> int:
    p = get_player(conn, gid)
    new = p["points"] + amount
    conn.execute("UPDATE player_state SET points=? WHERE game_id=?", (new, gid))
    return new


def add_item(conn, gid: str, name: str, description: str = "", qty: int = 1) -> None:
    p = get_player(conn, gid)
    inv = db.loads(p["inventory"], [])
    for it in inv:
        if it["name"].lower() == name.lower():
            it["qty"] = it.get("qty", 1) + qty
            break
    else:
        inv.append({"name": name, "description": description, "qty": qty})
    conn.execute("UPDATE player_state SET inventory=? WHERE game_id=?", (json.dumps(inv), gid))


def remove_item(conn, gid: str, name: str, qty: int = 1) -> bool:
    p = get_player(conn, gid)
    inv = db.loads(p["inventory"], [])
    for it in inv:
        if it["name"].lower() == name.lower():
            it["qty"] = it.get("qty", 1) - qty
            if it["qty"] <= 0:
                inv.remove(it)
            conn.execute("UPDATE player_state SET inventory=? WHERE game_id=?", (json.dumps(inv), gid))
            return True
    return False  # nothing removed; caller decides how to handle


def _ensure_exit(conn, gid: str, scene_name: str, label: str, target: str) -> None:
    """Add an exit to a scene if it doesn't already lead to `target` (dedup by target)."""
    sc = get_scene(conn, gid, scene_name)
    if not sc:
        return
    exits = db.loads(sc["exits"], [])
    if any(e["target"].lower() == target.lower() for e in exits):
        return
    exits.append({"id": _id(), "label": label, "target": target})
    conn.execute("UPDATE scenes SET exits=? WHERE id=?", (json.dumps(exits), sc["id"]))


def set_location(conn, gid: str, location: str) -> None:
    prev = get_player(conn, gid)["location"]
    get_or_create_scene(conn, gid, location)   # the destination scene persists
    conn.execute("UPDATE player_state SET location=? WHERE game_id=?", (location, gid))
    # Only FOLLOWING characters travel with the player. Everyone else stays at their scene
    # (and is there again if the player returns) - this is the scene-persistence behaviour.
    conn.execute("UPDATE characters SET location=? WHERE game_id=? AND following=1 AND alive=1",
                 (location, gid))
    # Always leave a way back so the player can never get stranded.
    if prev and prev.lower() != location.lower():
        _ensure_exit(conn, gid, location, label=f"back to {prev}", target=prev)


def set_flag(conn, gid: str, key: str, value: str) -> None:
    p = get_player(conn, gid)
    flags = db.loads(p["flags"], {})
    flags[key] = value
    conn.execute("UPDATE player_state SET flags=? WHERE game_id=?", (json.dumps(flags), gid))


# ---------- characters ----------

def get_characters(conn, gid: str):
    return conn.execute("SELECT * FROM characters WHERE game_id=?", (gid,)).fetchall()


def present_characters(conn, gid: str, location: str):
    return conn.execute(
        "SELECT * FROM characters WHERE game_id=? AND present=1 AND location=?",
        (gid, location),
    ).fetchall()


def find_character_by_name(conn, gid: str, name: str):
    return conn.execute(
        "SELECT * FROM characters WHERE game_id=? AND lower(name)=lower(?)",
        (gid, name.strip()),
    ).fetchone()


def set_character_images(conn, char_id: str, face_url=None, body_front_url=None, body_side_url=None) -> None:
    conn.execute(
        "UPDATE characters SET face_url=?, body_front_url=?, body_side_url=? WHERE id=?",
        (face_url, body_front_url, body_side_url, char_id),
    )


def character_has_images(c) -> bool:
    return bool(c["face_url"] or c["body_front_url"] or c["body_side_url"])


def set_character_voice(conn, char_id: str, voice_id: str) -> None:
    conn.execute("UPDATE characters SET voice_id=? WHERE id=?", (voice_id, char_id))


def set_narrator_voice(conn, gid: str, voice_id: str) -> None:
    conn.execute("UPDATE games SET narrator_voice_id=? WHERE id=?", (voice_id, gid))


def get_character(conn, cid: str):
    return conn.execute("SELECT * FROM characters WHERE id=?", (cid,)).fetchone()


def resolve_target(conn, gid: str, name: str):
    """Map a target name to ('player', None) | ('character', row) | (None, None)."""
    n = (name or "").strip().lower()
    if n in ("player", "you", "me", "the player", "hero", "protagonist"):
        return ("player", None)
    if not n:
        return (None, None)
    ch = conn.execute("SELECT * FROM characters WHERE game_id=? AND lower(name)=lower(?)",
                      (gid, n)).fetchone()
    return ("character", ch) if ch else (None, None)


def set_character_life(conn, cid: str, delta: int):
    """Apply a life delta to a character. Returns (new_life, died: bool). At 0 the character dies."""
    c = get_character(conn, cid)
    new = max(0, min(c["max_life"], c["life"] + delta))
    died = new <= 0
    conn.execute("UPDATE characters SET life=?, alive=?, present=? WHERE id=?",
                 (new, 0 if died else 1, 0 if died else c["present"], cid))
    return new, died


def character_add_item(conn, cid: str, name: str, description: str = "",
                       hidden: bool = False, qty: int = 1, cap: int | None = None) -> str:
    c = get_character(conn, cid)
    inv = db.loads(c["inventory"], [])
    for it in inv:
        if it["name"].lower() == name.lower():
            it["qty"] = it.get("qty", 1) + qty
            break
    else:
        if cap is not None and len(inv) >= cap:
            return "full"
        inv.append({"id": _id(), "name": name, "description": description,
                    "image_url": None, "hidden": bool(hidden), "qty": qty})
    conn.execute("UPDATE characters SET inventory=? WHERE id=?", (json.dumps(inv), cid))
    return "ok"


def character_reveal_item(conn, cid: str, name: str) -> bool:
    c = get_character(conn, cid)
    inv = db.loads(c["inventory"], [])
    for it in inv:
        if it["name"].lower() == name.lower() and it.get("hidden"):
            it["hidden"] = False
            conn.execute("UPDATE characters SET inventory=? WHERE id=?", (json.dumps(inv), cid))
            return True
    return False


def character_remove_item(conn, cid: str, name: str, qty: int = 1) -> bool:
    c = get_character(conn, cid)
    inv = db.loads(c["inventory"], [])
    for it in inv:
        if it["name"].lower() == name.lower():
            it["qty"] = it.get("qty", 1) - qty
            if it["qty"] <= 0:
                inv.remove(it)
            conn.execute("UPDATE characters SET inventory=? WHERE id=?", (json.dumps(inv), cid))
            return True
    return False


def spawn_character(conn, gid: str, name: str, persona: str, appearance: str = "",
                    knowledge: str = "", location: str | None = None,
                    life: int = 10) -> str:
    """Add a character to the game on the fly (dynamic narrator)."""
    if location is None:
        location = get_player(conn, gid)["location"]
    cid = _id()
    conn.execute(
        "INSERT INTO characters (id, game_id, name, persona, knowledge, appearance, "
        "location, life, max_life, present) VALUES (?,?,?,?,?,?,?,?,?,1)",
        (cid, gid, name, persona, knowledge, appearance, location, life, life),
    )
    return cid


def kill_character(conn, cid: str) -> None:
    conn.execute("UPDATE characters SET alive=0, present=0, life=0 WHERE id=?", (cid,))


def set_disposition(conn, cid: str, disposition: str) -> None:
    conn.execute("UPDATE characters SET disposition=? WHERE id=?", (disposition, cid))


def set_following(conn, cid: str, following: bool) -> None:
    conn.execute("UPDATE characters SET following=? WHERE id=?", (1 if following else 0, cid))


def set_game_status(conn, gid: str, status: str) -> None:
    conn.execute("UPDATE games SET status=? WHERE id=?", (status, gid))


def set_goal(conn, gid: str, goal: str) -> None:
    conn.execute("UPDATE games SET current_goal=? WHERE id=?", (goal, gid))


def set_character_description(conn, cid: str, description: str) -> None:
    conn.execute("UPDATE characters SET description=? WHERE id=?", (description, cid))


def offer_action(conn, cid: str, label: str, cap_total: int) -> bool:
    """Add a narrator-offered contextual action to a character, within the total-action cap."""
    from . import constants
    c = get_character(conn, cid)
    base = len(constants.ACTIONS_BY_DISPOSITION.get(c["disposition"], []))
    offers = db.loads(c["offers"], [])
    if base + len(offers) >= cap_total:
        return False
    if any(o["label"].lower() == label.lower() for o in offers):
        return True
    offers.append({"id": _id(), "label": label})
    conn.execute("UPDATE characters SET offers=? WHERE id=?", (json.dumps(offers), cid))
    return True


def available_actions(conn, c, cap_total: int) -> list[dict]:
    """The player's action buttons for a character: disposition base set + narrator offers, capped."""
    from . import constants
    base = [{"id": f"b{i}", "label": lbl, "type": typ}
            for i, (lbl, typ) in enumerate(constants.ACTIONS_BY_DISPOSITION.get(c["disposition"], []))]
    offers = [{"id": o["id"], "label": o["label"], "type": "offer"} for o in db.loads(c["offers"], [])]
    return (base + offers)[:cap_total]


# ---------- scenes (the main card) ----------

def get_scene(conn, gid: str, name: str):
    return conn.execute("SELECT * FROM scenes WHERE game_id=? AND lower(name)=lower(?)",
                        (gid, name)).fetchone()


def get_or_create_scene(conn, gid: str, name: str, description: str = ""):
    from .constants import SCENE_STATUS_DEFAULT
    sc = get_scene(conn, gid, name)
    if sc:
        return sc
    conn.execute("INSERT INTO scenes (id, game_id, name, description, status) VALUES (?,?,?,?,?)",
                 (_id(), gid, name, description, SCENE_STATUS_DEFAULT))
    return get_scene(conn, gid, name)


def current_scene(conn, gid: str):
    return get_or_create_scene(conn, gid, get_player(conn, gid)["location"])


def get_scene_by_id(conn, scene_id: str):
    return conn.execute("SELECT * FROM scenes WHERE id=?", (scene_id,)).fetchone()


def set_scene_image(conn, scene_id: str, url: str) -> None:
    conn.execute("UPDATE scenes SET image_url=? WHERE id=?", (url, scene_id))


def set_scene_status(conn, gid: str, status: str) -> None:
    conn.execute("UPDATE scenes SET status=? WHERE id=?", (status, current_scene(conn, gid)["id"]))


def set_scene_description(conn, gid: str, description: str) -> None:
    conn.execute("UPDATE scenes SET description=? WHERE id=?", (description, current_scene(conn, gid)["id"]))


def add_exit(conn, gid: str, label: str, target: str, cap: int) -> str:
    sc = current_scene(conn, gid)
    exits = db.loads(sc["exits"], [])
    if any(e["target"].lower() == target.lower() for e in exits):
        return "exists"
    if len(exits) >= cap:
        return "full"
    exits.append({"id": _id(), "label": label, "target": target})
    conn.execute("UPDATE scenes SET exits=? WHERE id=?", (json.dumps(exits), sc["id"]))
    return "ok"


def add_scene_item(conn, gid: str, name: str, description: str, hidden: bool, cap: int,
                   fixed: bool = False) -> str:
    sc = current_scene(conn, gid)
    items = db.loads(sc["items"], [])
    if any(i["name"].lower() == name.lower() for i in items):
        return "exists"
    if len(items) >= cap:
        return "full"
    items.append({"id": _id(), "name": name, "description": description,
                  "image_url": None, "hidden": bool(hidden), "fixed": bool(fixed)})
    conn.execute("UPDATE scenes SET items=? WHERE id=?", (json.dumps(items), sc["id"]))
    return "ok"


def reveal_scene_item(conn, gid: str, name: str) -> bool:
    sc = current_scene(conn, gid)
    items = db.loads(sc["items"], [])
    for it in items:
        if it["name"].lower() == name.lower() and it.get("hidden"):
            it["hidden"] = False
            conn.execute("UPDATE scenes SET items=? WHERE id=?", (json.dumps(items), sc["id"]))
            return True
    return False


def take_scene_item(conn, gid: str, name: str) -> str:
    """Move a REVEALED, non-fixed scene item into the player's inventory.
    Returns 'ok' | 'fixed' (scenery, can't be pocketed) | 'missing'."""
    sc = current_scene(conn, gid)
    items = db.loads(sc["items"], [])
    for it in items:
        if it["name"].lower() == name.lower() and not it.get("hidden"):
            if it.get("fixed"):
                return "fixed"
            items.remove(it)
            conn.execute("UPDATE scenes SET items=? WHERE id=?", (json.dumps(items), sc["id"]))
            add_item(conn, gid, it["name"], it.get("description", ""))
            return "ok"
    return "missing"


def scene_available_actions(conn, sc, cap_total: int) -> list[dict]:
    from . import constants
    base = [{"id": f"s{i}", "label": lbl, "type": typ}
            for i, (lbl, typ) in enumerate(constants.SCENE_BASE_ACTIONS)]
    offers = [{"id": o["id"], "label": o["label"], "type": "offer"} for o in db.loads(sc["offers"], [])]
    return (base + offers)[:cap_total]


def offer_scene_action(conn, gid: str, label: str, cap_total: int) -> bool:
    from . import constants
    sc = current_scene(conn, gid)
    offers = db.loads(sc["offers"], [])
    if len(constants.SCENE_BASE_ACTIONS) + len(offers) >= cap_total:
        return False
    if any(o["label"].lower() == label.lower() for o in offers):
        return True
    offers.append({"id": _id(), "label": label})
    conn.execute("UPDATE scenes SET offers=? WHERE id=?", (json.dumps(offers), sc["id"]))
    return True


# ---------- quests ----------

def get_quests(conn, gid: str):
    return conn.execute("SELECT * FROM quests WHERE game_id=?", (gid,)).fetchall()


def get_objectives(conn, qid: str):
    return conn.execute("SELECT * FROM objectives WHERE quest_id=?", (qid,)).fetchall()


def quest_dict(conn, q) -> dict:
    objs = [
        {"id": o["id"], "text": o["text"], "done": bool(o["done"]), "progress": o["progress"]}
        for o in get_objectives(conn, q["id"])
    ]
    return {"id": q["id"], "title": q["title"], "description": q["description"],
            "status": q["status"], "objectives": objs}


def start_quest(conn, gid: str, title: str, description: str, objectives: list[str]) -> str:
    qid = _id()
    conn.execute("INSERT INTO quests (id, game_id, title, description) VALUES (?,?,?,?)",
                 (qid, gid, title, description))
    for text in objectives or []:
        conn.execute("INSERT INTO objectives (id, quest_id, text) VALUES (?,?,?)", (_id(), qid, text))
    return qid


def update_objective(conn, oid: str, done: bool, progress: str | None) -> bool:
    cur = conn.execute("UPDATE objectives SET done=?, progress=? WHERE id=?",
                       (int(done), progress, oid))
    return cur.rowcount > 0


def set_quest_status(conn, qid: str, status: str) -> bool:
    cur = conn.execute("UPDATE quests SET status=? WHERE id=?", (status, qid))
    return cur.rowcount > 0


# ---------- lore ----------

def match_lore(conn, gid: str, text: str, budget: int):
    rows = conn.execute("SELECT * FROM lore WHERE game_id=?", (gid,)).fetchall()
    haystack = text.lower()
    selected = []
    for r in rows:
        keys = db.loads(r["keys"], [])
        if r["constant"] or any(k.lower() in haystack for k in keys):
            selected.append(r)
    selected.sort(key=lambda r: (-r["constant"], -r["priority"]))
    return selected[:budget]


# ---------- beats ----------

def next_turn_index(conn, gid: str) -> int:
    row = conn.execute("SELECT COALESCE(MAX(turn_index), 0) AS t FROM beats WHERE game_id=?", (gid,)).fetchone()
    return row["t"] + 1


def add_beat(conn, gid, speaker, speaker_name, kind, text, location,
             turn_index=None, seq=None, private_with=None) -> dict:
    if turn_index is None:
        turn_index = next_turn_index(conn, gid)
    if seq is None:
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), -1) AS s FROM beats WHERE game_id=? AND turn_index=?",
            (gid, turn_index)).fetchone()
        seq = row["s"] + 1
    bid = _id()
    conn.execute(
        "INSERT INTO beats (id, game_id, turn_index, seq, speaker, speaker_name, kind, text, location, private_with) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (bid, gid, turn_index, seq, speaker, speaker_name, kind, text, location, private_with),
    )
    return {"id": bid, "turn_index": turn_index, "seq": seq, "speaker": speaker,
            "speaker_name": speaker_name, "kind": kind, "text": text, "location": location,
            "image_url": None, "audio_url": None, "private_with": private_with}


def all_beats(conn, gid: str, since_turn: int = 0):
    rows = conn.execute(
        "SELECT * FROM beats WHERE game_id=? AND turn_index>? ORDER BY turn_index, seq",
        (gid, since_turn)).fetchall()
    return rows


def recent_beats(conn, gid: str, limit: int):
    rows = conn.execute(
        "SELECT * FROM beats WHERE game_id=? ORDER BY turn_index DESC, seq DESC LIMIT ?",
        (gid, limit)).fetchall()
    return list(reversed(rows))


def recent_beats_at(conn, gid: str, location: str, limit: int):
    rows = conn.execute(
        "SELECT * FROM beats WHERE game_id=? AND location=? ORDER BY turn_index DESC, seq DESC LIMIT ?",
        (gid, location, limit)).fetchall()
    return list(reversed(rows))


def scene_beats_for_character(conn, gid: str, location: str, char_id: str, limit: int):
    """A character's POV: public beats at the location PLUS private beats addressed to THEM.
    Private beats meant for other characters are excluded (knowledge stays where it belongs)."""
    rows = conn.execute(
        "SELECT * FROM beats WHERE game_id=? AND location=? AND (private_with IS NULL OR private_with=?) "
        "ORDER BY turn_index DESC, seq DESC LIMIT ?",
        (gid, location, char_id, limit)).fetchall()
    return list(reversed(rows))


# ---------- assembled state for API ----------

def game_state(conn, gid: str) -> dict:
    g = get_game(conn, gid)
    p = get_player(conn, gid)
    quests = [quest_dict(conn, q) for q in get_quests(conn, gid)]
    chars = [
        {"id": c["id"], "name": c["name"], "description": c["description"],
         "voice_id": c["voice_id"], "color": c["color"],
         "present": bool(c["present"]), "location": c["location"],
         "life": c["life"], "max_life": c["max_life"], "alive": bool(c["alive"]),
         "disposition": c["disposition"], "following": bool(c["following"]),
         "face_url": c["face_url"], "body_url": c["body_front_url"],
         "body_front_url": c["body_front_url"], "body_side_url": c["body_side_url"],
         "inventory": visible_items(c["inventory"]),
         "available_actions": available_actions(conn, c, settings.CHAR_ACTION_CAP)}
        for c in get_characters(conn, gid)
    ]
    sc = current_scene(conn, gid)
    scene = {
        "id": sc["id"], "name": sc["name"], "description": sc["description"],
        "status": sc["status"], "image_url": sc["image_url"],
        "exits": db.loads(sc["exits"], []),
        "items": visible_items(sc["items"]),
        "available_actions": scene_available_actions(conn, sc, settings.SCENE_ACTION_CAP),
    }
    return {
        "game_id": gid,
        "title": g["title"],
        "status": g["status"],
        "scene_status": sc["status"],
        "current_goal": g["current_goal"],
        "scene": scene,
        "narrator_voice_id": g["narrator_voice_id"],
        "player": player_dict(p),
        "quests": quests,
        "characters": chars,
    }
