"""Data access package. Plain SQL helpers over the connection from db.get_conn();
functions take an open sqlite3.Connection so the engine controls the transaction
boundary (one turn = one commit).

One module per domain (see INDEX.md in this folder); this __init__ re-exports the
whole surface so every caller keeps the single import: `from . import repo` then
`repo.<function>(...)`."""
from .. import db  # noqa: F401  (prompts uses repo.db.loads on row blobs)
from .base import _id, norm_location, norm_name  # noqa: F401
from .beats import (  # noqa: F401
    add_beat, all_beats, beats_between, clear_beats, last_image_turn, next_turn_index,
    recent_beats, recent_beats_at, scene_beats_for_character,
)
from .characters import (  # noqa: F401
    add_moment, add_origin_fact, add_trait, available_actions, character_add_item,
    character_gender, character_has_images, character_moments,
    character_origin_revealed, character_profile, character_remove_item,
    character_relation, character_reveal_item, character_traits, find_character_by_name,
    gender_hint, get_character, get_characters, kill_character, offer_action,
    present_characters, resolve_target, set_character_context, set_character_description,
    set_character_images, set_character_life, set_character_voice, set_disposition,
    set_following, set_relation, spawn_character,
)
from .clock import advance_time, elapsed_text, game_time, time_at  # noqa: F401
from .games import (  # noqa: F401
    append_memory, clear_arrival_note, create_game, delete_game, effective_history_beats,
    get_game, list_games, set_context_used, set_difficulty, set_game_status, set_goal,
    set_history_beats, set_narrator_gender, set_narrator_voice, set_story_summary,
)
from .items import (  # noqa: F401
    _item_matches, narrator_items, set_item_image, visible_item_index, visible_items,
)
from .lore import match_lore  # noqa: F401
from .players import (  # noqa: F401
    add_item, add_points, get_player, player_dict, player_has_item, remove_item,
    set_flag, set_life,
)
from .quests import (  # noqa: F401
    get_objectives, get_quests, objective_text, quest_dict, quest_title,
    set_quest_status, start_quest, update_objective,
)
from .scenes import (  # noqa: F401
    add_exit, add_scene_item, current_scene, get_or_create_scene, get_scene,
    get_scene_by_id, offer_scene_action, reveal_scene_item, scene_available_actions,
    scene_is_established, set_location, set_scene_background, set_scene_description,
    set_scene_draft, set_scene_image, set_scene_status, take_scene_item,
)
from .state import game_state  # noqa: F401
