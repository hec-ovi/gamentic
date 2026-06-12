"""Thin client for the llama.cpp OpenAI-compatible endpoint.

One function: chat(). No framework. Returns the assistant message with parsed
tool calls. The same server + model backs every agent; only the messages differ.
"""
import json
import time
from dataclasses import dataclass, field

import httpx

from .config import settings
from .providers import base as providers


@dataclass
class ToolCall:
    name: str
    arguments: dict


@dataclass
class LLMReply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    usage: dict = field(default_factory=dict)  # {prompt_tokens, completion_tokens, total_tokens}


def chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_choice: str = "auto",
    temperature: float = 0.8,
    max_tokens: int = 400,
    stop: list[str] | None = None,
    thinking: bool | None = None,
) -> LLMReply:
    # Resolved at call time (env -> default), so a .env change lands on the
    # next compose up with no code involved.
    cfg = providers.resolve("text")
    payload: dict = {
        "model": cfg.model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens and max_tokens > 0:   # 0/None = uncapped: the prompt governs length
        payload["max_tokens"] = max_tokens
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice
    if stop:
        # Truncate, never error: stops are a guard, not content. Upstream llama.cpp
        # imposes NO cap (the server reads the whole "stop" array into its antiprompt
        # vector; verified against ggml-org/llama.cpp tools/server), so the local
        # max_stops=8 is OUR conservative budget (providers/base.py); the OpenAI
        # dialect hard-caps at 4. The slice keeps the FRONT of the list, and the turn
        # engine builds its scaffold stops before the cast name-stops, so under any
        # truncation the scaffold guards survive and only name-stops fall off.
        payload["stop"] = stop[:cfg.max_stops] if cfg.max_stops > 0 else stop
    if thinking and cfg.supports_thinking:
        # llama.cpp merges request-level chat_template_kwargs over the server-level ones,
        # so this enables hybrid-model reasoning for THIS call only. If the reply carries
        # message.reasoning_content, it is ignored: content stays the only consumed field.
        # Capability-gated: cloud OpenAI-dialect endpoints have no such kwarg.
        payload["chat_template_kwargs"] = {"enable_thinking": True}

    url = f"{cfg.base_url}/chat/completions"
    kwargs: dict = {"json": payload, "timeout": settings.LLM_TIMEOUT}
    if cfg.api_key:                     # local llama.cpp needs none; cloud gets Bearer
        kwargs["headers"] = {"Authorization": f"Bearer {cfg.api_key}"}
    # One retry on connection-level failures only: a redeploy of the llama.cpp container
    # kills in-flight requests (seen live), and a fresh connection a beat later succeeds.
    # Timeouts are NOT retried (a 180s timeout means the box is busy; retrying doubles
    # the pain), and HTTP status errors are real answers, not transport flakes.
    for attempt in (0, 1):
        try:
            resp = httpx.post(url, **kwargs)
            break
        except (httpx.ConnectError, httpx.RemoteProtocolError):
            if attempt:
                raise
            time.sleep(0.5)
    resp.raise_for_status()
    data = resp.json()
    choice = data["choices"][0]
    msg = choice.get("message", {})

    calls: list[ToolCall] = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            args = {}
        calls.append(ToolCall(name=fn.get("name", ""), arguments=args))

    return LLMReply(
        content=(msg.get("content") or "").strip(),
        tool_calls=calls,
        finish_reason=choice.get("finish_reason", ""),
        usage=data.get("usage") or {},
    )
