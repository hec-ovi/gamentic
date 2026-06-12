"""Per-modality provider config, resolved AT CALL TIME.

Resolution order per setting: env -> default. Defaults reproduce today's local
stack byte-for-byte (local llama.cpp text, local Maya1 voice-api audio, comfy
image-api image). Config changes live in .env (the setup faces write it) and
apply on the next compose up; there is no runtime override layer on top.

Env spine (TEXT_*/AUDIO_*/IMAGE_*; LLM_BASE_URL/LLM_MODEL stay as working aliases
for TEXT_*). Capability flags are set by dialect and overridable by env.
"""
import os
import time
from dataclasses import dataclass

import httpx

from ..config import settings

MODALITIES = ("text", "audio", "image")

# The dialects per modality (the validation surface; the setup schema mirrors it).
# text 'local' and 'openai' speak the SAME wire dialect (OpenAI /chat/completions);
# they differ only in capability defaults (stop-list budget, thinking support).
DIALECTS = {
    "text": ("local", "openai"),
    "audio": ("local", "openai", "elevenlabs", "fal"),
    "image": ("comfy", "openai", "gemini", "fal"),
}

_DEFAULT_PROVIDER = {"text": "local", "audio": "local", "image": "comfy"}

# Cloud bases when the env names none. local/comfy fall back to the legacy
# settings URLs so today's compose wiring keeps working untouched.
_CLOUD_BASES = {
    ("text", "openai"): "https://api.openai.com/v1",
    ("audio", "openai"): "https://api.openai.com",
    ("audio", "elevenlabs"): "https://api.elevenlabs.io",
    ("audio", "fal"): "https://queue.fal.run",
    ("image", "openai"): "https://api.openai.com",
    ("image", "gemini"): "https://generativelanguage.googleapis.com",
    ("image", "fal"): "https://queue.fal.run",
}

_DEFAULT_MODELS = {
    ("audio", "openai"): "gpt-4o-mini-tts",
    ("audio", "elevenlabs"): "eleven_v3",
    ("audio", "fal"): "fal-ai/maya/batch",
    ("image", "openai"): "gpt-image-2",
    ("image", "gemini"): "gemini-2.5-flash-image",
    ("image", "fal"): "fal-ai/nano-banana-2",
}


@dataclass
class ProviderConfig:
    modality: str
    provider: str
    base_url: str
    api_key: str = ""
    model: str = ""
    # capabilities (dialect defaults, overridable by env):
    supports_seed: bool = False
    supports_references: bool = False
    emotion_mode: str = "none"        # tags | instructions | none
    max_stops: int = 4
    supports_thinking: bool = False
    voice_pool: str = ""              # elevenlabs: comma-separated voice ids to pick from


# ---------- Anna mode (the hackathon's cloud gateway) ----------
# One boolean that retargets text AND image at Anna's OpenAI-compatible endpoints
# and silences voice (Anna has no TTS surface). Expansion, not restriction: with
# anna off, resolution below behaves exactly as it always did, byte for byte.
# Resolution for the boolean and its settings mirrors everything else here:
# env (ANNA*) -> default.


@dataclass
class AnnaConfig:
    enabled: bool = False
    api_key: str = ""
    base_url: str = ""        # one URL, with or without a trailing /v1; normalized per modality
    text_model: str = ""
    image_model: str = ""


def _anna_truth(v: str) -> bool:
    """Mirrors the compose profile trick EXACTLY: the local services run only when
    ANNA is unset/empty or the literal 'false' (their profile name
    local-inference-anna-${ANNA} must equal the pinned COMPOSE_PROFILES constant,
    a string match compose does verbatim). So here too, ANY other value counts as
    on - 'ANNA=1' or 'ANNA=yes' must never read as off in the app while compose
    has already skipped the GPU containers (that split-brain kills every turn)."""
    v = (v or "").strip()
    return bool(v) and v != "false"


def anna_config() -> AnnaConfig:
    """The Anna preset, resolved NOW (env -> off)."""
    return AnnaConfig(
        enabled=_anna_truth(_env("ANNA")),
        api_key=_env("ANNA_API_KEY"),
        base_url=_env("ANNA_BASE_URL"),
        text_model=_env("ANNA_TEXT_MODEL"),
        image_model=_env("ANNA_IMAGE_MODEL"),
    )


def anna_enabled() -> bool:
    return anna_config().enabled


def voice_enabled() -> bool:
    """The voice gate every speak/cleanup surface checks: Anna has no voice API,
    so anna on means voice off, whatever VOICE_ENABLED says."""
    return settings.VOICE_ENABLED and not anna_enabled()


def _anna_text_base(url: str) -> str:
    """Text dialect wants .../v1 (chat/completions hangs off it)."""
    u = (url or "").rstrip("/")
    return u if (not u or u.endswith("/v1")) else f"{u}/v1"


def _anna_image_base(url: str) -> str:
    """Image dialect appends /v1/images/... itself, so it wants the bare host."""
    u = (url or "").rstrip("/")
    return u[:-3].rstrip("/") if u.endswith("/v1") else u


def _anna_resolve(modality: str, anna: AnnaConfig) -> ProviderConfig:
    """Text/image under Anna: the openai dialect against Anna's gateway, with the
    dialect's own capability defaults (no env capability knobs leak in)."""
    if modality == "text":
        return ProviderConfig(
            modality="text", provider="openai",
            base_url=_anna_text_base(anna.base_url), api_key=anna.api_key,
            model=anna.text_model, max_stops=4, supports_thinking=False)
    return ProviderConfig(
        modality="image", provider="openai",
        base_url=_anna_image_base(anna.base_url), api_key=anna.api_key,
        model=anna.image_model or _DEFAULT_MODELS[("image", "openai")],
        supports_seed=False, supports_references=True)


def _env(*names: str, default: str = "") -> str:
    """First NON-EMPTY env var among names (compose passes empties through)."""
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return default


def _as_bool(v, default: bool) -> bool:
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip().lower() == "true"


def _as_int(v, default: int) -> int:
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return default


def _capability_defaults(modality: str, provider: str, model: str) -> dict:
    if modality == "text":
        # local llama.cpp tolerates a generous stop list and hybrid thinking;
        # the OpenAI dialect caps stop at 4 and has no enable_thinking kwarg.
        return {"max_stops": 8 if provider == "local" else 4,
                "supports_thinking": provider == "local"}
    if modality == "audio":
        return {"emotion_mode": "instructions" if provider == "openai" else "tags"}
    # image
    if provider == "comfy":
        return {"supports_seed": True, "supports_references": True}
    if provider in ("openai", "gemini"):
        return {"supports_seed": False, "supports_references": True}
    # fal: per-model parameter maps; nano-banana exposes a seed, neither map takes refs
    return {"supports_seed": "nano-banana" in (model or ""), "supports_references": False}


def resolve(modality: str) -> ProviderConfig:
    """The active config for a modality: env -> default, NOW.
    Anna mode sits on top: when the anna boolean is on, text and image resolve to
    the Anna preset wholesale (per-modality env settings wait underneath,
    untouched); audio resolves as usual but every speak surface is gated by
    voice_enabled()."""
    if modality in ("text", "image"):
        anna = anna_config()
        if anna.enabled:
            return _anna_resolve(modality, anna)

    def pick(field: str, *env_names: str, default: str = "") -> str:
        return _env(*env_names, default=default)

    if modality == "text":
        provider = pick("provider", "TEXT_PROVIDER", default=_DEFAULT_PROVIDER["text"])
        base_url = pick("base_url", "TEXT_BASE_URL", "LLM_BASE_URL",
                        default=settings.LLM_BASE_URL)
        model = pick("model", "TEXT_MODEL", "LLM_MODEL", default=settings.LLM_MODEL)
        api_key = pick("api_key", "TEXT_API_KEY")
    elif modality == "audio":
        provider = pick("provider", "AUDIO_PROVIDER", default=_DEFAULT_PROVIDER["audio"])
        default_base = (settings.VOICE_API_URL if provider == "local"
                        else _CLOUD_BASES.get(("audio", provider), ""))
        base_url = pick("base_url", "AUDIO_BASE_URL", default=default_base)
        model = pick("model", "AUDIO_MODEL",
                     default=_DEFAULT_MODELS.get(("audio", provider), ""))
        api_key = pick("api_key", "AUDIO_API_KEY")
    elif modality == "image":
        provider = pick("provider", "IMAGE_PROVIDER", default=_DEFAULT_PROVIDER["image"])
        default_base = (settings.IMAGE_API_URL if provider == "comfy"
                        else _CLOUD_BASES.get(("image", provider), ""))
        base_url = pick("base_url", "IMAGE_BASE_URL", default=default_base)
        model = pick("model", "IMAGE_MODEL",
                     default=_DEFAULT_MODELS.get(("image", provider), ""))
        api_key = pick("api_key", "IMAGE_API_KEY")
    else:
        raise ValueError(f"unknown modality: {modality!r}")

    caps = _capability_defaults(modality, provider, model)
    cfg = ProviderConfig(modality=modality, provider=provider,
                         base_url=base_url.rstrip("/"), api_key=api_key, model=model)
    cfg.supports_seed = _as_bool(
        pick("supports_seed", f"{modality.upper()}_SUPPORTS_SEED"),
        caps.get("supports_seed", False))
    cfg.supports_references = _as_bool(
        pick("supports_references", f"{modality.upper()}_SUPPORTS_REFERENCES"),
        caps.get("supports_references", False))
    cfg.emotion_mode = pick("emotion_mode", "AUDIO_EMOTION_MODE",
                            default=caps.get("emotion_mode", "none"))
    cfg.max_stops = _as_int(pick("max_stops", "TEXT_MAX_STOPS"),
                            caps.get("max_stops", 4))
    cfg.supports_thinking = _as_bool(
        pick("supports_thinking", "TEXT_SUPPORTS_THINKING"),
        caps.get("supports_thinking", False))
    cfg.voice_pool = pick("voice_pool", "AUDIO_VOICE_POOL")
    return cfg


def fal_queue_run(cfg: ProviderConfig, model: str, payload: dict,
                  timeout: float = 120.0, interval: float = 1.0) -> dict | None:
    """The fal queue dialect, shared by the image and audio providers:
    POST {base}/{model} -> {request_id, status_url, response_url}; poll the status
    until COMPLETED; GET the response. Auth header is 'Authorization: Key <key>'."""
    headers = {"Authorization": f"Key {cfg.api_key}"} if cfg.api_key else {}
    r = httpx.post(f"{cfg.base_url}/{model}", json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    sub = r.json()
    req_id = sub.get("request_id", "")
    status_url = sub.get("status_url") or f"{cfg.base_url}/{model}/requests/{req_id}/status"
    response_url = sub.get("response_url") or f"{cfg.base_url}/{model}/requests/{req_id}"
    deadline = time.monotonic() + timeout
    while True:
        s = httpx.get(status_url, headers=headers, timeout=30)
        s.raise_for_status()
        status = (s.json().get("status") or "").upper()
        if status == "COMPLETED":
            break
        if status not in ("IN_QUEUE", "IN_PROGRESS"):
            return None                       # FAILED/CANCELLED: a real answer, not a flake
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)
    res = httpx.get(response_url, headers=headers, timeout=30)
    res.raise_for_status()
    return res.json()
