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


def test_private_modal_stacks_say_and_do_with_one_reply(client, fake_llm):
    """The private modal composes say AND do at one character; the stack lands as one
    exchange (all player lines, then ONE reply), every beat private to that character."""
    gid = client.post("/games", json=WORLD).json()["game_id"]
    fake_llm.character_replies = {"Mara": llm.LLMReply(content='[say]"Understood."[/say]')}
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "text": "They are watching us.", "target": "Mara"},
        {"type": "whisper", "mode": "do", "text": "slip her the brass key under the table",
         "target": "Mara"},
    ]}).json()
    beats = d["beats"]
    player_beats = [b for b in beats if b["speaker"] == "player"]
    assert len(player_beats) == 2
    assert 'you tell Mara privately: "They are watching us."' == player_beats[0]["text"]
    assert "only Mara notices" in player_beats[1]["text"]            # the discreet do
    assert all(b["private_with"] for b in beats)                     # everything stays private
    # ONE exchange -> ONE reply, after both player lines
    assert len([b for b in beats if b["speaker_name"] == "Mara"]) == 1
    assert beats[-1]["speaker_name"] == "Mara"
    # Mara's context saw both private lines
    mara_call = next(c for c in fake_llm.character_calls() if c["system"].startswith("You are Mara"))
    assert "watching us" in _user(mara_call) and "brass key" in _user(mara_call)


def test_whisper_only_turn_skips_narrator(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    fake_llm.narrator = llm.LLMReply(content="PUBLIC NARRATION SHOULD NOT APPEAR")
    fake_llm.character_replies = {"Mara": llm.LLMReply(content="\"Quietly, then.\"")}
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "text": "Meet me later.", "target": "Mara"}]}).json()
    # a whisper-only turn is a private aside: no public narration beat
    assert not any(b["kind"] == "narration" for b in d["beats"])
    assert any(b["speaker_name"] == "Mara" and b["private_with"] for b in d["beats"])
