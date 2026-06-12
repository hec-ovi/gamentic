"""Anna mode: one boolean (admin override -> env ANNA) that retargets text and
image at Anna's OpenAI-compatible cloud gateway and silences voice. Expansion,
not restriction: with the boolean off, resolution is byte-identical to the local
stack. The compose side (GPU services profiled out under ANNA=true) is pinned by
the .env COMPOSE_PROFILES constant and verified by hand with `docker compose
config --services`; here we pin the app side end-to-end through the real routes."""
import json

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


def test_admin_round_trip_masking_and_validation(client):
    d = client.get("/admin/providers").json()
    assert d["anna"]["enabled"] is False and d["anna"]["api_key"] == ""

    r = client.put("/admin/providers", json={"anna": {
        "enabled": "true", "api_key": "sk-anna-secret",
        "base_url": "https://gw.example", "text_model": "anna-large"}})
    assert r.status_code == 200
    d = r.json()
    assert d["anna"]["enabled"] is True
    assert d["anna"]["api_key"] == "********"                   # write-only, like every key
    assert "sk-anna-secret" not in json.dumps(d)
    # the modality cards show the UNDERLYING config (never the anna overlay), so a
    # Save of what is displayed can never copy anna's gateway into local overrides
    assert d["text"]["provider"] == "local"
    assert d["image"]["provider"] == "comfy"
    # while the live resolution really is anna
    assert pbase.resolve("text").provider == "openai"
    assert pbase.resolve("text").base_url == "https://gw.example/v1"
    assert pbase.resolve("image").provider == "openai"

    # survives a fresh GET; flipping off restores the local stack
    assert client.get("/admin/providers").json()["anna"]["enabled"] is True
    client.put("/admin/providers", json={"anna": {"enabled": "false"}})
    d = client.get("/admin/providers").json()
    assert d["anna"]["enabled"] is False
    assert d["text"]["provider"] == "local" and d["image"]["provider"] == "comfy"

    # validation: junk boolean / unknown field
    assert client.put("/admin/providers",
                      json={"anna": {"enabled": "maybe"}}).status_code == 422
    assert client.put("/admin/providers",
                      json={"anna": {"voice_model": "x"}}).status_code == 422


def test_admin_override_beats_env_both_ways(client, monkeypatch):
    _enable_anna_env(monkeypatch)
    client.put("/admin/providers", json={"anna": {"enabled": "false"}})
    assert pbase.resolve("text").provider == "local"            # panel says no, env says yes

    monkeypatch.setenv("ANNA", "false")
    client.put("/admin/providers", json={"anna": {
        "enabled": "true", "base_url": "https://gw.example", "api_key": "k"}})
    assert pbase.resolve("text").provider == "openai"           # panel says yes, env says no
    # blanking returns control to the env
    client.put("/admin/providers", json={"anna": {"enabled": ""}})
    assert pbase.resolve("text").provider == "local"


def test_card_save_while_anna_on_cannot_poison_the_local_stack(client):
    """Re-saving exactly what a modality card displays while anna is ON (the
    admin pressing Save out of habit) must leave the anna-off world untouched."""
    baseline = pbase.resolve("text", apply_anna=False)
    client.put("/admin/providers", json={"anna": {
        "enabled": "true", "base_url": "https://gw.example", "api_key": "k"}})
    card = client.get("/admin/providers").json()["text"]
    client.put("/admin/providers", json={"text": {
        "provider": card["provider"], "base_url": card["base_url"],
        "model": card["model"]}})
    client.put("/admin/providers", json={"anna": {"enabled": "false"}})
    assert pbase.resolve("text") == baseline


def test_text_turns_speak_to_anna_with_bearer(client, monkeypatch):
    """The same llm.chat the whole engine uses: under anna the request goes to the
    gateway's /chat/completions with the Bearer key, and the stop list obeys the
    openai dialect's cap of 4 (the local 8-stop budget must not leak through)."""
    client.put("/admin/providers", json={"anna": {
        "enabled": "true", "api_key": "sk-anna-key", "base_url": "https://gw.example",
        "text_model": "anna-large"}})
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


def test_image_renders_through_anna_gateway(client, monkeypatch):
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    client.put("/admin/providers", json={"anna": {
        "enabled": "true", "api_key": "sk-anna-key", "base_url": "https://gw.example/v1"}})
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
    client.put("/admin/providers", json={"anna": {"enabled": "true",
                                                  "base_url": "https://gw.example"}})
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

    # the admin TEST button answers plainly instead of dialing a dead service
    d = client.post("/admin/providers/test", json={"modality": "audio"}).json()
    assert d["ok"] is False and "Anna" in d["error"]

    client.put("/admin/providers", json={"anna": {"enabled": "false"}})
    assert pbase.voice_enabled() is True


def test_admin_test_flags_missing_base_url(client):
    client.put("/admin/providers", json={"anna": {"enabled": "true"}})
    d = client.post("/admin/providers/test", json={"modality": "text"}).json()
    assert d["ok"] is False and "base URL" in d["error"]


def test_admin_page_carries_the_anna_card(client):
    page = client.get("/admin").content
    assert b"Anna mode" in page and b"anna-enabled" in page
