# tools/ index

The model's ONLY way to change state. One module per domain; each tool is one self-contained block: its JSON schema (what the model sees) directly above its handler (what applies it), registered together by the `@tool` decorator into `base.SCHEMAS` / `base.HANDLERS`.

To change ONE tool: find its module below, edit the one block. To add a tool: write one `@tool({...}) def name(conn, gid, args, actor)` block in the right module, then add its name to `_NARRATOR_ORDER` in `__init__.py` (schema order is part of what the small model reads; append unless you mean to retune).

| Module | Tools |
|---|---|
| `combat.py` | `apply_damage` (alias `attack`), `heal`; the character-agent `attack` schema (`CHARACTER_ATTACK`) |
| `items.py` | `add_item`, `remove_item`, `place_item`, `reveal_item`, `take_item`, `give_item` (alias `give`); the character-agent give schema (`CHARACTER_GIVE`) |
| `characters.py` | `cue_character`, `spawn_character`, `kill_character`, `set_disposition`, `set_following`, `describe_character`, `note_trait`, `reveal_origin`, `offer_action` |
| `progression.py` | `award_points`, `start_quest`, `update_objective`, `complete_quest`, `fail_quest`, `set_goal` |
| `scene.py` | `move_location`, `set_scene_status`, `describe_scene`, `add_exit`, `offer_scene_action`, `note_scene` |
| `world.py` | `set_flag`, `remember`, `set_game_status`, `advance_time` |
| `narrative.py` | `reject_attempt` (offered only while attempts await adjudication), `show_image` (offered only when images are on) |
| `base.py` | the registry (`SCHEMAS`/`HANDLERS`, `@tool`, `alias`) and the result shapes (`_result`/`_invalid`) |
| `__init__.py` | composes `NARRATOR_TOOLS` (in the model's stable order), `CHARACTER_TOOLS`, `narrator_tools()`, and the `apply_tool` dispatcher |

Handler contract: `(conn, gid, args, actor) -> {kind, text, cue, reactions}` where kind is `state | cue | memory | invalid | spawn | kill | reject | image`; `text` is the system-beat receipt shown to the player (None = silent); `actor` is None for the narrator/player or the acting character's row. ValueError/TypeError inside a handler comes back as `invalid`, never as a crash.
