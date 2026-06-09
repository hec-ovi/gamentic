"""Finite state vocabularies (the 'rules of crafting'), single-sourced.

These are enforced in code (tools validate against them and expose them as JSON-schema
enums so the model is constrained to valid values) and surfaced to the model ONCE, as a
compact WORLD RULES block in the system prompt (present, not repeated). Keep each set
small (3-4 values) so the narrator/orchestrator is never overwhelmed.
"""

DISPOSITIONS = ("friendly", "neutral", "hostile", "unknown")
DISPOSITION_DEFAULT = "neutral"

SCENE_STATUSES = ("calm", "tense", "dangerous")
SCENE_STATUS_DEFAULT = "calm"

GAME_STATUSES = ("active", "won", "lost")
GAME_STATUS_DEFAULT = "active"

# Base player-facing action buttons per character, derived from disposition (code rule).
# The frontend renders these (plus any narrator-offered contextual actions), capped at CHAR_ACTION_CAP.
# Each action: (label, type). type tells the frontend what clicking does.
ACTIONS_BY_DISPOSITION = {
    "friendly": [("Talk", "talk"), ("Give...", "give"), ("Ask to follow", "follow")],
    "neutral":  [("Talk", "talk"), ("Give...", "give"), ("Provoke", "offer")],
    "hostile":  [("Talk", "talk"), ("Attack", "attack"), ("Back away", "offer")],
    "unknown":  [("Talk", "talk"), ("Observe", "offer")],
}

# Base scene-level actions (always available); the narrator can offer up to SCENE_ACTION_CAP total.
SCENE_BASE_ACTIONS = [("Look around", "look"), ("Search", "search")]


def world_rules() -> str:
    """One compact block stating the finite vocabularies. Injected once into the narrator prompt."""
    return (
        "WORLD RULES (use these exact values, nothing else):\n"
        f"- Character disposition toward the player: {' | '.join(DISPOSITIONS)} (set_disposition).\n"
        "- A character either follows the player or stays put (set_following). Followers move "
        "with you between scenes; others remain where they are and are there again if you return.\n"
        f"- Scene mood: {' | '.join(SCENE_STATUSES)} (set_scene_status).\n"
        f"- Story status: {' | '.join(GAME_STATUSES)} (set_game_status).\n"
        "- The player begins with NO goal. Give them a current goal with set_goal once their "
        "purpose emerges, and update it as the story turns.\n"
        "- A scene has at most 3 exits (add_exit), 6 items (place_item), and 3 player actions; "
        "a character carries at most 3 items and offers at most 3 actions. Items can be placed "
        "hidden and revealed later (reveal_item) when the player discovers them. Offer a one-off "
        "contextual action to a character with offer_action, or to the scene with offer_scene_action."
    )
