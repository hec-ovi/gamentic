"""Item-blob logic. Items live as JSON lists on their owner's row (player pack, a
character's inventory, a scene's items); this module owns every shape and search over
those blobs so the rules live in ONE place."""
from .. import db
from .base import _id, norm_name


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


def _item_matches(it: dict, key: str) -> bool:
    """An inventory item matches by ID (entity chips) or by case-insensitive name (the model).
    Names compare underscore/whitespace-collapsed, so 'scanner_device' finds 'scanner device'."""
    k = norm_name(key or "").lower()
    return bool(k) and ((it.get("id") or "").lower() == k
                        or norm_name(it["name"]).lower() == k)


# ---------- blob mutations (shared by pack / character inventories / scene items) ----------
# These mutate a LOADED list in place; the owner module loads the blob, calls one of
# these, and saves it back to its own table. The rules live here, once.

def find_by_name(items_list: list[dict], name: str):
    """The record whose stored name matches (stored names are already normalized)."""
    return next((it for it in items_list if it["name"].lower() == name.lower()), None)


def stack(it: dict, qty: int = 1, image_url: str | None = None) -> None:
    """Add quantity onto an existing record; an arriving image fills an empty slot only
    (an item never swaps an image it already has)."""
    it["qty"] = it.get("qty", 1) + qty
    if image_url and not it.get("image_url"):
        it["image_url"] = image_url


def new_record(name: str, description: str = "", **fields) -> dict:
    """A fresh item record. ids let the UI's entity chips reference items precisely;
    each owner passes exactly the fields its records carry (qty / hidden / fixed / image_url)."""
    return {"id": _id(), "name": name, "description": description, **fields}


def take_out(items_list: list[dict], key: str, qty: int = 1):
    """Remove by item ID or name (decrements qty, drops the record at zero). Returns the
    matched record (so callers know the real name even when called with an ID) or None.
    The caller saves the blob only when something matched."""
    for it in items_list:
        if _item_matches(it, key):
            it["qty"] = it.get("qty", 1) - qty
            if it["qty"] <= 0:
                items_list.remove(it)
            return it
    return None


def unhide(items_list: list[dict], name: str) -> bool:
    """Reveal a hidden record by stored name. The caller saves the blob on True."""
    it = find_by_name(items_list, name)
    if it is not None and it.get("hidden"):
        it["hidden"] = False
        return True
    return False


def set_item_image(conn, gid: str, name: str, url: str) -> bool:
    """Attach a generated image to an item WHEREVER it lives now (pack, any scene, any
    character): the item may have moved while the render ran in the background. Only fills
    empty slots (an item never swaps an image it already has). Returns True if anything matched."""
    import json
    from . import characters, players
    k = norm_name(name).lower()
    hit = False

    def _fill(items) -> bool:
        changed = False
        for it in items:
            if norm_name(it["name"]).lower() == k and not it.get("image_url"):
                it["image_url"] = url
                changed = True
        return changed

    p = players.get_player(conn, gid)
    inv = db.loads(p["inventory"], [])
    if _fill(inv):
        conn.execute("UPDATE player_state SET inventory=? WHERE game_id=?", (json.dumps(inv), gid))
        hit = True
    for sc in conn.execute("SELECT * FROM scenes WHERE game_id=?", (gid,)).fetchall():
        items = db.loads(sc["items"], [])
        if _fill(items):
            conn.execute("UPDATE scenes SET items=? WHERE id=?", (json.dumps(items), sc["id"]))
            hit = True
    for c in characters.get_characters(conn, gid):
        items = db.loads(c["inventory"], [])
        if _fill(items):
            conn.execute("UPDATE characters SET inventory=? WHERE id=?", (json.dumps(items), c["id"]))
            hit = True
    return hit


def visible_item_index(conn, gid: str) -> dict:
    """Every item the player can SEE right now (pack + revealed scene items + revealed
    items on present characters), keyed by collapsed name. The engine diffs this across
    a turn to find newly unlocked items (for their small unlock images)."""
    from . import characters, players, scenes
    pd = players.get_player(conn, gid)
    out: dict[str, dict] = {}

    def _take(items):
        for it in items:
            out.setdefault(norm_name(it["name"]).lower(),
                           {"name": it["name"], "description": it.get("description") or "",
                            "image_url": it.get("image_url")})
    _take(db.loads(pd["inventory"], []))
    _take(visible_items(scenes.current_scene(conn, gid)["items"]))
    for c in characters.present_characters(conn, gid, pd["location"]):
        _take(visible_items(c["inventory"]))
    return out
