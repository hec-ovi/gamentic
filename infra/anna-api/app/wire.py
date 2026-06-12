"""OpenAI chat wire <-> one copilot message.

The orchestrator speaks OpenAI /v1/chat/completions (messages + tools, expects
message.content and message.tool_calls back). The copilot API takes ONE string
and returns ONE string. So: flatten the stack into a transcript, and when tools
are in play wrap the call in the loose-args JSON contract from
docs/anna/05-sampling-llm.md ({"prose": ..., "tool_calls": [{name, arguments}]})
and parse it back out. A reply that fails the contract degrades to prose-only,
which the engine already tolerates from weak function-callers.
"""

from __future__ import annotations

import json
from typing import Any

_ROLE_LABELS = {"system": "SYSTEM", "user": "USER", "assistant": "ASSISTANT", "tool": "TOOL RESULT"}


def _content_text(content: Any) -> str:
    """Message content is normally a string; tolerate OpenAI part-lists."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
        )
    return "" if content is None else str(content)


def flatten_messages(messages: list[dict]) -> str:
    """The whole stack as one labeled transcript, system prompt first."""
    blocks: list[str] = []
    for msg in messages:
        label = _ROLE_LABELS.get(msg.get("role", "user"), str(msg.get("role", "user")).upper())
        if msg.get("role") == "tool" and msg.get("name"):
            label = f"TOOL RESULT ({msg['name']})"
        text = _content_text(msg.get("content"))
        if not text and msg.get("tool_calls"):
            calls = [
                f"{c.get('function', {}).get('name', '?')}({c.get('function', {}).get('arguments', '{}')})"
                for c in msg["tool_calls"]
            ]
            text = "(called tools: " + ", ".join(calls) + ")"
        blocks.append(f"[{label}]\n{text}")
    return "\n\n".join(blocks)


def tools_instruction(tools: list[dict]) -> str:
    """The loose-args wrapper contract, appended after the transcript."""
    compact = []
    for tool in tools:
        fn = tool.get("function", tool)
        compact.append(
            {
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {}),
            }
        )
    return (
        "[RESPONSE FORMAT]\n"
        "You may use these tools:\n"
        + json.dumps(compact, ensure_ascii=False)
        + "\n\nAnswer with ONE JSON object and nothing else, no code fences:\n"
        '{"prose": "<your in-character text, may be empty>", '
        '"tool_calls": [{"name": "<tool name>", "arguments": {<args>}}]}\n'
        'Use "tool_calls": [] when no tool applies. Arguments must follow the '
        "tool's parameters schema."
    )


def build_prompt(messages: list[dict], tools: list[dict] | None) -> str:
    prompt = flatten_messages(messages)
    if tools:
        prompt += "\n\n" + tools_instruction(tools)
    prompt += "\n\n[ASSISTANT]\n"
    return prompt


def _first_json_object(text: str, want_keys: tuple[str, ...] = ()) -> dict | None:
    """The first balanced JSON object in text, fences and prefixes ignored.
    With want_keys, objects missing all of those keys are skipped (a weak caller
    may echo an example/argument object before the real wrapper); the first
    non-matching object is kept as a fallback so the caller can still inspect it."""
    cleaned = text.replace("```json", "```")
    decoder = json.JSONDecoder()
    fallback = None
    start = cleaned.find("{")
    while start != -1:
        try:
            obj, _ = decoder.raw_decode(cleaned[start:])
        except ValueError:
            start = cleaned.find("{", start + 1)
            continue
        if isinstance(obj, dict):
            if not want_keys or any(k in obj for k in want_keys):
                return obj
            if fallback is None:
                fallback = obj
        start = cleaned.find("{", start + 1)
    return fallback


def parse_reply(text: str, had_tools: bool) -> tuple[str, list[dict]]:
    """(content, openai_tool_calls). Without tools the text passes through; with
    tools we expect the wrapper object but degrade to prose when it is absent."""
    if not had_tools:
        return text, []
    obj = _first_json_object(text, want_keys=("prose", "tool_calls"))
    if obj is None or ("prose" not in obj and "tool_calls" not in obj):
        return text, []
    prose = obj.get("prose") or obj.get("content") or ""
    if not isinstance(prose, str):
        prose = json.dumps(prose, ensure_ascii=False)
    calls: list[dict] = []
    raw_calls = obj.get("tool_calls") or []
    if isinstance(raw_calls, list):
        for i, call in enumerate(raw_calls):
            if not isinstance(call, dict):
                continue
            name = call.get("name") or call.get("function", {}).get("name")
            if not name:
                continue
            args = call.get("arguments", call.get("function", {}).get("arguments", {}))
            if not isinstance(args, str):
                args = json.dumps(args if isinstance(args, dict) else {}, ensure_ascii=False)
            calls.append(
                {
                    "id": f"call_{i}",
                    "type": "function",
                    "function": {"name": str(name), "arguments": args},
                }
            )
    return prose, calls


def apply_stops(text: str, stops: list[str] | None) -> str:
    """Client-side stop sequences: the copilot API has none, so cut here."""
    if not stops:
        return text
    cut = len(text)
    for stop in stops:
        if not stop:
            continue
        idx = text.find(stop)
        if idx != -1:
            cut = min(cut, idx)
    return text[:cut]


def usage_estimate(prompt: str, completion: str) -> dict:
    """Rough chars/4 token estimate so the UI context meter has a signal."""
    p, c = max(1, len(prompt) // 4), max(1, len(completion) // 4)
    return {"prompt_tokens": p, "completion_tokens": c, "total_tokens": p + c}


def chat_response(model: str, content: str, tool_calls: list[dict], usage: dict) -> dict:
    message: dict = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-anna",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": usage,
    }


def extract_image_url(text: str) -> str | None:
    """First image URL in a copilot reply: markdown image, then any http(s) URL."""
    import re

    md = re.search(r"!\[[^\]]*\]\((https?://[^\s)]+)\)", text)
    if md:
        return md.group(1)
    plain = re.search(r"https?://[^\s)\]\"'<>]+", text)
    return plain.group(0) if plain else None
