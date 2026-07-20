"""Streaming transport in llm.chat(): opted into by passing on_delta/cancel, it must
assemble the exact LLMReply the blocking path would have built, honor cancel by
closing the stream, and keep the retry contract (one retry on connection failures,
but never after a chunk was consumed - a half-eaten stream must not double-generate)."""
import threading

import httpx
import pytest

from app import llm
from app.config import settings


def _sse(lines):
    return [f"data: {ln}" if ln != "[DONE]" else "data: [DONE]" for ln in lines]


class _FakeStream:
    """Stands in for httpx.stream(): a context manager yielding scripted SSE lines."""

    def __init__(self, lines, fail_after=None):
        self.lines = lines
        self.fail_after = fail_after      # yield N lines, then die mid-stream

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        return None

    def iter_lines(self):
        for i, ln in enumerate(self.lines):
            if self.fail_after is not None and i >= self.fail_after:
                raise httpx.RemoteProtocolError("server died mid-stream")
            yield ln


_CHUNKS = _sse([
    '{"choices":[{"index":0,"delta":{"role":"assistant","content":null}}]}',
    '{"choices":[{"index":0,"delta":{"content":"The dust"}}]}',
    '{"choices":[{"index":0,"delta":{"content":" settles."}}]}',
    '{"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"x","type":"function",'
    '"function":{"name":"add_item","arguments":"{\\"name\\""}}]}}]}',
    '{"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,'
    '"function":{"arguments":":\\"key\\",\\"qty\\":1}"}}]}}]}',
    '{"choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}',
    '{"choices":[],"usage":{"prompt_tokens":19,"completion_tokens":5,"total_tokens":24}}',
    "[DONE]",
])


def test_stream_assembles_the_same_reply_and_fires_deltas(monkeypatch):
    monkeypatch.setattr(llm.httpx, "stream", lambda m, u, **kw: _FakeStream(_CHUNKS))
    seen = []
    reply = llm.chat([{"role": "user", "content": "hi"}], on_delta=seen.append)
    assert reply.content == "The dust settles."
    assert seen == ["The dust", " settles."]          # raw fragments, in order
    assert [(c.name, c.arguments) for c in reply.tool_calls] == [("add_item", {"name": "key", "qty": 1})]
    assert reply.finish_reason == "tool_calls"
    assert reply.usage["total_tokens"] == 24          # the context meter depends on this


def test_plain_calls_never_touch_the_streaming_path(monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("plain chat() must stay on httpx.post")
    monkeypatch.setattr(llm.httpx, "stream", _boom)

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    monkeypatch.setattr(llm.httpx, "post", lambda url, **kw: _Resp())
    assert llm.chat([{"role": "user", "content": "hi"}]).content == "ok"


def test_cancel_mid_stream_raises_and_stops_consuming(monkeypatch):
    cancel = threading.Event()
    consumed = []

    class _CancellingStream(_FakeStream):
        def iter_lines(self):
            for ln in self.lines:
                consumed.append(ln)
                yield ln
                cancel.set()              # fires after the first yielded line

    monkeypatch.setattr(llm.httpx, "stream", lambda m, u, **kw: _CancellingStream(_CHUNKS))
    with pytest.raises(llm.LLMCancelled):
        llm.chat([{"role": "user", "content": "hi"}], cancel=cancel)
    assert len(consumed) == 2             # the line before the check, plus one


def test_cancel_already_set_bails_before_any_request(monkeypatch):
    cancel = threading.Event()
    cancel.set()

    def _boom(*a, **kw):
        raise AssertionError("no HTTP call may happen after cancel")
    monkeypatch.setattr(llm.httpx, "stream", _boom)
    monkeypatch.setattr(llm.httpx, "post", _boom)
    with pytest.raises(llm.LLMCancelled):
        llm.chat([{"role": "user", "content": "hi"}], cancel=cancel)


def test_connection_drop_before_first_chunk_is_retried(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def _stream(m, u, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("container restarting")
        return _FakeStream(_CHUNKS)
    monkeypatch.setattr(llm.httpx, "stream", _stream)
    reply = llm.chat([{"role": "user", "content": "hi"}], on_delta=lambda f: None)
    assert reply.content == "The dust settles."
    assert calls["n"] == 2


def test_death_mid_stream_is_never_retried(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def _stream(m, u, **kw):
        calls["n"] += 1
        return _FakeStream(_CHUNKS, fail_after=3)     # dies after real chunks flowed
    monkeypatch.setattr(llm.httpx, "stream", _stream)
    with pytest.raises(httpx.RemoteProtocolError):
        llm.chat([{"role": "user", "content": "hi"}], on_delta=lambda f: None)
    assert calls["n"] == 1                # retrying would double-generate


def test_kill_switch_falls_back_to_blocking_with_one_late_delta(monkeypatch):
    monkeypatch.setattr(settings, "LLM_STREAM", False)

    def _boom(*a, **kw):
        raise AssertionError("LLM_STREAM=false must not open a stream")
    monkeypatch.setattr(llm.httpx, "stream", _boom)

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "Whole text."}, "finish_reason": "stop"}]}
    monkeypatch.setattr(llm.httpx, "post", lambda url, **kw: _Resp())
    seen = []
    reply = llm.chat([{"role": "user", "content": "hi"}], on_delta=seen.append)
    assert reply.content == "Whole text."
    assert seen == ["Whole text."]        # once, whole, at the end
