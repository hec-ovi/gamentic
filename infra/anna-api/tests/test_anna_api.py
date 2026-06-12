"""End-to-end: OpenAI-shaped requests in, copilot asks out, through the real routes."""

import json

import httpx
import pytest
import respx

from tests.conftest import AGENT

CHAT = "/v1/chat/completions"


def _ask_payload(text: str) -> dict:
    # the envelope the agent's copilot endpoint answers with (success shape)
    return {"success": True, "data": {"content": text}}


def _messages():
    return [
        {"role": "system", "content": "You narrate a dungeon."},
        {"role": "user", "content": "I open the door."},
    ]


# ---------------------------------------------------------------- plain text

@respx.mock
def test_chat_plain_text(client, no_creds):
    route = respx.post(f"{AGENT}/api/copilot/ask").mock(
        return_value=httpx.Response(200, json=_ask_payload("The door creaks open."))
    )
    r = client.post(CHAT, json={"model": "anna-copilot", "messages": _messages()})
    assert r.status_code == 200
    body = r.json()
    msg = body["choices"][0]["message"]
    assert msg["content"] == "The door creaks open."
    assert "tool_calls" not in msg
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"]["prompt_tokens"] > 0

    # the outbound ask carries the flattened stack, stateless; this agent build
    # rejects stream=false, so asks always stream
    sent = json.loads(route.calls[0].request.content)
    assert sent["stream"] is True
    assert sent["conversation_id"] is None
    assert "[SYSTEM]\nYou narrate a dungeon." in sent["message"]
    assert "[USER]\nI open the door." in sent["message"]


@respx.mock
def test_chat_applies_stop_sequences(client, no_creds):
    respx.post(f"{AGENT}/api/copilot/ask").mock(
        return_value=httpx.Response(200, json=_ask_payload("Hello there.\nPLAYER: I attack"))
    )
    r = client.post(CHAT, json={"messages": _messages(), "stop": ["\nPLAYER"]})
    assert r.json()["choices"][0]["message"]["content"] == "Hello there."


@respx.mock
def test_chat_sse_stream_reply(client, no_creds):
    sse = (
        'data: {"content": "The "}\n\n'
        'data: {"content": "torch flares."}\n\n'
        "data: [DONE]\n\n"
    )
    respx.post(f"{AGENT}/api/copilot/ask").mock(
        return_value=httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
    )
    r = client.post(CHAT, json={"messages": _messages()})
    assert r.json()["choices"][0]["message"]["content"] == "The torch flares."


# ---------------------------------------------------------------- tool calls

def _tools():
    return [
        {
            "type": "function",
            "function": {
                "name": "cue_character",
                "description": "Hand the scene to a character.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        }
    ]


@respx.mock
def test_chat_tools_round_trip(client, no_creds):
    wrapper = {"prose": "Orin steps forward.", "tool_calls": [{"name": "cue_character", "arguments": {"name": "Orin"}}]}
    route = respx.post(f"{AGENT}/api/copilot/ask").mock(
        return_value=httpx.Response(200, json=_ask_payload(json.dumps(wrapper)))
    )
    r = client.post(CHAT, json={"messages": _messages(), "tools": _tools()})
    body = r.json()
    msg = body["choices"][0]["message"]
    assert msg["content"] == "Orin steps forward."
    assert body["choices"][0]["finish_reason"] == "tool_calls"
    call = msg["tool_calls"][0]
    assert call["type"] == "function"
    assert call["function"]["name"] == "cue_character"
    assert json.loads(call["function"]["arguments"]) == {"name": "Orin"}

    # the contract went out with the prompt
    sent = json.loads(route.calls[0].request.content)
    assert '"tool_calls"' in sent["message"]
    assert "cue_character" in sent["message"]


@respx.mock
def test_chat_tools_fenced_json_still_parses(client, no_creds):
    wrapper = '```json\n{"prose": "Done.", "tool_calls": []}\n```'
    respx.post(f"{AGENT}/api/copilot/ask").mock(
        return_value=httpx.Response(200, json=_ask_payload(wrapper))
    )
    r = client.post(CHAT, json={"messages": _messages(), "tools": _tools()})
    msg = r.json()["choices"][0]["message"]
    assert msg["content"] == "Done."
    assert "tool_calls" not in msg


@respx.mock
def test_chat_tools_stray_object_before_wrapper(client, no_creds):
    # weak callers echo an example/argument object before the real wrapper; the
    # contract object must win, not the first balanced JSON in the text
    reply = (
        'Example arg shape: {"target": "guard", "amount": 5}\n\n'
        '{"prose": "You hit the guard.", "tool_calls": '
        '[{"name": "apply_damage", "arguments": {"target": "guard", "amount": 5}}]}'
    )
    respx.post(f"{AGENT}/api/copilot/ask").mock(
        return_value=httpx.Response(200, json=_ask_payload(reply))
    )
    r = client.post(CHAT, json={"messages": _messages(), "tools": _tools()})
    msg = r.json()["choices"][0]["message"]
    assert msg["content"] == "You hit the guard."
    assert msg["tool_calls"][0]["function"]["name"] == "apply_damage"
    assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"target": "guard", "amount": 5}


@respx.mock
def test_chat_tools_multiple_calls_and_surrounding_prose(client, no_creds):
    reply = (
        "Sure, here is my move:\n"
        '{"prose": "Steel rings out.", "tool_calls": ['
        '{"name": "apply_damage", "arguments": {"target": "guard", "amount": 3}}, '
        '{"name": "cue_character", "arguments": {"name": "Orin"}}]}\n'
        "Hope that helps!"
    )
    respx.post(f"{AGENT}/api/copilot/ask").mock(
        return_value=httpx.Response(200, json=_ask_payload(reply))
    )
    r = client.post(CHAT, json={"messages": _messages(), "tools": _tools()})
    body = r.json()
    msg = body["choices"][0]["message"]
    assert msg["content"] == "Steel rings out."
    assert body["choices"][0]["finish_reason"] == "tool_calls"
    assert [c["id"] for c in msg["tool_calls"]] == ["call_0", "call_1"]
    assert [c["function"]["name"] for c in msg["tool_calls"]] == ["apply_damage", "cue_character"]
    assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"target": "guard", "amount": 3}
    assert json.loads(msg["tool_calls"][1]["function"]["arguments"]) == {"name": "Orin"}


@respx.mock
def test_chat_tools_prose_only_degrades(client, no_creds):
    respx.post(f"{AGENT}/api/copilot/ask").mock(
        return_value=httpx.Response(200, json=_ask_payload("The narrator just talks, no JSON."))
    )
    r = client.post(CHAT, json={"messages": _messages(), "tools": _tools()})
    msg = r.json()["choices"][0]["message"]
    assert msg["content"] == "The narrator just talks, no JSON."
    assert "tool_calls" not in msg
    assert r.json()["choices"][0]["finish_reason"] == "stop"


# ------------------------------------------------- refresh-token session (the
# real path: the adapter rides the Web UI sign-in via the agent's state volume)

@respx.mock
def test_refresh_token_session_from_volume(client, no_creds, agent_volume):
    refresh = respx.post(f"{AGENT}/refresh").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "message": "ok"},
            headers=[
                ("set-cookie", "access_token=sess-1; Path=/; SameSite=lax"),
                ("set-cookie", "access_token__production=sess-1p; HttpOnly; Secure"),
            ],
        )
    )
    sse = 'data: {"type": "content", "content": "Hello."}\n\ndata: {"type": "done", "message": "对话完成"}\n\n'
    ask = respx.post(f"{AGENT}/api/copilot/ask").mock(
        return_value=httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
    )
    r = client.post(CHAT, json={"messages": _messages()})
    assert r.status_code == 200
    # the done frame's message must NOT leak into the prose
    assert r.json()["choices"][0]["message"]["content"] == "Hello."

    # the stored token went out as a cookie, and the minted session rode the ask
    assert refresh.calls[0].request.headers["cookie"] == "refresh_token=rt-volume-secret"
    ask_cookie = ask.calls[0].request.headers["cookie"]
    assert "access_token=sess-1" in ask_cookie
    assert "access_token__production=sess-1p" in ask_cookie  # Secure flag must not strip it


@respx.mock
def test_expired_session_re_refreshes_and_retries(client, no_creds, agent_volume):
    refresh = respx.post(f"{AGENT}/refresh").mock(
        return_value=httpx.Response(
            200, json={"success": True}, headers={"set-cookie": "access_token=sess-2; Path=/"}
        )
    )
    ask = respx.post(f"{AGENT}/api/copilot/ask")
    ask.side_effect = [
        httpx.Response(500, json={"success": False, "error": "未认证"}),
        httpx.Response(200, json=_ask_payload("Back again.")),
    ]
    r = client.post(CHAT, json={"messages": _messages()})
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "Back again."
    assert refresh.call_count == 2  # initial session + the re-mint after expiry
    assert ask.call_count == 2


# ---------------------------------------------------------------- auth + errors

@respx.mock
def test_unauthenticated_no_creds_is_actionable_502(client, no_creds):
    respx.post(f"{AGENT}/api/copilot/ask").mock(
        return_value=httpx.Response(
            500, json={"success": False, "error": 'Copilot Ask Mode failed: {"detail":"Could not validate credentials"}'}
        )
    )
    r = client.post(CHAT, json={"messages": _messages()})
    assert r.status_code == 502
    assert "sign" in r.json()["error"]["message"].lower()
    assert "19001" in r.json()["error"]["message"]


@respx.mock
def test_auth_error_logs_in_and_retries(client, creds):
    ask = respx.post(f"{AGENT}/api/copilot/ask")
    ask.side_effect = [
        httpx.Response(500, json={"success": False, "error": "未认证"}),
        httpx.Response(200, json=_ask_payload("Back in business.")),
    ]
    login = respx.post(f"{AGENT}/login").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    r = client.post(CHAT, json={"messages": _messages()})
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "Back in business."
    assert login.called
    assert ask.call_count == 2
    sent = login.calls[0].request.content.decode()
    assert "username=hec%40example.com" in sent


@respx.mock
def test_http_401_status_is_actionable_502(client, no_creds):
    respx.post(f"{AGENT}/api/copilot/ask").mock(
        return_value=httpx.Response(401, json={"detail": "未认证"})
    )
    r = client.post(CHAT, json={"messages": _messages()})
    assert r.status_code == 502
    assert "19001" in r.json()["error"]["message"]


@respx.mock
def test_login_failure_does_not_loop(client, creds):
    # the agent's real bad-creds answer is HTTP 200 {"success": false, ...}; the
    # original auth error must surface, with exactly one login attempt and no
    # retry storm
    ask = respx.post(f"{AGENT}/api/copilot/ask").mock(
        return_value=httpx.Response(500, json={"success": False, "error": "未认证"})
    )
    login = respx.post(f"{AGENT}/login").mock(
        return_value=httpx.Response(200, json={"success": False, "error_code": "login.badRequest"})
    )
    r = client.post(CHAT, json={"messages": _messages()})
    assert r.status_code == 502
    # pre-emptive login (creds set, not yet logged in) + one post-failure attempt;
    # the failed second login means the ask is NOT retried
    assert login.call_count == 2
    assert ask.call_count == 1


@respx.mock
def test_agent_down_is_502(client, no_creds):
    respx.post(f"{AGENT}/api/copilot/ask").mock(side_effect=httpx.ConnectError("boom"))
    r = client.post(CHAT, json={"messages": _messages()})
    assert r.status_code == 502
    assert "unreachable" in r.json()["error"]["message"]


def test_empty_messages_is_400(client):
    r = client.post(CHAT, json={"messages": []})
    assert r.status_code == 400


# ---------------------------------------------------------------- models + health

@respx.mock
def test_models_proxies_agent_list(client, no_creds):
    respx.get(f"{AGENT}/api/llm/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "anna-large"}, "anna-mini"]})
    )
    r = client.get("/v1/models")
    ids = [m["id"] for m in r.json()["data"]]
    assert ids == ["anna-large", "anna-mini"]


@respx.mock
def test_models_degrades_to_static_when_gated(client, no_creds):
    respx.get(f"{AGENT}/api/llm/models").mock(
        return_value=httpx.Response(401, json={"detail": "未认证"})
    )
    r = client.get("/v1/models")
    assert [m["id"] for m in r.json()["data"]] == ["anna-copilot"]


@respx.mock
def test_health_reports_agent_state(client, no_creds):
    respx.get(f"{AGENT}/api/agent/status").mock(
        return_value=httpx.Response(200, json={"connected": False, "client_id": ""})
    )
    r = client.get("/health")
    body = r.json()
    assert body["status"] == "ok"
    assert body["agent_reachable"] is True
    assert body["agent_connected"] is False


# ---------------------------------------------------------------- images

def test_images_default_clean_501(client):
    r = client.post("/v1/images/generations", json={"prompt": "a vault door"})
    assert r.status_code == 501
    assert "text-only" in r.json()["error"]["message"]


def test_image_edits_always_501(client):
    r = client.post("/v1/images/edits")
    assert r.status_code == 501


@respx.mock
def test_images_via_copilot_extracts_url(client, no_creds, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "IMAGE_VIA_COPILOT", True)
    respx.post(f"{AGENT}/api/copilot/ask").mock(
        return_value=httpx.Response(
            200, json=_ask_payload("Here you go: ![vault](https://cdn.anna.example/img/123.png)")
        )
    )
    r = client.post("/v1/images/generations", json={"prompt": "a vault door"})
    assert r.status_code == 200
    assert r.json()["data"][0]["url"] == "https://cdn.anna.example/img/123.png"


@respx.mock
def test_images_via_copilot_no_url_is_502(client, no_creds, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "IMAGE_VIA_COPILOT", True)
    respx.post(f"{AGENT}/api/copilot/ask").mock(
        return_value=httpx.Response(200, json=_ask_payload("I cannot draw that."))
    )
    r = client.post("/v1/images/generations", json={"prompt": "a vault door"})
    assert r.status_code == 502
