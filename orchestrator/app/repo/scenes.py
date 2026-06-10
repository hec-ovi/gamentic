"""Scenes (the main card): rows, movement + the draft layer, exits, scene items, offers."""
import json

from .. import db
from . import clock, games, items, players
from .base import _id, norm_name


def scene_is_established(sc) -> bool:
    """A scene is 'established' once the narrator has furnished it (given it a description).
    A fresh scene the player just entered has an empty description; the state block flags it
    NEW so the narrator knows to describe it, set its mood, and reveal a way onward."""
    return bool((sc["description"] or "").strip())


def get_scene(conn, gid: str, name: str):
    # replace() in SQL covers legacy rows stored before normalization existed
    return conn.execute(
        "SELECT * FROM scenes WHERE game_id=? AND lower(replace(name,'_',' '))=lower(?)",
        (gid, norm_name(name))).fetchone()


def get_or_create_scene(conn, gid: str, name: str, description: str = ""):
    from ..constants import SCENE_STATUS_DEFAULT
    name = norm_name(name)
    sc = get_scene(conn, gid, name)
    if sc:
        return sc
    conn.execute("INSERT INTO scenes (id, game_id, name, description, status) VALUES (?,?,?,?,?)",
                 (_id(), gid, name, description, SCENE_STATUS_DEFAULT))
    return get_scene(conn, gid, name)


def current_scene(conn, gid: str):
    return get_or_create_scene(conn, gid, players.get_player(conn, gid)["location"])


def get_scene_by_id(conn, scene_id: str):
    return conn.execute("SELECT * FROM scenes WHERE id=?", (scene_id,)).fetchone()


def set_scene_image(conn, scene_id: str, url: str) -> None:
    conn.execute("UPDATE scenes SET image_url=? WHERE id=?", (url, scene_id))


def set_scene_status(conn, gid: str, status: str) -> None:
    conn.execute("UPDATE scenes SET status=? WHERE id=?", (status, current_scene(conn, gid)["id"]))


def set_scene_description(conn, gid: str, description: str) -> None:
    conn.execute("UPDATE scenes SET description=? WHERE id=?", (description, current_scene(conn, gid)["id"]))


def set_scene_draft(conn, gid: str, note: str) -> None:
    """The narrator's draft of open threads on the CURRENT scene (note_scene tool)."""
    conn.execute("UPDATE scenes SET draft=? WHERE id=?", (note, current_scene(conn, gid)["id"]))


# ---------- movement + the draft layer ----------

def _ensure_exit(conn, gid: str, scene_name: str, label: str, target: str) -> None:
    """Add an exit to a scene if it doesn't already lead to `target` (dedup by target)."""
    sc = get_scene(conn, gid, scene_name)
    if not sc:
        return
    target = norm_name(target)
    exits = db.loads(sc["exits"], [])
    if any(norm_name(e["target"]).lower() == target.lower() for e in exits):
        return
    exits.append({"id": _id(), "label": label, "target": target})
    conn.execute("UPDATE scenes SET exits=? WHERE id=?", (json.dumps(exits), sc["id"]))


def set_location(conn, gid: str, location: str) -> None:
    location = norm_name(location)
    prev = players.get_player(conn, gid)["location"]
    moved = bool(prev) and norm_name(prev).lower() != location.lower()
    now = games.get_game(conn, gid)["time_minutes"] or 0
    if moved:
        # Draft layer: stamp the scene being LEFT with the story clock, so a return can
        # reason about the elapsed fictional time.
        prev_sc = get_scene(conn, gid, prev)
        if prev_sc:
            conn.execute("UPDATE scenes SET left_at_minutes=? WHERE id=?", (now, prev_sc["id"]))
    dest_existing = get_scene(conn, gid, location)
    get_or_create_scene(conn, gid, location)   # the destination scene persists
    conn.execute("UPDATE player_state SET location=? WHERE game_id=?", (location, gid))
    # Only FOLLOWING characters travel with the player. Everyone else stays at their scene
    # (and is there again if the player returns) - this is the scene-persistence behaviour.
    conn.execute("UPDATE characters SET location=? WHERE game_id=? AND following=1 AND alive=1",
                 (location, gid))
    if moved:
        # Always leave a way back so the player can never get stranded.
        _ensure_exit(conn, gid, location, label=f"back to {prev}", target=prev)
        # Returning somewhere previously left: hand the narrator the elapsed time + the
        # draft note so it can reason about what changed while the player was away.
        if dest_existing is not None and dest_existing["left_at_minutes"] is not None:
            ago = clock.elapsed_text(now - dest_existing["left_at_minutes"])
            then = clock.time_at(dest_existing["left_at_minutes"])["label"]
            note = f"The player was last here {ago} ago ({then})."
            draft = (dest_existing["draft"] or "").strip()
            if draft:
                note += f" Note from then: {draft}"
            conn.execute("UPDATE games SET arrival_note=? WHERE id=?", (note, gid))


# ---------- exits, scene items, offered actions ----------

def add_exit(conn, gid: str, label: str, target: str, cap: int) -> str:
    sc = current_scene(conn, gid)
    target = norm_name(target)
    exits = db.loads(sc["exits"], [])
    if any(norm_name(e["target"]).lower() == target.lower() for e in exits):
        return "exists"
    if len(exits) >= cap:
        return "full"
    exits.append({"id": _id(), "label": label, "target": target})
    conn.execute("UPDATE scenes SET exits=? WHERE id=?", (json.dumps(exits), sc["id"]))
    return "ok"


def add_scene_item(conn, gid: str, name: str, description: str, hidden: bool, cap: int,
                   fixed: bool = False) -> str:
    name = norm_name(name)
    sc = current_scene(conn, gid)
    scene_items = db.loads(sc["items"], [])
    if any(i["name"].lower() == name.lower() for i in scene_items):
        return "exists"
    if len(scene_items) >= cap:
        return "full"
    scene_items.append({"id": _id(), "name": name, "description": description,
                        "image_url": None, "hidden": bool(hidden), "fixed": bool(fixed)})
    conn.execute("UPDATE scenes SET items=? WHERE id=?", (json.dumps(scene_items), sc["id"]))
    return "ok"


def reveal_scene_item(conn, gid: str, name: str) -> bool:
    sc = current_scene(conn, gid)
    scene_items = db.loads(sc["items"], [])
    for it in scene_items:
        if it["name"].lower() == name.lower() and it.get("hidden"):
            it["hidden"] = False
            conn.execute("UPDATE scenes SET items=? WHERE id=?", (json.dumps(scene_items), sc["id"]))
            return True
    return False


def take_scene_item(conn, gid: str, key: str) -> str:
    """Move a REVEALED, non-fixed scene item into the player's inventory. Accepts item
    ID (entity chips) or name. Returns 'ok' | 'fixed' (scenery) | 'missing'."""
    sc = current_scene(conn, gid)
    scene_items = db.loads(sc["items"], [])
    for it in scene_items:
        if items._item_matches(it, key) and not it.get("hidden"):
            if it.get("fixed"):
                return "fixed"
            scene_items.remove(it)
            conn.execute("UPDATE scenes SET items=? WHERE id=?", (json.dumps(scene_items), sc["id"]))
            # the item's generated image travels with it into the pack
            players.add_item(conn, gid, it["name"], it.get("description", ""),
                             image_url=it.get("image_url"))
            return "ok"
    return "missing"


def scene_available_actions(conn, sc, cap_total: int) -> list[dict]:
    from .. import constants
    base = [{"id": f"s{i}", "label": lbl, "type": typ}
            for i, (lbl, typ) in enumerate(constants.SCENE_BASE_ACTIONS)]
    offers = [{"id": o["id"], "label": o["label"], "type": "offer"} for o in db.loads(sc["offers"], [])]
    return (base + offers)[:cap_total]


def offer_scene_action(conn, gid: str, label: str, cap_total: int) -> bool:
    from .. import constants
    sc = current_scene(conn, gid)
    offers = db.loads(sc["offers"], [])
    if len(constants.SCENE_BASE_ACTIONS) + len(offers) >= cap_total:
        return False
    if any(o["label"].lower() == label.lower() for o in offers):
        return True
    offers.append({"id": _id(), "label": label})
    conn.execute("UPDATE scenes SET offers=? WHERE id=?", (json.dumps(offers), sc["id"]))
    return True
