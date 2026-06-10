"""The scene: movement, mood, description, exits, offered scene actions, the draft note."""
from .. import constants, repo
from ..config import settings
from .base import _invalid, _result, tool


@tool({"type": "function", "function": {
    "name": "move_location", "description": "Move the scene/player to a new location.",
    "parameters": {"type": "object", "properties": {"location": {"type": "string"}}, "required": ["location"]}}})
def move_location(conn, gid, args, actor):
    loc = repo.norm_name(args.get("location") or "")
    if not loc:
        return _invalid("move_location: empty location")
    repo.set_location(conn, gid, loc)
    return _result("state", f"You move to {loc}.")


@tool({"type": "function", "function": {
    "name": "set_scene_status",
    "description": "Set the mood of the current scene as it shifts.",
    "parameters": {"type": "object", "properties": {
        "status": {"type": "string", "enum": list(constants.SCENE_STATUSES)},
    }, "required": ["status"]}}})
def set_scene_status(conn, gid, args, actor):
    st = (args.get("status") or "").strip().lower()
    if st not in constants.SCENE_STATUSES:
        return _invalid(f"set_scene_status: '{st}' not in {constants.SCENE_STATUSES}")
    repo.set_scene_status(conn, gid, st)
    return _result("state")  # silent; reflected in HUD


@tool({"type": "function", "function": {
    "name": "describe_scene",
    "description": "Write or update the current scene's short description (do this when the "
                   "player enters a new place so the scene card reads right).",
    "parameters": {"type": "object", "properties": {
        "description": {"type": "string"}}, "required": ["description"]}}})
def describe_scene(conn, gid, args, actor):
    desc = (args.get("description") or "").strip()
    if desc:
        repo.set_scene_description(conn, gid, desc)
    return _result("state")  # silent; shown on the scene card


@tool({"type": "function", "function": {
    "name": "add_exit",
    "description": "Reveal a way out of the current scene (a button the player can take). "
                   "A scene has at most 3 exits; a scene with none is a dead end.",
    "parameters": {"type": "object", "properties": {
        "label": {"type": "string", "description": "Button text, e.g. 'the rain-slick street'."},
        "target": {"type": "string", "description": "Destination scene name."},
    }, "required": ["label", "target"]}}})
def add_exit(conn, gid, args, actor):
    label = (args.get("label") or "").strip()
    target = (args.get("target") or "").strip()
    if not label or not target:
        return _invalid("add_exit: need label and target")
    res = repo.add_exit(conn, gid, label, target, settings.SCENE_EXIT_CAP)
    if res == "full":
        return _invalid(f"add_exit: scene already has {settings.SCENE_EXIT_CAP} exits")
    if res == "exists":
        return _result("state")  # already there, silent
    return _result("state", f"A way out opens: {label}.")


@tool({"type": "function", "function": {
    "name": "offer_scene_action",
    "description": "Offer the player a one-off contextual action in the scene (a button), "
                   "e.g. 'Pray at the altar'. A scene offers at most 3 actions total.",
    "parameters": {"type": "object", "properties": {
        "label": {"type": "string"}}, "required": ["label"]}}})
def offer_scene_action(conn, gid, args, actor):
    label = (args.get("label") or "").strip()
    ok = repo.offer_scene_action(conn, gid, label, settings.SCENE_ACTION_CAP)
    return _result("state") if ok else _invalid(f"offer_scene_action: scene already has {settings.SCENE_ACTION_CAP} actions")


@tool({"type": "function", "function": {
    "name": "note_scene",
    "description": "Leave a draft note on the CURRENT scene (open threads, what was left "
                   "unresolved, who or what stayed behind), so when the player returns you "
                   "remember exactly how it was left. Overwrites the previous note.",
    "parameters": {"type": "object", "properties": {
        "note": {"type": "string"}}, "required": ["note"]}}})
def note_scene(conn, gid, args, actor):
    note = (args.get("note") or "").strip()
    repo.set_scene_draft(conn, gid, note)
    return _result("state")  # silent bookkeeping
