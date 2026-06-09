"""Test fixtures.

A fake llama.cpp upstream (real HTTP server on a random localhost port) stands in
for the Maya1 token model: /tokenize echoes deterministic ids and records the
exact content string the service sent (the assertion surface for tag translation
and voice design), /completion returns hash-deterministic SNAC tokens so the same
prompt always yields the same audio. The SNAC decoder is the real one (CPU,
~80MB, resolved through the HF cache); if it cannot load the suite skips with a
clear reason rather than failing spuriously.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

SNAC_MIN = 128266
SNAC_RANGE = 28672  # 7 slots x 4096 codes
CODE_END = 128258


class _FakeMaya1Handler(BaseHTTPRequestHandler):
    server_version = "fake-llamacpp"

    def log_message(self, *a):  # keep pytest output clean
        pass

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def _json(self, payload: dict, status: int = 200) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/health":
            self._json({"status": "ok"})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        body = self._body()
        self.server.requests.append((self.path, body))  # type: ignore[attr-defined]
        if self.path == "/tokenize":
            # deterministic ids; the recorded content string is what tests assert on
            self._json({"tokens": [200000 + b for b in body["content"].encode()][:512]})
        elif self.path == "/completion":
            toks = _snac_tokens(body["prompt"])
            if body.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for i in range(0, len(toks), 14):
                    chunk = {"tokens": toks[i:i + 14], "stop": i + 14 >= len(toks)}
                    self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
            else:
                self._json({"tokens": toks + [CODE_END], "stop_type": "eos"})
        else:
            self._json({"error": "not found"}, 404)


def _snac_tokens(prompt_tokens: list[int]) -> list[int]:
    """Hash-deterministic SNAC tokens: same prompt -> same audio. ~12-17 frames."""
    seed = hashlib.sha256(json.dumps(prompt_tokens).encode()).digest()
    frames = 12 + seed[0] % 6
    out = []
    for i in range(frames * 7):
        h = hashlib.sha256(seed + i.to_bytes(4, "big")).digest()
        out.append(SNAC_MIN + int.from_bytes(h[:4], "big") % SNAC_RANGE)
    return out


# Start the fake upstream and redirect env BEFORE app/config import.
_server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeMaya1Handler)
_server.requests = []  # type: ignore[attr-defined]
threading.Thread(target=_server.serve_forever, daemon=True).start()

_TMP = tempfile.mkdtemp(prefix="voiceapi-test-")
os.environ.setdefault("VOICE_DATA_DIR", _TMP)
os.environ["MAYA1_URL"] = f"http://127.0.0.1:{_server.server_address[1]}"

import config  # noqa: E402


def _snac_available() -> str | None:
    try:
        from snac import SNAC
        SNAC.from_pretrained(config.SNAC_MODEL)
        return None
    except Exception as e:  # offline box without the HF cache
        return f"SNAC decoder unavailable: {e}"


_SNAC_SKIP = _snac_available()


@pytest.fixture()
def upstream():
    """The fake llama.cpp server; .requests is the recorded (path, body) list."""
    _server.requests.clear()  # type: ignore[attr-defined]
    return _server


@pytest.fixture(scope="session")
def client():
    """Integration client running the real startup (loads the SNAC decoder)."""
    if _SNAC_SKIP:
        pytest.skip(_SNAC_SKIP)
    from fastapi.testclient import TestClient
    import app as appmod
    with TestClient(appmod.app) as c:
        yield c


def tokenized_contents(server) -> list[str]:
    """Every content string the service sent to /tokenize, oldest first."""
    return [b["content"] for p, b in server.requests if p == "/tokenize"]
