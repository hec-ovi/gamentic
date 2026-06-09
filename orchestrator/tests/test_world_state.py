"""World state machines: character disposition, following + scene persistence,
scene/story status enums, and code-side validation of the finite vocabularies.
"""
from app import llm


def _world(chars, start="hall"):
    return {
        "title": "Statetown", "setting": "a town", "tone": "calm",
        "narrator_persona": "Plain.", "opening_scenario": "A quiet square.",
        "start_location": start, "player_life": 20,
        "characters": chars,
        "quests": [{"title": "Look around", "description": "", "objectives": ["Explore"]}],
        "lore": [],
    }


def _new(client, chars, start="hall"):
    return client.post("/games", json=_world(chars, start)).json()["game_id"]


def _find(state, name):
    return next(c for c in state["characters"] if c["name"] == name)


def test_disposition_set(client, fake_llm):
    gid = _new(client, [{"name": "Mara", "persona": "a guard"}])
    assert _find(client.get(f"/games/{gid}/state").json(), "Mara")["disposition"] == "neutral"
    fake_llm.narrator = llm.LLMReply(content="Mara's eyes harden.",
                                     tool_calls=[llm.ToolCall("set_disposition", {"name": "Mara", "disposition": "hostile"})])
    d = client.post(f"/games/{gid}/action", json={"action": "I insult Mara."}).json()
    assert _find(d["state"], "Mara")["disposition"] == "hostile"


def test_invalid_disposition_rejected(client, fake_llm):
    gid = _new(client, [{"name": "Mara", "persona": "a guard"}])
    fake_llm.narrator = llm.LLMReply(content="...",
                                     tool_calls=[llm.ToolCall("set_disposition", {"name": "Mara", "disposition": "furious"})])
    d = client.post(f"/games/{gid}/action", json={"action": "x"}).json()
    assert _find(d["state"], "Mara")["disposition"] == "neutral"      # unchanged
    assert not any(b["kind"] == "system" for b in d["beats"])          # invalid -> no system beat


def test_following_and_scene_persistence(client, fake_llm):
    gid = _new(client, [{"name": "Mara", "persona": "a scout"}, {"name": "Bron", "persona": "a clerk"}],
               start="hall")
    # Mara begins following
    fake_llm.narrator = llm.LLMReply(content="Mara falls in beside you.",
                                     tool_calls=[llm.ToolCall("set_following", {"name": "Mara", "following": True})])
    s = client.post(f"/games/{gid}/action", json={"action": "Mara, with me."}).json()["state"]
    assert _find(s, "Mara")["following"] is True

    # move to the cellar: Mara (following) comes, Bron stays
    fake_llm.narrator = llm.LLMReply(content="You descend.",
                                     tool_calls=[llm.ToolCall("move_location", {"location": "cellar"})])
    s = client.post(f"/games/{gid}/action", json={"action": "I go to the cellar."}).json()["state"]
    assert s["player"]["location"] == "cellar"
    assert _find(s, "Mara")["location"] == "cellar"        # follower moved
    assert _find(s, "Bron")["location"] == "hall"          # stayed behind

    # return to the hall: Bron is there again (scene persistence)
    fake_llm.narrator = llm.LLMReply(content="You climb back up.",
                                     tool_calls=[llm.ToolCall("move_location", {"location": "hall"})])
    s = client.post(f"/games/{gid}/action", json={"action": "I return."}).json()["state"]
    assert _find(s, "Bron")["location"] == "hall"
    assert _find(s, "Mara")["location"] == "hall"          # follower returned too


def test_scene_and_game_status(client, fake_llm):
    gid = _new(client, [{"name": "Mara", "persona": "a guard"}])
    assert client.get(f"/games/{gid}/state").json()["scene_status"] == "calm"
    fake_llm.narrator = llm.LLMReply(content="Steel rasps free.",
                                     tool_calls=[llm.ToolCall("set_scene_status", {"status": "dangerous"})])
    s = client.post(f"/games/{gid}/action", json={"action": "I draw."}).json()["state"]
    assert s["scene_status"] == "dangerous"

    fake_llm.narrator = llm.LLMReply(content="The threat is over; you have won.",
                                     tool_calls=[llm.ToolCall("set_game_status", {"status": "won"})])
    s = client.post(f"/games/{gid}/action", json={"action": "I end it."}).json()["state"]
    assert s["status"] == "won"


def test_invalid_scene_status_rejected(client, fake_llm):
    gid = _new(client, [{"name": "Mara", "persona": "a guard"}])
    fake_llm.narrator = llm.LLMReply(content="...",
                                     tool_calls=[llm.ToolCall("set_scene_status", {"status": "apocalyptic"})])
    s = client.post(f"/games/{gid}/action", json={"action": "x"}).json()["state"]
    assert s["scene_status"] == "calm"                     # unchanged (not in enum)


def test_current_goal_seeded_from_quest_then_updatable(client, fake_llm):
    # The player always has a purpose: the goal is seeded from the first quest's first
    # objective at creation, and the narrator can refine it as the story turns.
    gid = _new(client, [{"name": "Mara", "persona": "a guard"}])
    assert client.get(f"/games/{gid}/state").json()["current_goal"] == "Explore"  # seeded
    fake_llm.narrator = llm.LLMReply(content="A purpose crystallizes.",
                                     tool_calls=[llm.ToolCall("set_goal", {"goal": "Escape the keep"})])
    s = client.post(f"/games/{gid}/action", json={"action": "I realize I must flee."}).json()["state"]
    assert s["current_goal"] == "Escape the keep"


def test_world_rules_block_present_once(client, fake_llm):
    """The finite vocabularies are surfaced to the narrator exactly once (system level)."""
    gid = _new(client, [{"name": "Mara", "persona": "a guard"}])
    client.post(f"/games/{gid}/action", json={"action": "I wait."})
    sys = fake_llm.narrator_calls()[0]["system"]
    assert sys.count("WORLD RULES") == 1
    assert "friendly | neutral | hostile | unknown" in sys
