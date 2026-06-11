"""Multi-actor turn loop: tagged player actions, character tools (attack/give),
cascading reactions, directed-say routing, and the dynamic narrator (spawn/kill).
"""
from app import llm


def _world(chars):
    return {
        "title": "Brawl Hall", "setting": "a rowdy tavern", "tone": "rough",
        "narrator_persona": "Terse.", "opening_scenario": "The tavern roars.",
        "start_location": "tavern", "player_life": 20,
        "characters": chars,
        "quests": [{"title": "Survive", "description": "Don't die.", "objectives": ["Last the night"]}],
        "lore": [],
    }


def _char(name, life=10):
    return {"name": name, "persona": f"{name}, a tavern regular.", "life": life, "max_life": life}


def _new(client, chars):
    return client.post("/games", json=_world(chars)).json()["game_id"]


def _find(state, name):
    return next(c for c in state["characters"] if c["name"] == name)


def test_player_attacks_character_and_it_reacts(client, fake_llm):
    gid = _new(client, [_char("Mara", life=10)])
    fake_llm.character_replies = {"Mara": llm.LLMReply(content="\"You'll regret that!\"")}
    r = client.post(f"/games/{gid}/action",
                    json={"segments": [{"type": "attack", "target": "Mara", "amount": 4}]})
    d = r.json()
    assert _find(d["state"], "Mara")["life"] == 6                  # 10 - 4
    assert any(b["kind"] == "system" and "Mara" in b["text"] for b in d["beats"])
    assert any(b["speaker_name"] == "Mara" and b["kind"] == "dialogue" for b in d["beats"])  # reacted


def test_player_gives_item_to_character(client, fake_llm):
    gid = _new(client, [_char("Mara")])
    # player must hold the item first
    fake_llm.narrator = llm.LLMReply(content="A key glints on the floor.",
                                     tool_calls=[llm.ToolCall("add_item", {"name": "brass key"})])
    client.post(f"/games/{gid}/action", json={"action": "I grab the key."})
    fake_llm.narrator = llm.LLMReply(content="")                   # quiet narrator next turn
    fake_llm.character_replies = {"Mara": llm.LLMReply(content="\"...thanks.\"")}
    d = client.post(f"/games/{gid}/action",
                    json={"segments": [{"type": "give", "item": "brass key", "target": "Mara"}]}).json()
    assert d["state"]["player"]["inventory"] == []                 # gone from player
    assert any("brass key" in b["text"] and b["kind"] == "system" for b in d["beats"])
    assert any(b["speaker_name"] == "Mara" for b in d["beats"])    # recipient reacts


def test_character_produces_an_item_on_the_fly(client, fake_llm):
    """Owner spec: a character may give what the fiction says they have, even when
    their carrying list does not show it (a key from a pocket). Player stays strict."""
    gid = _new(client, [_char("Mara")])
    fake_llm.narrator = llm.LLMReply(content="Mara reaches into her coat.",
                                     tool_calls=[llm.ToolCall("cue_character", {"name": "Mara"})])
    fake_llm.character_replies = {"Mara": llm.LLMReply(
        content='[say]Take it. You will need it below.[/say]',
        tool_calls=[llm.ToolCall("give_item", {"item": "rusted signal key",
                                               "description": "an old maintenance key",
                                               "target": "player"})])}
    d = client.post(f"/games/{gid}/action", json={"action": "Is there any way past the hatch, Mara?"}).json()
    inv = d["state"]["player"]["inventory"]
    assert [i["name"] for i in inv] == ["rusted signal key"]       # materialized + handed over
    assert inv[0]["description"] == "an old maintenance key"
    assert any(b["kind"] == "system" and b["text"] == "Mara gives rusted signal key to you."
               for b in d["beats"])
    # ...but the PLAYER still cannot give what they do not hold
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "give", "item": "golden crown", "target": "Mara"}]}).json()
    assert any("don't have" in b["text"] for b in d["beats"] if b["kind"] == "system")


def test_character_attacks_player(client, fake_llm):
    gid = _new(client, [_char("Mara")])
    fake_llm.narrator = llm.LLMReply(content="Mara bristles.",
                                     tool_calls=[llm.ToolCall("cue_character", {"name": "Mara"})])
    fake_llm.character_replies = {"Mara": llm.LLMReply(
        content="\"Enough talk.\"", tool_calls=[llm.ToolCall("attack", {"target": "player", "amount": 5})])}
    d = client.post(f"/games/{gid}/action", json={"action": "I insult Mara."}).json()
    assert d["state"]["player"]["life"] == 15
    assert any("from Mara" in b["text"] for b in d["beats"] if b["kind"] == "system")


def test_character_attacks_character_cascades(client, fake_llm):
    gid = _new(client, [_char("Mara"), _char("Bron")])
    fake_llm.narrator = llm.LLMReply(content="Tension snaps.",
                                     tool_calls=[llm.ToolCall("cue_character", {"name": "Mara"})])
    fake_llm.character_replies = {
        "Mara": llm.LLMReply(content="\"This is for last week!\"",
                             tool_calls=[llm.ToolCall("attack", {"target": "Bron", "amount": 3})]),
        "Bron": llm.LLMReply(content="\"Have you lost your mind?!\""),
    }
    d = client.post(f"/games/{gid}/action", json={"action": "I watch them."}).json()
    assert _find(d["state"], "Bron")["life"] == 7                  # Mara hit Bron
    # Bron reacted via the cascade even though the narrator never cued him
    assert any(b["speaker_name"] == "Bron" and b["kind"] == "dialogue" for b in d["beats"])


def test_directed_say_routes_to_character_without_narrator_cue(client, fake_llm):
    """The structural fix: a directed 'say to X' routes to X even if the narrator never cues."""
    gid = _new(client, [_char("Jacker"), _char("Mara")])
    fake_llm.narrator = llm.LLMReply(content="The bar hums.")      # narrator cues NO ONE
    fake_llm.character_replies = {"Jacker": llm.LLMReply(content="\"What'll it be?\"")}
    d = client.post(f"/games/{gid}/action",
                    json={"segments": [{"type": "say", "text": "Hey Jacker", "target": "Jacker"}]}).json()
    speakers = {b["speaker_name"] for b in d["beats"] if b["kind"] == "dialogue"}
    assert "Jacker" in speakers
    assert "Mara" not in speakers                                  # only the addressed one


def test_spawn_character_appears_and_speaks(client, fake_llm):
    gid = _new(client, [_char("Mara")])
    fake_llm.narrator = llm.LLMReply(
        content="The door bangs open.",
        tool_calls=[llm.ToolCall("spawn_character",
                                 {"name": "Stranger", "persona": "a hooded mercenary"})])
    fake_llm.character_replies = {"Stranger": llm.LLMReply(content="\"I'm looking for someone.\"")}
    d = client.post(f"/games/{gid}/action", json={"action": "I wait."}).json()
    names = {c["name"] for c in d["state"]["characters"]}
    assert "Stranger" in names
    assert any(b["speaker_name"] == "Stranger" for b in d["beats"])  # the newcomer speaks


def test_kill_character_removes_them(client, fake_llm):
    gid = _new(client, [_char("Mara")])
    fake_llm.narrator = llm.LLMReply(content="A blade flashes from the dark.",
                                     tool_calls=[llm.ToolCall("kill_character", {"name": "Mara"})])
    d = client.post(f"/games/{gid}/action", json={"action": "I duck."}).json()
    mara = _find(d["state"], "Mara")
    assert mara["alive"] is False and mara["present"] is False


def test_cascade_is_bounded(client, fake_llm, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "TURN_MAX_ACTOR_STEPS", 1)
    gid = _new(client, [_char("Mara"), _char("Bron")])
    fake_llm.narrator = llm.LLMReply(content="It kicks off.",
                                     tool_calls=[llm.ToolCall("cue_character", {"name": "Mara"})])
    fake_llm.character_replies = {
        "Mara": llm.LLMReply(content="\"Take this!\"",
                             tool_calls=[llm.ToolCall("attack", {"target": "Bron", "amount": 2})]),
        "Bron": llm.LLMReply(content="\"Ow!\""),
    }
    d = client.post(f"/games/{gid}/action", json={"action": "I step back."}).json()
    # only 1 actor step allowed: Mara acts, Bron is queued but not processed
    dialogues = [b for b in d["beats"] if b["kind"] == "dialogue"]
    assert len(dialogues) == 1 and dialogues[0]["speaker_name"] == "Mara"


def test_turn_voices_dial_limits_cued_speakers(client, fake_llm):
    """Per-game turn_voices=1: the narrator cues three characters, exactly ONE speaks
    (the env default would let two through)."""
    gid = _new(client, [_char("Mara"), _char("Bron"), _char("Tessa")])
    assert client.patch(f"/games/{gid}/settings", json={"turn_voices": 1}).status_code == 200
    fake_llm.narrator = llm.LLMReply(content="All three turn toward you.",
                                     tool_calls=[llm.ToolCall("cue_character", {"name": "Mara"}),
                                                 llm.ToolCall("cue_character", {"name": "Bron"}),
                                                 llm.ToolCall("cue_character", {"name": "Tessa"})])
    fake_llm.character_replies = {
        "Mara": llm.LLMReply(content="\"I'll do the talking.\""),
        "Bron": llm.LLMReply(content="\"And me.\""),
        "Tessa": llm.LLMReply(content="\"Me too.\""),
    }
    d = client.post(f"/games/{gid}/action", json={"action": "I address the room."}).json()
    speakers = [b["speaker_name"] for b in d["beats"] if b["kind"] == "dialogue"]
    assert speakers == ["Mara"]                                    # one voice: the first cued


def test_turn_acts_dial_lets_a_character_act_twice(client, fake_llm):
    """Per-game turn_acts=2: a character pulled BACK into the cascade speaks again;
    flipping back to the default (0 -> env cap 1) silences the second act."""
    gid = _new(client, [_char("Mara"), _char("Bron")])

    def script():
        fake_llm.narrator = llm.LLMReply(content="Steel scrapes.",
                                         tool_calls=[llm.ToolCall("cue_character", {"name": "Mara"})])
        fake_llm.character_replies = {
            # Mara strikes Bron; Bron strikes back, putting Mara BACK in the queue
            "Mara": [llm.LLMReply(content="\"Take this!\"",
                                  tool_calls=[llm.ToolCall("attack", {"target": "Bron", "amount": 2})]),
                     llm.LLMReply(content="\"And stay down!\"")],
            "Bron": llm.LLMReply(content="\"Right back at you!\"",
                                 tool_calls=[llm.ToolCall("attack", {"target": "Mara", "amount": 2})]),
        }

    assert client.patch(f"/games/{gid}/settings", json={"turn_acts": 2}).status_code == 200
    script()
    d = client.post(f"/games/{gid}/action", json={"action": "I watch them."}).json()
    mara = [b for b in d["beats"] if b["speaker_name"] == "Mara" and b["kind"] == "dialogue"]
    assert len(mara) == 2 and "stay down" in mara[1]["text"]       # acted twice

    client.patch(f"/games/{gid}/settings", json={"turn_acts": 0})  # back to the default (1)
    script()
    d = client.post(f"/games/{gid}/action", json={"action": "I watch them."}).json()
    mara = [b for b in d["beats"] if b["speaker_name"] == "Mara" and b["kind"] == "dialogue"]
    assert len(mara) == 1                                          # re-entry blocked again


def test_character_say_do_tags_split_into_beats(client, fake_llm):
    gid = _new(client, [_char("Mara")])
    fake_llm.narrator = llm.LLMReply(content="Mara tenses.",
                                     tool_calls=[llm.ToolCall("cue_character", {"name": "Mara"})])
    fake_llm.character_replies = {"Mara": llm.LLMReply(
        content='[say]"Stay back."[/say][do]She lifts her blade between you.[/do]')}
    beats = client.post(f"/games/{gid}/action", json={"action": "I step toward Mara."}).json()["beats"]
    say = next(b for b in beats if b["speaker_name"] == "Mara" and b["kind"] == "dialogue")
    do = next(b for b in beats if b["speaker_name"] == "Mara" and b["kind"] == "action")
    assert "Stay back" in say["text"] and "[say]" not in say["text"]   # speech beat, tags stripped
    assert "lifts her blade" in do["text"] and "[do]" not in do["text"]  # action beat
    assert "*" not in do["text"]                                        # no asterisks


def test_character_output_hygiene_strips_live_artifacts(client, fake_llm):
    """Exact artifacts observed live against the real model: tag debris '*]' trailing a
    [do] segment, and a pseudo tool call leaked as text. Both must never reach a beat."""
    gid = _new(client, [_char("Mara")])
    fake_llm.narrator = llm.LLMReply(content="Mara reacts.",
                                     tool_calls=[llm.ToolCall("cue_character", {"name": "Mara"})])
    fake_llm.character_replies = {"Mara": llm.LLMReply(content=(
        '[say]"You\'ll regret that strike!"[/say]'
        '[do]She lunges forward, attempting to strike you.[attack{amount:10,target: "player"}][/do]'
        '[do]She grips the hilt of her blade, her gaze piercing.*][/do]'))}
    beats = client.post(f"/games/{gid}/action", json={"action": "I strike Mara."}).json()["beats"]
    mara = [b for b in beats if b["speaker_name"] == "Mara"]
    assert any("regret that strike" in b["text"] for b in mara)
    for b in mara:
        assert "attack{" not in b["text"] and "*]" not in b["text"]
        assert not b["text"].endswith("*") and not b["text"].endswith("]")


def test_untagged_character_output_is_dialogue(client, fake_llm):
    gid = _new(client, [_char("Mara")])
    fake_llm.narrator = llm.LLMReply(content="Mara nods.",
                                     tool_calls=[llm.ToolCall("cue_character", {"name": "Mara"})])
    fake_llm.character_replies = {"Mara": llm.LLMReply(content="Hello there, traveler.")}
    beats = client.post(f"/games/{gid}/action", json={"action": "I greet Mara."}).json()["beats"]
    # tolerant: untagged output becomes a single dialogue beat
    assert any(b["speaker_name"] == "Mara" and b["kind"] == "dialogue"
               and "Hello there" in b["text"] for b in beats)


def test_multi_segment_turn_composes(client, fake_llm):
    gid = _new(client, [_char("Mara")])
    fake_llm.narrator = llm.LLMReply(content="The room watches.")
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "do", "text": "walk to the bar"},
        {"type": "say", "text": "quiet night"},
        {"type": "do", "text": "lean on the counter"},
    ]}).json()
    action_beat = next(b for b in d["beats"] if b["kind"] == "action")
    assert "walk to the bar" in action_beat["text"]
    assert "quiet night" in action_beat["text"]
