"""Resolver-style prompt dispatch: the narrator's core system prompt stays lean; the
detailed protocol blocks (furnish a NEW place, handle a RETURN after absence) and the
reject_attempt tool are injected ONLY on the turns where the state triggers them."""
import os

from app import llm, prompts


WORLD = {
    "title": "Dispatch", "setting": "a town", "tone": "calm",
    "narrator_persona": "Plain.", "opening_scenario": "A quiet square.",
    "start_location": "square", "player_life": 20,
    "characters": [{"name": "Bron", "persona": "a bored guard, he naps standing up"}],
    "quests": [{"title": "Look", "objectives": ["Explore"]}], "lore": [],
}

NEWPLACE = "NEW PLACE: furnish it THIS turn"
RETURNING = "RETURNING: the place lived while the player was gone"


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _last(fake_llm):
    return fake_llm.narrator_calls()[-1]


def test_newplace_block_only_while_scene_is_unfurnished(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    # the opening scene is seeded with a description at creation -> NOT a new place
    client.post(f"/games/{gid}/action", json={"action": "I look around."})
    assert NEWPLACE not in _last(fake_llm)["system"]

    # moving somewhere fresh injects the furnish protocol (with its few-shot)
    fake_llm.narrator = _nar(T("move_location", location="alley"))
    client.post(f"/games/{gid}/action", json={"action": "I duck into the alley."})
    fake_llm.narrator = _nar(content="...")
    client.post(f"/games/{gid}/action", json={"action": "I look."})
    sys = _last(fake_llm)["system"]
    assert NEWPLACE in sys
    assert "drain tunnel" in sys                       # its few-shot travels with it

    # once described, the block is gone (lean core again)
    fake_llm.narrator = _nar(T("describe_scene", description="A cramped, wet alley."))
    client.post(f"/games/{gid}/action", json={"action": "I take it in."})
    fake_llm.narrator = _nar(content="...")
    client.post(f"/games/{gid}/action", json={"action": "I wait."})
    assert NEWPLACE not in _last(fake_llm)["system"]


def test_returning_block_only_when_arriving_back(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    client.post(f"/games/{gid}/action", json={"action": "I look."})
    assert RETURNING not in _last(fake_llm)["system"]   # never been away

    fake_llm.narrator = _nar(T("move_location", location="tavern"))
    client.post(f"/games/{gid}/action", json={"action": "I head to the tavern."})
    fake_llm.narrator = _nar(T("move_location", location="square"))
    client.post(f"/games/{gid}/action", json={"action": "I go back."})
    fake_llm.narrator = _nar(content="...")
    client.post(f"/games/{gid}/action", json={"action": "I look around."})
    sys = _last(fake_llm)["system"]
    assert RETURNING in sys                             # protocol rides with the state flag
    assert "RETURNING: The player was last here" in sys # ...which is also present


def test_core_always_carries_the_transition_protocol_and_worked_turn(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    client.post(f"/games/{gid}/action", json={"action": "I look."})
    sys = _last(fake_llm)["system"]
    assert "Reason about the state transition (silently, in your thinking)" in sys
    assert "the NEXT state" in sys
    assert "A worked turn" in sys and "NEVER printed" in sys
    # the stale claim is gone: the goal is seeded at creation, never "starts with NO goal"
    assert "NO goal" not in sys


def test_reject_attempt_offered_only_while_adjudicating(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    # plain narration turn: no pending attempts -> no veto tool in the schema
    client.post(f"/games/{gid}/action", json={"action": "I look around."})
    assert "reject_attempt" not in _last(fake_llm)["names"]

    # an attack segment creates a pending attempt -> the veto tool appears
    client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "attack", "target": "Bron", "amount": 2}]})
    call = _last(fake_llm)
    assert "reject_attempt" in call["names"]
    assert "PLAYER ATTEMPTS" in call["messages"][1]["content"]


def test_no_prompt_template_carries_authoring_artifacts():
    """A literal </content> line shipped to the model from three templates (an authoring
    artifact); templates are model-facing prose, never markup."""
    for name in os.listdir(prompts.PROMPT_DIR):
        with open(os.path.join(prompts.PROMPT_DIR, name), encoding="utf-8") as f:
            assert "</content" not in f.read(), name
