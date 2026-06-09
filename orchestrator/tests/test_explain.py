"""'Ask what this is' (tap-to-explain): POST /games/{gid}/explain returns an in-world
explanation built from PLAYER-VISIBLE facts only. Spoiler-safe: hidden items don't exist
for it, character knowledge/personas never reach the model."""
from app import llm


WORLD = {
    "title": "Tapworld", "setting": "a town", "tone": "calm",
    "narrator_persona": "Plain.", "opening_scenario": "A quiet square.",
    "start_location": "square", "player_life": 20,
    "characters": [{"name": "Mara", "persona": "secretly a royal spy",
                    "description": "A wary dwarven scout.",
                    "knowledge": "Knows the tunnel behind the altar."}],
    "quests": [{"title": "Find the gate", "description": "Get out of town.",
                "objectives": ["Reach the wall"]}], "lore": [],
}


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _explain_call(fake_llm):
    return [c for c in fake_llm.calls if c["system"].startswith("You answer the player's tap")][-1]


def test_explain_item_uses_its_visible_facts(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    fake_llm.narrator = _nar(T("add_item", name="scanner device", description="A cracked wasteland relic that hums."))
    client.post(f"/games/{gid}/action", json={"action": "I pick it up."})

    r = client.post(f"/games/{gid}/explain", json={"kind": "item", "key": "scanner_device"})
    assert r.status_code == 200 and r.json()["text"]
    user = _explain_call(fake_llm)["messages"][1]["content"]
    assert "scanner device" in user and "cracked wasteland relic" in user
    assert "in your pack" in user


def test_explain_character_is_spoiler_safe(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    r = client.post(f"/games/{gid}/explain", json={"kind": "character", "key": "Mara"})
    assert r.status_code == 200
    user = _explain_call(fake_llm)["messages"][1]["content"]
    assert "wary dwarven scout" in user                  # public bio: yes
    assert "royal spy" not in user                       # persona: never
    assert "tunnel behind the altar" not in user         # private knowledge: never


def test_hidden_items_do_not_exist_for_the_explainer(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    fake_llm.narrator = _nar(T("place_item", target="scene", name="buried strongbox", hidden=True))
    client.post(f"/games/{gid}/action", json={"action": "I look around."})
    r = client.post(f"/games/{gid}/explain", json={"kind": "item", "key": "buried strongbox"})
    assert r.status_code == 404                          # not discovered = not explainable


def test_explain_beat_carries_its_surrounding_moment(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    fake_llm.narrator = _nar(T("add_item", name="brass key"), content="A key glints in the dust.")
    d = client.post(f"/games/{gid}/action", json={"action": "I search the fountain."}).json()
    receipt = next(b for b in d["beats"] if b["kind"] == "system")
    r = client.post(f"/games/{gid}/explain", json={"kind": "beat", "beat_id": receipt["id"]})
    assert r.status_code == 200
    user = _explain_call(fake_llm)["messages"][1]["content"]
    assert "Obtained: brass key." in user                # the tapped moment
    assert "search the fountain" in user                 # ...with its surroundings


def test_explain_scene_quest_goal_and_unknown(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    assert client.post(f"/games/{gid}/explain", json={"kind": "scene"}).status_code == 200
    assert client.post(f"/games/{gid}/explain", json={"kind": "quest", "key": "Find the gate"}).status_code == 200
    assert client.post(f"/games/{gid}/explain", json={"kind": "goal"}).status_code == 200
    assert client.post(f"/games/{gid}/explain", json={"kind": "item", "key": "nonsense"}).status_code == 404
    assert client.post("/games/nope/explain", json={"kind": "scene"}).status_code == 404
