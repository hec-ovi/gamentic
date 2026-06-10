"""Character rows: lookup, life, inventory, traits, origin, offers, and the
full-screen profile. Also home of the gender net: gender is decided ONCE (explicit
field, or inferred from the sheet at creation) and stored, so image, prose and voice
can never disagree about it."""
import json
import re

from .. import db
from . import clock, games, items
from .base import _id, norm_name

_FEMALE = re.compile(r"\b(woman|women|female|girl|lady|she|her|hers)\b", re.I)
_MALE = re.compile(r"\b(man|men|male|boy|guy|gentleman|he|him|his)\b", re.I)


def gender_hint(*texts) -> str:
    """'female' | 'male' | '' inferred from pronouns/nouns across the given texts."""
    blob = " ".join(t or "" for t in texts)
    if _FEMALE.search(blob):
        return "female"
    if _MALE.search(blob):
        return "male"
    return ""


def character_gender(c) -> str:
    """The character's gender: the stored field, else inferred from their sheet
    (legacy rows created before the column existed)."""
    stored = (c["gender"] or "").strip() if "gender" in c.keys() else ""
    return stored or gender_hint(c["appearance"], c["description"], c["persona"], c["name"])


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


def _save_inventory(conn, cid: str, inv: list) -> None:
    conn.execute("UPDATE characters SET inventory=? WHERE id=?", (json.dumps(inv), cid))


def character_add_item(conn, cid: str, name: str, description: str = "",
                       hidden: bool = False, qty: int = 1, cap: int | None = None,
                       image_url: str | None = None) -> str:
    name = norm_name(name)
    inv = db.loads(get_character(conn, cid)["inventory"], [])
    it = items.find_by_name(inv, name)
    if it is not None:
        items.stack(it, qty, image_url)
    else:
        if cap is not None and len(inv) >= cap:
            return "full"
        inv.append(items.new_record(name, description, image_url=image_url,
                                    hidden=bool(hidden), qty=qty))
    _save_inventory(conn, cid, inv)
    return "ok"


def character_reveal_item(conn, cid: str, name: str) -> bool:
    inv = db.loads(get_character(conn, cid)["inventory"], [])
    if items.unhide(inv, name):
        _save_inventory(conn, cid, inv)
        return True
    return False


def character_remove_item(conn, cid: str, key: str, qty: int = 1):
    """Remove by item ID or name; returns the matched item dict or None (see players.remove_item)."""
    inv = db.loads(get_character(conn, cid)["inventory"], [])
    it = items.take_out(inv, key, qty)
    if it is not None:
        _save_inventory(conn, cid, inv)
    return it


def spawn_character(conn, gid: str, name: str, persona: str, appearance: str = "",
                    knowledge: str = "", location: str | None = None,
                    life: int = 10, gender: str = "", origin: str = "",
                    relation: str = "") -> str:
    """Add a character to the game on the fly (dynamic narrator). Gender is fixed at
    birth: explicit when given, else inferred once from the sheet, so every consumer
    (image, prose, voice) agrees from the first moment."""
    from . import players
    location = norm_name(location) if location else players.get_player(conn, gid)["location"]
    gender = (gender or "").strip().lower()
    if gender not in ("female", "male"):
        gender = gender_hint(appearance, persona, name)
    cid = _id()
    conn.execute(
        "INSERT INTO characters (id, game_id, name, persona, knowledge, appearance, "
        "location, life, max_life, present, gender, origin, relation) "
        "VALUES (?,?,?,?,?,?,?,?,?,1,?,?,?)",
        (cid, gid, name, persona, knowledge, appearance, location, life, life, gender,
         origin, relation.strip()),
    )
    return cid


def kill_character(conn, cid: str) -> None:
    conn.execute("UPDATE characters SET alive=0, present=0, life=0 WHERE id=?", (cid,))


def set_disposition(conn, cid: str, disposition: str) -> None:
    conn.execute("UPDATE characters SET disposition=? WHERE id=?", (disposition, cid))


def set_relation(conn, cid: str, relation: str) -> None:
    """What this character IS to the player (free 1-2 words: sister, boss, ally, rival).
    A different axis from disposition: disposition is the 4-mood mechanical dial,
    relation is the narrative bond, the narrator's free choice."""
    conn.execute("UPDATE characters SET relation=? WHERE id=?", (relation.strip(), cid))


def character_relation(c) -> str:
    return (c["relation"] or "").strip() if "relation" in c.keys() else ""


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
    text = norm_name(text).rstrip(".")   # collapses snake_case too (live: "desperate_gambler")
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


def add_origin_fact(conn, cid: str, text: str, cap: int) -> str | None:
    """The player just LEARNED a piece of this character's past (reveal_origin tool).
    Returns the cleaned text, or None when duplicate/empty/full. Story-clock stamped.
    The full origin stays private; only revealed pieces ever reach the profile."""
    text = norm_name(text).rstrip(".")   # collapses snake_case too (live: "desperate_gambler")
    if not text:
        return None
    c = get_character(conn, cid)
    revealed = db.loads(c["origin_revealed"], [])
    if len(revealed) >= cap or any(r["text"].lower() == text.lower() for r in revealed):
        return None
    minutes = games.get_game(conn, c["game_id"])["time_minutes"] or 0
    revealed.append({"id": _id(), "text": text, "minutes": minutes})
    conn.execute("UPDATE characters SET origin_revealed=? WHERE id=?",
                 (json.dumps(revealed), cid))
    return text


def character_origin_revealed(c) -> list[dict]:
    return [{"id": r["id"], "text": r["text"],
             "learned": clock.time_at(r.get("minutes") or 0)["label"]}
            for r in db.loads(c["origin_revealed"], [])]


def add_moment(conn, cid: str, text: str, cap: int = 20) -> str | None:
    """Record a PIVOTAL shared event between this character and the player (a bond, a
    wound, a gift, a betrayal, a parting). These are the character's MEMORIES of the
    player: curated events, never transcript. Deduped, story-clock stamped, capped."""
    text = norm_name(text).rstrip(".")   # collapses snake_case too (live: "desperate_gambler")
    if not text:
        return None
    c = get_character(conn, cid)
    moments = db.loads(c["moments"], []) if "moments" in c.keys() else []
    if len(moments) >= cap or any(m["text"].lower() == text.lower() for m in moments):
        return None
    minutes = games.get_game(conn, c["game_id"])["time_minutes"] or 0
    moments.append({"id": _id(), "text": text, "minutes": minutes})
    conn.execute("UPDATE characters SET moments=? WHERE id=?", (json.dumps(moments), cid))
    return text


def character_moments(c) -> list[dict]:
    moments = db.loads(c["moments"], []) if "moments" in c.keys() else []
    return [{"id": m["id"], "text": m["text"],
             "when": clock.time_at(m.get("minutes") or 0)["label"]}
            for m in moments]


def character_profile(conn, gid: str, cid: str) -> dict | None:
    """The full-screen character view: public card data + unlocked traits + PIVOTAL
    shared moments (curated events: bonds, wounds, gifts, partings - never transcript,
    never whispers) + story images as memories. PLAYER-VISIBLE only: persona and
    private knowledge never leave the DB."""
    c = get_character(conn, cid)
    if not c or c["game_id"] != gid:
        return None
    # memories: ONLY images whose own description names this character (they are a main
    # part of that moment). Location-based attribution gave every bystander the same
    # gallery, which read as nonsense (live-found).
    mem_rows = conn.execute(
        "SELECT * FROM beats WHERE game_id=? AND kind='image' AND image_url IS NOT NULL "
        "ORDER BY turn_index DESC LIMIT 60", (gid,)).fetchall()
    name_low = (c["name"] or "").lower()
    memories = [{"image_url": b["image_url"], "caption": b["text"], "turn_index": b["turn_index"]}
                for b in mem_rows
                if name_low and name_low in (b["text"] or "").lower()][:8]
    memories.reverse()
    return {
        "id": c["id"], "name": c["name"], "description": c["description"],
        "gender": character_gender(c),
        "relation": character_relation(c),
        "disposition": c["disposition"], "following": bool(c["following"]),
        "alive": bool(c["alive"]), "life": c["life"], "max_life": c["max_life"],
        "face_url": c["face_url"], "body_url": c["body_front_url"],
        "voice_id": c["voice_id"], "color": c["color"],
        "carrying": items.visible_items(c["inventory"]),
        "traits": character_traits(c),
        # only the pieces of their past the player has LEARNED (the full origin is private)
        "origin": character_origin_revealed(c),
        "moments": character_moments(c),
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
