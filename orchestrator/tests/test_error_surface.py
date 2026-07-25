"""How a failed turn REACHES the player, and how long the brain is allowed to think.

Live 2026-07-25: a thinking narrator at deep context outran the 300s transport
ceiling. The ReadTimeout escaped the route, Starlette's ServerErrorMiddleware
answered with a bare 500 that carried no Access-Control-Allow-Origin, and the
browser reported a CORS failure instead of the status. The player saw "failed to
fetch" and lost the turn. Two contracts came out of it:

  1. no ceiling on a generation (LLM_TIMEOUT=0 -> None, straight into httpx)
  2. whatever goes wrong, the answer is JSON the frontend can read and show
"""
import httpx
import pytest

from app import llm
from app.config import Settings, settings


# ---------- 1. the generation runs as long as it takes ----------

def test_no_transport_ceiling_by_default():
    assert Settings.LLM_TIMEOUT is None          # 0/unset in env = wait forever


def test_a_positive_env_value_still_puts_the_ceiling_back(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT", "45")
    from app.config import _seconds_or_none
    assert _seconds_or_none("LLM_TIMEOUT", "0") == 45.0


def test_garbage_in_the_env_reads_as_no_ceiling(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT", "soon")
    from app.config import _seconds_or_none
    assert _seconds_or_none("LLM_TIMEOUT", "0") is None


def test_the_blocking_call_hands_httpx_no_timeout(monkeypatch):
    monkeypatch.setattr(settings, "LLM_STREAM", False)
    seen = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}

    def _post(url, **kw):
        seen.update(kw)
        return _Resp()
    monkeypatch.setattr(llm.httpx, "post", _post)
    llm.chat([{"role": "user", "content": "hi"}])
    assert "timeout" in seen and seen["timeout"] is None


def test_a_slow_stream_is_never_cut_off(monkeypatch):
    """The streamed path used to hold its own deadline (now None): a generation
    that decodes slowly must still finish, not raise ReadTimeout mid-prose."""
    chunks = [
        'data: {"choices":[{"delta":{"content":"The dust "}}]}',
        'data: {"choices":[{"delta":{"content":"settles."},"finish_reason":"stop"}]}',
        "data: [DONE]",
    ]
    clock = {"t": 0.0}
    monkeypatch.setattr(llm.time, "monotonic", lambda: clock["t"])

    class _Stream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            return None

        def iter_lines(self):
            for line in chunks:
                clock["t"] += 10_000      # hours pass between fragments
                yield line

    monkeypatch.setattr(llm.httpx, "stream", lambda m, u, **kw: _Stream())
    reply = llm.chat([{"role": "user", "content": "hi"}], on_delta=lambda f: None)
    assert reply.content == "The dust settles."


def test_a_configured_ceiling_still_cuts_a_runaway_stream(monkeypatch):
    monkeypatch.setattr(settings, "LLM_TIMEOUT", 30.0)
    clock = {"t": 0.0}
    monkeypatch.setattr(llm.time, "monotonic", lambda: clock["t"])

    class _Stream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            return None

        def iter_lines(self):
            while True:
                clock["t"] += 100
                yield 'data: {"choices":[{"delta":{"content":"and "}}]}'

    monkeypatch.setattr(llm.httpx, "stream", lambda m, u, **kw: _Stream())
    with pytest.raises(httpx.ReadTimeout):
        llm.chat([{"role": "user", "content": "hi"}], on_delta=lambda f: None)


# ---------- 2. a failure the browser can actually read ----------

ORIGIN = {"Origin": "http://localhost:5173"}


def test_a_crashing_turn_answers_500_with_the_cors_header(client, fake_llm, world, monkeypatch):
    gid = client.post("/games", json=world).json()["game_id"]

    def _boom(*a, **kw):
        raise httpx.ReadTimeout("the model is still thinking")
    monkeypatch.setattr(llm, "chat", _boom)

    r = client.post(f"/games/{gid}/action", json={"action": "I look around."},
                    headers=ORIGIN)
    assert r.status_code == 500
    # without this header the browser reports a CORS error and drops the status
    assert r.headers.get("access-control-allow-origin") == "*"
    detail = r.json()["detail"]
    assert "ReadTimeout" in detail          # named, so the log is findable


def test_the_error_body_is_json_the_frontend_can_show(client, fake_llm, world, monkeypatch):
    gid = client.post("/games", json=world).json()["game_id"]

    def _boom(*a, **kw):
        raise RuntimeError("something deep in the engine")
    monkeypatch.setattr(llm, "chat", _boom)

    r = client.post(f"/games/{gid}/action", json={"action": "I wait."}, headers=ORIGIN)
    assert r.headers["content-type"].startswith("application/json")
    assert isinstance(r.json().get("detail"), str) and r.json()["detail"]


def test_a_healthy_turn_is_untouched_by_the_error_middleware(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    r = client.post(f"/games/{gid}/action", json={"action": "I look around."},
                    headers=ORIGIN)
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "*"


def test_a_404_still_reads_as_a_404_not_a_500(client):
    r = client.post("/games/nope/action", json={"action": "hi"}, headers=ORIGIN)
    assert r.status_code == 404
    assert r.headers.get("access-control-allow-origin") == "*"
