"""Conditionally offered narrative tools: the adjudication veto and the moment renderer.
Neither sits in the base narrator toolset; narrator_tools() adds them when they apply."""
from .base import _invalid, tool


@tool({"type": "function", "function": {
    "name": "reject_attempt",
    "description": "Veto one numbered PLAYER ATTEMPT with an in-world reason (shown to the "
                   "player), e.g. 'Mara steps back, refusing the coin.' Attempts you neither "
                   "apply nor veto simply happen as attempted.",
    "parameters": {"type": "object", "properties": {
        "attempt": {"type": "integer", "description": "The attempt number from the list."},
        "reason": {"type": "string", "description": "In-world reason it does not happen."},
    }, "required": ["attempt", "reason"]}}})
def reject_attempt(conn, gid, args, actor):
    reason = (args.get("reason") or "").strip() or "It does not happen."
    return {"kind": "reject", "text": reason,
            "cue": {"attempt": args.get("attempt")}, "reactions": []}


@tool({"type": "function", "function": {
    "name": "show_image",
    "description": "Render an image of this moment for the player. Call it when the player "
                   "looks at something, and on your own ONLY for a truly significant sight "
                   "(a reveal, an arrival, a transformation). At most one per turn. Describe "
                   "the VIEW in concrete visual terms: each subject and WHERE it is (left, "
                   "center, right, behind), notable objects, posture, light. Name present "
                   "characters by their exact names so their faces stay consistent. Looks "
                   "only; never words, signs or symbols to draw.",
    "parameters": {"type": "object", "properties": {
        "description": {"type": "string",
                        "description": "Detailed visual description of the shot."},
    }, "required": ["description"]}}})
def show_image(conn, gid, args, actor):
    desc = (args.get("description") or "").strip()
    if not desc:
        return _invalid("show_image: empty description")
    # generation is slow: the ENGINE collects this and main schedules it in the
    # background; the image lands later as its own image beat
    return {"kind": "image", "text": desc, "cue": None, "reactions": []}
