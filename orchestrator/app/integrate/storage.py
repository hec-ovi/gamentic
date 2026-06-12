"""Media persistence on disk: download rendered images into the per-game folder we own
(served under /media/<gid>/...), detect already-persisted reference sets, and wipe
folders when games go."""
import json
import os

from .. import media
from ..config import settings


def _persist(gid: str, src_url, name: str):
    """Download an image from image-api into the per-game folder; return the /media URL.
    Falls back to the original image-api URL if the download fails (still works, not persisted)."""
    data = media.fetch_image_bytes(src_url)
    if not data:
        return src_url   # the staging file IS the live copy now: it must survive
    d = os.path.join(settings.GAMES_DATA_DIR, gid, "images")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{name}.png"), "wb") as f:
        f.write(data)
    # From this write on OUR copy is the truth and the staging file the image-api
    # kept is garbage (owner decision 2026-06-11: ownership-based deletion, no
    # retention timers). Fire-and-forget, success path ONLY - the fallback above
    # returns the staging URL as the live copy. Non-image-api sources (data: URLs,
    # cloud providers) skip inside the facade; so does any service failure.
    media.delete_staging_image(src_url)
    return f"/media/{gid}/{name}.png"


def _item_image_urls(raw_json) -> list[str]:
    """image_urls inside an inventory/items JSON column. Defensive parse: a sweep
    runs during game DELETE, and a malformed row must never block the funeral."""
    try:
        return [str(it.get("image_url") or "") for it in json.loads(raw_json or "[]")
                if isinstance(it, dict)]
    except Exception:
        return []


def remote_image_urls(conn, gid: str) -> list[str]:
    """Every URL this game stored that still points at the image-api staging folder
    (persist fallbacks: the download failed at render time, so the staging file is
    the only copy). Collected BEFORE the rows die so the game-delete sweep can free
    those files on the image-api side too - deleting only our /media folder would
    leave them in the ComfyUI output dir forever. Covers scenes, character views,
    beats, and the item images in player/scene/character inventories."""
    urls: list[str] = []
    for r in conn.execute("SELECT image_url, items FROM scenes WHERE game_id=?", (gid,)):
        urls.append(r["image_url"] or "")
        urls += _item_image_urls(r["items"])
    for r in conn.execute("SELECT face_url, body_front_url, body_side_url, inventory"
                          " FROM characters WHERE game_id=?", (gid,)):
        urls += [r["face_url"] or "", r["body_front_url"] or "", r["body_side_url"] or ""]
        urls += _item_image_urls(r["inventory"])
    for r in conn.execute("SELECT image_url FROM beats WHERE game_id=?", (gid,)):
        urls.append(r["image_url"] or "")
    p = conn.execute("SELECT inventory FROM player_state WHERE game_id=?", (gid,)).fetchone()
    if p:
        urls += _item_image_urls(p["inventory"])
    return sorted({u for u in urls if "/image/file?" in u})


def _existing_char_urls(gid: str, cid: str) -> dict | None:
    """Reference images already persisted on disk for this character (a crashed earlier
    run may have written the files but lost the DB commit). Returns the /media urls only
    when ALL THREE files exist; a partial set re-renders the full set instead (the
    renderer overwrites the partial files: _persist writes fixed names). Relinking a
    partial set would re-schedule forever without ever completing it."""
    d = os.path.join(settings.GAMES_DATA_DIR, gid, "images")
    urls = {}
    for view, key in (("face", "face_url"), ("front", "body_front_url"), ("side", "body_side_url")):
        if not os.path.isfile(os.path.join(d, f"char-{cid}-{view}.png")):
            return None
        urls[key] = f"/media/{gid}/char-{cid}-{view}.png"
    return urls


def delete_game_images(gid: str) -> None:
    """Remove the per-game image folder (called on wipe)."""
    import shutil
    shutil.rmtree(os.path.join(settings.GAMES_DATA_DIR, gid), ignore_errors=True)


def delete_all_media(known_gids: set[str] | None = None) -> int:
    """Remove EVERY per-game media folder, including ORPHANS (folders whose game no
    longer exists: pre-fix delete races and DB resets left these behind). Pass the
    surviving game ids to keep; with None everything goes. Returns folders removed."""
    import shutil
    keep = known_gids or set()
    removed = 0
    root = settings.GAMES_DATA_DIR
    if not os.path.isdir(root):
        return 0
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if os.path.isdir(path) and name not in keep:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    return removed
