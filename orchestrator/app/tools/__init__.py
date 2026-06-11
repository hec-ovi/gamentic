"""Game tools package: the model's ONLY way to change state.

One module per domain (see INDEX.md in this folder); each tool's JSON schema and its
handler live side by side, registered into base.SCHEMAS / base.HANDLERS by the @tool
decorator. This __init__ composes the toolsets and exposes the same public surface as
before: NARRATOR_TOOLS, CHARACTER_TOOLS, narrator_tools(), apply_tool().

Two toolsets share the one validated dispatcher:
  - NARRATOR_TOOLS: world/state adjudication + directing (cue) + dynamic cast (spawn/kill).
  - CHARACTER_TOOLS: a character can act on others - attack / give_item - targeting another
    character OR the player. The engine resolves these and queues the target to REACT, so a
    turn can cascade (bounded for pacing).
"""
import json
import logging

from . import characters, combat, items, narrative, progression, scene, world  # noqa: F401 (registration)
from .base import HANDLERS, SCHEMAS, _invalid, clean_arg

# One INFO line per tool call (name, result kind, compact args): the raw material for
# the measured tool-frequency review. main.py's lifespan makes INFO visible.
_log = logging.getLogger("gamentic.tools")

# The base narrator toolset, in the EXACT order the model has always seen (schema order
# is part of the prompt a small model reads; keep it stable unless deliberately retuned).
_NARRATOR_ORDER = [
    "apply_damage", "heal", "add_item", "remove_item", "award_points",
    "start_quest", "update_objective", "complete_quest", "fail_quest",
    "move_location", "set_flag", "remember",
    "cue_character", "spawn_character", "kill_character",
    "set_disposition", "set_following",
    "set_scene_status", "set_game_status",
    "describe_scene", "describe_character", "set_goal",
    "add_exit", "place_item", "reveal_item", "take_item",
    "offer_action", "offer_scene_action", "give_item",
    "note_trait", "note_scene", "advance_time",
    "reveal_origin", "note_moment", "set_relation",   # appended (schema order is stable; new tools go at the end)
]
NARRATOR_TOOLS = [SCHEMAS[n] for n in _NARRATOR_ORDER]

# Conditionally offered (see narrator_tools): a veto tool with nothing to veto, or an
# image tool with images off, is schema noise and an invitation to misuse.
REJECT_ATTEMPT_TOOL = SCHEMAS["reject_attempt"]
SHOW_IMAGE_TOOL = SCHEMAS["show_image"]

# Tools a CHARACTER agent may call to act on others. Their speech is the message content;
# these are for doing things to another character or to the player.
CHARACTER_TOOLS = [combat.CHARACTER_ATTACK, items.CHARACTER_GIVE,
                   characters.SHARE_PAST, characters.MARK_MOMENT, characters.ADMIT_TRAIT]


def narrator_tools(adjudicating: bool, images: bool = False) -> list:
    """The narrator's toolset for one call; reject_attempt only when attempts are pending,
    show_image only when image generation is on."""
    return (NARRATOR_TOOLS + ([REJECT_ATTEMPT_TOOL] if adjudicating else [])
            + ([SHOW_IMAGE_TOOL] if images else []))


def apply_tool(conn, gid: str, name: str, args: dict, actor=None) -> dict:
    """Validated dispatch. actor: None (narrator/player/world) or a character row acting
    on others. Unknown names and bad argument types come back as kind='invalid'."""
    handler = HANDLERS.get(name)
    if handler is None:
        out = _invalid(f"unknown tool '{name}'")
    else:
        try:
            # tool-stream debris is scrubbed from every string argument BEFORE it can reach
            # state or a receipt (live: a malformed stream put "<|tool_call>..." inside a goal)
            out = handler(conn, gid, clean_arg(args or {}), actor)
        except (ValueError, TypeError) as e:
            out = _invalid(f"{name}: bad args ({e})")
    _log.info("tool=%s kind=%s args=%s", name, out["kind"],
              json.dumps(args or {}, default=str)[:200])
    return out
