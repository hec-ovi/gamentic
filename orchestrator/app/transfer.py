"""Adventure portability: export/import.

Two kinds, one file format family (plain JSON, versioned):
  - TEMPLATE ("gamentic": "adventure"): the world as designed - setting, cast, quests,
    lore - so someone else can play it FRESH from the start. No progress, no history.
  - CHECKPOINT ("gamentic": "checkpoint"): the full game - state, scenes, inventory,
    traits, the entire story log - to resume or share a specific moment.

Import always creates a NEW game id and remaps every internal id (so the same file can
be imported twice, or imported alongside the original, with no collisions). Media files
are NOT bundled: on the same box the per-game image folder is copied; on another box,
URLs whose files are missing are scrubbed (scene art and portraits regenerate in the
background; story image beats without their file are dropped).
"""
import json
import os
import shutil

from . import db, repo
from .config import settings
from .models import WorldSheet

FORMAT_VERSION = 1
_MEDIA_FIELDS = ("image_url", "audio_url", "face_url", "body_front_url", "body_side_url")


# ---------- export ----------

def export_template(conn, gid: str) -> dict | None:
    g = repo.get_game(conn, gid)
    if not g:
        return None
    p = repo.get_player(conn, gid)
    first_scene = conn.execute(
        "SELECT name FROM scenes WHERE game_id=? ORDER BY created_at, rowid LIMIT 1",
        (gid,)).fetchone()
    world = {
        "title": g["title"], "setting": g["setting"] or "", "tone": g["tone"] or "",
        "art_style": g["art_style"] or "", "narrator_persona": g["narrator_persona"] or "",
        "opening_scenario": g["opening_scenario"] or "",
        "start_location": (first_scene["name"] if first_scene else p["location"]),
        "player_life": p["max_life"],
        "characters": [{"name": c["name"], "persona": c["persona"],
                        "description": c["description"] or "",
                        "knowledge": c["knowledge"] or "",
                        "appearance": c["appearance"] or "",
                        "disposition": c["disposition"] or "neutral"}
                       for c in repo.get_characters(conn, gid) if c["alive"]],
        "quests": [{"title": q["title"], "description": q["description"] or "",
                    "objectives": [o["text"] for o in repo.get_objectives(conn, q["id"])]}
                   for q in repo.get_quests(conn, gid)],
        "lore": [{"keys": db.loads(r["keys"], []), "content": r["content"],
                  "constant": bool(r["constant"]), "priority": r["priority"]}
                 for r in conn.execute("SELECT * FROM lore WHERE game_id=?", (gid,)).fetchall()],
    }
    return {"gamentic": "adventure", "version": FORMAT_VERSION, "world": world}


def export_checkpoint(conn, gid: str) -> dict | None:
    if not repo.get_game(conn, gid):
        return None

    def rows(table):
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM {table} WHERE game_id=?", (gid,)).fetchall()]

    return {
        "gamentic": "checkpoint", "version": FORMAT_VERSION,
        "game": dict(repo.get_game(conn, gid)),
        "player": dict(repo.get_player(conn, gid)),
        "characters": rows("characters"),
        "scenes": rows("scenes"),
        "quests": rows("quests"),
        "objectives": [dict(r) for r in conn.execute(
            "SELECT o.* FROM objectives o JOIN quests q ON o.quest_id=q.id "
            "WHERE q.game_id=?", (gid,)).fetchall()],
        "lore": rows("lore"),
        "beats": rows("beats"),
    }


# ---------- import ----------

def import_payload(conn, payload: dict) -> str:
    """Create a NEW game from an exported file. Returns the new game id.
    Raises ValueError on anything that is not a valid gamentic export."""
    if not isinstance(payload, dict):
        raise ValueError("not a gamentic export")
    kind = payload.get("gamentic")
    if kind == "adventure":
        try:
            sheet = WorldSheet(**(payload.get("world") or {}))
        except Exception as e:
            raise ValueError(f"invalid adventure template: {e}")
        return repo.create_game(conn, sheet)
    if kind == "checkpoint":
        return _import_checkpoint(conn, payload)
    raise ValueError("not a gamentic export (missing 'gamentic': adventure|checkpoint)")


def _insert(conn, table: str, row: dict, overrides: dict) -> None:
    """Insert a payload row, keeping only columns this schema knows (forward-tolerant)."""
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    row = {k: v for k, v in row.items() if k in cols}
    row.update(overrides)
    marks = ",".join("?" * len(row))
    conn.execute(f"INSERT INTO {table} ({','.join(row)}) VALUES ({marks})",
                 list(row.values()))


def _import_checkpoint(conn, data: dict) -> str:
    for key in ("game", "player", "characters", "scenes", "quests", "objectives", "beats"):
        if key not in data:
            raise ValueError(f"invalid checkpoint: missing '{key}'")
    old_gid = (data["game"] or {}).get("id")
    if not old_gid:
        raise ValueError("invalid checkpoint: game has no id")
    new_gid = repo._id()

    # same-box resume: bring the image folder along so every URL keeps working
    src_dir = os.path.join(settings.GAMES_DATA_DIR, old_gid, "images")
    dst_dir = os.path.join(settings.GAMES_DATA_DIR, new_gid, "images")
    if os.path.isdir(src_dir):
        shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)

    def media(url):
        """Re-home a /media URL onto the new game; scrub it if the file is not here."""
        if not url or not isinstance(url, str):
            return url
        if url.startswith(f"/media/{old_gid}/"):
            url = url.replace(f"/media/{old_gid}/", f"/media/{new_gid}/", 1)
        if url.startswith("/media/"):
            name = url.rsplit("/", 1)[-1]
            if not os.path.isfile(os.path.join(dst_dir, name)):
                return None
        return url

    def fix_media(row: dict) -> dict:
        out = dict(row)
        for f in _MEDIA_FIELDS:
            if f in out:
                out[f] = media(out[f])
        # item blobs (scene items / inventories) carry their own image_url
        for f in ("items", "inventory"):
            if out.get(f):
                items = db.loads(out[f], [])
                for it in items:
                    if it.get("image_url"):
                        it["image_url"] = media(it["image_url"])
                out[f] = json.dumps(items)
        return out

    _insert(conn, "games", fix_media(data["game"]), {"id": new_gid})
    _insert(conn, "player_state", fix_media(data["player"]), {"game_id": new_gid})

    char_map = {}
    for c in data["characters"]:
        char_map[c["id"]] = repo._id()
        _insert(conn, "characters", fix_media(c), {"id": char_map[c["id"]], "game_id": new_gid})
    for sc in data["scenes"]:
        _insert(conn, "scenes", fix_media(sc), {"id": repo._id(), "game_id": new_gid})
    quest_map = {}
    for q in data["quests"]:
        quest_map[q["id"]] = repo._id()
        _insert(conn, "quests", q, {"id": quest_map[q["id"]], "game_id": new_gid})
    for o in data["objectives"]:
        if o.get("quest_id") in quest_map:
            _insert(conn, "objectives", o, {"id": repo._id(), "quest_id": quest_map[o["quest_id"]]})
    for r in data.get("lore", []):
        _insert(conn, "lore", r, {"id": repo._id(), "game_id": new_gid})
    for b in data["beats"]:
        b = fix_media(b)
        if b.get("kind") == "image" and not b.get("image_url"):
            continue                       # a story image whose file did not travel
        _insert(conn, "beats", b, {
            "id": repo._id(), "game_id": new_gid,
            "speaker": char_map.get(b.get("speaker"), b.get("speaker")),
            "private_with": char_map.get(b.get("private_with"), b.get("private_with")),
        })
    return new_gid
