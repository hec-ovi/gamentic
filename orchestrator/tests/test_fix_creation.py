"""Creation seeding (live e2e 2026-06-11): the creator's opening fiction must be TRUE in
state. The deployed game opened with a sealed ledger in the player's satchel (and a quest
about it) while the inventory sat empty for 40 turns, the clock said morning while the
fiction was a rainy evening, every character card rendered a blank description line, and
creator chat replies shipped raw model content. Finalize now seeds possessions and the
story clock from the sheet, descriptions backstop from the persona, and creator replies
are sanitized before they are stored or returned."""
from app import llm, prompts, repo


def _finalize_world(**extra):
    return {
        "title": "The Shadows of Graywater",
        "setting": "a rain-soaked port town",
        "tone": "grim",
        "narrator_persona": "Low and close.",
        "opening_scenario": "In your satchel lies the water-damaged ledger, its seal unbroken.",
        "start_location": "The Rusty Hook Inn",
        "player_life": 20,
        "characters": [{"name": "Tamsin", "sex": "female", "description": "",
                        "persona": "A sharp-tongued ferry girl. She rows the night crossings."}],
        "quests": [{"title": "The Unbroken Seal", "objectives": ["Open the ledger"]}],
        "lore": [],
        **extra,
    }


def _finalize(client, fake_llm, world, sid="seed"):
    client.post("/create/message", json={"session_id": sid, "message": "A port town mystery."})
    fake_llm.finalize = llm.LLMReply(content="", tool_calls=[llm.ToolCall("save_world", world)])
    r = client.post("/create/finalize", json={"session_id": sid})
    assert r.status_code == 200
    return r.json()["game_id"]


# ---------- player_items + start_time_of_day reach state ----------

def test_finalize_seeds_player_items_and_the_story_clock(client, fake_llm):
    gid = _finalize(client, fake_llm, _finalize_world(
        player_items=[{"name": "water-damaged ledger", "description": "its wax seal unbroken"}],
        start_time_of_day="evening"))
    s = client.get(f"/games/{gid}/state").json()
    inv = s["player"]["inventory"]
    assert [i["name"] for i in inv] == ["water-damaged ledger"]
    assert inv[0]["description"] == "its wax seal unbroken"
    assert s["time"]["label"] == "Day 1, evening"          # the fiction's evening, not 10:00


def test_finalize_without_extras_keeps_the_defaults(client, fake_llm):
    gid = _finalize(client, fake_llm, _finalize_world())
    s = client.get(f"/games/{gid}/state").json()
    assert s["player"]["inventory"] == []
    assert s["time"]["minutes"] == 0 and s["time"]["part"] == "morning"


def test_unknown_start_time_is_tolerated_and_ignored(client, fake_llm):
    # the model never owns the clock: junk maps to the default start, never a crash
    gid = _finalize(client, fake_llm, _finalize_world(start_time_of_day="high noon"))
    assert client.get(f"/games/{gid}/state").json()["time"]["minutes"] == 0


def test_every_start_time_lands_its_own_label_on_day_one():
    # the chosen hours must round-trip through the label derivation (live: a mismatch
    # here is exactly how a night's sleep once landed on 'Day 1, afternoon')
    for part in repo.START_HOURS:
        t = repo.time_at(repo.start_minutes(part))
        assert (t["part"], t["day"]) == (part, 1), part


# ---------- character description backstop ----------

def test_blank_character_description_backstops_from_persona(client, fake_llm):
    gid = _finalize(client, fake_llm, _finalize_world())
    c = client.get(f"/games/{gid}/state").json()["characters"][0]
    assert c["description"] == "A sharp-tongued ferry girl."   # persona's first sentence


def test_explicit_description_is_never_overwritten(client, fake_llm):
    w = _finalize_world()
    w["characters"][0]["description"] = "The ferry girl everyone owes."
    gid = _finalize(client, fake_llm, w)
    c = client.get(f"/games/{gid}/state").json()["characters"][0]
    assert c["description"] == "The ferry girl everyone owes."


def test_direct_creation_route_gets_the_description_backstop_too(client, fake_llm, world):
    # the fallback lives on the MODEL, so POST /games (templates, imports) heals as well
    gid = client.post("/games", json=world).json()["game_id"]
    c = client.get(f"/games/{gid}/state").json()["characters"][0]
    assert c["description"] == "A wary dwarven scout, loyal but blunt."


# ---------- creator readiness (the begin button's gate) ----------

def test_ready_marker_unlocks_and_never_displays(client, fake_llm):
    """Owner (2026-06-11): the agent says it is ready and nothing changes - the begin
    button now LOCKS until the creator signals readiness. The marker itself is plumbing
    and never reaches the player or the stored history."""
    fake_llm.creator_text = llm.LLMReply(content=(
        "Your lighthouse world is complete. Say the word and we begin. [ready]"))
    r = client.post("/create/message", json={"session_id": "rdy1", "message": "That is all."}).json()
    assert r["ready"] is True
    assert "[ready]" not in r["reply"] and r["reply"].endswith("we begin.")
    h = client.get("/create/rdy1").json()
    assert "[ready]" not in h["history"][1]["content"]
    # the marker is the DURABLE truth (live: the model said "when YOU are ready" - no
    # prose signal - and a refresh lost the unlocked button): a refresh stays ready
    assert h["ready"] is True


def test_ready_prose_alone_unlocks_too(client, fake_llm):
    """Parse the intent, never demand the protocol: a builder that only SAYS it in
    words ('ready to start the adventure') still unlocks."""
    fake_llm.creator_text = llm.LLMReply(content=(
        "I'm ready to start the adventure whenever you are."))
    r = client.post("/create/message", json={"session_id": "rdy2", "message": "Go on."}).json()
    assert r["ready"] is True
    assert client.get("/create/rdy2").json()["ready"] is True   # survives a refresh


def test_an_ordinary_creator_reply_stays_locked(client, fake_llm):
    fake_llm.creator_text = llm.LLMReply(content="What tone do you want - grim or playful?")
    r = client.post("/create/message", json={"session_id": "rdy3", "message": "Pirates."}).json()
    assert r["ready"] is False
    assert client.get("/create/rdy3").json()["ready"] is False


def test_creator_prompt_teaches_the_ready_marker():
    from app import prompts
    assert "[ready]" in prompts.render("creator.system.md")


# ---------- creator-reply sanitation ----------

def test_creator_reply_is_sanitized_before_store_and_return(client, fake_llm):
    fake_llm.creator_text = llm.LLMReply(content=(
        "(think: the user wants pirates, I should ask about tone)\n"
        'A pirate cove it is!\nmove_location("the cove")\nWhat tone do you want?'))
    r = client.post("/create/message", json={"session_id": "san", "message": "Pirates."})
    reply = r.json()["reply"]
    assert "(think" not in reply and "move_location" not in reply
    assert "A pirate cove it is!" in reply and "What tone do you want?" in reply
    # the stored history is equally clean: it is re-fed to the model on every later turn
    h = client.get("/create/san").json()["history"]
    assert h[1]["role"] == "assistant"
    assert "(think" not in h[1]["content"] and "move_location" not in h[1]["content"]


# ---------- the schema and the prompts that drive the model ----------

def test_finalize_tool_offers_the_seeding_fields_single_sourced():
    props = prompts.FINALIZE_TOOL[0]["function"]["parameters"]["properties"]
    assert props["start_time_of_day"]["enum"] == list(repo.START_HOURS)  # ONE source
    item_props = props["player_items"]["items"]["properties"]
    assert set(item_props) == {"name", "description"}
    sysmd = prompts.render("finalize.system.md")
    assert "player_items" in sysmd and "start_time_of_day" in sysmd
    assert "must never be empty" in sysmd                  # description demand


def test_origin_skill_demands_five_to_eight_sentences():
    # live: biographies came back ~3 sentences against a 5-8 spec; the demand is now firm
    text = prompts.render("origin.system.md")
    assert "FIVE to EIGHT full sentences" in text
    assert "never fewer than five" in text


def test_direct_post_games_seeds_extras_like_finalize(client, fake_llm):
    # the FE's POST /games path must make the sheet's opening fiction true in state
    # exactly like the creator finalize path does (it shares _seed_sheet_extras)
    world = _finalize_world(
        player_items=[{"name": "sealed letter", "description": "wax stamped with a gull"}],
        start_time_of_day="night")
    gid = client.post("/games", json=world).json()["game_id"]
    s = client.get(f"/games/{gid}/state").json()
    assert [i["name"] for i in s["player"]["inventory"]] == ["sealed letter"]
    assert s["time"]["label"] == "Day 1, night"


def test_player_life_is_clamped_never_rejected(client, fake_llm):
    # live replay: the creator filled player_life=1 and the hero spawned one scratch
    # from death; the sheet's number is a proposal, code bounds it 10..100
    world = _finalize_world()
    world["player_life"] = 1
    gid = client.post("/games", json=world).json()["game_id"]
    s = client.get(f"/games/{gid}/state").json()
    assert s["player"]["life"] == 10 and s["player"]["max_life"] == 10
    world["player_life"] = 9000
    gid2 = client.post("/games", json=world).json()["game_id"]
    assert client.get(f"/games/{gid2}/state").json()["player"]["max_life"] == 100


def test_explain_facts_name_both_locations_when_apart(client, fake_llm):
    # live replay: 'elsewhere (at X)' got garbled into telling the player THEY were at X
    from app import db
    world = _finalize_world()
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = llm.LLMReply(
        content="You step into the stables.",
        tool_calls=[llm.ToolCall("move_location", {"location": "The Stables"})])
    client.post(f"/games/{gid}/action", json={"action": "I go to the stables."})
    with db.get_conn() as conn:
        facts = prompts._explain_facts(conn, gid, "character", "Tamsin", None)
    assert "they are at" in facts and "while you are at The Stables" in facts


def test_finalize_prompt_keeps_player_secrets_out_of_the_public_opening():
    text = prompts.render("finalize.system.md")
    assert "The `opening_scenario` is PUBLIC" in text
    assert "must never be named in it" in text


def test_creation_schedules_unlock_cards_for_seeded_items(client, fake_llm, monkeypatch):
    # live 2026-06-11: a creation-seeded item showed initials forever; cards only
    # rendered on the action route's new-item diff and turn-0 items are never "new".
    # Creation art is one composed pass now: patch the jobs-level stages it calls.
    from app.config import settings as cfg
    from app.integrate import jobs
    calls = []
    monkeypatch.setattr(cfg, "IMAGE_ENABLED", True)
    monkeypatch.setattr(cfg, "IMAGE_ITEMS", True)
    monkeypatch.setattr(jobs, "art_direction", lambda gid: None)
    monkeypatch.setattr(jobs, "generate_images_for_game", lambda gid, direction=None: None)
    monkeypatch.setattr(jobs, "generate_scene_image", lambda gid, sid, prompt_override="": None)
    monkeypatch.setattr(jobs, "generate_item_image",
                        lambda gid, name: calls.append(name))
    world = _finalize_world(
        player_items=[{"name": "Neural Interface Deck", "description": "a cracked deck"}])
    client.post("/games", json=world).json()
    assert "Neural Interface Deck" in calls
