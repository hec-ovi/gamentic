"""Game tools: the model's ONLY way to change state.

Two toolsets share one validated dispatcher:
  - NARRATOR_TOOLS: world/state adjudication + directing (cue) + dynamic cast (spawn/kill).
  - CHARACTER_TOOLS: a character can act on others - attack / give_item - targeting another
    character OR the player. The engine resolves these and queues the target to REACT, so a
    turn can cascade (bounded for pacing).

apply_tool(conn, gid, name, args, actor) returns {kind, text, cue, reactions}:
  kind: state | cue | memory | invalid | spawn | kill
  text: a short system-beat string to show the player (or None = silent)
  cue:  {id,name,reason} when a character should be given the scene (cue_character / spawn)
  reactions: character ids the engine should queue to react to this action
`actor` is None when the narrator/player drives the tool, or the character row when a
character acts (so "you take 5 from Jacker" vs "Jacker takes 5").

See docs/SPECS.md section 5.
"""
from . import repo, constants
from .config import settings

_DAMAGE_DEFAULT = 3
_SCENE_WORDS = ("scene", "room", "here", "the scene", "the room")

NARRATOR_TOOLS = [
    {"type": "function", "function": {
        "name": "apply_damage",
        "description": "Deal harm. Target defaults to the player; pass a character name to hurt them.",
        "parameters": {"type": "object", "properties": {
            "amount": {"type": "integer", "description": "Hit points lost (positive)."},
            "target": {"type": "string", "description": "'player' (default) or a character name."},
        }, "required": ["amount"]}}},
    {"type": "function", "function": {
        "name": "heal",
        "description": "Restore life. Target defaults to the player; pass a character name to heal them.",
        "parameters": {"type": "object", "properties": {
            "amount": {"type": "integer"}, "target": {"type": "string"},
        }, "required": ["amount"]}}},
    {"type": "function", "function": {
        "name": "add_item",
        "description": "Give the player an item.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}, "description": {"type": "string"}, "qty": {"type": "integer"},
        }, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "remove_item",
        "description": "Take an item from the player (must already be in inventory).",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}, "qty": {"type": "integer"}}, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "award_points",
        "description": "Add (or subtract, if negative) score.",
        "parameters": {"type": "object", "properties": {
            "amount": {"type": "integer"}, "reason": {"type": "string"}}, "required": ["amount"]}}},
    {"type": "function", "function": {
        "name": "start_quest",
        "description": "Begin a new quest with one or more objectives.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"}, "description": {"type": "string"},
            "objectives": {"type": "array", "items": {"type": "string"}}}, "required": ["title"]}}},
    {"type": "function", "function": {
        "name": "update_objective",
        "description": "Mark a quest objective done or note progress.",
        "parameters": {"type": "object", "properties": {
            "objective_id": {"type": "string"}, "done": {"type": "boolean"},
            "progress": {"type": "string"}}, "required": ["objective_id"]}}},
    {"type": "function", "function": {
        "name": "complete_quest", "description": "Mark a quest completed.",
        "parameters": {"type": "object", "properties": {"quest_id": {"type": "string"}}, "required": ["quest_id"]}}},
    {"type": "function", "function": {
        "name": "fail_quest", "description": "Mark a quest failed.",
        "parameters": {"type": "object", "properties": {"quest_id": {"type": "string"}}, "required": ["quest_id"]}}},
    {"type": "function", "function": {
        "name": "move_location", "description": "Move the scene/player to a new location.",
        "parameters": {"type": "object", "properties": {"location": {"type": "string"}}, "required": ["location"]}}},
    {"type": "function", "function": {
        "name": "set_flag", "description": "Record an arbitrary world/story flag.",
        "parameters": {"type": "object", "properties": {
            "key": {"type": "string"}, "value": {"type": "string"}}, "required": ["key", "value"]}}},
    {"type": "function", "function": {
        "name": "remember", "description": "Persist an important fact to long-term memory.",
        "parameters": {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]}}},
    {"type": "function", "function": {
        "name": "cue_character",
        "description": "Hand the scene to a present character so they speak/act next. Call several "
                       "times, in order, for multiple reactions. Cue no one if it is only description.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}, "reason": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "spawn_character",
        "description": "Introduce a NEW character into the scene on the fly (someone arrives/appears).",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"},
            "persona": {"type": "string", "description": "Who they are, how they behave."},
            "appearance": {"type": "string",
                           "description": "What they look like (for their portrait). Start with explicit "
                                          "sex and rough age ('a young woman...', 'an old man...'); looks "
                                          "only, never words or signs to draw."},
            "knowledge": {"type": "string", "description": "Private things only they know."},
            "life": {"type": "integer"},
        }, "required": ["name", "persona"]}}},
    {"type": "function", "function": {
        "name": "kill_character",
        "description": "Remove a character from the story (they die or permanently leave).",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "set_disposition",
        "description": "Set how a character feels toward the player as it changes.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"},
            "disposition": {"type": "string", "enum": list(constants.DISPOSITIONS)},
        }, "required": ["name", "disposition"]}}},
    {"type": "function", "function": {
        "name": "set_following",
        "description": "Make a character travel with the player (join you), or stop following.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}, "following": {"type": "boolean"},
        }, "required": ["name", "following"]}}},
    {"type": "function", "function": {
        "name": "set_scene_status",
        "description": "Set the mood of the current scene as it shifts.",
        "parameters": {"type": "object", "properties": {
            "status": {"type": "string", "enum": list(constants.SCENE_STATUSES)},
        }, "required": ["status"]}}},
    {"type": "function", "function": {
        "name": "set_game_status",
        "description": "Set the overall story status (use when the player decisively wins or loses).",
        "parameters": {"type": "object", "properties": {
            "status": {"type": "string", "enum": list(constants.GAME_STATUSES)},
        }, "required": ["status"]}}},
    {"type": "function", "function": {
        "name": "describe_scene",
        "description": "Write or update the current scene's short description (do this when the "
                       "player enters a new place so the scene card reads right).",
        "parameters": {"type": "object", "properties": {
            "description": {"type": "string"}}, "required": ["description"]}}},
    {"type": "function", "function": {
        "name": "describe_character",
        "description": "Write or update a character's short public bio (one line shown in the UI).",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}, "description": {"type": "string"}},
            "required": ["name", "description"]}}},
    {"type": "function", "function": {
        "name": "set_goal",
        "description": "Update the player's current goal (their immediate purpose) as the story turns it.",
        "parameters": {"type": "object", "properties": {
            "goal": {"type": "string"}}, "required": ["goal"]}}},
    {"type": "function", "function": {
        "name": "add_exit",
        "description": "Reveal a way out of the current scene (a button the player can take). "
                       "A scene has at most 3 exits; a scene with none is a dead end.",
        "parameters": {"type": "object", "properties": {
            "label": {"type": "string", "description": "Button text, e.g. 'the rain-slick street'."},
            "target": {"type": "string", "description": "Destination scene name."},
        }, "required": ["label", "target"]}}},
    {"type": "function", "function": {
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
        }, "required": ["target", "name"]}}},
    {"type": "function", "function": {
        "name": "reveal_item",
        "description": "Reveal a hidden item (the player discovers it) in the scene or on a character.",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string", "description": "'scene' or a character name."},
            "name": {"type": "string"},
        }, "required": ["target", "name"]}}},
    {"type": "function", "function": {
        "name": "take_item",
        "description": "The player picks up a revealed item from the current scene into their inventory.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "offer_action",
        "description": "Offer the player a one-off contextual action toward a character (a button), "
                       "e.g. 'Bribe'. A character offers at most 3 actions total.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}, "label": {"type": "string"}}, "required": ["name", "label"]}}},
    {"type": "function", "function": {
        "name": "offer_scene_action",
        "description": "Offer the player a one-off contextual action in the scene (a button), "
                       "e.g. 'Pray at the altar'. A scene offers at most 3 actions total.",
        "parameters": {"type": "object", "properties": {
            "label": {"type": "string"}}, "required": ["label"]}}},
    {"type": "function", "function": {
        "name": "give_item",
        "description": "Transfer an item from the player's inventory to a character (use to "
                       "accept the player's handover, or when they drop or trade something).",
        "parameters": {"type": "object", "properties": {
            "item": {"type": "string"}, "target": {"type": "string"}},
            "required": ["item", "target"]}}},
    {"type": "function", "function": {
        "name": "note_scene",
        "description": "Leave a draft note on the CURRENT scene (open threads, what was left "
                       "unresolved, who or what stayed behind), so when the player returns you "
                       "remember exactly how it was left. Overwrites the previous note.",
        "parameters": {"type": "object", "properties": {
            "note": {"type": "string"}}, "required": ["note"]}}},
    {"type": "function", "function": {
        "name": "advance_time",
        "description": "Jump the STORY clock forward when the fiction skips ahead (a rest, a "
                       "journey, 'the next morning'). Small per-action time passes automatically; "
                       "use this only for real jumps.",
        "parameters": {"type": "object", "properties": {
            "amount": {"type": "integer", "description": "How much time passes (positive)."},
            "unit": {"type": "string", "enum": ["minutes", "hours", "days"]},
        }, "required": ["amount", "unit"]}}},
]

# Only offered while PLAYER ATTEMPTS are pending adjudication (see narrator_tools); a veto
# tool with nothing to veto is schema noise and an invitation to misuse for a small model.
REJECT_ATTEMPT_TOOL = {"type": "function", "function": {
    "name": "reject_attempt",
    "description": "Veto one numbered PLAYER ATTEMPT with an in-world reason (shown to the "
                   "player), e.g. 'Mara steps back, refusing the coin.' Attempts you neither "
                   "apply nor veto simply happen as attempted.",
    "parameters": {"type": "object", "properties": {
        "attempt": {"type": "integer", "description": "The attempt number from the list."},
        "reason": {"type": "string", "description": "In-world reason it does not happen."},
    }, "required": ["attempt", "reason"]}}}


def narrator_tools(adjudicating: bool) -> list:
    """The narrator's toolset for one call; reject_attempt only when attempts are pending."""
    return NARRATOR_TOOLS + ([REJECT_ATTEMPT_TOOL] if adjudicating else [])

# Tools a CHARACTER agent may call to act on others. Their speech is the message content;
# these are for doing things to another character or to the player.
CHARACTER_TOOLS = [
    {"type": "function", "function": {
        "name": "attack",
        "description": "Physically harm a target: another character by name, or 'player' for the hero.",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string"}, "amount": {"type": "integer"}}, "required": ["target"]}}},
    {"type": "function", "function": {
        "name": "give_item",
        "description": "Hand an item you hold to a target ('player' or a character name).",
        "parameters": {"type": "object", "properties": {
            "item": {"type": "string"}, "target": {"type": "string"}}, "required": ["item", "target"]}}},
]


def apply_tool(conn, gid: str, name: str, args: dict, actor=None) -> dict:
    """actor: None (narrator/player/world) or a character row acting on others."""
    try:
        if name in ("apply_damage", "attack"):
            return _damage(conn, gid, args, actor)
        if name == "heal":
            return _heal(conn, gid, args)
        if name in ("give_item", "give"):
            return _give(conn, gid, args, actor)
        if name == "add_item":
            nm = repo.norm_location(args.get("name") or "")
            if not nm:
                return _invalid("add_item: empty name")
            repo.add_item(conn, gid, nm, args.get("description", ""), int(args.get("qty", 1) or 1))
            return _result("state", f"Obtained: {nm}.")
        if name == "remove_item":
            nm = (args.get("name") or "").strip()
            removed = repo.remove_item(conn, gid, nm, int(args.get("qty", 1) or 1))
            if not removed:
                return _invalid(f"remove_item: '{nm}' not in inventory")
            return _result("state", f"Lost: {removed['name']}.")
        if name == "award_points":
            amount = int(args.get("amount", 0))
            new = repo.add_points(conn, gid, amount)
            tail = f" ({args['reason']})" if args.get("reason") else ""
            return _result("state", f"{'+' if amount >= 0 else ''}{amount} points{tail}. Score: {new}.")
        if name == "start_quest":
            title = (args.get("title") or "").strip()
            if not title:
                return _invalid("start_quest: empty title")
            repo.start_quest(conn, gid, title, args.get("description", ""), args.get("objectives", []))
            return _result("state", f"New quest: {title}.")
        if name == "update_objective":
            oid = args.get("objective_id", "")
            done = bool(args.get("done", True))
            if not repo.update_objective(conn, oid, done, args.get("progress")):
                return _invalid("update_objective: unknown objective_id")
            text = repo.objective_text(conn, oid)
            label = "complete" if done else "updated"
            return _result("state", f"Objective {label}: {text}." if text else "Objective updated.")
        if name == "complete_quest":
            qid = args.get("quest_id", "")
            if not repo.set_quest_status(conn, qid, "done"):
                return _invalid("complete_quest: unknown quest_id")
            title = repo.quest_title(conn, qid)
            return _result("state", f"Quest complete: {title}." if title else "Quest complete.")
        if name == "fail_quest":
            qid = args.get("quest_id", "")
            if not repo.set_quest_status(conn, qid, "failed"):
                return _invalid("fail_quest: unknown quest_id")
            title = repo.quest_title(conn, qid)
            return _result("state", f"Quest failed: {title}." if title else "Quest failed.")
        if name == "move_location":
            loc = repo.norm_location(args.get("location") or "")
            if not loc:
                return _invalid("move_location: empty location")
            repo.set_location(conn, gid, loc)
            return _result("state", f"You move to {loc}.")
        if name == "set_flag":
            repo.set_flag(conn, gid, args.get("key", ""), str(args.get("value", "")))
            return _result("state")  # silent
        if name == "remember":
            note = (args.get("note") or "").strip()
            if note:
                repo.append_memory(conn, gid, note)
            return _result("memory")
        if name == "cue_character":
            who = (args.get("name") or "").strip()
            ch = repo.find_character_by_name(conn, gid, who)
            if not ch:
                return _invalid(f"cue_character: no character named '{who}'")
            return _result("cue", cue={"id": ch["id"], "name": ch["name"], "reason": args.get("reason", "")})
        if name == "spawn_character":
            return _spawn(conn, gid, args)
        if name == "kill_character":
            return _kill(conn, gid, args)
        if name == "set_disposition":
            who = (args.get("name") or "").strip()
            disp = (args.get("disposition") or "").strip().lower()
            if disp not in constants.DISPOSITIONS:
                return _invalid(f"set_disposition: '{disp}' not in {constants.DISPOSITIONS}")
            ch = repo.find_character_by_name(conn, gid, who)
            if not ch:
                return _invalid(f"set_disposition: no character '{who}'")
            repo.set_disposition(conn, ch["id"], disp)
            return _result("state", f"{ch['name']} turns {disp}.")
        if name == "set_following":
            who = (args.get("name") or "").strip()
            ch = repo.find_character_by_name(conn, gid, who)
            if not ch:
                return _invalid(f"set_following: no character '{who}'")
            foll = bool(args.get("following", True))
            repo.set_following(conn, ch["id"], foll)
            if foll:  # a new follower joins the player's current scene
                conn.execute("UPDATE characters SET location=? WHERE id=?",
                             (repo.get_player(conn, gid)["location"], ch["id"]))
            return _result("state", f"{ch['name']} {'joins you' if foll else 'stays behind'}.")
        if name == "set_scene_status":
            st = (args.get("status") or "").strip().lower()
            if st not in constants.SCENE_STATUSES:
                return _invalid(f"set_scene_status: '{st}' not in {constants.SCENE_STATUSES}")
            repo.set_scene_status(conn, gid, st)
            return _result("state")  # silent; reflected in HUD
        if name == "set_game_status":
            st = (args.get("status") or "").strip().lower()
            if st not in constants.GAME_STATUSES:
                return _invalid(f"set_game_status: '{st}' not in {constants.GAME_STATUSES}")
            repo.set_game_status(conn, gid, st)
            return _result("state", None if st == "active" else f"The story is {st}.")
        if name == "describe_scene":
            desc = (args.get("description") or "").strip()
            if desc:
                repo.set_scene_description(conn, gid, desc)
            return _result("state")  # silent; shown on the scene card
        if name == "describe_character":
            who = (args.get("name") or "").strip()
            desc = (args.get("description") or "").strip()
            ch = repo.find_character_by_name(conn, gid, who)
            if not ch:
                return _invalid(f"describe_character: no character '{who}'")
            repo.set_character_description(conn, ch["id"], desc)
            return _result("state")  # silent; shown on the character card
        if name == "set_goal":
            goal = (args.get("goal") or "").strip()
            repo.set_goal(conn, gid, goal)
            return _result("state", f"New goal: {goal}." if goal else None)
        if name == "add_exit":
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
        if name == "place_item":
            target = (args.get("target") or "").strip()
            nm = repo.norm_location(args.get("name") or "")
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
        if name == "reveal_item":
            target = (args.get("target") or "").strip()
            nm = repo.norm_location(args.get("name") or "")
            if target.lower() in _SCENE_WORDS:
                ok = repo.reveal_scene_item(conn, gid, nm)
                return _result("state", f"You spot {nm}.") if ok else _invalid(f"reveal_item: no hidden '{nm}' here")
            kt, row = repo.resolve_target(conn, gid, target)
            if kt != "character" or not row:
                return _invalid(f"reveal_item: unknown target '{target}'")
            ok = repo.character_reveal_item(conn, row["id"], nm)
            return _result("state", f"You notice {row['name']} carries {nm}.") if ok else _invalid("reveal_item: nothing hidden")
        if name == "take_item":
            nm = repo.norm_location(args.get("name") or "")
            res = repo.take_scene_item(conn, gid, nm)
            if res == "ok":
                return _result("state", f"You take {nm}.")
            if res == "fixed":
                # scenery (altar, lever, statue): can't be pocketed, but say so in-world so flow continues
                return _result("state", f"The {nm} is part of the place; it won't come with you.")
            return _invalid(f"take_item: no '{nm}' to take")
        if name == "offer_action":
            who = (args.get("name") or "").strip()
            label = (args.get("label") or "").strip()
            ch = repo.find_character_by_name(conn, gid, who)
            if not ch:
                return _invalid(f"offer_action: no character '{who}'")
            ok = repo.offer_action(conn, ch["id"], label, settings.CHAR_ACTION_CAP)
            return _result("state") if ok else _invalid(f"offer_action: {ch['name']} already has {settings.CHAR_ACTION_CAP} actions")
        if name == "offer_scene_action":
            label = (args.get("label") or "").strip()
            ok = repo.offer_scene_action(conn, gid, label, settings.SCENE_ACTION_CAP)
            return _result("state") if ok else _invalid(f"offer_scene_action: scene already has {settings.SCENE_ACTION_CAP} actions")
        if name == "note_scene":
            note = (args.get("note") or "").strip()
            repo.set_scene_draft(conn, gid, note)
            return _result("state")  # silent bookkeeping
        if name == "advance_time":
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
        if name == "reject_attempt":
            reason = (args.get("reason") or "").strip() or "It does not happen."
            return {"kind": "reject", "text": reason,
                    "cue": {"attempt": args.get("attempt")}, "reactions": []}
        return _invalid(f"unknown tool '{name}'")
    except (ValueError, TypeError) as e:
        return _invalid(f"{name}: bad args ({e})")


def _damage(conn, gid, args, actor):
    amount = abs(int(args.get("amount", _DAMAGE_DEFAULT) or _DAMAGE_DEFAULT))
    if amount == 0:
        return _invalid("damage: amount 0")
    tname = args.get("target") or ("player" if actor is None else "")
    kind_t, row = repo.resolve_target(conn, gid, tname)
    by = f"{actor['name']} " if actor else ""
    if kind_t == "player":
        new = repo.set_life(conn, gid, -amount)
        src = f" from {actor['name']}" if actor else ""
        return _result("state", f"You take {amount} damage{src}. Life: {new}.")
    if kind_t == "character":
        if not row["alive"]:
            return _invalid(f"{row['name']} is already down")
        new, died = repo.set_character_life(conn, row["id"], -amount)
        if died:
            return _result("state", f"{by}strikes down {row['name']}." if by else f"{row['name']} is struck down.")
        hit = f"{by}hits {row['name']} for {amount}" if by else f"{row['name']} takes {amount} damage"
        return _result("state", f"{hit} ({new} left).", reactions=[row["id"]])
    return _invalid(f"attack: unknown target '{tname}'")


def _heal(conn, gid, args):
    amount = abs(int(args.get("amount", 0) or 0))
    if amount == 0:
        return _invalid("heal: amount 0")
    tname = args.get("target") or "player"
    kind_t, row = repo.resolve_target(conn, gid, tname)
    if kind_t == "player":
        return _result("state", f"You recover {amount}. Life: {repo.set_life(conn, gid, amount)}.")
    if kind_t == "character":
        new, _ = repo.set_character_life(conn, row["id"], amount)
        return _result("state", f"{row['name']} recovers {amount} ({new}).")
    return _invalid(f"heal: unknown target '{tname}'")


def _give(conn, gid, args, actor):
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
    nm, desc = moved["name"], moved.get("description", "")
    if kind_t == "player":
        repo.add_item(conn, gid, nm, desc)
        return _result("state", f"{giver} {nm} to you.")
    repo.character_add_item(conn, row["id"], nm, desc)
    return _result("state", f"{giver} {nm} to {row['name']}.", reactions=[row["id"]])


def _spawn(conn, gid, args):
    nm = (args.get("name") or "").strip()
    if not nm:
        return _invalid("spawn_character: no name")
    if repo.find_character_by_name(conn, gid, nm):
        return _invalid(f"spawn_character: '{nm}' already here")
    cid = repo.spawn_character(conn, gid, nm, args.get("persona", ""), args.get("appearance", ""),
                               args.get("knowledge", ""), life=int(args.get("life", 10) or 10))
    return _result("spawn", text=f"{nm} arrives.",
                   cue={"id": cid, "name": nm, "reason": "has just arrived"}, reactions=[cid])


def _kill(conn, gid, args):
    tname = (args.get("name") or args.get("target") or "").strip()
    kind_t, row = repo.resolve_target(conn, gid, tname)
    if kind_t != "character" or not row:
        return _invalid(f"kill_character: unknown character '{tname}'")
    repo.kill_character(conn, row["id"])
    return _result("kill", f"{row['name']} is gone.")


def _result(kind, text=None, cue=None, reactions=None):
    return {"kind": kind, "text": text, "cue": cue, "reactions": reactions or []}


def _invalid(reason):
    return {"kind": "invalid", "text": reason, "cue": None, "reactions": []}
