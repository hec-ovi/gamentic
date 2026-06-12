"""Anna mode: one boolean (env ANNA) that retargets text and image at the Anna
gateway (the in-stack anna-api adapter by default) and silences voice. Expansion,
not restriction: with the boolean off, resolution is byte-identical to the local
stack. The compose side (GPU services profiled out under ANNA=true) is pinned by
the .env COMPOSE_PROFILES constant and verified by hand with `docker compose
config --services`; here we pin the app side end-to-end through the real paths."""
from app import llm, media
from app.config import settings
from app.providers import base as pbase
from app.providers import image as pimage

# Captured at import time, BEFORE the autouse inert_media_cleanup fixture stubs
# them on the media module: the voice-off test must drive the REAL functions.
_real_purge_all_audio = media.purge_all_audio
_real_purge_game_audio = media.purge_game_audio


class _Resp:
    def __init__(self, payload=None, content=b"", headers=None):
        self._payload = payload or {}
        self.content = content
        self.headers = headers or {}
    def raise_for_status(self): pass
    def json(self): return self._payload


def _enable_anna_env(monkeypatch, base="https://gw.example/v1"):
    monkeypatch.setenv("ANNA", "true")
    monkeypatch.setenv("ANNA_API_KEY", "sk-anna-key")
    monkeypatch.setenv("ANNA_BASE_URL", base)
    monkeypatch.setenv("ANNA_TEXT_MODEL", "anna-large")


def test_env_boolean_flips_text_and_image_to_anna(monkeypatch):
    before_text, before_image = pbase.resolve("text"), pbase.resolve("image")
    _enable_anna_env(monkeypatch)

    text = pbase.resolve("text")
    assert text.provider == "openai"
    assert text.base_url == "https://gw.example/v1"
    assert text.model == "anna-large"
    assert text.api_key == "sk-anna-key"
    assert text.max_stops == 4 and not text.supports_thinking   # openai dialect caps

    image = pbase.resolve("image")
    assert image.provider == "openai"
    assert image.base_url == "https://gw.example"               # /v1 stripped: dialect appends it
    assert image.model == "gpt-image-2"                         # blank model falls to the dialect default
    assert image.api_key == "sk-anna-key"
    assert image.supports_references and not image.supports_seed

    # audio resolution is untouched (the speak surfaces gate via voice_enabled())
    assert pbase.resolve("audio").provider == "local"

    # expansion, not restriction: boolean off = exactly the local resolution again
    monkeypatch.setenv("ANNA", "false")
    assert pbase.resolve("text") == before_text
    assert pbase.resolve("image") == before_image


def test_env_boolean_mirrors_compose_exactly(monkeypatch):
    """The compose profile trick string-matches the literal 'false', so the app
    parses ANNA the same way: any other set value is ON. 'ANNA=1' must never
    read as off here while compose has already skipped the GPU containers."""
    monkeypatch.setenv("ANNA_BASE_URL", "https://gw.example")
    for v, on in (("true", True), ("1", True), ("yes", True), ("False", True),
                  ("false", False), ("", False)):
        monkeypatch.setenv("ANNA", v)
        assert pbase.resolve("text").provider == ("openai" if on else "local"), v


def test_base_url_normalized_per_modality(monkeypatch):
    _enable_anna_env(monkeypatch, base="https://gw.example")    # bare host
    assert pbase.resolve("text").base_url == "https://gw.example/v1"
    assert pbase.resolve("image").base_url == "https://gw.example"
    monkeypatch.setenv("ANNA_BASE_URL", "https://gw.example/v1/")  # trailing slash + /v1
    assert pbase.resolve("text").base_url == "https://gw.example/v1"
    assert pbase.resolve("image").base_url == "https://gw.example"


def test_text_turns_speak_to_anna_with_bearer(monkeypatch):
    """The same llm.chat the whole engine uses: under anna the request goes to the
    gateway's /chat/completions with the Bearer key, and the stop list obeys the
    openai dialect's cap of 4 (the local 8-stop budget must not leak through)."""
    _enable_anna_env(monkeypatch, base="https://gw.example")
    captured = {}

    def _post(url, **kw):
        captured.update(url=url, **kw)
        return _Resp({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})

    monkeypatch.setattr(llm.httpx, "post", _post)
    reply = llm.chat([{"role": "user", "content": "hi"}],
                     stop=[f"s{i}" for i in range(8)], thinking=True)
    assert reply.content == "ok"
    assert captured["url"] == "https://gw.example/v1/chat/completions"
    assert captured["headers"] == {"Authorization": "Bearer sk-anna-key"}
    assert captured["json"]["model"] == "anna-large"
    assert captured["json"]["stop"] == ["s0", "s1", "s2", "s3"]
    assert "chat_template_kwargs" not in captured["json"]       # no thinking kwarg on cloud


def test_image_renders_through_anna_gateway(monkeypatch):
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    _enable_anna_env(monkeypatch)
    monkeypatch.delenv("ANNA_TEXT_MODEL", raising=False)
    captured = {}
    monkeypatch.setattr(pimage.httpx, "post",
                        lambda url, json=None, headers=None, timeout=None:
                        captured.update(url=url, headers=headers, json=json)
                        or _Resp({"data": [{"b64_json": "aGk="}]}))
    out = media.generate_scene_image("a cave at dusk")
    assert captured["url"] == "https://gw.example/v1/images/generations"
    assert captured["headers"] == {"Authorization": "Bearer sk-anna-key"}
    assert captured["json"]["model"] == "gpt-image-2"
    assert out["image_url"].startswith("data:image/png;base64,")


def test_voice_is_off_in_anna_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "VOICE_ENABLED", True)
    assert pbase.voice_enabled() is True
    monkeypatch.setenv("ANNA", "true")
    monkeypatch.setenv("ANNA_BASE_URL", "https://gw.example")
    assert pbase.voice_enabled() is False

    # the speak passthrough refuses; the cleanup/registry surfaces no-op without
    # touching the (absent) voice-api
    r = client.post("/audio/speak", json={"text": "hello there"})
    assert r.status_code == 409

    def _no_network(*a, **k):
        raise AssertionError("anna mode must not call the voice-api")
    monkeypatch.setattr(media.httpx, "get", _no_network)
    monkeypatch.setattr(media.httpx, "post", _no_network)
    monkeypatch.setattr(media.httpx, "delete", _no_network)
    assert media.list_voice_ids() == []
    # the REAL purge functions (the autouse fixture stubs the module attributes;
    # the module-level captures above predate it), plus the legacy registry pair
    assert _real_purge_all_audio() is None
    assert _real_purge_game_audio("g1") is None
    assert media.register_character_voice("c1", "Vex", "a wary scout") is None
    assert media.delete_character_voice("c1") is None

    monkeypatch.setenv("ANNA", "false")
    assert pbase.voice_enabled() is True
