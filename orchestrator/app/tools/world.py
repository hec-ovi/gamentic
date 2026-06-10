"""World-level state: flags, long-term memory, the story status, the story clock."""
from .. import constants, repo
from ..config import settings
from .base import _invalid, _result, tool


@tool({"type": "function", "function": {
    "name": "set_flag", "description": "Record an arbitrary world/story flag.",
    "parameters": {"type": "object", "properties": {
        "key": {"type": "string"}, "value": {"type": "string"}}, "required": ["key", "value"]}}})
def set_flag(conn, gid, args, actor):
    repo.set_flag(conn, gid, args.get("key", ""), str(args.get("value", "")))
    return _result("state")  # silent


@tool({"type": "function", "function": {
    "name": "remember", "description": "Persist an important fact to long-term memory.",
    "parameters": {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]}}})
def remember(conn, gid, args, actor):
    note = (args.get("note") or "").strip()
    if note:
        repo.append_memory(conn, gid, note)
    return _result("memory")


@tool({"type": "function", "function": {
    "name": "set_game_status",
    "description": "Set the overall story status (use when the player decisively wins or loses).",
    "parameters": {"type": "object", "properties": {
        "status": {"type": "string", "enum": list(constants.GAME_STATUSES)},
    }, "required": ["status"]}}})
def set_game_status(conn, gid, args, actor):
    st = (args.get("status") or "").strip().lower()
    if st not in constants.GAME_STATUSES:
        return _invalid(f"set_game_status: '{st}' not in {constants.GAME_STATUSES}")
    repo.set_game_status(conn, gid, st)
    return _result("state", None if st == "active" else f"The story is {st}.")


@tool({"type": "function", "function": {
    "name": "advance_time",
    "description": "Jump the STORY clock forward when the fiction skips ahead (a rest, a "
                   "journey, 'the next morning'). Small per-action time passes automatically; "
                   "use this only for real jumps.",
    "parameters": {"type": "object", "properties": {
        "amount": {"type": "integer", "description": "How much time passes (positive)."},
        "unit": {"type": "string", "enum": ["minutes", "hours", "days"]},
    }, "required": ["amount", "unit"]}}})
def advance_time(conn, gid, args, actor):
    amount = int(args.get("amount", 0) or 0)
    unit = (args.get("unit") or "").strip().lower()
    per = {"minutes": 1, "hours": 60, "days": 1440}.get(unit)
    if per is None:
        return _invalid(f"advance_time: unit '{unit}' not in minutes|hours|days")
    if amount <= 0:
        return _invalid("advance_time: amount must be positive")
    minutes = min(amount * per, settings.TIME_ADVANCE_CAP_DAYS * 1440)
    repo.advance_time(conn, gid, minutes)
    t = repo.game_time(conn, gid)
    return _result("state", f"Time passes. It is now {t['label']}.")
