"""Character rows: lookup, life, inventory, traits, offers, and the full-screen profile."""
import json

from .. import db
from . import clock, games, items
from .base import _id, norm_name


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


def get_character(conn, cid: str):
    return conn.execute("SELECT * FROM characters WHERE id=?", (cid,)).fetchone()


def resolve_target(conn, gid: str, name: str):
    """Map a target to ('player', None) | ('character', row) | (None, None).
    Accepts a character ID (what the UI's entity chips send) or a name (what the
    model writes); ID is tried first so renames/duplicate names cannot misroute."""
    n = (name or "").strip().lower()
    if n in ("player", "you", "me", "the player", "hero", "protagonist"):
        return ("player", None)
    if not n:
        return (None, None)
    ch = conn.execute("SELECT * FROM characters WHERE game_id=? AND id=?", (gid, n)).fetchone()
    if not ch:
        ch = conn.execute("SELECT * FROM characters WHERE game_id=? AND lower(name)=lower(?)",
                          (gid, n)).fetchone()
    return ("character", ch) if ch else (None, None)


def set_character_images(conn, char_id: str, face_url=None, body_front_url=None, body_side_url=None) -> None:
    conn.execute(
        "UPDATE characters SET face_url=?, body_front_url=?, body_side_url=? WHERE id=?",
        (face_url, body_front_url, body_side_url, char_id),
    )


def character_has_images(c) -> bool:
    return bool(c["face_url"] or c["body_front_url"] or c["body_side_url"])


def set_character_voice(conn, char_id: str, voice_id: str) -> None:
    conn.execute("UPDATE characters SET voice_id=? WHERE id=?", (voice_id, char_id))


def set_character_life(conn, cid: str, delta: int):
    """Apply a life delta to a character. Returns (new_life, died: bool). At 0 the character dies."""
    c = get_character(conn, cid)
    new = max(0, min(c["max_life"], c["life"] + delta))
    died = new <= 0
    conn.execute("UPDATE characters SET life=?, alive=?, present=? WHERE id=?",
                 (new, 0 if died else 1, 0 if died else c["present"], cid))
    return new, died


def character_add_item(conn, cid: str, name: str, description: str = "",
                       hidden: bool = False, qty: int = 1, cap: int | None = None,
                       image_url: str | None = None) -> str:
    name = norm_name(name)
    c = get_character(conn, cid)
    inv = db.loads(c["inventory"], [])
    for it in inv:
        if it["name"].lower() == name.lower():
            it["qty"] = it.get("qty", 1) + qty
            if image_url and not it.get("image_url"):
                it["image_url"] = image_url
            break
    else:
        if cap is not None and len(inv) >= cap:
            return "full"
        inv.append({"id": _id(), "name": name, "description": description,
                    "image_url": image_url, "hidden": bool(hidden), "qty": qty})
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


def character_remove_item(conn, cid: str, key: str, qty: int = 1):
    """Remove by item ID or name; returns the matched item dict or None (see players.remove_item)."""
    c = get_character(conn, cid)
    inv = db.loads(c["inventory"], [])
    for it in inv:
        if items._item_matches(it, key):
            it["qty"] = it.get("qty", 1) - qty
            if it["qty"] <= 0:
                inv.remove(it)
            conn.execute("UPDATE characters SET inventory=? WHERE id=?", (json.dumps(inv), cid))
            return it
    return None


def spawn_character(conn, gid: str, name: str, persona: str, appearance: str = "",
                    knowledge: str = "", location: str | None = None,
                    life: int = 10) -> str:
    """Add a character to the game on the fly (dynamic narrator)."""
    from . import players
    location = norm_name(location) if location else players.get_player(conn, gid)["location"]
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


def set_character_description(conn, cid: str, description: str) -> None:
    conn.execute("UPDATE characters SET description=? WHERE id=?", (description, cid))


def set_character_context(conn, char_id: str, used: int) -> None:
    """Each character agent has its OWN context; record its last prompt size."""
    conn.execute("UPDATE characters SET context_used=? WHERE id=?", (int(used or 0), char_id))


# ---------- traits (personality unlocked through play) ----------

def add_trait(conn, cid: str, text: str, cap: int) -> str | None:
    """Unlock a personality trait on a character (earned through play). Returns the
    cleaned trait text, or None when it is a duplicate, empty, or the card is full.
    Stamped with the story clock so the profile can say WHEN it was revealed."""
    text = " ".join((text or "").split()).strip().rstrip(".")
    if not text:
        return None
    c = get_character(conn, cid)
    traits = db.loads(c["traits"], [])
    if len(traits) >= cap or any(t["text"].lower() == text.lower() for t in traits):
        return None
    minutes = games.get_game(conn, c["game_id"])["time_minutes"] or 0
    traits.append({"id": _id(), "text": text, "minutes": minutes})
    conn.execute("UPDATE characters SET traits=? WHERE id=?", (json.dumps(traits), cid))
    return text


def character_traits(c) -> list[dict]:
    return [{"id": t["id"], "text": t["text"],
             "unlocked": clock.time_at(t.get("minutes") or 0)["label"]}
            for t in db.loads(c["traits"], [])]


def character_profile(conn, gid: str, cid: str) -> dict | None:
    """The full-screen character view: public card data + unlocked traits + the moments
    shared with the player (their words/acts, including private exchanges) + story images
    as memories. PLAYER-VISIBLE only: persona and private knowledge never leave the DB."""
    c = get_character(conn, cid)
    if not c or c["game_id"] != gid:
        return None
    rows = conn.execute(
        "SELECT * FROM beats WHERE game_id=? AND (speaker=? OR private_with=?) "
        "AND kind IN ('dialogue','action') ORDER BY turn_index DESC, seq DESC LIMIT 12",
        (gid, cid, cid)).fetchall()
    moments = [{"turn_index": b["turn_index"], "kind": b["kind"], "text": b["text"],
                "speaker": "player" if b["speaker"] == "player" else "character",
                "private": bool(b["private_with"])} for b in reversed(rows)]
    # memories: story images from places this character has been part of, or that name them
    locs = {r["location"] for r in conn.execute(
        "SELECT DISTINCT location FROM beats WHERE game_id=? AND speaker=?",
        (gid, cid)).fetchall() if r["location"]}
    mem_rows = conn.execute(
        "SELECT * FROM beats WHERE game_id=? AND kind='image' AND image_url IS NOT NULL "
        "ORDER BY turn_index DESC LIMIT 24", (gid,)).fetchall()
    name_low = (c["name"] or "").lower()
    memories = [{"image_url": b["image_url"], "caption": b["text"], "turn_index": b["turn_index"]}
                for b in mem_rows
                if b["location"] in locs or (name_low and name_low in (b["text"] or "").lower())][:8]
    memories.reverse()
    return {
        "id": c["id"], "name": c["name"], "description": c["description"],
        "disposition": c["disposition"], "following": bool(c["following"]),
        "alive": bool(c["alive"]), "life": c["life"], "max_life": c["max_life"],
        "face_url": c["face_url"], "body_url": c["body_front_url"],
        "voice_id": c["voice_id"], "color": c["color"],
        "carrying": items.visible_items(c["inventory"]),
        "traits": character_traits(c),
        "moments": moments,
        "memories": memories,
    }


# ---------- offered actions (the player's buttons toward a character) ----------

def offer_action(conn, cid: str, label: str, cap_total: int) -> bool:
    """Add a narrator-offered contextual action to a character, within the total-action cap."""
    from .. import constants
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
    from .. import constants
    base = [{"id": f"b{i}", "label": lbl, "type": typ}
            for i, (lbl, typ) in enumerate(constants.ACTIONS_BY_DISPOSITION.get(c["disposition"], []))]
    offers = [{"id": o["id"], "label": o["label"], "type": "offer"} for o in db.loads(c["offers"], [])]
    return (base + offers)[:cap_total]
