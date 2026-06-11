"""Fixes for the issues the live 26B-MoE runs surfaced (all evidence-backed):
1. the model prints the worked example's reasoning line as prose ('(think: ...)'),
2. it fakes cast dialogue inside narration as screenplay lines ('Vane: "..."'),
3. it leaks a hallucinated call-syntax line as prose (a name no tool filter knows),
4. invalid tool calls with recoverable intents were silently dropped,
5. an A/B knob to enable hybrid-model thinking on the narrator call only."""
from app import llm
from app.config import settings
from app.engine import parsing


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


# ---- 1. think-leak scrub (narration-only path) ----

def test_leading_think_span_lifts_away():
    e, t = parsing._scrub_narration(
        "(think: the player is pressing Vane, escalate) The alley narrows.")
    assert e == ""
    assert t == "The alley narrows."


def test_emotion_extraction_survives_a_leading_think_span():
    e, t = parsing._scrub_narration("(think: he is scared) [whisper] The dark stirs.")
    assert e == "whisper"
    assert t == "The dark stirs."


def test_mid_prose_think_line_is_stripped():
    raw = ("The street hums under the rain.\n\n"
           '(think: time to bring in the courier, she has the "chip")\n'
           "A courier rounds the corner.")
    _, t = parsing._scrub_narration(raw)
    assert "(think" not in t
    assert t == "The street hums under the rain.\n\nA courier rounds the corner."


def test_unclosed_think_paren_drops_the_whole_line():
    _, t = parsing._scrub_narration("(think: he is scared and the\nThe dark stirs.")
    assert t == "The dark stirs."


def test_legitimate_parenthetical_prose_is_untouched():
    raw = "She laughs (not kindly) and turns away."
    _, t = parsing._scrub_narration(raw)
    assert t == raw


# ---- 2. impersonation stop-sequences (plumbing: FakeLLM ignores stop) ----

def test_narrator_call_receives_present_character_stop_list(client, fake_llm, world):
    world["characters"] = [
        {"name": "Vane Korr", "persona": "A fixer with cold eyes."},
        {"name": "Mara", "persona": "A wary scout."},
    ]
    gid = client.post("/games", json=world).json()["game_id"]
    client.post(f"/games/{gid}/action", json={"action": "I scan the room."})
    nar = fake_llm.narrator_calls()[0]
    assert nar["stop"] == ["\nVane Korr:", "\nVane:", "\nMara:"]
    # every non-narrator call (interpreter and friends) runs unconstrained
    others = [c for c in fake_llm.calls if "cue_character" not in c["names"]]
    assert all(c["stop"] is None for c in others)


def test_character_calls_receive_no_stop(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "target": "Mara", "text": "stay quiet"}]})
    chars = fake_llm.character_calls()
    assert chars and all(c["stop"] is None for c in chars)


def test_stop_list_dedupes_first_names_and_caps_at_8(client, fake_llm, world):
    world["characters"] = [
        {"name": "Vane Korr", "persona": "p"},
        {"name": "Vane Solo", "persona": "p"},   # shares the first word: deduped
        {"name": "Echo Nine", "persona": "p"},
        {"name": "Lex Marrow", "persona": "p"},
        {"name": "Juno Hale", "persona": "p"},
    ]
    gid = client.post("/games", json=world).json()["game_id"]
    client.post(f"/games/{gid}/action", json={"action": "I wait."})
    stop = fake_llm.narrator_calls()[0]["stop"]
    assert len(stop) == 8
    assert stop.count("\nVane:") == 1
    assert "\nJuno Hale:" in stop and "\nJuno:" not in stop


# ---- 3. generic code-line scrub (clean_prose) ----

def test_hallucinated_call_line_is_scrubbed():
    raw = ("The standoff tightens.\n"
           'set_distance(distance="close") # Implicit in the tense standoff.')
    assert parsing.clean_prose(raw) == "The standoff tightens."


def test_prose_with_mid_sentence_parens_survives():
    raw = "He lowered the gun (he knew it) and stepped back."
    assert parsing.clean_prose(raw) == raw


# ---- 4. invalid-feedback loop (intra-reply retry + next-turn note) ----

def test_disposition_before_spawn_applies_via_retry(client, fake_llm, world):
    """Live: set_disposition fired BEFORE its spawn_character in the same reply."""
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(
        T("set_disposition", name="Korr", disposition="hostile"),
        T("spawn_character", name="Korr", persona="An enforcer.", sex="male"),
        content="Korr steps out of the shadows.")
    d = client.post(f"/games/{gid}/action", json={"action": "I knock."}).json()
    korr = next(c for c in d["state"]["characters"] if c["name"] == "Korr")
    assert korr["disposition"] == "hostile"
    # the retry succeeded, so the next narrator message carries no failed-call note
    fake_llm.narrator = _nar(content="The hall waits.")
    client.post(f"/games/{gid}/action", json={"action": "I step inside."})
    assert "DID NOT APPLY" not in fake_llm.narrator_calls()[1]["messages"][1]["content"]


def test_still_invalid_reason_feeds_next_narrator_message_once(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(
        T("set_disposition", name="Corporate Security Force", disposition="hostile"),
        content="The lobby goes quiet.")
    client.post(f"/games/{gid}/action", json={"action": "I push past the desk."})
    fake_llm.narrator = _nar(content="The elevator hums.")
    client.post(f"/games/{gid}/action", json={"action": "I take the elevator."})
    second = fake_llm.narrator_calls()[1]["messages"][1]["content"]
    assert "YOUR CALLS THAT DID NOT APPLY LAST TURN (fix the call, not the story):" in second
    assert "set_disposition: no character 'Corporate Security Force'" in second
    # the block rides the USER message, right before the player action
    assert second.index("DID NOT APPLY") < second.index("PLAYER ACTION:")
    client.post(f"/games/{gid}/action", json={"action": "I step out."})
    third = fake_llm.narrator_calls()[2]["messages"][1]["content"]
    assert "DID NOT APPLY" not in third


def test_no_block_when_nothing_failed(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    client.post(f"/games/{gid}/action", json={"action": "I study the carvings."})
    client.post(f"/games/{gid}/action", json={"action": "I wait."})
    for call in fake_llm.narrator_calls():
        assert "DID NOT APPLY" not in call["messages"][1]["content"]


def test_character_invalid_calls_never_produce_the_block(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.character = llm.LLMReply(
        content="[say]Take it up with the ghost.[/say]",
        tool_calls=[T("give_item", item="dagger", target="The Ghost")])  # unknown target: invalid
    client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "say", "text": "hand it over", "target": "Mara"}]})
    fake_llm.narrator = _nar(content="The crypt settles.")
    client.post(f"/games/{gid}/action", json={"action": "I wait."})
    last = fake_llm.narrator_calls()[-1]["messages"][1]["content"]
    assert "DID NOT APPLY" not in last


# ---- 5. narrator thinking flag ----

class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _capture_post(captured, data=None):
    data = data or {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                    "usage": {}}

    def post(url, json=None, timeout=None):
        captured.append(json)
        return _Resp(data)
    return post


def test_thinking_true_adds_chat_template_kwargs(monkeypatch):
    captured = []
    monkeypatch.setattr(llm.httpx, "post", _capture_post(captured))
    llm.chat([{"role": "user", "content": "hi"}], thinking=True)
    assert captured[0]["chat_template_kwargs"] == {"enable_thinking": True}


def test_thinking_off_sends_no_kwargs(monkeypatch):
    captured = []
    monkeypatch.setattr(llm.httpx, "post", _capture_post(captured))
    llm.chat([{"role": "user", "content": "hi"}])
    llm.chat([{"role": "user", "content": "hi"}], thinking=False)
    assert all("chat_template_kwargs" not in p for p in captured)


def test_reasoning_content_in_reply_is_ignored(monkeypatch):
    data = {"choices": [{"message": {"content": "The street hums.",
                                     "reasoning_content": "I should escalate now."},
                         "finish_reason": "stop"}], "usage": {}}
    monkeypatch.setattr(llm.httpx, "post", _capture_post([], data=data))
    reply = llm.chat([{"role": "user", "content": "hi"}], thinking=True)
    assert reply.content == "The street hums."


def test_narrator_call_passes_the_flag_and_others_do_not(client, fake_llm, world, monkeypatch):
    monkeypatch.setattr(settings, "NARRATOR_THINKING", True)
    gid = client.post("/games", json=world).json()["game_id"]
    client.post(f"/games/{gid}/action", json={"action": "I wait."})
    assert fake_llm.narrator_calls()[0]["thinking"] is True
    others = [c for c in fake_llm.calls if "cue_character" not in c["names"]]
    assert all(not c["thinking"] for c in others)
