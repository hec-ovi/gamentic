"""The provider admin surface: GET masks keys (write-only), PUT round-trips overrides
into provider_config and hot-swaps the live provider with NO restart, the optional
ADMIN_TOKEN gates the page and the API, TEST performs one real minimal call against
the resolved config, and an audio provider switch re-resolves character voices once."""
import json

from app import db, llm, media, repo, voice_design
from app.config import settings
from app.providers import audio as paudio
from app.providers import image as pimage


class _Resp:
    def __init__(self, payload=None, content=b"", headers=None):
        self._payload = payload or {}
        self.content = content
        self.headers = headers or {}
    def raise_for_status(self): pass
    def json(self): return self._payload


def test_get_masks_api_keys_write_only(client, monkeypatch):
    monkeypatch.setenv("IMAGE_API_KEY", "sk-super-secret")
    d = client.get("/admin/providers").json()
    assert set(d) == {"text", "audio", "image"}
    assert d["image"]["api_key"] == "********"               # set, but never echoed
    assert d["text"]["api_key"] == ""                        # unset reads empty
    assert "sk-super-secret" not in json.dumps(d)
    assert d["image"]["dialects"] == ["comfy", "openai", "gemini", "fal"]
    assert isinstance(d["image"]["notes"], list) and d["image"]["notes"]


def test_put_round_trip_and_validation(client):
    r = client.put("/admin/providers", json={
        "image": {"provider": "gemini", "api_key": "g-key", "model": "gemini-2.5-flash-image"}})
    assert r.status_code == 200
    img = r.json()["image"]
    assert img["provider"] == "gemini" and img["api_key"] == "********"
    assert not img["capabilities"]["supports_seed"]          # dialect capabilities follow
    # the override survives into a fresh GET and the resolver
    assert client.get("/admin/providers").json()["image"]["provider"] == "gemini"
    # blanking a field clears the override (back to env/default)
    client.put("/admin/providers", json={"image": {"provider": ""}})
    assert client.get("/admin/providers").json()["image"]["provider"] == "comfy"
    # validation: unknown modality / dialect / field
    assert client.put("/admin/providers", json={"video": {}}).status_code == 422
    assert client.put("/admin/providers",
                      json={"image": {"provider": "dalle"}}).status_code == 422
    assert client.put("/admin/providers",
                      json={"image": {"frobnicate": "x"}}).status_code == 422


def test_hot_swap_image_provider_no_restart(client, monkeypatch):
    """PUT a cloud image provider, then the NEXT media call (the same code path the
    game uses) speaks the new dialect; PUT back and it returns home. No restart."""
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    captured = {}
    monkeypatch.setattr(pimage.httpx, "post",
                        lambda url, json=None, headers=None, timeout=None:
                        captured.update(url=url, headers=headers)
                        or _Resp({"data": [{"url": "https://oai/i.png"}],
                                  "image_url": "/image/file?f=1"}))
    client.put("/admin/providers", json={
        "image": {"provider": "openai", "api_key": "sk-img"}})
    out = media.generate_scene_image("a cave at dusk")
    assert captured["url"] == "https://api.openai.com/v1/images/generations"
    assert captured["headers"] == {"Authorization": "Bearer sk-img"}
    assert out == {"image_url": "https://oai/i.png"}

    client.put("/admin/providers", json={"image": {"provider": "", "api_key": ""}})
    media.generate_scene_image("a cave at dusk")
    assert captured["url"].endswith("/image/generate")       # comfy again, same process


def test_admin_token_gates_page_and_api(client, monkeypatch):
    # open by default
    assert client.get("/admin/providers").status_code == 200
    assert client.get("/admin").status_code == 200
    assert b"Inference providers" in client.get("/admin").content

    monkeypatch.setattr(settings, "ADMIN_TOKEN", "s3cret")
    assert client.get("/admin/providers").status_code == 401
    assert client.get("/admin").status_code == 401
    assert client.put("/admin/providers", json={}).status_code == 401
    assert client.post("/admin/providers/test",
                       json={"modality": "text"}).status_code == 401
    bad = {"Authorization": "Bearer wrong"}
    assert client.get("/admin/providers", headers=bad).status_code == 401
    good = {"Authorization": "Bearer s3cret"}
    assert client.get("/admin/providers", headers=good).status_code == 200
    assert client.put("/admin/providers", json={}, headers=good).status_code == 200
    # the page itself accepts ?token= (a browser can't header the initial load)
    assert client.get("/admin?token=s3cret").status_code == 200


def test_test_endpoint_text_ok_and_error(client, fake_llm, monkeypatch):
    d = client.post("/admin/providers/test", json={"modality": "text"}).json()
    assert d["ok"] is True and "latency_ms" in d             # one real (faked) chat call

    def _boom(*a, **k): raise RuntimeError("401 invalid api key")
    monkeypatch.setattr(llm, "chat", _boom)
    d = client.post("/admin/providers/test", json={"modality": "text"}).json()
    assert d["ok"] is False and "invalid api key" in d["error"]

    assert client.post("/admin/providers/test",
                       json={"modality": "smell"}).status_code == 422


def test_test_endpoint_audio_and_image_minimal_calls(client, monkeypatch):
    monkeypatch.setattr(paudio.httpx, "post",
                        lambda url, json=None, timeout=None:
                        _Resp({"audio_url": "/audio/t.wav"}))
    monkeypatch.setattr(paudio.httpx, "get",
                        lambda url, timeout=None: _Resp(content=b"WAV"))
    d = client.post("/admin/providers/test", json={"modality": "audio"}).json()
    assert d["ok"] is True and "3 audio bytes" in d["detail"]

    monkeypatch.setattr(pimage.httpx, "post",
                        lambda url, json=None, timeout=None:
                        _Resp({"image_url": "/image/file?f=t"}))
    d = client.post("/admin/providers/test", json={"modality": "image"}).json()
    assert d["ok"] is True

    def _down(*a, **k): raise RuntimeError("connect refused")
    monkeypatch.setattr(pimage.httpx, "post", _down)
    d = client.post("/admin/providers/test", json={"modality": "image"}).json()
    assert d["ok"] is False and "connect refused" in d["error"]


def test_put_audio_provider_switch_reresolves_voices_once(client, fake_llm, monkeypatch):
    """The voice fold rides the admin hot-swap: switching the audio provider re-maps
    every character's stored design into the new voice space, exactly once."""
    monkeypatch.setattr(settings, "VOICE_ENABLED", True)
    monkeypatch.setattr(media, "list_voice_ids", lambda: ["narrator"])
    world = {"title": "W", "setting": "s", "tone": "t", "narrator_persona": "p",
             "opening_scenario": "o", "start_location": "sq", "player_life": 20,
             "characters": [{"name": "Vex", "persona": "a wary scout",
                             "description": "A sharp-eyed woman."}],
             "quests": [{"title": "x", "objectives": ["x"]}], "lore": []}
    gid = client.post("/games", json=world).json()["game_id"]

    def vex():
        with db.get_conn() as conn:
            return dict(repo.get_characters(conn, gid)[0])
    before = vex()
    assert before["voice_id"] == before["voice_design"]      # local mapping

    client.put("/admin/providers", json={"audio": {"provider": "openai"}})
    after = vex()
    assert after["voice_id"] in voice_design.OPENAI_VOICES   # re-resolved server-side
    assert after["voice_design"] == before["voice_design"]   # the design never moves
    assert after["voice_provider"] == "openai"

    # saving the SAME provider again must not reshuffle anything
    client.put("/admin/providers", json={"audio": {"provider": "openai"}})
    assert vex()["voice_id"] == after["voice_id"]
