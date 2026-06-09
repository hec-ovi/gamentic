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
# FLUX has no negative prompt and negation phrasing backfires ("no text" invites text);
# per the official BFL prompting guide, exclusions are phrased as the positive visual
# that occupies the space. https://docs.bfl.ai/guides/prompting_guide_t2i_negative
NO_TEXT_GUARD = "plain unmarked surfaces, no signage"


def _gender_hint(*texts) -> str:
    blob = " ".join(t or "" for t in texts)
    if _FEMALE.search(blob):
        return "female"
    if _MALE.search(blob):
        return "male"
    return ""


def _gendered_base(c) -> str:
    """A character's visual base: appearance text with an explicit gender lead. If the
    appearance itself names no gender, one is inferred from description/persona pronouns."""
    base = (c["appearance"] or c["description"] or c["persona"] or c["name"]).strip()
    if not _gender_hint(base):
        hint = _gender_hint(c["description"], c["persona"], c["name"])
        if hint:
            base = f"{hint}, {base}"
    return base


def character_descriptor(c) -> str:
    """The outgoing image descriptor: explicit gender first, then looks, then the no-text guard."""
    return f"{_gendered_base(c)}, {NO_TEXT_GUARD}"


def scene_prompt(sc, style: str) -> str:
    """Scene art prompt: the description with quoted spans stripped (sign names and spoken
    lines provoke garbled rendered text), plus the world style and the no-text guard."""
    desc = _QUOTED.sub("", sc["description"] or "").strip() or sc["name"]
    return ", ".join(x for x in [desc, style, NO_TEXT_GUARD] if x)


# ---------- the 'See' snapshot (scene + present characters, grounded in state) ----------
# Built to the FLUX.2 klein recipe (official BFL prompting guide): subjects first, ONE
# positionally anchored sentence per character so traits don't bleed, at most 3 people
# (the 4B blending ceiling), style named once for the whole frame, exclusions phrased
# positively, total kept tight (klein degrades past ~100 words).

_VIEW_POSITIONS = {1: ("in the center",), 2: ("on the left", "on the right"),
                   3: ("on the left", "in the center", "on the right")}
_VIEW_LIGHT = {"morning": "soft morning light", "afternoon": "bright afternoon light",
               "evening": "warm fading evening light", "night": "dim night, long shadows"}
_VIEW_MOOD = {"tense": "tense atmosphere", "dangerous": "menacing atmosphere"}


def _clip(s: str, words: int) -> str:
    return " ".join((s or "").split()[:words])


def view_prompt(conn, gid: str) -> str:
    """Compose the snapshot prompt from ACTUAL state: scene, present characters, story
    time of day, scene mood, world style."""
    g = repo.get_game(conn, gid)
    pd = repo.get_player(conn, gid)
    sc = repo.current_scene(conn, gid)
    chars = list(repo.present_characters(conn, gid, pd["location"]))[:3]
    env = _clip(_QUOTED.sub("", sc["description"] or "").strip() or sc["name"], 20)
    if chars:
        count = ("one person", "two people", "three people")[len(chars) - 1]
        lead = f"Wide full-body shot of {count} in {env}"
        lead += "" if lead.rstrip().endswith(".") else "."
        people = " ".join(f"{p.capitalize()}, {_clip(_gendered_base(c), 18).rstrip('.')}."
                          for p, c in zip(_VIEW_POSITIONS[len(chars)], chars))
    else:
        lead = f"Wide shot of {env}"
        lead += "" if lead.rstrip().endswith(".") else "."
        people = ""
    t = repo.game_time(conn, gid)
    tail = ". ".join(x for x in (
        _VIEW_LIGHT.get(t.get("part") or "", ""),
        _VIEW_MOOD.get(sc["status"] or "", ""),
        g["art_style"] or g["tone"] or "",
        NO_TEXT_GUARD,
    ) if x) + "."
    return " ".join(x for x in (lead, people, tail) if x)


def generate_view_snapshot(gid: str) -> dict | None:
    """The 'See' button: render the scene WITH the characters present in it, as it is NOW.
    Synchronous (the player watches a loader); persists the image and lands it as an image
    beat in the story flow. Returns the beat dict, or None when generation is unavailable."""
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            return None
        prompt = view_prompt(conn, gid)
        loc = repo.get_player(conn, gid)["location"]
    result = media.generate_scene_image(prompt, width=settings.IMAGE_VIEW_W,
                                        height=settings.IMAGE_VIEW_H)
    if not result or not result.get("image_url"):
        return None
    with db.get_conn() as conn:
        turn = repo.next_turn_index(conn, gid)
        url = _persist(gid, result["image_url"], f"view-t{turn}")
        return repo.add_beat(conn, gid, "narrator", None, "image", "", loc,
                             turn_index=turn, image_url=url)


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
