"""Characters: directing (cue), the dynamic cast (spawn/kill), bonds, bios, traits,
and offered actions."""
from .. import constants, repo
from ..config import settings
from .base import _invalid, _result, tool


@tool({"type": "function", "function": {
    "name": "cue_character",
    "description": "Hand the scene to a present character so they speak/act next. Call several "
                   "times, in order, for multiple reactions. Cue no one if it is only description.",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string"}, "reason": {"type": "string"}}, "required": ["name"]}}})
def cue_character(conn, gid, args, actor):
    who = (args.get("name") or "").strip()
    ch = repo.find_character_by_name(conn, gid, who)
    if not ch:
        return _invalid(f"cue_character: no character named '{who}'")
    return _result("cue", cue={"id": ch["id"], "name": ch["name"], "reason": args.get("reason", "")})


@tool({"type": "function", "function": {
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
    }, "required": ["name", "persona"]}}})
def spawn_character(conn, gid, args, actor):
    nm = (args.get("name") or "").strip()
    if not nm:
        return _invalid("spawn_character: no name")
    if repo.find_character_by_name(conn, gid, nm):
        return _invalid(f"spawn_character: '{nm}' already here")
    cid = repo.spawn_character(conn, gid, nm, args.get("persona", ""), args.get("appearance", ""),
                               args.get("knowledge", ""), life=int(args.get("life", 10) or 10))
    return _result("spawn", text=f"{nm} arrives.",
                   cue={"id": cid, "name": nm, "reason": "has just arrived"}, reactions=[cid])


@tool({"type": "function", "function": {
    "name": "kill_character",
    "description": "Remove a character from the story (they die or permanently leave).",
    "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}})
def kill_character(conn, gid, args, actor):
    tname = (args.get("name") or args.get("target") or "").strip()
    kind_t, row = repo.resolve_target(conn, gid, tname)
    if kind_t != "character" or not row:
        return _invalid(f"kill_character: unknown character '{tname}'")
    repo.kill_character(conn, row["id"])
    return _result("kill", f"{row['name']} is gone.")


@tool({"type": "function", "function": {
    "name": "set_disposition",
    "description": "Set how a character feels toward the player as it changes.",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string"},
        "disposition": {"type": "string", "enum": list(constants.DISPOSITIONS)},
    }, "required": ["name", "disposition"]}}})
def set_disposition(conn, gid, args, actor):
    who = (args.get("name") or "").strip()
    disp = (args.get("disposition") or "").strip().lower()
    if disp not in constants.DISPOSITIONS:
        return _invalid(f"set_disposition: '{disp}' not in {constants.DISPOSITIONS}")
    ch = repo.find_character_by_name(conn, gid, who)
    if not ch:
        return _invalid(f"set_disposition: no character '{who}'")
    repo.set_disposition(conn, ch["id"], disp)
    return _result("state", f"{ch['name']} turns {disp}.")


@tool({"type": "function", "function": {
    "name": "set_following",
    "description": "Make a character travel with the player (join you), or stop following.",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string"}, "following": {"type": "boolean"},
    }, "required": ["name", "following"]}}})
def set_following(conn, gid, args, actor):
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


@tool({"type": "function", "function": {
    "name": "describe_character",
    "description": "Write or update a character's short public bio (one line shown in the UI).",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string"}, "description": {"type": "string"}},
        "required": ["name", "description"]}}})
def describe_character(conn, gid, args, actor):
    who = (args.get("name") or "").strip()
    desc = (args.get("description") or "").strip()
    ch = repo.find_character_by_name(conn, gid, who)
    if not ch:
        return _invalid(f"describe_character: no character '{who}'")
    repo.set_character_description(conn, ch["id"], desc)
    return _result("state")  # silent; shown on the character card


@tool({"type": "function", "function": {
    "name": "note_trait",
    "description": "Unlock a lasting personality trait of a character that THIS moment "
                   "just revealed through their behavior (never invented). Short and "
                   "concrete: 'distrusts authority', 'sentimental about her ship'. Use "
                   "sparingly; a trait is earned by a real moment. It appears on their "
                   "card and they will stay true to it.",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string"},
        "trait": {"type": "string", "description": "The revealed trait, a short phrase."},
    }, "required": ["name", "trait"]}}})
def note_trait(conn, gid, args, actor):
    who = (args.get("name") or "").strip()
    ch = repo.find_character_by_name(conn, gid, who)
    if not ch:
        return _invalid(f"note_trait: no character '{who}'")
    trait = repo.add_trait(conn, ch["id"], args.get("trait", ""), settings.CHAR_TRAIT_CAP)
    if not trait:
        return _result("state")  # duplicate or full: silent
    return _result("state", f"Trait unlocked: {ch['name']} - {trait}.")


@tool({"type": "function", "function": {
    "name": "offer_action",
    "description": "Offer the player a one-off contextual action toward a character (a button), "
                   "e.g. 'Bribe'. A character offers at most 3 actions total.",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string"}, "label": {"type": "string"}}, "required": ["name", "label"]}}})
def offer_action(conn, gid, args, actor):
    who = (args.get("name") or "").strip()
    label = (args.get("label") or "").strip()
    ch = repo.find_character_by_name(conn, gid, who)
    if not ch:
        return _invalid(f"offer_action: no character '{who}'")
    ok = repo.offer_action(conn, ch["id"], label, settings.CHAR_ACTION_CAP)
    return _result("state") if ok else _invalid(f"offer_action: {ch['name']} already has {settings.CHAR_ACTION_CAP} actions")
