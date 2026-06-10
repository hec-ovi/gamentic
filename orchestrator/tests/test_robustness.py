"""Prose hygiene + reply resilience (owner-reported live issues):
- tool-call syntax occasionally leaks INTO narration/dialogue text -> scrubbed
- a character spoken to occasionally returns nothing -> one retry before staying silent
- character replies were clipped -> the budget is roomy and the prompt invites real talk
"""
from app import llm
from app.config import settings


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def _beats(d, kind):
    return [b for b in d["beats"] if b["kind"] == kind]


# ---------- tool-call leakage scrubbed from player-facing prose ----------

def test_narration_drops_leaked_tool_call_lines(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(content='The docks reek of brine and old rope.\n'
                                     'move_location("the docks")\n'
                                     '{"name": "add_item", "arguments": {"name": "rope"}}\n'
                                     'A gull screams overhead.')
    d = client.post(f"/games/{gid}/action", json={"action": "I walk to the docks."}).json()
    text = _beats(d, "narration")[0]["text"]
    assert "The docks reek" in text and "A gull screams" in text
    assert "move_location" not in text and "add_item" not in text and "{" not in text


def test_narration_drops_fenced_code_blocks(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(content='Rain hammers the canvas.\n```json\n'
                                     '{"tool": "apply_damage"}\n```\nYou shiver.')
    d = client.post(f"/games/{gid}/action", json={"action": "I wait."}).json()
    text = _beats(d, "narration")[0]["text"]
    assert "Rain hammers" in text and "You shiver" in text
    assert "apply_damage" not in text and "```" not in text


def test_fully_junk_narration_falls_back_to_resolve_pass(client, fake_llm, world):
    """If scrubbing leaves NOTHING, the turn is not dead air: the resolve pass voices it."""
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("add_item", name="rope"), content='add_item({"name": "rope"})')
    d = client.post(f"/games/{gid}/action", json={"action": "I grab the rope."}).json()
    narrations = _beats(d, "narration")
    assert narrations and narrations[0]["text"] == "The moment settles around you."


def test_character_dialogue_scrubs_tool_call_lines(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara turns.")
    fake_llm.character_replies = {
        "Mara": llm.LLMReply(content='[say]"Stay sharp."\nattack("player", 5)[/say]')}
    d = client.post(f"/games/{gid}/action", json={"action": "I greet Mara."}).json()
    line = _beats(d, "dialogue")[0]["text"]
    assert "Stay sharp" in line and "attack(" not in line


# ---------- empty character reply: one retry ----------

def test_silent_character_is_retried_once(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara looks up.")
    fake_llm.character_replies = {
        "Mara": [llm.LLMReply(content=""), llm.LLMReply(content='[say]"Yes?"[/say]')]}
    d = client.post(f"/games/{gid}/action", json={"action": "Mara, did you hear that?"}).json()
    assert any(b["text"] == "Yes?" for b in _beats(d, "dialogue"))   # wrapping quotes stripped
    assert len(fake_llm.character_calls()) == 2          # first empty, then the retry


def test_silent_character_gives_up_after_one_retry(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara says nothing.")
    fake_llm.character_replies = {"Mara": llm.LLMReply(content="")}
    d = client.post(f"/games/{gid}/action", json={"action": "Mara?"}).json()
    assert not _beats(d, "dialogue")
    assert len(fake_llm.character_calls()) == 2          # retried once, then accepted silence


# ---------- speech mis-tagged as action reclassifies by shape ----------

def test_quoted_speech_inside_a_do_tag_becomes_voiced_dialogue(client, fake_llm, world):
    """Live (Serah's whisper): [do][sigh] [whisper] "Do not waste your breath..."[/do]
    rendered as an italic action with visible tags and was never voiced."""
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara exhales.")
    fake_llm.character_replies = {"Mara": llm.LLMReply(
        content='[do][sigh] [whisper] "Do not waste your breath on my temperament."[/do]')}
    d = client.post(f"/games/{gid}/action", json={"action": "Are you angry with me?"}).json()
    line = next(b for b in d["beats"] if b["kind"] == "dialogue")
    assert line["text"] == "Do not waste your breath on my temperament."
    assert line["emotion"] == "sigh"                       # first tag wins as the tone
    assert "[" not in line["text"]
    # a GENUINE action with a stray tag keeps its kind, tags scrubbed, no tone
    fake_llm.character_replies = {"Mara": llm.LLMReply(
        content='[do][sigh] She turns away to face the wall.[/do]')}
    d = client.post(f"/games/{gid}/action", json={"action": "I wait."}).json()
    act = next(b for b in d["beats"] if b["kind"] == "action" and b["speaker"] != "player")
    assert act["text"] == "She turns away to face the wall." and act["emotion"] == ""


# ---------- parenthetical stage directions split out of speech ----------

def test_parenthetical_stage_directions_become_action_beats(client, fake_llm, world):
    """Live: '(She looks at the stone...) "A whetstone..."' rendered (and would be
    SPOKEN) as one speech bubble; the parenthetical is an action, not words."""
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara turns it over.")
    fake_llm.character_replies = {"Mara": llm.LLMReply(
        content='[say](She tightens her fingers around the stone.) "A whetstone. A way to keep the edge."[/say]')}
    d = client.post(f"/games/{gid}/action", json={"action": "I hand it over."}).json()
    act = next(b for b in d["beats"] if b["kind"] == "action" and b["speaker"] != "player")
    assert act["text"] == "She tightens her fingers around the stone."
    line = next(b for b in d["beats"] if b["kind"] == "dialogue")
    assert line["text"] == "A whetstone. A way to keep the edge."
    assert "(" not in line["text"]


# ---------- emotion tags: extracted for the voice, never shown ----------

def test_emotion_tag_becomes_the_beats_tone(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara whirls.")
    fake_llm.character_replies = {
        "Mara": llm.LLMReply(content='[say][angry] You dare come back here?[/say]')}
    d = client.post(f"/games/{gid}/action", json={"action": "I step out of the shadows."}).json()
    line = next(b for b in d["beats"] if b["kind"] == "dialogue")
    assert line["emotion"] == "angry"
    assert line["text"] == "You dare come back here?"          # tag never shows
    # tag inside the quotes works too
    fake_llm.character_replies = {
        "Mara": llm.LLMReply(content='[say]"[whisper] Not here. Follow me."[/say]')}
    d = client.post(f"/games/{gid}/action", json={"action": "I lean in."}).json()
    line = next(b for b in d["beats"] if b["kind"] == "dialogue")
    assert line["emotion"] == "whisper" and line["text"] == "Not here. Follow me."
    # persisted: the story log serves it for replays
    beats = client.get(f"/games/{gid}/beats").json()["beats"]
    assert any(b.get("emotion") == "angry" for b in beats)


def test_private_replies_default_to_a_whispered_tone(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.character_replies = {"Mara": llm.LLMReply(content='[say]Meet me at the altar.[/say]')}
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "text": "Can we talk?", "target": "Mara"}]}).json()
    line = next(b for b in d["beats"] if b["kind"] == "dialogue")
    assert line["emotion"] == "whisper"                        # private = whispered by nature


def test_unknown_or_stray_tags_are_scrubbed_not_voiced(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara mutters.")
    fake_llm.character_replies = {
        "Mara": llm.LLMReply(content='[say][brooding] Fine. [pause] Take it.[/say]')}
    d = client.post(f"/games/{gid}/action", json={"action": "I hold out the coin."}).json()
    line = next(b for b in d["beats"] if b["kind"] == "dialogue")
    assert line["emotion"] == ""                               # 'brooding' is not a tone we know
    assert line["text"] == "Fine. Take it."                    # all stray tags scrubbed


# ---------- speech to the absent bounces deterministically ----------

def test_directed_say_to_an_absent_character_bounces(client, fake_llm, world):
    """Live: the narrator wrote an 'elsewhere' character into the scene because a missed
    say failed silently. Now it bounces like attack/give, and the narrator is told."""
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("move_location", location="the flooded vault"),
                             content="You wade onward; Mara stays at her post.")
    client.post(f"/games/{gid}/action", json={"action": "I press on alone."})
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "say", "text": "Mara, do you see this?", "target": "Mara"}]}).json()
    assert any(b["kind"] == "system" and b["text"] == "Mara is not here."
               for b in d["beats"])
    assert not any(b["kind"] == "dialogue" for b in d["beats"])     # she cannot answer
    user = fake_llm.narrator_calls()[-1]["messages"][1]["content"]
    assert "(failed: Mara is not here.)" in user                    # the narrator knows
    assert "cannot speak, act, be addressed" in fake_llm.narrator_calls()[-1]["system"]


# ---------- characters may actually talk ----------

def test_character_reply_budget_is_roomy(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara leans in.")
    client.post(f"/games/{gid}/action", json={"action": "Tell me everything, Mara."})
    call = fake_llm.character_calls()[-1]
    assert call["max_tokens"] == settings.CHARACTER_MAX_TOKENS >= 400
    assert "Keep it short" not in call["system"]         # the old clamp is gone
