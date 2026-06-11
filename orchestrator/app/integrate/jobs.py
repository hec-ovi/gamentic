"""The stateful generate_* orchestrators: each opens its own DB conns around the slow
render call (never across it), re-checks the game still exists before persisting (a
wipe mid-render must never resurrect a media folder), and lands results as beats or
row updates. All run as background tasks except the synchronous See snapshot."""
from .. import db, repo, media
from ..config import settings
from . import events, image_prompts, storage


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
        prompt = image_prompts.view_prompt(conn, gid, focus=focus or None)
        context = image_prompts._image_context(conn, gid, include_chars=True, focus=focus or None) \
            if settings.IMAGE_AGENTIC_PROMPTS else ""
        loc = repo.get_player(conn, gid)["location"]
        if focus:
            fc = image_prompts._focus_character(conn, gid, focus)
            if not fc and private_with:
                # a PRIVATE look is always a study of that character, whatever the
                # focus words say (live: "any picture of you and your brother?" named
                # nobody, so the render went out with no identity reference and came
                # back a stranger)
                fc = repo.get_character(conn, private_with)
            chars = [fc] if fc else []
        elif private_with:
            chars = [repo.get_character(conn, private_with)]
        else:
            chars = list(repo.present_characters(conn, gid, loc))[:3]
        chars = [c for c in chars if c]
        refs = [u for u in (_reference_url(c["body_front_url"]) for c in chars) if u]
    if context:
        prompt = image_prompts._agentic_prompt(context, fallback=prompt)   # LLM call outside the DB conn
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
        caption = image_prompts._concept(
            focus, f"{sc['name']}, {t['label']}",
            image_prompts._clip(image_prompts._strip_quoted(sc["description"]), 30))
        turn = repo.next_turn_index(conn, gid)
        # unique suffix: two renders can persist while the turn counter reads the same
        # value (live: two beats pointed at one overwritten view-t7.png, two captions)
        url = storage._persist(gid, result["image_url"], f"view-t{turn}-{repo._id()}")
        # private_with: a quiet study from the private panel lands IN that thread
        beat = repo.add_beat(conn, gid, "narrator", None, "image", caption, loc,
                             turn_index=turn, image_url=url, private_with=private_with)
    events.publish(gid, "beat", private_with=private_with)
    return beat


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
        prompt = image_prompts._harden_image_prompt(
            f"{image_prompts._strip_quoted(description)} {style}".strip())
    result = media.generate_scene_image(prompt, width=settings.IMAGE_VIEW_W,
                                        height=settings.IMAGE_VIEW_H,
                                        references=refs or None)
    if not result or not result.get("image_url"):
        return None
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            return None    # game wiped while rendering: never re-create its media folder
        turn = repo.next_turn_index(conn, gid)
        url = storage._persist(gid, result["image_url"], f"shot-t{turn}-{repo._id()}")
        # the narrator's own visual description IS the moment's concept
        beat = repo.add_beat(conn, gid, "narrator", None, "image",
                             image_prompts._concept(caption, description), loc,
                             turn_index=turn, image_url=url)
    events.publish(gid, "beat")
    return beat


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
        prompt = image_prompts.item_prompt(entry["name"], entry["description"], style)
    result = media.generate_scene_image(prompt, width=settings.IMAGE_ITEM_SIZE,
                                        height=settings.IMAGE_ITEM_SIZE)
    if not result or not result.get("image_url"):
        return None
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            return None    # game wiped while rendering: never re-create its media folder
        url = storage._persist(gid, result["image_url"], f"item-{image_prompts._slug(name)}")
        if not repo.set_item_image(conn, gid, name, url):
            return None                                # the item vanished mid-render
        beat = repo.add_beat(conn, gid, "system", None, "image",
                             image_prompts._concept(entry["name"], entry["description"]), loc,
                             image_url=url)
    events.publish(gid, "item", name=name)
    return beat


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
            urls = storage._existing_char_urls(gid, c["id"])
            if not urls:
                result = media.generate_character_images(
                    image_prompts.character_descriptor(c), style)
                if not result:
                    continue
                with db.get_conn() as conn:
                    if not repo.get_game(conn, gid):
                        return   # game wiped while rendering: never re-create its folder
                    urls = {
                        "face_url": storage._persist(gid, result.get("face_url"), f"char-{c['id']}-face"),
                        "body_front_url": storage._persist(gid, result.get("body_front_url"), f"char-{c['id']}-front"),
                        "body_side_url": storage._persist(gid, result.get("body_side_url"), f"char-{c['id']}-side"),
                    }
                    repo.set_character_images(conn, c["id"], **urls)
                events.publish(gid, "portrait", char_id=c["id"])
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
        prompt = image_prompts.scene_prompt(sc, style)
        # agentic context only if this is still the CURRENT scene (this runs in the
        # background; the player may have moved on, and the context follows the player)
        context = image_prompts._image_context(conn, gid, include_chars=False) \
            if settings.IMAGE_AGENTIC_PROMPTS \
            and sc["id"] == repo.current_scene(conn, gid)["id"] else ""
    if context:
        prompt = image_prompts._agentic_prompt(context, fallback=prompt)   # LLM call outside the DB conn
    result = media.generate_scene_image(prompt)
    if not result:
        return
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            return         # game wiped while rendering: never re-create its media folder
        url = storage._persist(gid, result.get("image_url"), f"scene-{scene_id}")
        repo.set_scene_image(conn, scene_id, url)
    events.publish(gid, "scene", scene_id=scene_id)
