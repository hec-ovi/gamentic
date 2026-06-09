"""Private / whisper channel: a 1:1 exchange the other characters never see."""
from app import llm


WORLD = {
    "title": "Whisper Hall", "setting": "a hall", "tone": "tense",
    "narrator_persona": "Terse.", "opening_scenario": "Two figures wait.",
    "start_location": "hall", "player_life": 20,
    "characters": [{"name": "Mara", "persona": "a conspirator", "description": "A sharp-eyed woman."},
                   {"name": "Bron", "persona": "a guard", "description": "A bored guard."}],
    "quests": [{"title": "x", "description": "", "objectives": ["x"]}], "lore": [],
}


def _user(call):
    return call["messages"][1]["content"]


def test_whisper_is_private_to_the_target(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    fake_llm.character_replies = {
        "Mara": llm.LLMReply(content="\"There's a tunnel behind the altar,\" she breathes."),
        "Bron": llm.LLMReply(content="\"Move along.\""),
    }
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "text": "What's the way out of here?", "target": "Mara"}]}).json()

    beats = d["beats"]
    # the whisper and Mara's reply are private to Mara
    pw = next(b for b in beats if b["speaker"] == "player")
    assert pw["private_with"]                              # the player's whisper is private
    mara_reply = next(b for b in beats if b["speaker_name"] == "Mara")
    assert mara_reply["private_with"] == pw["private_with"]
    # Mara saw the whisper in her own context
    mara_call = next(c for c in fake_llm.character_calls() if c["system"].startswith("You are Mara"))
    assert "way out of here" in _user(mara_call)

    # later, a PUBLIC turn cues Bron: he must NOT have seen the private exchange
    fake_llm.narrator = llm.LLMReply(content="The hall is still.",
                                     tool_calls=[llm.ToolCall("cue_character", {"name": "Bron"})])
    client.post(f"/games/{gid}/action", json={"action": "I glance at Bron."})
    bron_call = [c for c in fake_llm.character_calls() if c["system"].startswith("You are Bron")][-1]
    ctx = _user(bron_call)
    assert "way out of here" not in ctx                   # never saw the whisper
    assert "tunnel behind the altar" not in ctx           # nor Mara's private reply


def test_whisper_only_turn_skips_narrator(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    fake_llm.narrator = llm.LLMReply(content="PUBLIC NARRATION SHOULD NOT APPEAR")
    fake_llm.character_replies = {"Mara": llm.LLMReply(content="\"Quietly, then.\"")}
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "text": "Meet me later.", "target": "Mara"}]}).json()
    # a whisper-only turn is a private aside: no public narration beat
    assert not any(b["kind"] == "narration" for b in d["beats"])
    assert any(b["speaker_name"] == "Mara" and b["private_with"] for b in d["beats"])
