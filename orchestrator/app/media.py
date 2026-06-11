"""Best-effort facade over the accessory media providers (image, voice).

These functions keep their historical signatures (tests and integrate/jobs.py call
them directly) but now dispatch to the ACTIVE provider from app/providers/, resolved
at call time (admin DB override -> env -> default). With the default local stack the
wire behavior is byte-identical to what this module always did.

Every call is wrapped so a missing/slow/erroring service NEVER breaks the game:
on any failure these return empty/None and the game stays fully playable text-only.
Gated by IMAGE_ENABLED / VOICE_ENABLED.
"""
import base64

import httpx

from .config import settings
from .providers import base as providers
from .providers import image as image_providers


# ---------- voice-api (local registry back-compat; the engine composes voice
# designs itself now and no longer registers them here) ----------

def list_voice_ids() -> list[str]:
    if not settings.VOICE_ENABLED:
        return []
    try:
        r = httpx.get(f"{settings.VOICE_API_URL}/voices", timeout=5)
        r.raise_for_status()
        return [v["voice_id"] for v in r.json().get("voices", []) if v.get("voice_id")]
    except Exception:
        return []


def register_character_voice(char_id: str, name: str, description: str,
                             gender: str = "") -> str | None:
    """DEPRECATED for the engine (voice identity lives in OUR DB now; see
    integrate/voice.py). Kept for back-compat with anything still calling it."""
    if not settings.VOICE_ENABLED or not (description or name).strip():
        return None
    body = {"id": char_id, "name": name, "description": description}
    if gender:
        body["gender"] = gender
    try:
        r = httpx.post(f"{settings.VOICE_API_URL}/characters", json=body, timeout=10)
        r.raise_for_status()
        return r.json().get("voice_id")
    except Exception:
        return None


def delete_character_voice(char_id: str) -> None:
    """Release a character's legacy registry entry (called on game wipe so old
    voice-api state never piles up). Best-effort."""
    if not settings.VOICE_ENABLED:
        return
    try:
        httpx.delete(f"{settings.VOICE_API_URL}/characters/{char_id}", timeout=5)
    except Exception:
        pass


# ---------- image ----------

def _provider() -> image_providers.ImageProvider:
    return image_providers.get_provider(providers.resolve("image"))


def generate_character_images(descriptor: str, style: str = "", seed: int | None = None) -> dict | None:
    """Returns {face_url, body_front_url, body_side_url, seed} or None."""
    if not settings.IMAGE_ENABLED or not descriptor.strip():
        return None
    try:
        return _provider().character_set(descriptor, style, seed=seed)
    except Exception:
        return None


def fetch_image_bytes(url: str | None) -> bytes | None:
    """Materialize a provider image (data: URL, absolute URL, or a path relative to
    the active image provider's base) so we can persist it per-game."""
    if not url:
        return None
    try:
        if url.startswith("data:"):
            return base64.b64decode(url.split(",", 1)[1])
        if not url.startswith("http"):
            base = providers.resolve("image").base_url
            url = f"{base}{url}"
        r = httpx.get(url, timeout=60)
        r.raise_for_status()
        return r.content
    except Exception:
        return None


def generate_scene_image(prompt: str, seed: int | None = None,
                         width: int | None = None, height: int | None = None,
                         references: list[str] | None = None) -> dict | None:
    """Returns {image_url, ...} or None. Optional; off the turn hot-path by default.
    width/height override the scene defaults (the 'See' snapshot uses a landscape frame).
    references are fetchable image URLs (characters' stored views): providers that
    support them condition the render so existing characters keep their identity;
    providers that don't silently fall back to plain t2i."""
    if not settings.IMAGE_ENABLED or not prompt.strip():
        return None
    try:
        return _provider().generate(
            prompt, (width or settings.IMAGE_SCENE_W, height or settings.IMAGE_SCENE_H),
            seed=seed, references=references)
    except Exception:
        return None
