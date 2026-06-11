"""Adjudication of the player's stacked attempts. 7a: impossible attempts (no such
target, item not held, target elsewhere/dead) are rejected deterministically with a
friendly in-world beat, never applied, and the narrator is told they failed."""
from app import llm


def _world(chars=None):
    return {
        "title": "Court", "setting": "a keep", "tone": "grim",
        "narrator_persona": "Plain.", "opening_scenario": "A cold hall.",
        "start_location": "hall", "player_life": 20, "characters": chars or [],
        "quests": [{"title": "Get out", "objectives": ["Find the gate"]}], "lore": [],
    }


def _new(client, chars=None):
    return client.post("/games", json=_world(chars)).json()["game_id"]


def _state(client, gid):
    return client.get(f"/games/{gid}/state").json()


def _char(state, name):
    return next(c for c in state["characters"] if c["name"] == name)


def test_give_without_item_is_rejected_friendly(client, fake_llm):
    gid = _new(client, [{"name": "Mara", "persona": "a guard"}])
    out = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "give", "item": "golden crown", "target": "Mara"}]}).json()
    # friendly in-world rejection, not silence and not a dev error string
    assert any(b["kind"] == "system" and "You don't have golden crown" in b["text"]
               for b in out["beats"])
    assert all(i["name"] != "golden crown" for i in _char(out["state"], "Mara")["inventory"])
    # the narrator was told the attempt failed (cannot narrate a successful handover)
    sys_or_user = fake_llm.narrator_calls()[-1]["messages"][-1]["content"]
    assert "failed:" in sys_or_user and "You don't have golden crown" in sys_or_user


def test_attack_unknown_target_is_rejected_friendly(client, fake_llm):
    gid = _new(client)
    out = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "attack", "target": "the dragon"}]}).json()
    assert any(b["kind"] == "system" and "You see no sign of the dragon here" in b["text"]
               for b in out["beats"])


def test_attack_character_in_another_scene_is_rejected(client, fake_llm):
    gid = _new(client, [{"name": "Mara", "persona": "a guard"}])
    # move the player away; Mara (not following) stays in the hall
    fake_llm.narrator = llm.LLMReply(content="...", tool_calls=[
        llm.ToolCall("move_location", {"location": "yard"})])
    client.post(f"/games/{gid}/action", json={"action": "I walk out to the yard."})
    fake_llm.narrator = llm.LLMReply(content="...")
    out = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "attack", "target": "Mara", "amount": 5}]}).json()
    assert any(b["kind"] == "system" and "Mara is not here" in b["text"] for b in out["beats"])
    assert _char(out["state"], "Mara")["life"] == 10          # untouched


def test_valid_attempt_still_applies(client, fake_llm):
    # the narrator (FakeLLM default) says nothing about the attempt -> default-accepted
    gid = _new(client, [{"name": "Brute", "persona": "a thug"}])
    out = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "attack", "target": "Brute", "amount": 4}]}).json()
    assert _char(out["state"], "Brute")["life"] == 6


# ---- 7b: the narrator adjudicates valid attempts ----

def test_attempts_are_listed_for_adjudication(client, fake_llm):
    gid = _new(client, [{"name": "Brute", "persona": "a thug"}])
    client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "attack", "target": "Brute", "amount": 4}]})
    user = fake_llm.narrator_calls()[-1]["messages"][-1]["content"]
    assert "THE PLAYER ATTEMPTS" in user and "1. attack Brute (4 damage)" in user
    # and the block is absent on a plain free-text turn
    client.post(f"/games/{gid}/action", json={"action": "I look around."})
    assert "THE PLAYER ATTEMPTS" not in fake_llm.narrator_calls()[-1]["messages"][-1]["content"]


def test_narrator_can_veto_an_attempt(client, fake_llm):
    gid = _new(client, [{"name": "Mara", "persona": "a guard"}])
    fake_llm.narrator = llm.LLMReply(content="...", tool_calls=[
        llm.ToolCall("add_item", {"name": "coin"})])
    client.post(f"/games/{gid}/action", json={"action": "I pick up a coin."})
    fake_llm.narrator = llm.LLMReply(
        content="Mara folds her arms.",
        tool_calls=[llm.ToolCall("reject_attempt",
                                 {"attempt": 1, "reason": "Mara steps back, refusing the coin."})])
    out = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "give", "item": "coin", "target": "Mara"}]}).json()
    # vetoed: nothing transferred, and the in-world reason reaches the player
    assert any("refusing the coin" in b["text"] for b in out["beats"] if b["kind"] == "system")
    assert all(i["name"] != "coin" for i in _char(out["state"], "Mara")["inventory"])
    assert any(i["name"] == "coin" for i in out["state"]["player"]["inventory"])  # still held


def test_narrator_accepting_with_a_tool_prevents_double_apply(client, fake_llm):
    gid = _new(client, [{"name": "Brute", "persona": "a thug"}])
    # the narrator resolves the attack itself, with a modified amount (2 instead of 4)
    fake_llm.narrator = llm.LLMReply(
        content="Your blow glances off his shoulder plate.",
        tool_calls=[llm.ToolCall("apply_damage", {"target": "Brute", "amount": 2})])
    out = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "attack", "target": "Brute", "amount": 4}]}).json()
    assert _char(out["state"], "Brute")["life"] == 8       # 10-2, NOT 10-2-4


def test_narrator_give_item_tool_transfers_from_player(client, fake_llm):
    # free-text handovers now work too: the narrator has give_item (player -> character)
    gid = _new(client, [{"name": "Mara", "persona": "a guard"}])
    fake_llm.narrator = llm.LLMReply(content="...", tool_calls=[
        llm.ToolCall("add_item", {"name": "map"})])
    client.post(f"/games/{gid}/action", json={"action": "I take the map."})
    fake_llm.narrator = llm.LLMReply(content="She takes it.", tool_calls=[
        llm.ToolCall("give_item", {"item": "map", "target": "Mara"})])
    out = client.post(f"/games/{gid}/action", json={"action": "I hand Mara the map."}).json()
    assert any(i["name"] == "map" for i in _char(out["state"], "Mara")["inventory"])
    assert all(i["name"] != "map" for i in out["state"]["player"]["inventory"])
