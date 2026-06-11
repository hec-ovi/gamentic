"""Audio provider dialects: request shapes pinned to each provider's PUBLISHED schema,
emotion routing per the resolved emotion_mode (local = the voice-api field, openai =
an instructions sentence, elevenlabs = an inline [tag], fal-maya = a leading <tag>,
none = silently dropped), and the key-safe POST /audio/speak passthrough (local mode
simply proxies voice-api). All over mocked HTTP."""
from app.config import settings
from app.providers import audio as paudio
from app.providers import base as pbase


class _Resp:
    def __init__(self, payload=None, content=b"", headers=None):
        self._payload = payload or {}
        self.content = content
        self.headers = headers or {}
    def raise_for_status(self): pass
    def json(self): return self._payload


DESIGN = "Female voice, 30s, warm mellow rounded pitch, measured deliberate pacing"


# ---------- local (the live-tested default) ----------

def _mock_local(monkeypatch, captured):
    monkeypatch.setattr(paudio.httpx, "post",
                        lambda url, json=None, timeout=None:
                        captured.update(post_url=url, body=json)
                        or _Resp({"audio_url": "/audio/abc.wav"}))
    monkeypatch.setattr(paudio.httpx, "get",
                        lambda url, timeout=None:
                        captured.update(get_url=url) or _Resp(content=b"WAVBYTES"))


def test_local_speak_posts_voice_api_and_fetches_audio(monkeypatch):
    captured = {}
    _mock_local(monkeypatch, captured)
    p = paudio.get_provider(pbase.resolve("audio"))
    out = p.speak("Stay close.", DESIGN, "whisper")
    assert captured["post_url"] == f"{settings.VOICE_API_URL}/voice/speak"
    assert captured["body"] == {"text": "Stay close.", "voice_id": DESIGN,
                                "emotion": "whisper"}          # the emotion FIELD
    assert captured["get_url"] == f"{settings.VOICE_API_URL}/audio/abc.wav"
    assert out == (b"WAVBYTES", "audio/wav")


def test_local_speak_without_emotion_omits_the_field(monkeypatch):
    captured = {}
    _mock_local(monkeypatch, captured)
    paudio.get_provider(pbase.resolve("audio")).speak("Stay close.", DESIGN)
    assert captured["body"] == {"text": "Stay close.", "voice_id": DESIGN}


# ---------- openai (instructions mode) ----------

def test_openai_speak_renders_emotion_as_instructions(monkeypatch):
    monkeypatch.setenv("AUDIO_PROVIDER", "openai")
    monkeypatch.setenv("AUDIO_API_KEY", "sk-audio")
    captured = {}
    monkeypatch.setattr(paudio.httpx, "post",
                        lambda url, json=None, headers=None, timeout=None:
                        captured.update(url=url, body=json, headers=headers)
                        or _Resp(content=b"MP3", headers={"content-type": "audio/mpeg"}))
    p = paudio.get_provider(pbase.resolve("audio"))
    out = p.speak("Stay close.", "ash", "angry")
    assert captured["url"] == "https://api.openai.com/v1/audio/speech"
    assert captured["headers"] == {"Authorization": "Bearer sk-audio"}
    assert captured["body"] == {"model": "gpt-4o-mini-tts", "input": "Stay close.",
                                "voice": "ash",
                                "instructions": "Tone of voice: angry."}
    assert out == (b"MP3", "audio/mpeg")
    p.speak("Stay close.", "ash")                          # no emotion -> no instructions
    assert "instructions" not in captured["body"]


# ---------- elevenlabs (inline v3 audio tag) ----------

def test_elevenlabs_speak_inline_tag_and_header(monkeypatch):
    monkeypatch.setenv("AUDIO_PROVIDER", "elevenlabs")
    monkeypatch.setenv("AUDIO_API_KEY", "el-key")
    captured = {}
    monkeypatch.setattr(paudio.httpx, "post",
                        lambda url, json=None, headers=None, timeout=None:
                        captured.update(url=url, body=json, headers=headers)
                        or _Resp(content=b"MP3", headers={"content-type": "audio/mpeg"}))
    p = paudio.get_provider(pbase.resolve("audio"))
    out = p.speak("Stay close.", "v-123", "whisper")
    assert captured["url"] == "https://api.elevenlabs.io/v1/text-to-speech/v-123"
    assert captured["headers"] == {"xi-api-key": "el-key"}
    assert captured["body"] == {"text": "[whisper] Stay close.", "model_id": "eleven_v3"}
    assert out == (b"MP3", "audio/mpeg")


# ---------- fal (queue dialect, maya batch, leading angle tag) ----------

def test_fal_maya_batch_queue_flow(monkeypatch):
    monkeypatch.setenv("AUDIO_PROVIDER", "fal")
    monkeypatch.setenv("AUDIO_API_KEY", "f-key")
    captured = {}

    def _post(url, json=None, headers=None, timeout=None):
        captured.update(submit_url=url, body=json, headers=headers)
        return _Resp({"request_id": "r1", "status_url": f"{url}/requests/r1/status",
                      "response_url": f"{url}/requests/r1"})

    def _get(url, headers=None, timeout=None):
        if url.endswith("/status"):
            return _Resp({"status": "COMPLETED"})
        if url.endswith("/requests/r1"):
            return _Resp({"audios": [{"url": "https://fal.media/a.wav",
                                      "content_type": "audio/wav"}]})
        return _Resp(content=b"WAV")            # the audio file download
    monkeypatch.setattr(pbase.httpx, "post", _post)
    monkeypatch.setattr(pbase.httpx, "get", _get)

    p = paudio.get_provider(pbase.resolve("audio"))
    p.poll_interval = 0
    out = p.speak("Stay close.", DESIGN, "angry")
    assert captured["submit_url"] == "https://queue.fal.run/fal-ai/maya/batch"
    assert captured["headers"] == {"Authorization": "Key f-key"}
    assert captured["body"] == {"texts": ["<angry> Stay close."], "prompts": [DESIGN]}
    assert out == (b"WAV", "audio/wav")


# ---------- emotion_mode none: tone silently unused ----------

def test_emotion_mode_none_drops_the_tone(monkeypatch):
    monkeypatch.setenv("AUDIO_PROVIDER", "elevenlabs")
    monkeypatch.setenv("AUDIO_EMOTION_MODE", "none")
    captured = {}
    monkeypatch.setattr(paudio.httpx, "post",
                        lambda url, json=None, headers=None, timeout=None:
                        captured.update(body=json) or _Resp(content=b"MP3"))
    paudio.get_provider(pbase.resolve("audio")).speak("Stay close.", "v-123", "angry")
    assert captured["body"]["text"] == "Stay close."           # no tag anywhere

    monkeypatch.delenv("AUDIO_PROVIDER")
    monkeypatch.setattr(paudio.httpx, "get", lambda url, timeout=None: _Resp(content=b"W"))
    monkeypatch.setattr(paudio.httpx, "post",
                        lambda url, json=None, timeout=None:
                        captured.update(body=json) or _Resp({"audio_url": "/audio/x.wav"}))
    paudio.get_provider(pbase.resolve("audio")).speak("Stay close.", DESIGN, "angry")
    assert "emotion" not in captured["body"]                   # local field dropped too


# ---------- POST /audio/speak: the key-safe passthrough ----------

def test_audio_speak_route_proxies_local_voice_api(client, monkeypatch):
    monkeypatch.setattr(settings, "VOICE_ENABLED", True)
    captured = {}
    _mock_local(monkeypatch, captured)
    r = client.post("/audio/speak", json={"text": "Hold the line.",
                                          "voice_id": "narrator", "emotion": "whisper"})
    assert r.status_code == 200
    assert r.content == b"WAVBYTES"
    assert r.headers["content-type"].startswith("audio/wav")
    assert captured["body"] == {"text": "Hold the line.", "voice_id": "narrator",
                                "emotion": "whisper"}          # proxied verbatim


def test_audio_speak_route_resolves_cloud_provider_server_side(client, monkeypatch):
    """Cloud mode: the browser talks to US; the key rides only on the server-side hop."""
    monkeypatch.setattr(settings, "VOICE_ENABLED", True)
    monkeypatch.setenv("AUDIO_PROVIDER", "openai")
    monkeypatch.setenv("AUDIO_API_KEY", "sk-audio")
    captured = {}
    monkeypatch.setattr(paudio.httpx, "post",
                        lambda url, json=None, headers=None, timeout=None:
                        captured.update(url=url, headers=headers)
                        or _Resp(content=b"MP3", headers={"content-type": "audio/mpeg"}))
    r = client.post("/audio/speak", json={"text": "Hold.", "voice_id": "ash"})
    assert r.status_code == 200 and r.content == b"MP3"
    assert r.headers["content-type"].startswith("audio/mpeg")
    assert captured["headers"] == {"Authorization": "Bearer sk-audio"}


def test_audio_speak_route_disabled_and_down_are_graceful(client, monkeypatch):
    monkeypatch.setattr(settings, "VOICE_ENABLED", False)
    assert client.post("/audio/speak", json={"text": "Hi."}).status_code == 409

    monkeypatch.setattr(settings, "VOICE_ENABLED", True)
    def _boom(*a, **k): raise RuntimeError("voice-api down")
    monkeypatch.setattr(paudio.httpx, "post", _boom)
    assert client.post("/audio/speak", json={"text": "Hi."}).status_code == 502
    assert client.post("/audio/speak", json={"text": ""}).status_code == 422  # validation
