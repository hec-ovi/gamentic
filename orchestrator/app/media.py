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


def register_character_voice(char_id: str, name: str, description: str,
                             gender: str = "") -> str | None:
    """Maya1 registry: one character = one stored, DESIGNED voice, composed from the sheet
    (gender, age, pitch, tone, accent) and spaced from voices already in use. Idempotent
    per id (re-posting never reshuffles). Returns the composed voice_id, or None."""
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
    """Release a character's registry entry (called on game wipe). Best-effort."""
    if not settings.VOICE_ENABLED:
        return
    try:
        httpx.delete(f"{settings.VOICE_API_URL}/characters/{char_id}", timeout=5)
    except Exception:
        pass


# ---------- image-api ----------

def generate_character_images(descriptor: str, style: str = "", seed: int | None = None) -> dict | None:
    """Returns {face_url, body_front_url, body_side_url, seed} or None."""
    if not settings.IMAGE_ENABLED or not descriptor.strip():
        return None
    # Character view sizing (square face vs tall full-body) is owned by the image-api per view,
    # configured on its side. The orchestrator only describes the character; it does not dictate
    # sizes here (that would force one size on all views). See docs/image-agent-contract.md.
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


def generate_scene_image(prompt: str, seed: int | None = None,
                         width: int | None = None, height: int | None = None,
                         references: list[str] | None = None) -> dict | None:
    """Returns {image_url, ...} or None. Optional; off the turn hot-path by default.
    width/height override the scene defaults (the 'See' snapshot uses a landscape frame).
    references are fetchable image URLs (characters' stored views): the image-api
    conditions the render on them so existing characters keep their identity."""
    if not settings.IMAGE_ENABLED or not prompt.strip():
        return None
    body: dict = {"prompt": prompt, "width": width or settings.IMAGE_SCENE_W,
                  "height": height or settings.IMAGE_SCENE_H}
    if references:
        body["references"] = references
    if seed is not None:
        body["seed"] = seed
    try:
        r = httpx.post(f"{settings.IMAGE_API_URL}/image/generate", json=body, timeout=120)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None
