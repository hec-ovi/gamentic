"""The turn loop: a bounded multi-actor event loop over one model, many contexts.

One POST = one fully-resolved turn:
  1. record the player's action (tagged segments: say / do / attack / give)
  2. apply the player's DIRECTED actions (attack/give) -> may queue a target to react
  3. narrator call (world/scene + tools): narration, state changes, cues, spawn/kill
  4. process an ACTOR QUEUE (cued + targeted characters), each with its own POV + tools;
     a character's directed action (attack/give) queues ITS target to react -> cascade,
     bounded by a step cap and a per-character cap for pacing
  5. return new beats + updated state

Directed actions route deterministically to the targeted agent, so the narrator never has
to (and shouldn't) speak for characters.

One module per concern (see INDEX.md in this folder); this __init__ re-exports the
whole surface so every caller keeps the single import: `from . import engine` then
`engine.<function>(...)`.
"""
from .parsing import (  # noqa: F401
    EMOTIONS, _clean_segment, _extract_emotion, _reclassify_do, _scrub_narration,
    _unquote, clean_prose, parse_character_output, trim_to_sentence,
)
from .folds import maybe_update_character_summaries, maybe_update_summary  # noqa: F401
from .turn import (  # noqa: F401
    CONTINUE_IMPULSE, _DEDUP_EXEMPT, _SEGMENT_TYPES, _character_reply, _compose,
    _display, _image_pacing_ok, _why_impossible, interpret_action, run_turn,
)
