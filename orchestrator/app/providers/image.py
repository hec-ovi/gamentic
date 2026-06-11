"""Image provider dialects (docs/shared/inference-providers.md).

One interface: generate(prompt, size, seed=None, references=None) -> {image_url}
plus character_set(descriptor, style) -> {face_url, body_front_url, body_side_url}.
references are fetchable image URLs; providers that take bytes download them.
Providers that return raw image data hand back a data: URL, which the engine's
persistence path (media.fetch_image_bytes) decodes like any other image source.

Capability degradation is deterministic and silent: no references -> plain t2i
(identity softens, nothing breaks); no seed -> the seed is simply unused.

comfy is the live-tested local default (the exact behavior media.py always had).
The cloud dialects (openai, gemini, fal) are implemented against their PUBLISHED
schemas with contract tests over mocked HTTP; live verification = the admin TEST
button with a real key.
"""
import base64
import math

import httpx

from .base import ProviderConfig, fal_queue_run

# View prompts for the cloud character_set path. The comfy unit owns its own
# 3-view prompting server-side; these only exist for providers without it.
_FACE_VIEW = ("head and shoulders portrait of {d}, facing the viewer, "
              "neutral plain background")
_FRONT_VIEW = ("full body shot of {d}, standing, front view, whole figure visible "
               "head to feet, neutral plain background")
_SIDE_VIEW = ("full body shot of {d}, standing, side profile view, whole figure "
              "visible head to feet, neutral plain background")
_FACE_SIZE = (1024, 1024)
_BODY_SIZE = (1024, 1536)


def _ref_bytes(ref: str) -> bytes | None:
    """Materialize one reference (URL or data: URL) as bytes for providers that
    upload references instead of fetching them. Best-effort."""
    if not ref:
        return None
    try:
        if ref.startswith("data:"):
            return base64.b64decode(ref.split(",", 1)[1])
        r = httpx.get(ref, timeout=30)
        r.raise_for_status()
        return r.content
    except Exception:
        return None


class ImageProvider:
    def __init__(self, cfg: ProviderConfig):
        self.cfg = cfg

    @property
    def supports_seed(self) -> bool:
        return self.cfg.supports_seed

    @property
    def supports_references(self) -> bool:
        return self.cfg.supports_references

    def _degrade(self, seed, references):
        """Silently drop what the provider cannot honor."""
        return (seed if self.supports_seed else None,
                references if self.supports_references else None)

    def generate(self, prompt: str, size: tuple[int, int],
                 seed: int | None = None, references: list | None = None) -> dict | None:
        raise NotImplementedError

    def character_set(self, descriptor: str, style: str = "",
                      seed: int | None = None) -> dict | None:
        """Cloud default: reference-path identity when the provider takes references
        (generate the face, then condition front/side on it); otherwise three
        independent t2i calls (degraded: identity softens, nothing breaks)."""
        styled = f"{descriptor}. {style}".strip(". ") if style else descriptor
        face = self.generate(_FACE_VIEW.format(d=styled), _FACE_SIZE, seed=seed)
        if not face or not face.get("image_url"):
            return None
        refs = [face["image_url"]] if self.supports_references else None
        front = self.generate(_FRONT_VIEW.format(d=styled), _BODY_SIZE,
                              seed=seed, references=refs)
        side = self.generate(_SIDE_VIEW.format(d=styled), _BODY_SIZE,
                             seed=seed, references=refs)
        return {"face_url": face.get("image_url"),
                "body_front_url": (front or {}).get("image_url"),
                "body_side_url": (side or {}).get("image_url"),
                "seed": seed}


class ComfyProvider(ImageProvider):
    """Our image-api contract (template adapter in front of ComfyUI). The tested
    default; the request shapes are EXACTLY what media.py always sent."""

    def generate(self, prompt, size, seed=None, references=None):
        seed, references = self._degrade(seed, references)
        w, h = size
        body: dict = {"prompt": prompt, "width": w, "height": h}
        if references:
            body["references"] = references
        if seed is not None:
            body["seed"] = seed
        r = httpx.post(f"{self.cfg.base_url}/image/generate", json=body, timeout=120)
        r.raise_for_status()
        return r.json()

    def character_set(self, descriptor, style="", seed=None):
        # Character view sizing (square face vs tall full-body) is owned by the
        # image-api per view; the orchestrator only describes the character.
        body: dict = {"descriptor": descriptor, "style": style}
        if seed is not None:
            body["seed"] = seed
        # 3 images; generous time since this runs in a background task.
        r = httpx.post(f"{self.cfg.base_url}/image/character", json=body, timeout=300)
        r.raise_for_status()
        return r.json()


class OpenAIProvider(ImageProvider):
    """/v1/images/generations, switching to /v1/images/edits (multipart, image[]
    files, up to 16) when references are given. Returns b64 by dialect default."""

    _TIMEOUT = 180

    def _headers(self):
        return {"Authorization": f"Bearer {self.cfg.api_key}"} if self.cfg.api_key else {}

    @staticmethod
    def _snap_size(size) -> str:
        """The API takes fixed sizes; snap our WxH to the nearest supported frame."""
        w, h = size
        if w > h:
            return "1536x1024"
        if h > w:
            return "1024x1536"
        return "1024x1024"

    @staticmethod
    def _parse(data: dict) -> dict | None:
        first = (data.get("data") or [{}])[0]
        if first.get("b64_json"):
            return {"image_url": f"data:image/png;base64,{first['b64_json']}"}
        if first.get("url"):
            return {"image_url": first["url"]}
        return None

    def generate(self, prompt, size, seed=None, references=None):
        seed, references = self._degrade(seed, references)
        fields = {"model": self.cfg.model, "prompt": prompt,
                  "size": self._snap_size(size), "n": 1}
        files = []
        for i, ref in enumerate((references or [])[:16]):
            data = _ref_bytes(ref)
            if data:
                files.append(("image[]", (f"ref-{i}.png", data, "image/png")))
        if files:        # the edits endpoint is multipart per the published schema
            r = httpx.post(f"{self.cfg.base_url}/v1/images/edits",
                           data={k: str(v) for k, v in fields.items()}, files=files,
                           headers=self._headers(), timeout=self._TIMEOUT)
        else:
            r = httpx.post(f"{self.cfg.base_url}/v1/images/generations",
                           json=fields, headers=self._headers(), timeout=self._TIMEOUT)
        r.raise_for_status()
        return self._parse(r.json())


class GeminiProvider(ImageProvider):
    """generateContent parts dialect (nano banana family): one text part plus
    inline_data image parts for references; the image comes back as an inline
    blob inside the response candidates. No seed."""

    _TIMEOUT = 180

    def generate(self, prompt, size, seed=None, references=None):
        seed, references = self._degrade(seed, references)   # seed silently unused
        parts: list = [{"text": prompt}]
        for ref in (references or [])[:14]:                  # documented reference cap
            data = _ref_bytes(ref)
            if data:
                parts.append({"inline_data": {
                    "mime_type": "image/png",
                    "data": base64.b64encode(data).decode("ascii")}})
        r = httpx.post(
            f"{self.cfg.base_url}/v1beta/models/{self.cfg.model}:generateContent",
            json={"contents": [{"parts": parts}]},
            headers={"x-goog-api-key": self.cfg.api_key} if self.cfg.api_key else {},
            timeout=self._TIMEOUT)
        r.raise_for_status()
        for cand in r.json().get("candidates") or []:
            for part in (cand.get("content") or {}).get("parts") or []:
                blob = part.get("inlineData") or part.get("inline_data") or {}
                if blob.get("data"):
                    mime = blob.get("mimeType") or blob.get("mime_type") or "image/png"
                    return {"image_url": f"data:{mime};base64,{blob['data']}"}
        return None


# nano-banana-2's documented aspect_ratio enum (subset we can sensibly map onto).
_FAL_ASPECTS = ("21:9", "16:9", "3:2", "4:3", "5:4", "1:1", "4:5", "3:4", "2:3", "9:16")


class FalProvider(ImageProvider):
    """fal queue dialect with a small per-model parameter map:
    fal-ai/nano-banana-2 speaks {prompt, aspect_ratio, resolution, num_images, seed};
    openai/gpt-image-2 speaks {prompt, image_size, quality, num_images}."""

    poll_interval = 1.0
    poll_timeout = 180.0

    @staticmethod
    def _aspect(size) -> str:
        w, h = size
        target = math.log(w / h)
        return min(_FAL_ASPECTS,
                   key=lambda a: abs(math.log(int(a.split(":")[0]) / int(a.split(":")[1]))
                                     - target))

    def _payload(self, prompt, size, seed) -> dict:
        model = self.cfg.model or ""
        if "gpt-image" in model:
            w, h = size
            return {"prompt": prompt, "image_size": {"width": w, "height": h},
                    "quality": "high", "num_images": 1}
        # nano-banana-2 and the default map
        p: dict = {"prompt": prompt, "aspect_ratio": self._aspect(size),
                   "resolution": "1K", "num_images": 1}
        if seed is not None:
            p["seed"] = seed
        return p

    def generate(self, prompt, size, seed=None, references=None):
        seed, references = self._degrade(seed, references)   # no refs in either map
        result = fal_queue_run(self.cfg, self.cfg.model, self._payload(prompt, size, seed),
                               timeout=self.poll_timeout, interval=self.poll_interval)
        if not result:
            return None
        first = (result.get("images") or [{}])[0]
        return {"image_url": first["url"]} if first.get("url") else None


_PROVIDERS = {"comfy": ComfyProvider, "openai": OpenAIProvider,
              "gemini": GeminiProvider, "fal": FalProvider}


def get_provider(cfg: ProviderConfig) -> ImageProvider:
    cls = _PROVIDERS.get(cfg.provider)
    if not cls:
        raise ValueError(f"unknown image provider: {cfg.provider!r}")
    return cls(cfg)
