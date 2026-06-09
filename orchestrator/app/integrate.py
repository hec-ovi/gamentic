"""Glue between the game and the accessory media services.

Voice assignment is fast (a list lookup), so it runs inline at creation. Image
generation is slow, so it runs as a background task; the frontend's /state polling
picks up the URLs when they land. Generated images are DOWNLOADED into a per-game
folder we own and served under /media/<gid>/..., so they persist with the game and
are deleted when the game is wiped. All best-effort: if media is down/disabled, the
game is unaffected and fully playable text-only.
"""
import os
import re

from . import repo, media, db
from .config import settings


def assign_voices_for_game(conn, gid: str) -> None:
    """Give the narrator and each character a distinct voice_id from /voices."""
    voices = media.list_voice_ids()
    if not voices:
        return
    g = repo.get_game(conn, gid)
    if not g["narrator_voice_id"]:
        repo.set_narrator_voice(conn, gid, voices[0])
    for i, c in enumerate(repo.get_characters(conn, gid)):
        if c["voice_id"]:
            continue
        repo.set_character_voice(conn, c["id"], voices[(i + 1) % len(voices)])


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:40] or "img"


# ---------- image prompt composition ----------
# The model's appearance text is the source, but two failure modes are netted
# deterministically here: gender drift (a "woman" rendered ambiguous because the
# appearance never says so) and rendered text (FLUX draws any words it finds an
# excuse for: sign names, lettering, watermarks).

_FEMALE = re.compile(r"\b(woman|women|female|girl|lady|she|her|hers)\b", re.I)
_MALE = re.compile(r"\b(man|men|male|boy|guy|gentleman|he|him|his)\b", re.I)
_QUOTED = re.compile(r'["“”][^"“”]*["“”]')   # "..." spans (incl. curly quotes)
NO_TEXT_GUARD = "no readable text, no lettering, no captions, no watermark"


def _gender_hint(*texts) -> str:
    blob = " ".join(t or "" for t in texts)
    if _FEMALE.search(blob):
        return "female"
    if _MALE.search(blob):
        return "male"
    return ""


def character_descriptor(c) -> str:
    """The outgoing image descriptor: explicit gender first, then looks, then the no-text guard.
    If the appearance itself names no gender, one is inferred from description/persona pronouns."""
    base = (c["appearance"] or c["description"] or c["persona"] or c["name"]).strip()
    if not _gender_hint(base):
        hint = _gender_hint(c["description"], c["persona"], c["name"])
        if hint:
            base = f"{hint}, {base}"
    return f"{base}, {NO_TEXT_GUARD}"


def scene_prompt(sc, style: str) -> str:
    """Scene art prompt: the description with quoted spans stripped (sign names and spoken
    lines provoke garbled rendered text), plus the world style and the no-text guard."""
    desc = _QUOTED.sub("", sc["description"] or "").strip() or sc["name"]
    return ", ".join(x for x in [desc, style, NO_TEXT_GUARD] if x)


def _persist(gid: str, src_url, name: str):
    """Download an image from image-api into the per-game folder; return the /media URL.
    Falls back to the original image-api URL if the download fails (still works, not persisted)."""
    data = media.fetch_image_bytes(src_url)
    if not data:
        return src_url
    d = os.path.join(settings.GAMES_DATA_DIR, gid, "images")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{name}.png"), "wb") as f:
        f.write(data)
    return f"/media/{gid}/{name}.png"


def generate_images_for_game(gid: str) -> None:
    """Background: generate + persist the 3-image reference set for each character."""
    with db.get_conn() as conn:
        g = repo.get_game(conn, gid)
        if not g:
            return
        style = g["art_style"] or g["tone"] or ""
        chars = repo.get_characters(conn, gid)
    for c in chars:
        if repo.character_has_images(c):
            continue
        result = media.generate_character_images(character_descriptor(c), style)
        if not result:
            continue
        face = _persist(gid, result.get("face_url"), f"char-{c['id']}-face")
        front = _persist(gid, result.get("body_front_url"), f"char-{c['id']}-front")
        side = _persist(gid, result.get("body_side_url"), f"char-{c['id']}-side")
        with db.get_conn() as conn:
            repo.set_character_images(conn, c["id"], face_url=face, body_front_url=front, body_side_url=side)


def generate_scene_image(gid: str, scene_id: str) -> None:
    """Background: generate + persist art for one scene (skips if it already has an image)."""
    with db.get_conn() as conn:
        sc = repo.get_scene_by_id(conn, scene_id)
        g = repo.get_game(conn, gid)
        if not sc or not g or sc["image_url"]:
            return
        style = g["art_style"] or g["tone"] or ""
        prompt = scene_prompt(sc, style)
    result = media.generate_scene_image(prompt)
    if not result:
        return
    url = _persist(gid, result.get("image_url"), f"scene-{scene_id}")
    with db.get_conn() as conn:
        repo.set_scene_image(conn, scene_id, url)


def delete_game_images(gid: str) -> None:
    """Remove the per-game image folder (called on wipe)."""
    import shutil
    shutil.rmtree(os.path.join(settings.GAMES_DATA_DIR, gid), ignore_errors=True)
