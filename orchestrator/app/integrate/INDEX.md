# integrate/ index

Glue to the media services, one module per concern. Callers import the PACKAGE (`from . import integrate`) and call `integrate.<fn>`; `__init__.py` re-exports everything (plus `media`, which tests patch as `integrate.media.<fn>`). All best-effort: media down/disabled never breaks the game.

| Module | Owns | Key functions |
|---|---|---|
| `voice.py` | voice identity: engine-composed designs (app/voice_design.py) resolved per the ACTIVE audio provider; inline at creation, re-resolved once on provider switch | `assign_voices_for_game`, `apply_narrator_gender`, `reresolve_voices`, `release_game_voices`, `NARRATOR_VOICES` |
| `image_prompts.py` | prompt composition, the pure layer: gender net, quoted-span stripping, the no-text guard, the FLUX.2 klein view recipe, the per-image art director | `character_descriptor`, `scene_prompt`, `view_prompt`, `item_prompt`, `NO_TEXT_GUARD`, `_harden_image_prompt`, `_image_context`, `_artdirected_prompt`, `_gendered_base`, `_strip_quoted`, `_concept` |
| `storage.py` | media persistence on disk (the per-game /media folder); `_persist` also frees the image-api staging copy the instant our copy lands (ownership-based deletion, owner decision 2026-06-11), and `remote_image_urls` collects the persist-fallback `/image/file?` URLs a game-delete must sweep | `_persist`, `_existing_char_urls`, `delete_game_images`, `delete_all_media`, `remote_image_urls` |
| `jobs.py` | the stateful generate_* orchestrators (background tasks, plus the synchronous See snapshot): own DB conns around the slow render, wiped-game re-checks | `generate_view_snapshot`, `generate_directed_image`, `generate_item_image`, `generate_images_for_game`, `generate_scene_image`, `_reference_url` |

Conventions:
- Intra-package imports are module-style (`from . import image_prompts, storage`), same as repo/.
- Never hold a DB connection across a render or LLM call: read state, close, call out, re-open and RE-CHECK the game still exists before writing (a wipe mid-render must never resurrect a media folder).
- main.py schedules through the facade namespace (`integrate.generate_images_for_game`), resolved at call time; keep it that way so tests can monkeypatch `integrate.<fn>`.
