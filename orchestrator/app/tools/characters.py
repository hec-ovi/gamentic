"""Characters: directing (cue), the dynamic cast (spawn/kill), bonds, bios, traits,
and offered actions."""
from .. import constants, repo
from ..config import settings
from .base import _invalid, _result, tool


def _a_or_an(phrase: str) -> str:
    """'a stranger' / 'an old friend': the article follows the FIRST word's letter
    (multi-word relations like 'sworn enemy' read right; role-words like 'boss' still
    read fine with an article)."""
    return f"an {phrase}" if phrase.lstrip()[:1].lower() in "aeiou" else f"a {phrase}"


def _not_here(conn, gid, ch) -> str | None:
    """Why this character cannot witness the current moment: dead, or not in the
    player's scene. None when they are right here. Guards note_moment/note_trait only
    (static-confirmed they wrote into ANY character's prompt-visible memory);
    reveal_origin stays open - learning someone's past from a third party is fine."""
    if not ch["alive"]:
        return f"{ch['name']} is dead"
    here = repo.get_player(conn, gid)["location"]
    if not ch["present"] or repo.norm_name(ch["location"] or "").lower() != repo.norm_name(here).lower():
        return f"{ch['name']} is not present"
    return None


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
        "sex": {"type": "string", "enum": ["female", "male"],
                "description": "Their sex. Fixed at creation; portrait, pronouns and voice all follow it."},
        "appearance": {"type": "string",
                       "description": "What they look like (for their portrait). Start with explicit "
                                      "sex and rough age ('a young woman...', 'an old man...'); looks "
                                      "only, never words or signs to draw."},
        "knowledge": {"type": "string", "description": "Private things only they know."},
        "origin": {"type": "string",
                   "description": "Their backstory (private; the player discovers it through play)."},
        "relation": {"type": "string",
                     "description": "What they are to the player, one or two words (stranger, "
                                    "old friend, debt collector...)."},
        "life": {"type": "integer"},
    }, "required": ["name", "persona", "sex"]}}})
def spawn_character(conn, gid, args, actor):
    nm = (args.get("name") or "").strip()
    if not nm:
        return _invalid("spawn_character: no name")
    if repo.find_character_by_name(conn, gid, nm):
        return _invalid(f"spawn_character: '{nm}' already here")
    cid = repo.spawn_character(conn, gid, nm, args.get("persona", ""), args.get("appearance", ""),
                               args.get("knowledge", ""), life=int(args.get("life", 10) or 10),
                               gender=args.get("sex", ""), origin=args.get("origin", ""),
                               relation=(args.get("relation") or "").strip())
    # a person authored as scenery first becomes ONE entity, not an item card beside a
    # character card (live replay: 'a sleeping camel driver' kept its slot after he woke)
    repo.absorb_scene_item_into_character(conn, gid, nm)
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
    if not row["alive"]:
        # the no-op-receipt disease, kill flavor: re-killing someone already gone
        # must not print '{name} is gone.' a second time
        return _result("state")
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
    if (ch["disposition"] or "").lower() == disp:
        # unchanged: silent (live: 'Tamsin turns hostile.' printed SIX times while she
        # already was - the changed guard covered the moment but not the receipt)
        return _result("state")
    repo.set_disposition(conn, ch["id"], disp)
    # a real shift in the bond is a pivotal moment, mechanically detected
    repo.add_moment(conn, ch["id"], f"Turned {disp} toward the player")
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
    changed = bool(ch["following"]) != foll
    repo.set_following(conn, ch["id"], foll)
    if foll:  # a new follower joins the player's current scene
        repo.set_character_location(conn, ch["id"], repo.get_player(conn, gid)["location"])
    if changed:
        repo.add_moment(conn, ch["id"], "Began traveling with the player" if foll
                        else "Parted ways with the player")
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
    "description": "Unlock a lasting PERSONALITY trait of a character that THIS moment "
                   "just revealed through their behavior (never invented). A trait is "
                   "how they BEHAVE, vivid and specific: 'cynical', 'impulsive', "
                   "'aggressive when cornered', 'submissive to power', 'fiercely "
                   "loyal', 'distrusts authority', 'sentimental about her ship'. "
                   "Facts they know and things that happened belong in remember or "
                   "note_moment, not here. Use sparingly; a trait is earned by a real "
                   "moment. It appears on their card and they will stay true to it.",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string"},
        "trait": {"type": "string",
                  "description": "The behavior pattern as one vivid word or complete "
                                 "phrase of 2-6 words, e.g. 'impulsive', 'wary of "
                                 "strangers'."},
    }, "required": ["name", "trait"]}}})
def note_trait(conn, gid, args, actor):
    who = (args.get("name") or "").strip()
    ch = repo.find_character_by_name(conn, gid, who)
    if not ch:
        return _invalid(f"note_trait: no character '{who}'")
    why = _not_here(conn, gid, ch)
    if why:   # a trait is revealed by behavior in THIS moment; the absent reveal nothing
        return _invalid(f"note_trait: {why}")
    trait = repo.add_trait(conn, ch["id"], args.get("trait", ""), settings.CHAR_TRAIT_CAP)
    if not trait:
        return _result("state")  # duplicate or full: silent
    return _result("state", f"Trait unlocked: {ch['name']} - {trait}.")


@tool({"type": "function", "function": {
    "name": "set_relation",
    "description": "Set what a character IS to the player as the story defines it: one or "
                   "two words, your free choice (stranger, ally, friend, sister, boss, rival, "
                   "mentor, sworn enemy...). Always the BOND from the character toward the "
                   "player - never the character's own job or title. This is the narrative "
                   "bond; disposition stays the mood dial. Update it when the relationship "
                   "truly changes.",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string"},
        "relation": {"type": "string", "description": "One or two words."},
    }, "required": ["name", "relation"]}}})
def set_relation(conn, gid, args, actor):
    who = (args.get("name") or "").strip()
    rel = " ".join((args.get("relation") or "").split())[:40].strip()
    if not rel:
        return _invalid("set_relation: empty relation")
    ch = repo.find_character_by_name(conn, gid, who)
    if not ch:
        return _invalid(f"set_relation: no character '{who}'")
    old = repo.character_relation(ch)
    if old.lower() == rel.lower():
        return _result("state")  # unchanged: silent
    repo.set_relation(conn, ch["id"], rel)
    if not old and rel.lower() in ("stranger", "unknown"):
        # empty -> stranger is bookkeeping, not a story beat (live: 'Tamsin is now
        # your stranger.' plus a fake 'Became the player's stranger' pivotal moment
        # from this exact non-event); record the label, stage nothing
        return _result("state")
    # article-aware grammar (live: 'Tamsin is now your stranger.' read broken), and
    # DIRECTION-true: relation is what the CHARACTER is to the hero. The grammar
    # rewording ('X now sees you as...' / 'Came to see the player as...') had silently
    # flipped the meaning (live: Leyla, the acquaintance, was announced as seeing the
    # PLAYER as one) - and the flipped moment fed the agent's own memory ever after.
    repo.add_moment(conn, ch["id"], f"Became {_a_or_an(rel)} to the player")
    return _result("state", f"{ch['name']} is {_a_or_an(rel)} to you now.")


@tool({"type": "function", "function": {
    "name": "note_moment",
    "description": "Record a PIVOTAL shared moment between a character and the player: a "
                   "bond formed, a life saved, a betrayal, a promise, a sacrifice. One short "
                   "past-tense line, e.g. 'Stood beside the player against the Watch'. Only "
                   "true turning points, never small talk; it becomes one of the character's "
                   "lasting memories of the player.",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string"},
        "event": {"type": "string", "description": "The pivotal event, one short line."},
    }, "required": ["name", "event"]}}})
def note_moment(conn, gid, args, actor):
    who = (args.get("name") or "").strip()
    ch = repo.find_character_by_name(conn, gid, who)
    if not ch:
        return _invalid(f"note_moment: no character '{who}'")
    why = _not_here(conn, gid, ch)
    if why:   # a SHARED moment needs both parties in the scene; the absent share nothing
        return _invalid(f"note_moment: {why}")
    repo.add_moment(conn, ch["id"], args.get("event", ""))
    return _result("state")  # silent: the event itself was just narrated


@tool({"type": "function", "function": {
    "name": "reveal_origin",
    "description": "Record a piece of a character's PAST the player just LEARNED (they told "
                   "it, someone else did, or it surfaced in the scene). Short and concrete: "
                   "'fled the mining colonies after the riots'. Only what was actually "
                   "learned, never the whole biography at once. It appears on their profile.",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string"},
        "fact": {"type": "string", "description": "The piece of their past just learned."},
    }, "required": ["name", "fact"]}}})
def reveal_origin(conn, gid, args, actor):
    who = (args.get("name") or "").strip()
    ch = repo.find_character_by_name(conn, gid, who)
    if not ch:
        return _invalid(f"reveal_origin: no character '{who}'")
    fact = repo.add_origin_fact(conn, ch["id"], args.get("fact", ""), settings.CHAR_TRAIT_CAP)
    if not fact:
        return _result("state")  # duplicate or full: silent
    return _result("state", f"You learn of {ch['name']}'s past: {fact}.")


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

# ---------- the character's OWN memory (self-tools; whispers have no narrator) ----------
# A private exchange never runs a narrator pass, so confessions made there were never
# recorded anywhere (live 2026-06-11: a whispered life story - the slums, a brother lost
# to the sweeps - left the profile's past, traits and moments untouched). These three act
# on the SPEAKER only: a character writes their own memory, never anyone else's.

SHARE_PAST = {"type": "function", "function": {
    "name": "share_past",
    "description": "You just told or showed them a real piece of YOUR past. Record that piece "
                   "(one short sentence) so it becomes part of what they know of you. Only "
                   "genuine self-revelation, never small talk.",
    "parameters": {"type": "object", "properties": {
        "piece": {"type": "string", "description": "The piece of your past, one short sentence."},
    }, "required": ["piece"]}}}


@tool(SHARE_PAST)
def share_past(conn, gid, args, actor):
    if not actor:
        return _invalid("share_past: a character's own tool")
    fact = repo.add_origin_fact(conn, actor["id"], args.get("piece", ""), settings.CHAR_TRAIT_CAP)
    if not fact:
        return _result("state")  # duplicate or full: silent
    return _result("state", f"You learn of {actor['name']}'s past: {fact}.")


MARK_MOMENT = {"type": "function", "function": {
    "name": "mark_moment",
    "description": "A true turning point just happened between YOU and the one you are with "
                   "(a secret confided, a bond formed, a promise, a betrayal). Record it as "
                   "one short past-tense line; it becomes one of your lasting memories of them.",
    "parameters": {"type": "object", "properties": {
        "event": {"type": "string", "description": "The pivotal event, one short line."},
    }, "required": ["event"]}}}


@tool(MARK_MOMENT)
def mark_moment(conn, gid, args, actor):
    if not actor:
        return _invalid("mark_moment: a character's own tool")
    repo.add_moment(conn, actor["id"], args.get("event", ""))
    return _result("state")  # silent: the moment itself was just lived


ADMIT_TRAIT = {"type": "function", "function": {
    "name": "admit_trait",
    "description": "What you just said or did REVEALED a lasting personality trait of yours "
                   "(2-4 vivid words, e.g. 'distrusts authority', 'fiercely loyal'). Record it; "
                   "it becomes part of how they see you. Only when truly shown, never invented.",
    "parameters": {"type": "object", "properties": {
        "trait": {"type": "string", "description": "The trait, 2-4 words."},
    }, "required": ["trait"]}}}


@tool(ADMIT_TRAIT)
def admit_trait(conn, gid, args, actor):
    if not actor:
        return _invalid("admit_trait: a character's own tool")
    trait = repo.add_trait(conn, actor["id"], args.get("trait", ""), settings.CHAR_TRAIT_CAP)
    if not trait:
        return _result("state")  # duplicate or full: silent
    return _result("state", f"Trait unlocked: {actor['name']} - {trait}.")
