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

from . import repo, media, db, llm, prompts
from .config import settings


def assign_voices_for_game(conn, gid: str) -> None:
    """The narrator gets a preset; each character gets a DESIGNED voice from the Maya1
    registry, composed from their sheet at creation (the same moment their image
    descriptor is fixed), so gender/age/tone always match the character. One character =
    one stored voice (idempotent). Falls back to preset round-robin if the registry is
    unavailable. Best-effort throughout."""
    if not settings.VOICE_ENABLED:
        return
    voices = media.list_voice_ids()
    g = repo.get_game(conn, gid)
    if not g["narrator_voice_id"] and voices:
        repo.set_narrator_voice(conn, gid, "narrator" if "narrator" in voices else voices[0])
    for i, c in enumerate(repo.get_characters(conn, gid)):
        if c["voice_id"]:
            continue
        sheet = " ".join(x for x in (c["description"], c["persona"]) if x).strip() or c["name"]
        vid = media.register_character_voice(
            c["id"], c["name"], sheet,
            gender=repo.character_gender(c))   # the stored single source of truth
        if not vid and voices:
            vid = voices[(i + 1) % len(voices)]
        if vid:
            repo.set_character_voice(conn, c["id"], vid)


def release_game_voices(char_ids: list[str]) -> None:
    """Free the registry entries of a wiped game's characters (best-effort)."""
    for cid in char_ids:
        media.delete_character_voice(cid)


# Gendered narrator voices: full designed descriptions (voice-api treats any voice_id
# containing whitespace as a description), specified per the Maya1 anchoring rules:
# gender, age, pitch with texture, pacing, tone, accent. Distinctive = stable.
NARRATOR_VOICES = {
    "female": ("Female voice, in her 40s, warm low storyteller pitch with a velvet "
               "texture, unhurried measured pacing, intimate confident tone, neutral accent"),
    "male": ("Male voice, in his 50s, deep resonant storyteller pitch with a gravelly "
             "edge, unhurried measured pacing, intimate confident tone, neutral accent"),
}


def apply_narrator_gender(conn, gid: str, gender: str) -> None:
    """Switch the narrator's voice to the chosen gender (takes effect on the next line;
    the frontend reads narrator_voice_id from /state per beat). Empty gender returns to
    the preset default."""
    repo.set_narrator_gender(conn, gid, gender)
    if gender in NARRATOR_VOICES:
        repo.set_narrator_voice(conn, gid, NARRATOR_VOICES[gender])
    else:
        voices = media.list_voice_ids() if settings.VOICE_ENABLED else []
        repo.set_narrator_voice(conn, gid,
                                "narrator" if not voices or "narrator" in voices else voices[0])


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:40] or "img"


# ---------- image prompt composition ----------
# The model's appearance text is the source, but two failure modes are netted
# deterministically here: gender drift (a "woman" rendered ambiguous because the
# appearance never says so) and rendered text (FLUX draws any words it finds an
# excuse for: sign names, lettering, watermarks).

_QUOTED = re.compile(r'["“”][^"“”]*["“”]')   # "..." spans (incl. curly quotes)
# standalone '...' spans (a ship name like 'Star-Strider') but never apostrophes in words
_SQUOTED = re.compile(r"(?<!\w)'[^'\n]{1,80}'(?!\w)")


def _strip_quoted(s: str) -> str:
    return _SQUOTED.sub("", _QUOTED.sub("", s or "")).strip()


def _place_text(sc) -> str:
    """The art subject for a scene: its NAME (the concrete place) leading its description,
    quoted spans stripped. Description alone can be world-level prose; the name anchors it."""
    desc = _strip_quoted(sc["description"])
    name = (sc["name"] or "").strip()
    if not desc:
        return name
    if name and name.lower() not in desc.lower():
        return f"{name}. {desc}"
    return desc
# FLUX has no negative prompt and negation phrasing backfires ("no text" invites text);
# per the official BFL prompting guide, exclusions are phrased as the positive visual
# that occupies the space. https://docs.bfl.ai/guides/prompting_guide_t2i_negative
NO_TEXT_GUARD = "plain unmarked surfaces, no signage"


def _gendered_base(c) -> str:
    """A character's visual base: appearance text with an explicit gender lead from the
    character's STORED gender (decided once at creation), so the portrait can never
    disagree with the narrator's pronouns. The net (repo.gender_hint) only remains as
    the fallback inside repo.character_gender for legacy rows."""
    base = (c["appearance"] or c["description"] or c["persona"] or c["name"]).strip()
    gender = repo.character_gender(c)
    if gender and not repo.gender_hint(base):
        base = f"{gender}, {base}"
    return base


def character_descriptor(c) -> str:
    """The outgoing image descriptor: explicit gender first, then looks, then the no-text guard."""
    return f"{_gendered_base(c)}, {NO_TEXT_GUARD}"


def scene_prompt(sc, style: str) -> str:
    """Scene art prompt: the place (name + description, quoted spans stripped since sign
    and ship names provoke garbled rendered text), the world style, the no-text guard."""
    return ", ".join(x for x in [_place_text(sc), style, NO_TEXT_GUARD] if x)


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


def _concept(*parts, max_chars: int = 320) -> str:
    """A short human description of WHAT an image shows (its concept), built from the
    given parts: shown clamped as the caption in the chat flow and in full on the
    lightbox and the profile's memories (an image without a concept is just a picture)."""
    text = " ".join(p.strip().rstrip(".") + "." for p in parts if p and p.strip())
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0].rstrip(",;:") + "..."
    return text


def _focus_character(conn, gid: str, focus: str):
    """The present character the focus text names, if any."""
    pd = repo.get_player(conn, gid)
    low = (focus or "").lower()
    for c in repo.present_characters(conn, gid, pd["location"]):
        if c["name"] and c["name"].lower() in low:
            return c
    return None


def view_prompt(conn, gid: str, focus: str | None = None) -> str:
    """Compose the snapshot prompt from ACTUAL state: scene, present characters, story
    time of day, scene mood, world style. A focus ("what Layla is doing", "that ship")
    becomes THE subject instead of the whole-scene group shot."""
    g = repo.get_game(conn, gid)
    pd = repo.get_player(conn, gid)
    sc = repo.current_scene(conn, gid)
    chars = list(repo.present_characters(conn, gid, pd["location"]))[:3]
    env = _clip(_place_text(sc), 20)
    focus = _clip(_strip_quoted(focus or ""), 20).rstrip(".")
    if focus:
        fc = _focus_character(conn, gid, focus)
        if fc:
            lead = f"Full-body shot of {_clip(_gendered_base(fc), 18).rstrip('.')}, {focus}, in {env}"
        else:
            lead = f"Detailed shot of {focus}, in {env}"
        lead += "" if lead.rstrip().endswith(".") else "."
        people = ""
    elif chars:
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


# ---------- agentic image prompts (optional, settings.IMAGE_AGENTIC_PROMPTS) ----------
# Hybrid: the text model writes the prompt from live context (it can express poses and
# the just-happened moment, which a template cannot), then CODE enforces the invariants
# (quoted words become rendered lettering, length kills klein, the no-text tail). Any
# failure falls back to the deterministic template prompt.

def _harden_image_prompt(text: str) -> str:
    text = text.strip().strip('"').strip()
    text = _QUOTED.sub("", text).strip()
    text = _clip(text, 90)
    if NO_TEXT_GUARD.lower() not in text.lower():
        text = text.rstrip(".") + ". " + NO_TEXT_GUARD + "."
    return text


def _image_context(conn, gid: str, include_chars: bool, focus: str | None = None) -> str:
    g = repo.get_game(conn, gid)
    pd = repo.get_player(conn, gid)
    sc = repo.current_scene(conn, gid)
    t = repo.game_time(conn, gid)
    lines = [f"PLACE: {_place_text(sc)}",
             f"TIME OF DAY: {t.get('part') or 'day'}    MOOD: {sc['status']}"]
    if (focus or "").strip():
        lines.append(f"THE PLAYER WANTS TO LOOK AT: {_clip(_strip_quoted(focus), 25)}")
    if include_chars:
        chars = list(repo.present_characters(conn, gid, pd["location"]))[:3]
        if chars:
            lines.append("CHARACTERS PRESENT (depict them):")
            lines += [f"- {c['name']}: {_gendered_base(c)}" for c in chars]
        recent = [b for b in repo.recent_beats_at(conn, gid, pd["location"], 6)
                  if not b["private_with"]]
        if recent:
            lines.append("JUST HAPPENED (use for poses and action):")
            lines += [f"- {b['text']}" for b in recent]
    lines.append(f"STYLE: {g['art_style'] or g['tone'] or 'cinematic'}")
    return "\n".join(lines)


def _agentic_prompt(context: str, fallback: str) -> str:
    """One LLM call that writes the image prompt; guarded, with the template as the net."""
    try:
        reply = llm.chat(prompts.build_image_prompt_messages(context),
                         temperature=0.4, max_tokens=140)
        text = (reply.content or "").strip()
    except Exception:
        return fallback
    return _harden_image_prompt(text) if text else fallback


def _reference_url(stored: str | None) -> str | None:
    """Absolutize a character image URL so the image-api can fetch it (our /media files
    via the compose-internal hostname; its own /image/file paths via IMAGE_API_URL)."""
    if not stored:
        return None
    if stored.startswith("http"):
        return stored
    if stored.startswith("/media/"):
        return f"{settings.MEDIA_INTERNAL_BASE}{stored}"
    return f"{settings.IMAGE_API_URL}{stored}"


def generate_view_snapshot(gid: str, focus: str | None = None,
                           private_with: str | None = None) -> dict | None:
    """The 'See' button: render the scene WITH the characters present in it, as it is NOW.
    Synchronous (the player watches a loader); persists the image and lands it as an image
    beat in the story flow (the focus, when given, becomes the beat's caption text).
    Identity references follow the subject: looking at a named character sends ONLY their
    stored view; looking at a thing sends none; no focus sends every present character's."""
    focus = (focus or "").strip()
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            return None
        prompt = view_prompt(conn, gid, focus=focus or None)
        context = _image_context(conn, gid, include_chars=True, focus=focus or None) \
            if settings.IMAGE_AGENTIC_PROMPTS else ""
        loc = repo.get_player(conn, gid)["location"]
        if focus:
            fc = _focus_character(conn, gid, focus)
            chars = [fc] if fc else []
        else:
            chars = list(repo.present_characters(conn, gid, loc))[:3]
        refs = [u for u in (_reference_url(c["body_front_url"]) for c in chars) if u]
    if context:
        prompt = _agentic_prompt(context, fallback=prompt)   # LLM call outside the DB conn
    result = media.generate_scene_image(prompt, width=settings.IMAGE_VIEW_W,
                                        height=settings.IMAGE_VIEW_H,
                                        references=refs or None)
    if not result or not result.get("image_url"):
        return None
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            return None    # game wiped while rendering: never re-create its media folder
        sc = repo.current_scene(conn, gid)
        t = repo.game_time(conn, gid)
        caption = _concept(focus, f"{sc['name']}, {t['label']}",
                           _clip(_strip_quoted(sc["description"]), 30))
        turn = repo.next_turn_index(conn, gid)
        url = _persist(gid, result["image_url"], f"view-t{turn}")
        # private_with: a quiet study from the private panel lands IN that thread
        return repo.add_beat(conn, gid, "narrator", None, "image", caption, loc,
                             turn_index=turn, image_url=url, private_with=private_with)


def generate_directed_image(gid: str, description: str, caption: str = "") -> dict | None:
    """Background: the narrator fired show_image (answering a player look, or its own
    dramatic choice). The narrator's visual description IS the shot; code enforces the
    invariants (quoted spans stripped, length clipped, style + no-text guard appended)
    and conditions on the identity references of present characters named in it. The
    image lands as its own image beat, picked up by the frontend's beats polling."""
    description = (description or "").strip()
    if not description:
        return None
    with db.get_conn() as conn:
        g = repo.get_game(conn, gid)
        if not g:
            return None
        loc = repo.get_player(conn, gid)["location"]
        style = g["art_style"] or g["tone"] or ""
        named = [c for c in repo.present_characters(conn, gid, loc)
                 if c["name"] and c["name"].lower() in description.lower()][:3]
        refs = [u for u in (_reference_url(c["body_front_url"]) for c in named) if u]
        prompt = _harden_image_prompt(f"{_strip_quoted(description)} {style}".strip())
    result = media.generate_scene_image(prompt, width=settings.IMAGE_VIEW_W,
                                        height=settings.IMAGE_VIEW_H,
                                        references=refs or None)
    if not result or not result.get("image_url"):
        return None
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            return None    # game wiped while rendering: never re-create its media folder
        turn = repo.next_turn_index(conn, gid)
        url = _persist(gid, result["image_url"], f"shot-t{turn}")
        # the narrator's own visual description IS the moment's concept
        return repo.add_beat(conn, gid, "narrator", None, "image",
                             _concept(caption, description), loc,
                             turn_index=turn, image_url=url)


def item_prompt(name: str, description: str, style: str) -> str:
    """A small unlock card for one item: single centered subject, plain backdrop."""
    return ", ".join(x for x in (
        f"Close-up of a single {name}",
        _strip_quoted(description),
        "centered on a plain dark surface, soft dramatic light",
        style, NO_TEXT_GUARD) if x)


def generate_item_image(gid: str, name: str) -> dict | None:
    """Background: render the small unlock image of a newly visible item, attach it to the
    item wherever it now lives, and land it as a SYSTEM image beat (small card in the chat;
    system image beats don't count against the narrator's show_image pacing)."""
    with db.get_conn() as conn:
        g = repo.get_game(conn, gid)
        if not g:
            return None
        entry = repo.visible_item_index(conn, gid).get(repo.norm_name(name).lower())
        if not entry or entry.get("image_url"):       # gone from view, or already pictured
            return None
        style = g["art_style"] or g["tone"] or ""
        loc = repo.get_player(conn, gid)["location"]
        prompt = item_prompt(entry["name"], entry["description"], style)
    result = media.generate_scene_image(prompt, width=settings.IMAGE_ITEM_SIZE,
                                        height=settings.IMAGE_ITEM_SIZE)
    if not result or not result.get("image_url"):
        return None
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            return None    # game wiped while rendering: never re-create its media folder
        url = _persist(gid, result["image_url"], f"item-{_slug(name)}")
        if not repo.set_item_image(conn, gid, name, url):
            return None                                # the item vanished mid-render
        return repo.add_beat(conn, gid, "system", None, "image",
                             _concept(entry["name"], entry["description"]), loc,
                             image_url=url)


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


def _existing_char_urls(gid: str, cid: str) -> dict | None:
    """Reference images already persisted on disk for this character (a crashed earlier
    run may have written the files but lost the DB commit). Returns the /media urls,
    or None when no files exist."""
    d = os.path.join(settings.GAMES_DATA_DIR, gid, "images")
    urls = {}
    for view, key in (("face", "face_url"), ("front", "body_front_url"), ("side", "body_side_url")):
        if os.path.isfile(os.path.join(d, f"char-{cid}-{view}.png")):
            urls[key] = f"/media/{gid}/char-{cid}-{view}.png"
    return urls or None


def generate_images_for_game(gid: str) -> None:
    """Background: generate + persist the 3-image reference set for each character.
    Resilient (live bug: a 'database is locked' on ONE character's commit killed the
    whole loop, leaving every portrait null): each character is independent, files
    already on disk are RELINKED instead of re-rendered, and the per-turn self-heal
    re-schedules this job until every character has their set."""
    with db.get_conn() as conn:
        g = repo.get_game(conn, gid)
        if not g:
            return
        style = g["art_style"] or g["tone"] or ""
        chars = repo.get_characters(conn, gid)
    for c in chars:
        if repo.character_has_images(c):
            continue
        try:
            urls = _existing_char_urls(gid, c["id"])
            if not urls:
                result = media.generate_character_images(character_descriptor(c), style)
                if not result:
                    continue
                with db.get_conn() as conn:
                    if not repo.get_game(conn, gid):
                        return   # game wiped while rendering: never re-create its folder
                    urls = {
                        "face_url": _persist(gid, result.get("face_url"), f"char-{c['id']}-face"),
                        "body_front_url": _persist(gid, result.get("body_front_url"), f"char-{c['id']}-front"),
                        "body_side_url": _persist(gid, result.get("body_side_url"), f"char-{c['id']}-side"),
                    }
                    repo.set_character_images(conn, c["id"], **urls)
            else:
                with db.get_conn() as conn:   # relink: the render already happened
                    if not repo.get_game(conn, gid):
                        return
                    repo.set_character_images(conn, c["id"], **{
                        "face_url": None, "body_front_url": None, "body_side_url": None,
                        **urls})
        except Exception:
            continue   # one character's failure never costs the others their portraits


def generate_scene_image(gid: str, scene_id: str) -> None:
    """Background: generate + persist art for one scene (skips if it already has an image)."""
    with db.get_conn() as conn:
        sc = repo.get_scene_by_id(conn, scene_id)
        g = repo.get_game(conn, gid)
        if not sc or not g or sc["image_url"]:
            return
        style = g["art_style"] or g["tone"] or ""
        prompt = scene_prompt(sc, style)
        # agentic context only if this is still the CURRENT scene (this runs in the
        # background; the player may have moved on, and the context follows the player)
        context = _image_context(conn, gid, include_chars=False) \
            if settings.IMAGE_AGENTIC_PROMPTS \
            and sc["id"] == repo.current_scene(conn, gid)["id"] else ""
    if context:
        prompt = _agentic_prompt(context, fallback=prompt)   # LLM call outside the DB conn
    result = media.generate_scene_image(prompt)
    if not result:
        return
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            return         # game wiped while rendering: never re-create its media folder
        url = _persist(gid, result.get("image_url"), f"scene-{scene_id}")
        repo.set_scene_image(conn, scene_id, url)


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
