"""Items: the player's pack, placing/revealing/taking scene and character items,
and handovers (give_item, also a character-agent verb)."""
from .. import repo
from ..config import settings
from .base import _SCENE_WORDS, _invalid, _result, alias, tool

# The character agents' own give schema (same handler, actor-aware wording).
CHARACTER_GIVE = {"type": "function", "function": {
    "name": "give_item",
    "description": "Hand an item to a target ('player' or a character name). If it is not "
                   "in your carrying list it is produced from your person (a pocket, a "
                   "pack, a sheath) - give only what you would plausibly HAVE on you.",
    "parameters": {"type": "object", "properties": {
        "item": {"type": "string"},
        "description": {"type": "string", "description": "One short line: what it is."},
        "target": {"type": "string"}}, "required": ["item", "target"]}}}


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
    raw_qty = args.get("qty", 1)
    qty = 1 if raw_qty in (None, "") else int(raw_qty)
    if qty <= 0:
        # live: the narrator 'paid' with add_item(copper coins, qty=-3) and the player
        # GAINED coins plus an 'Obtained' receipt; bounce it so the retry/feedback
        # loop steers the model to the right tool instead
        return _invalid("add_item: qty must be positive; use remove_item to take things from the player")
    # The model says add_item where it means take_item (live: 'takes the rusted
    # lantern' minted a pack copy while the scene kept its own - three lanterns where
    # the fiction had one). A VISIBLE scene item by this name means MOVE it, exactly
    # as take_item would; fixed scenery refuses the same in-world way.
    res = repo.take_scene_item(conn, gid, nm)
    if res == "ok":
        return _result("state", f"You take {nm}.")
    if res == "fixed":
        return _result("state", f"The {nm} is part of the place; it won't come with you.")
    repo.add_item(conn, gid, nm, args.get("description", ""), qty)
    return _result("state", f"Obtained: {nm}.")


@tool({"type": "function", "function": {
    "name": "remove_item",
    "description": "Take an item from the player (must already be in inventory).",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string"}, "qty": {"type": "integer"}}, "required": ["name"]}}})
def remove_item(conn, gid, args, actor):
    nm = (args.get("name") or "").strip()
    qty = int(args.get("qty", 1) or 1)
    if qty <= 0:
        # symmetric to add_item's guard: a negative qty here INCREASED the count
        # while printing 'Lost'
        return _invalid("remove_item: qty must be positive; use add_item to give the player things")
    removed = repo.remove_item(conn, gid, nm, qty)
    if not removed:
        # near-miss net (live: remove_item('room key') against a pack holding 'heavy
        # iron key' showed the player BOTH "You don't have room key." and the retry's
        # "Lost: heavy iron key"): exactly one pack item sharing the final token wins;
        # zero or several stay invalid.
        near = repo.near_pack_item(conn, gid, nm)
        if near is not None:
            removed = repo.remove_item(conn, gid, near["id"], qty)
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
    # Placing something the PLAYER already holds MOVES it out of the pack (mirror of
    # add_item-as-take; live showcase 2026-06-11: the narrator delivered a gift with
    # place_item, so the girl received the glass float while the player's pack kept a
    # twin). The pull happens only on a path that actually lands the item, and a full
    # destination puts it straight back - a failed placement must never vanish the item.
    def _pack_pull():
        nonlocal nm, desc
        if repo.player_has_item(conn, gid, nm):
            pulled = repo.remove_item(conn, gid, nm)
            if pulled:
                nm, desc = pulled["name"], pulled.get("description") or desc
                return pulled
        return None
    if target.lower() in _SCENE_WORDS:
        pulled = _pack_pull()
        res = repo.add_scene_item(conn, gid, nm, desc, hidden, settings.SCENE_INVENTORY_CAP, fixed)
        if res == "full":
            if pulled:
                repo.add_item(conn, gid, pulled["name"], pulled.get("description", ""))
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
    pulled = _pack_pull()
    res = repo.character_add_item(conn, row["id"], nm, desc, hidden, cap=settings.CHAR_INVENTORY_CAP)
    if res == "full":
        if pulled:
            repo.add_item(conn, gid, pulled["name"], pulled.get("description", ""))
        return _invalid(f"place_item: {row['name']} can carry no more")
    return _result("state", None if hidden else f"{row['name']} now has {nm}.")


@tool({"type": "function", "function": {
    "name": "reveal_item",
    "description": "The player DISCOVERS an item: in the scene, on a character, or (target "
                   "'player') straight into their pack. Reveals it if it was planted hidden; "
                   "creates it on the spot otherwise.",
    "parameters": {"type": "object", "properties": {
        "target": {"type": "string", "description": "'scene', a character name, or 'player'."},
        "name": {"type": "string"},
    }, "required": ["target", "name"]}}})
def reveal_item(conn, gid, args, actor):
    target = (args.get("target") or "").strip()
    nm = repo.norm_name(args.get("name") or "")
    if not nm:
        return _invalid("reveal_item: no name")
    # The model reaches for reveal_item to AUTHOR discoveries, not just to flip planted
    # ones (live, both e2e games: reveal_item('water-damaged ledger', target='player')
    # and reveal_item('broken clay jug', target='scene') were the single most common
    # invalid class). The narrator can already invent items freely via place_item, so
    # degrading a miss into place-and-reveal grants no new power; it removes a dead end.
    if target.lower() in _SCENE_WORDS:
        if repo.reveal_scene_item(conn, gid, nm):
            return _result("state", f"You spot {nm}.")
        res = repo.add_scene_item(conn, gid, nm, args.get("description", ""), False,
                                  settings.SCENE_INVENTORY_CAP, False)
        if res == "full":
            return _invalid(f"reveal_item: scene is full ({settings.SCENE_INVENTORY_CAP})")
        if res == "exists":
            # already in plain sight: nothing was discovered (live replay: place_item +
            # reveal_item of the same name in one reply printed two receipts)
            return _result("state")
        return _result("state", f"You spot {nm}.")
    if target.lower() in ("player", "you", "me"):
        repo.add_item(conn, gid, nm, args.get("description", ""))
        return _result("state", f"Obtained: {nm}.")
    kt, row = repo.resolve_target(conn, gid, target)
    if kt != "character" or not row:
        return _invalid(f"reveal_item: unknown target '{target}'")
    if repo.character_reveal_item(conn, row["id"], nm):
        return _result("state", f"You notice {row['name']} carries {nm}.")
    res = repo.character_add_item(conn, row["id"], nm, args.get("description", ""), False,
                                  cap=settings.CHAR_INVENTORY_CAP)
    if res == "full":
        return _invalid(f"reveal_item: {row['name']} can carry no more")
    return _result("state", f"You notice {row['name']} carries {nm}.")


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
    # steer the retry: the most common miss is taking a thing the fiction produced but
    # state never held (live: a character handed over a lantern in prose only; the
    # narrator's take_item had nothing to take and the item stayed cosmetic for turns)
    return _invalid(f"take_item: no '{nm}' in this scene; if the fiction already put it "
                    f"in the player's hands, add_item it instead")


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
            # owner spec: a character may PRODUCE an item on the fly (a key from a
            # pocket, a coin from a sleeve) - the fiction says they have it, so they do.
            # Only characters get this; the player's possessions stay strict.
            moved = {"name": repo.norm_name(item),
                     "description": (args.get("description") or "").strip(),
                     "image_url": None}
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
