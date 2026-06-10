"""Combat: damage and healing. 'attack' (the character agents' verb) is an alias of
apply_damage; the engine routes player attack attempts here too after adjudication."""
from .. import repo
from .base import _DAMAGE_DEFAULT, _invalid, _result, alias, tool

# The character agents' own attack schema (same handler, actor-aware wording).
CHARACTER_ATTACK = {"type": "function", "function": {
    "name": "attack",
    "description": "Physically harm a target: another character by name, or 'player' for the hero.",
    "parameters": {"type": "object", "properties": {
        "target": {"type": "string"}, "amount": {"type": "integer"}}, "required": ["target"]}}}


@tool({"type": "function", "function": {
    "name": "apply_damage",
    "description": "Deal harm. Target defaults to the player; pass a character name to hurt them.",
    "parameters": {"type": "object", "properties": {
        "amount": {"type": "integer", "description": "Hit points lost (positive)."},
        "target": {"type": "string", "description": "'player' (default) or a character name."},
    }, "required": ["amount"]}}})
def apply_damage(conn, gid, args, actor):
    amount = abs(int(args.get("amount", _DAMAGE_DEFAULT) or _DAMAGE_DEFAULT))
    if amount == 0:
        return _invalid("damage: amount 0")
    tname = args.get("target") or ("player" if actor is None else "")
    kind_t, row = repo.resolve_target(conn, gid, tname)
    by = f"{actor['name']} " if actor else ""
    if kind_t == "player":
        new = repo.set_life(conn, gid, -amount)
        src = f" from {actor['name']}" if actor else ""
        if new == 0 and (repo.get_game(conn, gid)["status"] or "active") != "lost":
            # at zero the story turns: status flips so the narrator stages the aftermath
            # (turns stay allowed; a heal can bring the player back from the brink)
            repo.set_game_status(conn, gid, "lost")
            return _result("state", f"You take {amount} damage{src}. Life: 0. You fall.")
        return _result("state", f"You take {amount} damage{src}. Life: {new}.")
    if kind_t == "character":
        if not row["alive"]:
            return _invalid(f"{row['name']} is already down")
        new, died = repo.set_character_life(conn, row["id"], -amount)
        src = f"by {actor['name']}" if actor else "at the player's hand"
        if died:
            repo.add_moment(conn, row["id"], f"Was struck down {src}")
            return _result("state", f"{by}strikes down {row['name']}." if by else f"{row['name']} is struck down.")
        repo.add_moment(conn, row["id"], f"Was wounded {src}")
        hit = f"{by}hits {row['name']} for {amount}" if by else f"{row['name']} takes {amount} damage"
        return _result("state", f"{hit} ({new} left).", reactions=[row["id"]])
    return _invalid(f"attack: unknown target '{tname}'")


alias("attack", "apply_damage")


@tool({"type": "function", "function": {
    "name": "heal",
    "description": "Restore life. Target defaults to the player; pass a character name to heal them.",
    "parameters": {"type": "object", "properties": {
        "amount": {"type": "integer"}, "target": {"type": "string"},
    }, "required": ["amount"]}}})
def heal(conn, gid, args, actor):
    amount = abs(int(args.get("amount", 0) or 0))
    if amount == 0:
        return _invalid("heal: amount 0")
    tname = args.get("target") or "player"
    kind_t, row = repo.resolve_target(conn, gid, tname)
    if kind_t == "player":
        was_zero = repo.get_player(conn, gid)["life"] == 0
        new = repo.set_life(conn, gid, amount)
        text = f"You recover {amount}. Life: {new}."
        if was_zero and new > 0 and (repo.get_game(conn, gid)["status"] or "") == "lost":
            # the reverse transition: a staged rescue undoes the fall, deterministically
            repo.set_game_status(conn, gid, "active")
            text += " You are back from the brink."
        return _result("state", text)
    if kind_t == "character":
        new, _ = repo.set_character_life(conn, row["id"], amount)
        return _result("state", f"{row['name']} recovers {amount} ({new}).")
    return _invalid(f"heal: unknown target '{tname}'")
