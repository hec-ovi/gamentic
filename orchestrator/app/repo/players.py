"""Player state: life, points, flags, and the pack (player inventory)."""
import json

from .. import db
from . import items
from .base import _id, norm_name


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


def add_item(conn, gid: str, name: str, description: str = "", qty: int = 1,
             image_url: str | None = None) -> None:
    name = norm_name(name)   # model-invented snake_case never reaches the player
    p = get_player(conn, gid)
    inv = db.loads(p["inventory"], [])
    for it in inv:
        if it["name"].lower() == name.lower():
            it["qty"] = it.get("qty", 1) + qty
            if image_url and not it.get("image_url"):
                it["image_url"] = image_url
            break
    else:
        # ids let the UI's entity chips reference player items precisely (give/transfer)
        inv.append({"id": _id(), "name": name, "description": description, "qty": qty,
                    "image_url": image_url})
    conn.execute("UPDATE player_state SET inventory=? WHERE game_id=?", (json.dumps(inv), gid))


def player_has_item(conn, gid: str, key: str) -> bool:
    """Peek: does the player hold this item (by id or name)? No state change."""
    p = get_player(conn, gid)
    return any(items._item_matches(it, key) for it in db.loads(p["inventory"], []))


def remove_item(conn, gid: str, key: str, qty: int = 1):
    """Remove by item ID or name. Returns the matched item dict (so callers know the real
    name even when called with an ID), or None if the player does not hold it."""
    p = get_player(conn, gid)
    inv = db.loads(p["inventory"], [])
    for it in inv:
        if items._item_matches(it, key):
            it["qty"] = it.get("qty", 1) - qty
            if it["qty"] <= 0:
                inv.remove(it)
            conn.execute("UPDATE player_state SET inventory=? WHERE game_id=?", (json.dumps(inv), gid))
            return it
    return None  # nothing removed; caller decides how to handle


def set_flag(conn, gid: str, key: str, value: str) -> None:
    p = get_player(conn, gid)
    flags = db.loads(p["flags"], {})
    flags[key] = value
    conn.execute("UPDATE player_state SET flags=? WHERE game_id=?", (json.dumps(flags), gid))
