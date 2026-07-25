"""What the app sends about HOW to generate: nothing about sampling, one guard on length.

Owner call 2026-07-25, after a degenerate loop ran 61,805 tokens over 42 minutes from a
938-token prompt and only stopped at the context wall:

  - sampling is the server's ("leave all default", "i dont like toy with those values").
    Nine per-call temperatures guessed in app code are gone. A flag turns sending back
    on for an experiment, with the values in .env.
  - length gets ONE guard, high enough that no real answer meets it, so a loop ends but
    nothing is truncated. Not a length dial: prompts still shape how much to write.
"""
from app import llm
from app.config import Settings, settings


class _Resp:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}


def _capture(monkeypatch):
    sent = {}
    monkeypatch.setattr(settings, "LLM_STREAM", False)

    def _post(url, **kw):
        sent.update(kw["json"])
        return _Resp()
    monkeypatch.setattr(llm.httpx, "post", _post)
    return sent


# ---------- sampling: off, and off means absent ----------

def test_no_sampling_field_is_sent_by_default(monkeypatch):
    sent = _capture(monkeypatch)
    llm.chat([{"role": "user", "content": "hi"}])
    for field in ("temperature", "top_p", "top_k", "min_p"):
        assert field not in sent, f"{field} was sent; the server's default must stand"


def test_the_switch_is_off_in_the_shipped_config():
    assert Settings.LLM_SAMPLING is False


def test_the_switch_on_sends_only_the_values_that_were_set(monkeypatch):
    monkeypatch.setattr(settings, "LLM_SAMPLING", True)
    monkeypatch.setattr(settings, "LLM_TEMPERATURE", 0.7)
    monkeypatch.setattr(settings, "LLM_TOP_P", None)
    monkeypatch.setattr(settings, "LLM_TOP_K", 20.0)
    monkeypatch.setattr(settings, "LLM_MIN_P", None)
    sent = _capture(monkeypatch)
    llm.chat([{"role": "user", "content": "hi"}])
    assert sent["temperature"] == 0.7 and sent["top_k"] == 20.0
    assert "top_p" not in sent and "min_p" not in sent   # empty stays unsent


def test_the_switch_off_ignores_values_left_in_the_env(monkeypatch):
    monkeypatch.setattr(settings, "LLM_SAMPLING", False)
    monkeypatch.setattr(settings, "LLM_TEMPERATURE", 0.7)
    sent = _capture(monkeypatch)
    llm.chat([{"role": "user", "content": "hi"}])
    assert "temperature" not in sent


def test_an_empty_env_value_reads_as_unset():
    from app.config import _optional_float
    import os
    os.environ["_GAMENTIC_TEST_KNOB"] = ""
    assert _optional_float("_GAMENTIC_TEST_KNOB") is None
    os.environ["_GAMENTIC_TEST_KNOB"] = "not a number"
    assert _optional_float("_GAMENTIC_TEST_KNOB") is None
    os.environ["_GAMENTIC_TEST_KNOB"] = "0.9"
    assert _optional_float("_GAMENTIC_TEST_KNOB") == 0.9
    del os.environ["_GAMENTIC_TEST_KNOB"]


# ---------- the guard: present, high, and overridable ----------

def test_the_guard_rides_on_every_call(monkeypatch):
    sent = _capture(monkeypatch)
    llm.chat([{"role": "user", "content": "hi"}])
    assert sent["max_tokens"] == settings.LLM_MAX_TOKENS == 4096


def test_the_guard_is_far_above_any_real_answer():
    # ~3000 words. A narration beat is a paragraph, a recap a dozen lines: nothing
    # the model means to write comes near this, which is what makes it a guard.
    assert settings.LLM_MAX_TOKENS >= 4096
    assert settings.WORLD_MAX_TOKENS > settings.LLM_MAX_TOKENS


def test_a_caller_that_needs_more_room_wins(monkeypatch):
    sent = _capture(monkeypatch)
    llm.chat([{"role": "user", "content": "hi"}], max_tokens=settings.WORLD_MAX_TOKENS)
    assert sent["max_tokens"] == settings.WORLD_MAX_TOKENS


def test_the_world_bible_call_gets_the_larger_guard(client, fake_llm, world, monkeypatch):
    """save_world carries an entire world as tool-call JSON; JSON cut mid-object is
    unparseable, not merely short (the failure creator.py documents)."""
    from app import creator, db
    sid = client.post("/create/message", json={"session_id": "s1", "message": "a port town"}) \
        .json().get("session_id", "s1")
    fake_llm.finalize = llm.LLMReply(content="", tool_calls=[llm.ToolCall("save_world", {
        "title": "Port", "setting": "a port town", "tone": "wry",
        "narrator_persona": "dry", "opening_scenario": "Rain on the docks.",
        "start_location": "docks", "characters": [], "quests": [], "lore": []})])
    with db.get_conn() as conn:
        creator.finalize(conn, sid)
    call = next(c for c in fake_llm.calls if "save_world" in c["names"])
    assert call["max_tokens"] == settings.WORLD_MAX_TOKENS
