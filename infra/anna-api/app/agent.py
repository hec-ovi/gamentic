"""HTTP client for the Anna agent's local API.

The agent (vendor CLI in the anna-agent container) serves a small FastAPI on
:19001. The surface this adapter uses:

  POST /refresh               Cookie: refresh_token=<stored> -> session cookies
  POST /login                 form {username, password} -> session cookies
  POST /api/copilot/ask       {message, conversation_id, stream:true} -> SSE
  GET  /api/llm/models        the models the agent can reach (session-gated)
  GET  /api/agent/status      connection state, no auth required

AUTH (verified live on 1.1.0-beta.17): the copilot endpoints want a local user
session even after the agent's cloud sign-in. The Web UI sign-in (OAuth or
password) leaves the profile's refresh token on the agent's state volume
(.matrix/profiles/<active_profile>/refresh_token); POST /refresh with that token
as a cookie mints session cookies for the signed-in user. The adapter mounts the
volume read-only and rides that, so no credentials live in the environment.
Session cookies are managed by hand (a plain name->value dict) because some are
flagged Secure and a standards-following cookie jar would refuse to send them
over plain http on the docker network.

STREAMING: this build rejects stream=false ("Non-streaming responses are no
longer supported"), so asks always stream and the reply is assembled from
data: {"type": "content", "content": ...} frames; "done"/meta frames carry no
prose and are dropped.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from . import config

log = logging.getLogger("anna-api.agent")

# Substrings that mark an auth-shaped failure from the agent. The agent answers
# in Chinese ("未认证" = unauthenticated) or via FastAPI's English detail.
_AUTH_MARKERS = ("未认证", "credentials", "unauthorized", "not authenticated", "登录")

# Keys tried, in order, when digging reply text out of a JSON envelope.
_TEXT_KEYS = ("content", "message", "reply", "text", "answer", "response", "result")

# SSE frame types that carry reply text (vs done/meta/usage frames).
_CONTENT_TYPES = ("content", "delta", "token", "text")


class AgentError(RuntimeError):
    """The agent answered, but not with a usable reply."""

    def __init__(self, message: str, auth: bool = False):
        super().__init__(message)
        self.auth = auth


def _looks_auth(text: str) -> bool:
    low = text.lower()
    return any(m in low or m in text for m in _AUTH_MARKERS)


def extract_text(payload) -> str | None:
    """Dig the reply text out of an unknown JSON envelope. Returns None if no
    string-bearing field is found (caller decides how loud to be)."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        # error envelopes are the caller's job; here we only hunt for text
        for key in ("data",) + _TEXT_KEYS:
            if key in payload:
                found = extract_text(payload[key])
                if found is not None:
                    return found
        return None
    if isinstance(payload, list):
        parts = [extract_text(item) for item in payload]
        parts = [p for p in parts if p]
        return "".join(parts) if parts else None
    return None


def _sse_text(body: str) -> str:
    """Assemble the reply from the data: lines of an SSE stream. Typed frames
    contribute only when the type is content-bearing; the closing
    {"type": "done", "message": ...} frame must NOT leak into prose."""
    out: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        chunk = line[len("data:"):].strip()
        if not chunk or chunk == "[DONE]":
            continue
        try:
            payload = json.loads(chunk)
        except ValueError:
            out.append(chunk)
            continue
        if isinstance(payload, dict) and "type" in payload:
            kind = payload.get("type")
            if kind in _CONTENT_TYPES:
                piece = payload.get("content") or payload.get("delta") or payload.get("text") or ""
                if isinstance(piece, str):
                    out.append(piece)
            elif kind == "error":
                detail = str(payload.get("error") or payload.get("message") or payload)
                raise AgentError(f"Anna agent stream error: {detail[:300]}", auth=_looks_auth(detail))
            # done / meta / usage frames: no prose
            continue
        piece = extract_text(payload)
        if piece:
            out.append(piece)
    return "".join(out)


def _cookie_pairs(response: httpx.Response) -> dict[str, str]:
    """name -> value for every Set-Cookie on the response, policy-free."""
    pairs: dict[str, str] = {}
    for raw in response.headers.get_list("set-cookie"):
        first = raw.split(";", 1)[0]
        if "=" in first:
            name, value = first.split("=", 1)
            pairs[name.strip()] = value.strip()
    return pairs


class AgentClient:
    """One persistent client, hand-rolled cookie session. uvicorn runs a single
    worker, so a single shared instance per process is the simple correct shape."""

    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None
        self._cookies: dict[str, str] = {}

    @property
    def http(self) -> httpx.AsyncClient:
        # lazy + self-healing: app shutdown (and test client teardown) closes the
        # client; the next call simply builds a fresh one
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(base_url=config.AGENT_URL, timeout=config.ASK_TIMEOUT)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()

    def _session_headers(self) -> dict[str, str]:
        if not self._cookies:
            return {}
        return {"Cookie": "; ".join(f"{k}={v}" for k, v in self._cookies.items())}

    # ------------------------------------------------------------ session

    def _stored_refresh_token(self) -> str | None:
        """The signed-in profile's refresh token from the agent's state volume."""
        state = Path(config.AGENT_STATE_DIR)
        try:
            active = (state / "active_profile").read_text().strip()
            token = (state / "profiles" / active / "refresh_token").read_text().strip()
            return token or None
        except OSError:
            return None

    async def refresh_session(self) -> bool:
        """Mint local session cookies from the stored refresh token."""
        token = self._stored_refresh_token()
        if not token:
            return False
        try:
            r = await self.http.post(
                "/refresh", headers={"Cookie": f"refresh_token={token}"}, timeout=15.0
            )
        except httpx.HTTPError as err:
            log.warning("refresh failed: %s", err)
            return False
        ok = r.status_code == 200
        if ok:
            try:
                ok = bool(r.json().get("success", True))
            except ValueError:
                pass
        if ok:
            self._cookies.update(_cookie_pairs(r))
            return bool(self._cookies)
        log.warning("refresh rejected: HTTP %s %s", r.status_code, r.text[:200])
        return False

    async def login(self) -> bool:
        """POST /login with the configured credentials. True on success."""
        if not (config.AGENT_USERNAME and config.AGENT_PASSWORD):
            return False
        r = await self.http.post(
            "/login",
            data={"username": config.AGENT_USERNAME, "password": config.AGENT_PASSWORD},
            timeout=15.0,
        )
        ok = r.status_code in (200, 302, 303)
        if ok:
            try:
                payload = r.json()
                ok = bool(payload.get("success", True))
            except ValueError:
                pass  # HTML/redirect login pages count as success if the cookie landed
        if ok:
            self._cookies.update(_cookie_pairs(r))
        else:
            log.warning("agent login failed: HTTP %s %s", r.status_code, r.text[:200])
        return ok

    async def _ensure_session(self) -> bool:
        """Refresh-token path first (no secrets in env), creds fallback."""
        if await self.refresh_session():
            return True
        return await self.login()

    # ------------------------------------------------------------ calls

    async def status(self) -> dict:
        """Best-effort agent status (never raises)."""
        try:
            r = await self.http.get("/api/agent/status", timeout=5.0)
            return r.json() if r.status_code == 200 else {}
        except Exception:
            return {}

    async def ask(self, message: str) -> str:
        """One stateless copilot ask. Establishes a session lazily and retries
        once through a fresh session on an auth-shaped error."""
        if not self._cookies:
            await self._ensure_session()
        try:
            return await self._ask_once(message)
        except AgentError as err:
            if err.auth:
                self._cookies = {}
                if await self._ensure_session():
                    return await self._ask_once(message)
            raise

    async def _ask_once(self, message: str) -> str:
        try:
            r = await self.http.post(
                "/api/copilot/ask",
                json={"message": message, "conversation_id": None, "stream": True},
                headers=self._session_headers(),
            )
        except httpx.HTTPError as err:
            raise AgentError(f"Anna agent unreachable at {config.AGENT_URL}: {err}") from err

        body = r.text
        if r.status_code in (401, 403):
            raise AgentError(self._auth_message(body), auth=True)

        content_type = r.headers.get("content-type", "")
        if "text/event-stream" in content_type or body.lstrip().startswith("data:"):
            text = _sse_text(body)
            if text:
                return text
            raise AgentError(f"Anna agent stream carried no text: {body[:300]}")

        try:
            payload = r.json()
        except ValueError:
            if r.status_code == 200 and body.strip():
                return body  # plain-text reply
            raise AgentError(f"Anna agent answered HTTP {r.status_code}: {body[:300]}") from None

        if isinstance(payload, dict) and payload.get("success") is False:
            error = str(payload.get("error") or payload.get("detail") or payload)
            if _looks_auth(error):
                raise AgentError(self._auth_message(error), auth=True)
            raise AgentError(f"Anna agent error: {error[:300]}")

        text = extract_text(payload)
        if text:
            return text
        raise AgentError(f"Anna agent reply had no text field: {body[:300]}")

    async def models(self) -> list[str]:
        """Model ids the agent reports; [] when the call is unavailable."""
        if not self._cookies:
            await self._ensure_session()
        try:
            r = await self.http.get("/api/llm/models", timeout=15.0, headers=self._session_headers())
            payload = r.json()
        except Exception:
            return []
        items = payload.get("data", payload) if isinstance(payload, dict) else payload
        if isinstance(items, dict):
            items = items.get("models", [])
        ids: list[str] = []
        for item in items if isinstance(items, list) else []:
            if isinstance(item, str):
                ids.append(item)
            elif isinstance(item, dict):
                for key in ("id", "name", "model"):
                    if isinstance(item.get(key), str):
                        ids.append(item[key])
                        break
        return ids

    @staticmethod
    def _auth_message(detail: str) -> str:
        hint = (
            "Anna agent rejected the call as unauthenticated. Sign the agent in once "
            "via its Web UI (http://localhost:19001); the adapter rides that session "
            "through the agent's state volume"
        )
        if not (config.AGENT_USERNAME and config.AGENT_PASSWORD):
            hint += (
                " (or set ANNA_AGENT_USERNAME / ANNA_AGENT_PASSWORD in .env for a "
                "password account)"
            )
        return f"{hint}. Agent said: {detail[:200]}"
