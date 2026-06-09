"""Best-effort clients for the accessory media services (image-api, voice-api).

Every call is wrapped so a missing/slow/erroring service NEVER breaks the game:
on any failure these return empty/None and the game stays fully playable text-only.
Gated by IMAGE_ENABLED / VOICE_ENABLED.
"""
import httpx

from .config import settings


# ---------- voice-api ----------

def list_voice_ids() -> list[str]:
    if not settings.VOICE_ENABLED:
        return []
    try:
        r = httpx.get(f"{settings.VOICE_API_URL}/voices", timeout=5)
        r.raise_for_status()
        return [v["voice_id"] for v in r.json().get("voices", []) if v.get("voice_id")]
    except Exception:
        return []


# ---------- image-api ----------

def generate_character_images(descriptor: str, style: str = "", seed: int | None = None) -> dict | None:
    """Returns {face_url, body_front_url, body_side_url, seed} or None."""
    if not settings.IMAGE_ENABLED or not descriptor.strip():
        return None
    body: dict = {"descriptor": descriptor, "style": style}
    if seed is not None:
        body["seed"] = seed
    try:
        # 3 images; allow generous time since this runs in a background task.
        r = httpx.post(f"{settings.IMAGE_API_URL}/image/character", json=body, timeout=300)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def fetch_image_bytes(url: str | None) -> bytes | None:
    """Download an image-api image (relative or absolute URL) so we can persist it per-game."""
    if not url:
        return None
    full = url if url.startswith("http") else f"{settings.IMAGE_API_URL}{url}"
    try:
        r = httpx.get(full, timeout=60)
        r.raise_for_status()
        return r.content
    except Exception:
        return None


def generate_scene_image(prompt: str, seed: int | None = None) -> dict | None:
    """Returns {image_url, ...} or None. Optional; off the turn hot-path by default."""
    if not settings.IMAGE_ENABLED or not prompt.strip():
        return None
    body: dict = {"prompt": prompt, "width": settings.IMAGE_SCENE_W, "height": settings.IMAGE_SCENE_H}
    if seed is not None:
        body["seed"] = seed
    try:
        r = httpx.post(f"{settings.IMAGE_API_URL}/image/generate", json=body, timeout=120)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None
