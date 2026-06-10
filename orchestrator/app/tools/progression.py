"""Progression: quests, objectives, points, and the player's current goal."""
from .. import repo
from .base import _invalid, _result, tool


@tool({"type": "function", "function": {
    "name": "award_points",
    "description": "Add (or subtract, if negative) score.",
    "parameters": {"type": "object", "properties": {
        "amount": {"type": "integer"}, "reason": {"type": "string"}}, "required": ["amount"]}}})
def award_points(conn, gid, args, actor):
    amount = int(args.get("amount", 0))
    new = repo.add_points(conn, gid, amount)
    tail = f" ({args['reason']})" if args.get("reason") else ""
    return _result("state", f"{'+' if amount >= 0 else ''}{amount} points{tail}. Score: {new}.")


@tool({"type": "function", "function": {
    "name": "start_quest",
    "description": "Begin a new quest with one or more objectives.",
    "parameters": {"type": "object", "properties": {
        "title": {"type": "string"}, "description": {"type": "string"},
        "objectives": {"type": "array", "items": {"type": "string"}}}, "required": ["title"]}}})
def start_quest(conn, gid, args, actor):
    title = (args.get("title") or "").strip()
    if not title:
        return _invalid("start_quest: empty title")
    repo.start_quest(conn, gid, title, args.get("description", ""), args.get("objectives", []))
    return _result("state", f"New quest: {title}.")


@tool({"type": "function", "function": {
    "name": "update_objective",
    "description": "Mark a quest objective done or note progress.",
    "parameters": {"type": "object", "properties": {
        "objective_id": {"type": "string"}, "done": {"type": "boolean"},
        "progress": {"type": "string"}}, "required": ["objective_id"]}}})
def update_objective(conn, gid, args, actor):
    oid = args.get("objective_id", "")
    done = bool(args.get("done", True))
    if not repo.update_objective(conn, oid, done, args.get("progress")):
        return _invalid("update_objective: unknown objective_id")
    text = repo.objective_text(conn, oid)
    label = "complete" if done else "updated"
    return _result("state", f"Objective {label}: {text}." if text else "Objective updated.")


@tool({"type": "function", "function": {
    "name": "complete_quest", "description": "Mark a quest completed.",
    "parameters": {"type": "object", "properties": {"quest_id": {"type": "string"}}, "required": ["quest_id"]}}})
def complete_quest(conn, gid, args, actor):
    qid = args.get("quest_id", "")
    if not repo.set_quest_status(conn, qid, "done"):
        return _invalid("complete_quest: unknown quest_id")
    title = repo.quest_title(conn, qid)
    return _result("state", f"Quest complete: {title}." if title else "Quest complete.")


@tool({"type": "function", "function": {
    "name": "fail_quest", "description": "Mark a quest failed.",
    "parameters": {"type": "object", "properties": {"quest_id": {"type": "string"}}, "required": ["quest_id"]}}})
def fail_quest(conn, gid, args, actor):
    qid = args.get("quest_id", "")
    if not repo.set_quest_status(conn, qid, "failed"):
        return _invalid("fail_quest: unknown quest_id")
    title = repo.quest_title(conn, qid)
    return _result("state", f"Quest failed: {title}." if title else "Quest failed.")


@tool({"type": "function", "function": {
    "name": "set_goal",
    "description": "Update the player's current goal (their immediate purpose) as the story turns it.",
    "parameters": {"type": "object", "properties": {
        "goal": {"type": "string"}}, "required": ["goal"]}}})
def set_goal(conn, gid, args, actor):
    goal = (args.get("goal") or "").strip()
    repo.set_goal(conn, gid, goal)
    return _result("state", f"New goal: {goal}." if goal else None)
