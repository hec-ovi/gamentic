"""The provider config spine: per-modality resolution (admin DB override -> env ->
default) happens AT CALL TIME so the admin panel hot-swaps with no restart; the
defaults reproduce today's local stack byte-for-byte; LLM_BASE_URL/LLM_MODEL stay
working aliases for TEXT_*; capability flags default per dialect and are
overridable. Plus the text dialect wire contract (Bearer, stop cap, thinking gate)."""
import json

from app import db, llm, repo
from app.config import settings
from app.providers import base as pbase


def _clear_provider_env(monkeypatch):
    for n in ("TEXT_PROVIDER", "TEXT_BASE_URL", "TEXT_API_KEY", "TEXT_MODEL",
              "AUDIO_PROVIDER", "AUDIO_BASE_URL", "AUDIO_API_KEY", "AUDIO_MODEL",
              "IMAGE_PROVIDER", "IMAGE_BASE_URL", "IMAGE_API_KEY", "IMAGE_MODEL"):
        monkeypatch.delenv(n, raising=False)


# ---------- resolution order ----------

def test_defaults_reproduce_todays_local_stack(monkeypatch):
    _clear_provider_env(monkeypatch)
    text = pbase.resolve("text")
    assert text.provider == "local"
    assert text.base_url == settings.LLM_BASE_URL.rstrip("/")   # llama.cpp as configured
    assert text.model == settings.LLM_MODEL
    assert text.api_key == ""
    assert text.max_stops == 8 and text.supports_thinking       # llama.cpp capabilities

    audio = pbase.resolve("audio")
    assert audio.provider == "local"
    assert audio.base_url == settings.VOICE_API_URL.rstrip("/")
    assert audio.emotion_mode == "tags"

    image = pbase.resolve("image")
    assert image.provider == "comfy"
    assert image.base_url == settings.IMAGE_API_URL.rstrip("/")
    assert image.supports_seed and image.supports_references    # the tested default


def test_env_beats_default_and_llm_alias_still_works(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("LLM_BASE_URL", "http://alias:1234/v1")   # the legacy alias
    monkeypatch.setenv("LLM_MODEL", "alias-model")
    cfg = pbase.resolve("text")
    assert cfg.base_url == "http://alias:1234/v1" and cfg.model == "alias-model"
    monkeypatch.setenv("TEXT_BASE_URL", "http://spine:4321/v1")  # TEXT_* wins over the alias
    monkeypatch.setenv("TEXT_MODEL", "spine-model")
    cfg = pbase.resolve("text")
    assert cfg.base_url == "http://spine:4321/v1" and cfg.model == "spine-model"


def test_db_override_beats_env_and_clearing_restores_it(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL", "env-model")
    with db.get_conn() as conn:
        repo.set_provider_override(conn, "text.model", "db-model")
    assert pbase.resolve("text").model == "db-model"             # admin override on top
    with db.get_conn() as conn:
        repo.set_provider_override(conn, "text.model", "")       # blank = cleared
    assert pbase.resolve("text").model == "env-model"            # the env shows through


def test_empty_env_vars_are_treated_as_unset(monkeypatch):
    # compose passes `TEXT_BASE_URL=` through as empty; that must NOT blank the default
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("TEXT_BASE_URL", "")
    monkeypatch.setenv("IMAGE_PROVIDER", "")
    assert pbase.resolve("text").base_url == settings.LLM_BASE_URL.rstrip("/")
    assert pbase.resolve("image").provider == "comfy"


# ---------- capability defaults + overrides ----------

def test_capability_defaults_per_dialect(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("TEXT_PROVIDER", "openai")
    cfg = pbase.resolve("text")
    assert cfg.max_stops == 4 and not cfg.supports_thinking      # cloud OpenAI dialect

    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    img = pbase.resolve("image")
    assert not img.supports_seed and img.supports_references     # nano banana family

    monkeypatch.setenv("IMAGE_PROVIDER", "fal")                  # default model nano-banana-2
    img = pbase.resolve("image")
    assert img.supports_seed and not img.supports_references
    monkeypatch.setenv("IMAGE_MODEL", "openai/gpt-image-2")      # fal per-model map
    assert not pbase.resolve("image").supports_seed

    monkeypatch.setenv("AUDIO_PROVIDER", "openai")
    assert pbase.resolve("audio").emotion_mode == "instructions"
    monkeypatch.setenv("AUDIO_PROVIDER", "elevenlabs")
    assert pbase.resolve("audio").emotion_mode == "tags"


def test_cloud_dialects_get_sane_base_and_model_defaults(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("IMAGE_PROVIDER", "openai")
    img = pbase.resolve("image")
    assert img.base_url == "https://api.openai.com" and img.model == "gpt-image-2"
    monkeypatch.setenv("AUDIO_PROVIDER", "fal")
    aud = pbase.resolve("audio")
    assert aud.base_url == "https://queue.fal.run" and aud.model == "fal-ai/maya/batch"


def test_capability_override_via_db(monkeypatch):
    _clear_provider_env(monkeypatch)
    with db.get_conn() as conn:
        repo.set_provider_override(conn, "image.supports_references", "false")
        repo.set_provider_override(conn, "text.max_stops", "2")
    assert not pbase.resolve("image").supports_references        # comfy default overridden
    assert pbase.resolve("text").max_stops == 2


# ---------- text dialect wire contract ----------

_REPLY = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}}


class _Resp:
    def raise_for_status(self): pass
    def json(self): return _REPLY


def test_cloud_text_sends_bearer_caps_stops_and_drops_thinking(monkeypatch):
    captured = {}

    def _post(url, json=None, timeout=None, headers=None):
        captured.update(url=url, body=json, headers=headers)
        return _Resp()
    monkeypatch.setattr(llm.httpx, "post", _post)
    monkeypatch.setenv("TEXT_PROVIDER", "openai")
    monkeypatch.setenv("TEXT_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("TEXT_API_KEY", "sk-test")
    monkeypatch.setenv("TEXT_MODEL", "gpt-test")

    llm.chat([{"role": "user", "content": "hi"}],
             stop=[f"\nS{i}:" for i in range(8)], thinking=True)
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["headers"] == {"Authorization": "Bearer sk-test"}
    assert captured["body"]["model"] == "gpt-test"
    assert captured["body"]["stop"] == ["\nS0:", "\nS1:", "\nS2:", "\nS3:"]  # capped at 4
    assert "chat_template_kwargs" not in captured["body"]    # thinking unsupported: dropped


def test_local_text_keeps_no_auth_eight_stops_and_thinking(monkeypatch):
    captured = {}

    def _post(url, json=None, timeout=None, headers=None):
        captured.update(url=url, body=json, headers=headers)
        return _Resp()
    monkeypatch.setattr(llm.httpx, "post", _post)

    llm.chat([{"role": "user", "content": "hi"}],
             stop=[f"\nS{i}:" for i in range(8)], thinking=True)
    assert captured["headers"] is None                       # byte-identical local call
    assert captured["url"] == f"{settings.LLM_BASE_URL}/chat/completions"
    assert len(captured["body"]["stop"]) == 8                # llama.cpp budget kept
    assert captured["body"]["chat_template_kwargs"] == {"enable_thinking": True}


def test_text_hot_swap_via_db_override_no_restart(monkeypatch):
    captured = {}

    def _post(url, json=None, timeout=None, headers=None):
        captured.update(url=url, headers=headers)
        return _Resp()
    monkeypatch.setattr(llm.httpx, "post", _post)
    with db.get_conn() as conn:
        repo.set_provider_override(conn, "text.base_url", "https://swapped.example/v1")
        repo.set_provider_override(conn, "text.api_key", "sk-swap")
    llm.chat([{"role": "user", "content": "hi"}])
    assert captured["url"] == "https://swapped.example/v1/chat/completions"
    assert captured["headers"] == {"Authorization": "Bearer sk-swap"}
