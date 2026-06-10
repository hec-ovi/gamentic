"""Items: the player's pack, placing/revealing/taking scene and character items,
and handovers (give_item, also a character-agent verb)."""
from .. import repo
from ..config import settings
from .base import _SCENE_WORDS, _invalid, _result, alias, tool

# The character agents' own give schema (same handler, actor-aware wording).
CHARACTER_GIVE = {"type": "function", "function": {
    "name": "give_item",
    "description": "Hand an item you hold to a target ('player' or a character name).",
    "parameters": {"type": "object", "properties": {
        "item": {"type": "string"}, "target": {"type": "string"}}, "required": ["item", "target"]}}}


@tool({"type": "function", "function": {
    "name": "add_item",
    "description": "Give the player an item.",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string"}, "description": {"type": "string"}, "qty": {"type": "integer"},
    }, "required": ["name"]}}})
def add_item(conn, gid, args, actor):
    nm = repo.norm_name(args.get("name") or "")
    if not nm:
        return _invalid("add_item: empty name")
    repo.add_item(conn, gid, nm, args.get("description", ""), int(args.get("qty", 1) or 1))
    return _result("state", f"Obtained: {nm}.")


@tool({"type": "function", "function": {
    "name": "remove_item",
    "description": "Take an item from the player (must already be in inventory).",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string"}, "qty": {"type": "integer"}}, "required": ["name"]}}})
def remove_item(conn, gid, args, actor):
    nm = (args.get("name") or "").strip()
    removed = repo.remove_item(conn, gid, nm, int(args.get("qty", 1) or 1))
    if not removed:
        return _invalid(f"remove_item: '{nm}' not in inventory")
    return _result("state", f"Lost: {removed['name']}.")


@tool({"type": "function", "function": {
    "name": "place_item",
    "description": "Put an item somewhere: the scene (holds up to 6), a character (up to 3), or "
                   "the player. Set hidden=true if the player must discover it first. Set "
                   "fixed=true for scenery the player can see but NOT pocket (an altar, a lever, "
                   "a statue, a fountain); leave fixed=false for loose loot they can take.",
    "parameters": {"type": "object", "properties": {
        "target": {"type": "string", "description": "'scene', 'player', or a character name."},
        "name": {"type": "string"}, "description": {"type": "string"},
        "hidden": {"type": "boolean"},
        "fixed": {"type": "boolean", "description": "True = immovable scenery (can't be taken)."},
    }, "required": ["target", "name"]}}})
def place_item(conn, gid, args, actor):
    target = (args.get("target") or "").strip()
    nm = repo.norm_name(args.get("name") or "")
    desc = args.get("description", "")
    hidden = bool(args.get("hidden", False))
    fixed = bool(args.get("fixed", False))
    if not nm:
        return _invalid("place_item: no name")
    if target.lower() in _SCENE_WORDS:
        res = repo.add_scene_item(conn, gid, nm, desc, hidden, settings.SCENE_INVENTORY_CAP, fixed)
        if res == "full":
            return _invalid(f"place_item: scene is full ({settings.SCENE_INVENTORY_CAP})")
        if res == "exists":
            return _result("state")  # already here, silent
        return _result("state", None if hidden else f"There is {nm} here.")
    if target.lower() in ("player", "you", "me"):
        repo.add_item(conn, gid, nm, desc)
        return _result("state", f"Obtained: {nm}.")
    kt, row = repo.resolve_target(conn, gid, target)
    if kt != "character" or not row:
        return _invalid(f"place_item: unknown target '{target}'")
    res = repo.character_add_item(conn, row["id"], nm, desc, hidden, cap=settings.CHAR_INVENTORY_CAP)
    if res == "full":
        return _invalid(f"place_item: {row['name']} can carry no more")
    return _result("state", None if hidden else f"{row['name']} now has {nm}.")


@tool({"type": "function", "function": {
    "name": "reveal_item",
    "description": "Reveal a hidden item (the player discovers it) in the scene or on a character.",
    "parameters": {"type": "object", "properties": {
        "target": {"type": "string", "description": "'scene' or a character name."},
        "name": {"type": "string"},
    }, "required": ["target", "name"]}}})
def reveal_item(conn, gid, args, actor):
    target = (args.get("target") or "").strip()
    nm = repo.norm_name(args.get("name") or "")
    if target.lower() in _SCENE_WORDS:
        ok = repo.reveal_scene_item(conn, gid, nm)
        return _result("state", f"You spot {nm}.") if ok else _invalid(f"reveal_item: no hidden '{nm}' here")
    kt, row = repo.resolve_target(conn, gid, target)
    if kt != "character" or not row:
        return _invalid(f"reveal_item: unknown target '{target}'")
    ok = repo.character_reveal_item(conn, row["id"], nm)
    return _result("state", f"You notice {row['name']} carries {nm}.") if ok else _invalid("reveal_item: nothing hidden")


@tool({"type": "function", "function": {
    "name": "take_item",
    "description": "The player picks up a revealed item from the current scene into their inventory.",
    "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}})
def take_item(conn, gid, args, actor):
    nm = repo.norm_name(args.get("name") or "")
    res = repo.take_scene_item(conn, gid, nm)
    if res == "ok":
        return _result("state", f"You take {nm}.")
    if res == "fixed":
        # scenery (altar, lever, statue): can't be pocketed, but say so in-world so flow continues
        return _result("state", f"The {nm} is part of the place; it won't come with you.")
    return _invalid(f"take_item: no '{nm}' to take")


@tool({"type": "function", "function": {
    "name": "give_item",
    "description": "Transfer an item from the player's inventory to a character (use to "
                   "accept the player's handover, or when they drop or trade something).",
    "parameters": {"type": "object", "properties": {
        "item": {"type": "string"}, "target": {"type": "string"}},
        "required": ["item", "target"]}}})
def give_item(conn, gid, args, actor):
    item = (args.get("item") or args.get("name") or "").strip()
    if not item:
        return _invalid("give: no item")
    kind_t, row = repo.resolve_target(conn, gid, args.get("target") or "")
    if kind_t is None:
        return _invalid(f"give: unknown target '{args.get('target')}'")
    # item may be an ID (entity chip) or a name; the removed dict carries the real name,
    # so the recipient receives a properly named item either way.
    if actor is None:
        moved = repo.remove_item(conn, gid, item)
        if not moved:
            return _invalid(f"give: you don't have '{item}'")
        giver = "You give"
    else:
        moved = repo.character_remove_item(conn, actor["id"], item)
        if not moved:
            return _invalid(f"give: {actor['name']} has no '{item}'")
        giver = f"{actor['name']} gives"
    nm, desc, img = moved["name"], moved.get("description", ""), moved.get("image_url")
    if kind_t == "player":
        repo.add_item(conn, gid, nm, desc, image_url=img)    # the item's image travels with it
        if actor is not None:   # a gift TO the player is a pivotal moment for the giver
            repo.add_moment(conn, actor["id"], f"Gave the player {nm}")
        return _result("state", f"{giver} {nm} to you.")
    repo.character_add_item(conn, row["id"], nm, desc, image_url=img)
    if actor is None:           # a gift FROM the player is a pivotal moment for the receiver
        repo.add_moment(conn, row["id"], f"Received {nm} from the player")
    return _result("state", f"{giver} {nm} to {row['name']}.", reactions=[row["id"]])


alias("give", "give_item")
