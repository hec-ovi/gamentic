# repo/ index

Data access, one module per domain. Callers import the PACKAGE (`from . import repo`) and call `repo.<fn>`; `__init__.py` re-exports everything, so you never need to know the module to CALL a function, only to CHANGE one. All functions take an open sqlite3.Connection (the engine owns the transaction: one turn = one commit).

| Module | Owns | Key functions |
|---|---|---|
| `base.py` | ids + name normalization | `_id`, `norm_name` (alias `norm_location`) |
| `games.py` | the games table | `create_game`, `get_game`, `delete_game`, `set_goal`, `set_difficulty`, `set_narrator_gender`, `set_narrator_voice`, `append_memory`, `set_context_used`, `clear_arrival_note` |
| `players.py` | player_state: life, points, flags, the pack | `get_player`, `set_life`, `add_item`, `remove_item`, `player_has_item`, `set_flag` |
| `characters.py` | character rows, traits, the profile | `find_character_by_name`, `resolve_target`, `set_character_life`, `character_add/remove/reveal_item`, `spawn_character`, `add_trait`, `character_traits`, `character_profile`, `offer_action` |
| `items.py` | item-blob rules (ONE place) | `visible_items`, `narrator_items`, `_item_matches`, `find_by_name`, `stack`, `new_record`, `take_out`, `unhide`, `set_item_image`, `visible_item_index` |
| `scenes.py` | scene rows, movement + draft layer, exits, scene items | `current_scene`, `get_or_create_scene`, `set_location`, `add_exit`, `add/reveal/take_scene_item`, `set_scene_description/status/draft/image` |
| `quests.py` | quests + objectives | `start_quest`, `update_objective`, `set_quest_status`, `quest_dict` |
| `lore.py` | keyword-matched world facts | `match_lore` |
| `beats.py` | the story log + model-facing windows | `add_beat`, `all_beats`, `recent_beats(_at)`, `witnessed_beats_for_character`, `last_image_turn`, `next_turn_index` |
| `clock.py` | the FICTIONAL story clock | `advance_time`, `time_at`, `game_time`, `elapsed_text` |
| `state.py` | the assembled GameState the API serves | `game_state` |

Conventions:
- Items are JSON lists on their owner's row; the mutation rules (stack vs exists, caps, unhide, image carry-over) live in `items.py` and the owner modules only load/save their own blob.
- Intra-package imports are module-style (`from . import games`) so the few natural cycles (games<->scenes, items<->characters) resolve at call time; never `from .sibling import name` across a cycle.
- Names are normalized with `norm_name` on EVERY write and lookup (scenes and items): the model drifts between snake_case and spaces, and unnormalized keys strand state in duplicate rows.
