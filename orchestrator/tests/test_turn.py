"""End-to-end turn-loop tests through the real HTTP routes."""
from app import llm


def _new_game(client, world):
    r = client.post("/games", json=world)
    assert r.status_code == 200
    return r.json()["game_id"]


def test_create_game_and_state(client, fake_llm, world):
    gid = _new_game(client, world)
    s = client.get(f"/games/{gid}/state").json()
    assert s["title"] == "The Sunken Crypt"
    assert s["player"]["life"] == 20
    assert s["player"]["location"] == "crypt entrance"
    assert [c["name"] for c in s["characters"]] == ["Mara"]
    assert s["quests"][0]["title"] == "Escape the Crypt"
    assert len(s["quests"][0]["objectives"]) == 2


def test_beats_includes_opening_and_new_turns(client, fake_llm, world):
    gid = _new_game(client, world)
    opening = client.get(f"/games/{gid}/beats").json()["beats"]
    assert len(opening) == 1
    assert opening[0]["speaker"] == "narrator"
    assert "Cold water" in opening[0]["text"]

    last_turn = opening[0]["turn_index"]
    client.post(f"/games/{gid}/action", json={"action": "I look around."})
    new = client.get(f"/games/{gid}/beats", params={"since": last_turn}).json()["beats"]
    assert all(b["turn_index"] > last_turn for b in new)
    assert any(b["speaker"] == "player" for b in new)


def test_action_applies_tools_and_cues_character(client, fake_llm, world):
    gid = _new_game(client, world)
    fake_llm.narrator = llm.LLMReply(
        content="A skeletal hand bursts from the water and rakes your arm.",
        tool_calls=[
            llm.ToolCall("apply_damage", {"amount": 5}),
            llm.ToolCall("add_item", {"name": "rusty dagger", "qty": 1}),
            llm.ToolCall("award_points", {"amount": 10, "reason": "first blood"}),
            llm.ToolCall("cue_character", {"name": "Mara"}),
        ],
    )
    fake_llm.character = llm.LLMReply(content="\"Behind you!\" Mara hisses, blade drawn.")

    r = client.post(f"/games/{gid}/action", json={"action": "I wade deeper into the crypt."})
    assert r.status_code == 200
    data = r.json()

    kinds = [(b["speaker"], b["kind"]) for b in data["beats"]]
    assert ("player", "action") in kinds
    assert ("narrator", "narration") in kinds
    assert any(k == ("system", "system") for k in kinds)          # damage/item/points notes
    assert any(b["kind"] == "dialogue" and b["speaker_name"] == "Mara" for b in data["beats"])

    st = data["state"]["player"]
    assert st["life"] == 15
    assert st["points"] == 10
    assert any(i["name"] == "rusty dagger" for i in st["inventory"])


def test_invalid_tool_is_ignored(client, fake_llm, world):
    gid = _new_game(client, world)
    fake_llm.narrator = llm.LLMReply(
        content="You fumble for something you never had.",
        tool_calls=[llm.ToolCall("remove_item", {"name": "golden crown"})],  # not in inventory
    )
    r = client.post(f"/games/{gid}/action", json={"action": "I check my pack."})
    assert r.status_code == 200
    data = r.json()
    # no system beat should be emitted for the rejected tool
    assert not any(b["kind"] == "system" for b in data["beats"])
    assert data["state"]["player"]["inventory"] == []


def test_cue_unknown_character_does_not_crash(client, fake_llm, world):
    gid = _new_game(client, world)
    fake_llm.narrator = llm.LLMReply(
        content="The silence is total.",
        tool_calls=[llm.ToolCall("cue_character", {"name": "Nobody"})],
    )
    r = client.post(f"/games/{gid}/action", json={"action": "I listen."})
    assert r.status_code == 200
    assert not any(b["kind"] == "dialogue" for b in r.json()["beats"])


def test_move_location_updates_state(client, fake_llm, world):
    gid = _new_game(client, world)
    fake_llm.narrator = llm.LLMReply(
        content="You descend a slick stair into a wider chamber.",
        tool_calls=[llm.ToolCall("move_location", {"location": "altar chamber"})],
    )
    client.post(f"/games/{gid}/action", json={"action": "I go down the stairs."})
    s = client.get(f"/games/{gid}/state").json()
    assert s["player"]["location"] == "altar chamber"
    # scene persistence: a non-following character stays at its scene (does not trail along)
    assert all(not c["following"] for c in s["characters"])
    assert s["characters"][0]["location"] == "crypt entrance"


def test_quest_lifecycle(client, fake_llm, world):
    gid = _new_game(client, world)
    qid = client.get(f"/games/{gid}/state").json()["quests"][0]["id"]
    oid = client.get(f"/games/{gid}/state").json()["quests"][0]["objectives"][0]["id"]
    fake_llm.narrator = llm.LLMReply(
        content="The altar looms.",
        tool_calls=[
            llm.ToolCall("update_objective", {"objective_id": oid, "done": True}),
            llm.ToolCall("complete_quest", {"quest_id": qid}),
        ],
    )
    client.post(f"/games/{gid}/action", json={"action": "I find the altar."})
    q = client.get(f"/games/{gid}/state").json()["quests"][0]
    assert q["status"] == "done"
    assert q["objectives"][0]["done"] is True


def test_empty_action_rejected(client, fake_llm, world):
    gid = _new_game(client, world)
    r = client.post(f"/games/{gid}/action", json={"action": "   "})
    assert r.status_code == 400


def test_action_on_missing_game_404(client, fake_llm):
    r = client.post("/games/doesnotexist/action", json={"action": "hello"})
    assert r.status_code == 404


def test_delete_game_wipes_session(client, fake_llm, world):
    gid = _new_game(client, world)
    assert client.delete(f"/games/{gid}").status_code == 200
    assert client.get(f"/games/{gid}/state").status_code == 404
    assert gid not in [g["id"] for g in client.get("/games").json()["games"]]
    assert client.delete(f"/games/{gid}").status_code == 404      # already gone


def test_clear_history_keeps_state(client, fake_llm, world):
    gid = _new_game(client, world)
    fake_llm.narrator = llm.LLMReply(content="You take a step.")
    client.post(f"/games/{gid}/action", json={"action": "I step forward."})
    assert client.get(f"/games/{gid}/beats").json()["beats"]
    assert client.delete(f"/games/{gid}/beats").status_code == 200
    assert client.get(f"/games/{gid}/beats").json()["beats"] == []
    assert client.get(f"/games/{gid}/state").status_code == 200    # state survives


def test_creator_message_and_finalize(client, fake_llm):
    r = client.post("/create/message", json={"session_id": "s1", "message": "I want a haunted lighthouse."})
    assert r.status_code == 200
    assert r.json()["reply"]

    fake_llm.finalize = llm.LLMReply(content="", tool_calls=[llm.ToolCall("save_world", {
        "title": "The Lamp Keeper",
        "setting": "a haunted lighthouse",
        "tone": "eerie",
        "narrator_persona": "A hushed, dread-soaked narrator.",
        "opening_scenario": "The lamp gutters as you climb the spiral stair.",
        "start_location": "lighthouse base",
        "player_life": 18,
        "characters": [{"name": "The Keeper", "persona": "A drowned ghost who guards the lamp.",
                        "description": "A pale ghost in oilskins.", "disposition": "hostile"}],
        "quests": [{"title": "Relight the Lamp", "description": "Restore the beacon.",
                    "objectives": ["Reach the lamp room"]}],
        "lore": [],
    })])
    r = client.post("/create/finalize", json={"session_id": "s1"})
    assert r.status_code == 200
    gid = r.json()["game_id"]
    s = client.get(f"/games/{gid}/state").json()
    assert s["title"] == "The Lamp Keeper"
    assert s["player"]["life"] == 18
    keeper = s["characters"][0]
    assert keeper["name"] == "The Keeper"
    assert keeper["description"] == "A pale ghost in oilskins."   # creator set the bio
    assert keeper["disposition"] == "hostile"                     # and the disposition


def test_finalize_unknown_session_409(client, fake_llm):
    r = client.post("/create/finalize", json={"session_id": "nope"})
    assert r.status_code == 409
