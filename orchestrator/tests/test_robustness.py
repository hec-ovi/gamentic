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
    assert any(b["text"] == '"Yes?"' for b in _beats(d, "dialogue"))
    assert len(fake_llm.character_calls()) == 2          # first empty, then the retry


def test_silent_character_gives_up_after_one_retry(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara says nothing.")
    fake_llm.character_replies = {"Mara": llm.LLMReply(content="")}
    d = client.post(f"/games/{gid}/action", json={"action": "Mara?"}).json()
    assert not _beats(d, "dialogue")
    assert len(fake_llm.character_calls()) == 2          # retried once, then accepted silence


# ---------- characters may actually talk ----------

def test_character_reply_budget_is_roomy(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara leans in.")
    client.post(f"/games/{gid}/action", json={"action": "Tell me everything, Mara."})
    call = fake_llm.character_calls()[-1]
    assert call["max_tokens"] == settings.CHARACTER_MAX_TOKENS >= 400
    assert "Keep it short" not in call["system"]         # the old clamp is gone
