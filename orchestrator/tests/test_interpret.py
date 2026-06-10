"""The agentic input interpreter: freeform typed text is parsed into structured segments
(one LLM call, skill loaded only for that call) so it gets the same directed routing and
adjudication as the composer buttons. Any failure falls back to the raw text."""
from app import llm


WORLD = {
    "title": "Interpretland", "setting": "a town", "tone": "calm",
    "narrator_persona": "Plain.", "opening_scenario": "A quiet square.",
    "start_location": "square", "player_life": 20,
    "characters": [{"name": "Mara", "persona": "a scout"},
                   {"name": "Bron", "persona": "a guard"}],
    "quests": [{"title": "x", "objectives": ["x"]}], "lore": [],
}


def _interp(segments):
    return llm.LLMReply(content="", tool_calls=[llm.ToolCall("submit_segments", {"segments": segments})])


def test_typed_text_is_structured_and_gets_routing_and_adjudication(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    # give the player the key first
    fake_llm.narrator = llm.LLMReply(content="...", tool_calls=[
        llm.ToolCall("add_item", {"name": "brass key"})])
    client.post(f"/games/{gid}/action", json={"action": "I search my pockets."})

    fake_llm.narrator = llm.LLMReply(content="The square holds its breath.")
    fake_llm.interpret = _interp([
        {"type": "give", "item": "brass key", "target": "Mara"},
        {"type": "say", "text": "Keep it hidden.", "target": "Mara"},
        {"type": "do", "text": "watch the door"},
    ])
    fake_llm.character_replies = {"Mara": llm.LLMReply(content='[say]"Understood."[/say]')}
    d = client.post(f"/games/{gid}/action", json={
        "action": "I toss Mara the brass key, tell her to keep it hidden, and watch the door"}).json()

    # the interpreter grounded the call in who is present and what the player carries
    icall = [c for c in fake_llm.calls if "submit_segments" in c["names"]][-1]
    assert "Mara" in icall["messages"][1]["content"]
    assert "brass key" in icall["messages"][1]["content"]

    # the give became a real adjudicated attempt (PLAYER ATTEMPTS block in the narrator call)
    ncall = [c for c in fake_llm.calls if "cue_character" in c["names"]][-1]
    assert "give brass key to Mara" in ncall["messages"][1]["content"]
    # default-accept applied it: the key actually moved
    assert any("give brass key" in (b["text"] or "").lower() or "brass key to mara" in (b["text"] or "").lower()
               for b in d["beats"] if b["speaker"] == "system")
    st = client.get(f"/games/{gid}/state").json()
    assert all(i["name"] != "brass key" for i in st["player"]["inventory"])
    mara = next(c for c in st["characters"] if c["name"] == "Mara")
    assert any(i["name"] == "brass key" for i in mara["inventory"])
    # the directed say routed Mara to reply
    assert any(b["speaker_name"] == "Mara" for b in d["beats"])


def test_interpreted_whisper_stays_private(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    fake_llm.interpret = _interp([
        {"type": "whisper", "text": "Meet me at the well at dusk.", "target": "Mara"}])
    fake_llm.character_replies = {"Mara": llm.LLMReply(content='[say]"At dusk."[/say]')}
    d = client.post(f"/games/{gid}/action", json={"action": "I lean to Mara: meet me at dusk"}).json()
    assert all(b["private_with"] for b in d["beats"])      # the whole exchange is private


def test_interpreter_failure_falls_back_to_raw_text(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    fake_llm.interpret = llm.LLMReply(content="I cannot parse this.", tool_calls=[])  # no tool call
    d = client.post(f"/games/{gid}/action", json={"action": "I scan the rooftops."}).json()
    player = next(b for b in d["beats"] if b["speaker"] == "player")
    assert player["text"] == "I scan the rooftops."        # raw text path, nothing lost


def test_interpreter_drops_invalid_segments_keeps_valid(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    fake_llm.interpret = _interp([
        {"type": "teleport", "text": "zap"},               # unknown type: dropped
        {"type": "attack"},                                # attack without target: dropped
        {"type": "do", "text": "kick the bucket over"},    # valid
    ])
    d = client.post(f"/games/{gid}/action", json={"action": "zap and kick"}).json()
    player = next(b for b in d["beats"] if b["speaker"] == "player")
    assert player["text"] == "zap and kick"              # the echo is THEIR words
    user = fake_llm.narrator_calls()[-1]["messages"][1]["content"]
    assert "kick the bucket over" in user                # the narrator gets the kept segment


def test_structured_segments_skip_the_interpreter(client, fake_llm):
    """Composer-built segments are already structured; no interpreter call is spent."""
    gid = client.post("/games", json=WORLD).json()["game_id"]
    client.post(f"/games/{gid}/action", json={"segments": [{"type": "do", "text": "wait"}]})
    assert not any("submit_segments" in c["names"] for c in fake_llm.calls)
