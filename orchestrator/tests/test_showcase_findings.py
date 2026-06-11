"""Fixes for the bugs the 3-adventure showcase soak run surfaced (live, real model):
1. tool-stream debris leaked INSIDE a tool argument and reached state.current_goal,
2. a player's stated attack force was lost when the narrator accepted without an amount."""
from app import llm


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def test_tool_stream_debris_is_scrubbed_from_arguments(client, fake_llm, world):
    """Live: goal arrived as '...chamber.}<tool_call|><|tool_call>call:cue_character{name:'"""
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(
        T("set_goal", goal="Persuade the guards to let you enter}<tool_call|><|tool_call>call:cue_character{name:"),
        T("add_item", name="iron key}<tool_call>call:remember{note:"),
        content="The warden weighs your words.")
    d = client.post(f"/games/{gid}/action", json={"action": "I plead my case."}).json()
    assert d["state"]["current_goal"] == "Persuade the guards to let you enter"
    receipts = [b["text"] for b in d["beats"] if b["kind"] == "system"]
    assert "New goal: Persuade the guards to let you enter." in receipts
    assert "Obtained: iron key." in receipts
    assert not any("tool_call" in r for r in receipts)
    inv = d["state"]["player"]["inventory"]
    assert inv[0]["name"] == "iron key"


def test_player_attack_amount_wins_when_narrator_accepts_without_one(client, fake_llm, world,
                                                                     monkeypatch):
    """Live: 'attack for 12' was accepted as a default-3 hit (Ser Odo survived at 2 hp)."""
    from app.config import settings
    monkeypatch.setattr(settings, "DAMAGE_CAP", 12)   # this test pins carry-over, not the cap
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("apply_damage", target="Mara"),   # accepted, no amount named
                             content="Your blade bites deep.")
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "attack", "target": "Mara", "amount": 12}]}).json()
    assert any("12 damage" in b["text"] or "struck down" in b["text"]
               for b in d["beats"] if b["kind"] == "system")
    mara = next(c for c in d["state"]["characters"] if c["name"] == "Mara")
    assert not mara["alive"] or mara["life"] <= mara["max_life"] - 12


def test_narrators_own_amount_still_overrides(client, fake_llm, world):
    """The narrator may still ADJUST force when it names one (that is its adjudication)."""
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("apply_damage", target="Mara", amount=2),
                             content="The blow glances off her pauldron.")
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "attack", "target": "Mara", "amount": 12}]}).json()
    assert any("2 damage" in b["text"] for b in d["beats"] if b["kind"] == "system")


def test_plain_narrator_damage_keeps_its_default(client, fake_llm, world):
    """No pending attempt = no carry-over: the narrator's own spontaneous damage call
    still defaults as before."""
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("apply_damage", target="player"),
                             content="A stone falls from the arch.")
    d = client.post(f"/games/{gid}/action", json={"action": "I shelter by the wall."}).json()
    assert any("You take 3 damage" in b["text"] for b in d["beats"] if b["kind"] == "system")
