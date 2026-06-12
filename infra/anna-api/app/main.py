"""anna-api: an OpenAI-compatible face for the Anna agent.

The orchestrator's Anna mode speaks OpenAI (/v1/chat/completions + Bearer key)
at ANNA_BASE_URL. The Anna agent container speaks its own copilot API on :19001.
This adapter sits between them so the orchestrator needs zero code changes:

  POST /v1/chat/completions  -> POST {agent}/api/copilot/ask  (tools wrapped in JSON)
  GET  /v1/models            -> GET  {agent}/api/llm/models   (static fallback)
  POST /v1/images/*          -> clean 501 by default (the game absorbs it and
                                stays text-only); optional copilot experiment
                                behind ANNA_IMAGE_VIA_COPILOT.

No GPU, no state. Mirrors the image-api pattern: keep this small and boring.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import config, wire
from .agent import AgentClient, AgentError

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("anna-api")

agent = AgentClient()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    yield
    await agent.aclose()


app = FastAPI(title="gamentic anna-api", version="1.0", lifespan=_lifespan)


def _error(status: int, message: str) -> JSONResponse:
    # OpenAI error envelope so the orchestrator's logs carry the real reason
    return JSONResponse(status_code=status, content={"error": {"message": message, "type": "anna_api_error"}})


@app.get("/health")
async def health() -> dict:
    status = await agent.status()
    return {
        "status": "ok",
        "agent_url": config.AGENT_URL,
        "agent_reachable": bool(status),
        "agent_connected": bool(status.get("connected")),
    }


@app.get("/v1/models")
async def models() -> dict:
    ids = await agent.models()
    if not ids:
        ids = [config.MODEL_ID]
    return {"object": "list", "data": [{"id": mid, "object": "model"} for mid in ids]}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return _error(400, "body must be JSON")
    messages = body.get("messages") or []
    if not isinstance(messages, list) or not messages:
        return _error(400, "messages required")
    tools = body.get("tools") or []
    model = body.get("model") or config.MODEL_ID

    prompt = wire.build_prompt(messages, tools)
    try:
        reply = await agent.ask(prompt)
    except AgentError as err:
        log.warning("ask failed: %s", err)
        return _error(502, str(err))

    content, tool_calls = wire.parse_reply(reply, had_tools=bool(tools))
    content = wire.apply_stops(content, body.get("stop"))
    usage = wire.usage_estimate(prompt, content)
    return wire.chat_response(model, content, tool_calls, usage)


@app.post("/v1/images/generations")
async def images_generations(request: Request):
    if not config.IMAGE_VIA_COPILOT:
        return _error(
            501,
            "the Anna agent's local API has no image endpoint; set "
            "ANNA_IMAGE_VIA_COPILOT=true to experiment with copilot-generated "
            "images (the game plays text-only either way)",
        )
    try:
        body = await request.json()
    except ValueError:
        return _error(400, "body must be JSON")
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return _error(400, "prompt required")
    ask = (
        "Generate an image of the following and reply with ONLY the image URL, "
        f"nothing else:\n{prompt}"
    )
    try:
        reply = await agent.ask(ask)
    except AgentError as err:
        return _error(502, str(err))
    url = wire.extract_image_url(reply)
    if not url:
        return _error(502, f"copilot reply carried no image URL: {reply[:200]}")
    return {"created": 0, "data": [{"url": url}]}


@app.post("/v1/images/edits")
async def images_edits():
    # reference-conditioned renders have no copilot equivalent; the orchestrator
    # absorbs this and the game continues text-only
    return _error(501, "image edits are not available through the Anna agent")
