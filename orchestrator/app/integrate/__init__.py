"""Glue between the game and the accessory media services.

Voice assignment is fast (a list lookup), so it runs inline at creation. Image
generation is slow, so it runs as a background task; the frontend's /state polling
picks up the URLs when they land. Generated images are DOWNLOADED into a per-game
folder we own and served under /media/<gid>/..., so they persist with the game and
are deleted when the game is wiped. All best-effort: if media is down/disabled, the
game is unaffected and fully playable text-only.

One module per concern (see INDEX.md in this folder); this __init__ re-exports the
whole surface so every caller keeps the single import: `from . import integrate` then
`integrate.<function>(...)`.
"""
from .. import media  # noqa: F401  (tests patch integrate.media.<fn>)
from .voice import (  # noqa: F401
    NARRATOR_VOICES, apply_narrator_gender, assign_voices_for_game, release_game_voices,
    reresolve_voices,
)
from .image_prompts import (  # noqa: F401
    NO_TEXT_GUARD, _agentic_prompt, _clip, _concept, _focus_character, _gendered_base,
    _harden_image_prompt, _image_context, _place_text, _slug, _strip_quoted,
    character_descriptor, item_prompt, scene_prompt, view_prompt,
)
from .storage import (  # noqa: F401
    _existing_char_urls, _persist, delete_all_media, delete_game_images,
)
from .jobs import (  # noqa: F401
    _reference_url, art_direction, generate_creation_art, generate_directed_image,
    generate_images_for_game, generate_item_image, generate_scene_image,
    generate_view_snapshot,
)
