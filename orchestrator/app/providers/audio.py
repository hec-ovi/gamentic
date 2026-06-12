"""Audio provider dialects (docs/shared/inference-providers.md).

One interface: speak(text, voice, emotion) -> (audio bytes, content type).
Emotion routing follows the resolved capability emotion_mode:
  - tags: the tone rides inline with the line, in the dialect's native shape
    (local sends the voice-api's emotion field, which it renders as a Maya1 tag;
    elevenlabs prepends a [tag] v3 audio tag; fal-hosted Maya1 a leading <tag>);
  - instructions: the tone becomes a spoken-style instruction sentence (openai);
  - none: the tone is silently unused (deterministic degradation).

local is the live-tested default (the Maya1 voice-api). The cloud dialects are
implemented against their PUBLISHED schemas with contract tests over mocked HTTP;
live verification = the admin TEST button with a real key.
"""
import httpx

from .base import ProviderConfig, fal_queue_run


class AudioProvider:
    def __init__(self, cfg: ProviderConfig):
        self.cfg = cfg

    def _emotion(self, emotion: str) -> str:
        """Capability gate: a provider with emotion_mode none drops the tone."""
        return (emotion or "").strip() if self.cfg.emotion_mode != "none" else ""

    def speak(self, text: str, voice: str, emotion: str = "",
              game_id: str = "") -> tuple[bytes, str] | None:
        # game_id is a local-manifest concern (ownership-based wav cleanup, owner
        # decision 2026-06-11); cloud dialects have no wav cache to tag and drop it
        raise NotImplementedError


class LocalProvider(AudioProvider):
    """The Maya1 voice-api: POST /voice/speak {text, voice_id, emotion} -> {audio_url},
    then fetch the audio bytes. voice = a designed description (or a preset name)."""

    def speak(self, text, voice, emotion="", game_id=""):
        body: dict = {"text": text}
        if voice:
            body["voice_id"] = voice
        emotion = self._emotion(emotion)
        if emotion:
            body["emotion"] = emotion
        if game_id:
            # the wav's ownership tag: voice-api records filename -> [game_ids] in its
            # manifest so DELETE /voice/games/{gid} frees the wavs only that game claims
            body["game_id"] = game_id
        r = httpx.post(f"{self.cfg.base_url}/voice/speak", json=body, timeout=120)
        r.raise_for_status()
        url = r.json().get("audio_url")
        if not url:
            return None
        full = url if url.startswith("http") else f"{self.cfg.base_url}{url}"
        a = httpx.get(full, timeout=60)
        a.raise_for_status()
        return a.content, "audio/wav"


class OpenAIProvider(AudioProvider):
    """/v1/audio/speech {model, input, voice, instructions}: the emotion is rendered
    as an instruction sentence (their documented steerability channel)."""

    def speak(self, text, voice, emotion="", game_id=""):
        payload: dict = {"model": self.cfg.model, "input": text, "voice": voice}
        emotion = self._emotion(emotion)
        if emotion:
            payload["instructions"] = f"Tone of voice: {emotion}."
        r = httpx.post(f"{self.cfg.base_url}/v1/audio/speech", json=payload,
                       headers={"Authorization": f"Bearer {self.cfg.api_key}"}
                       if self.cfg.api_key else {},
                       timeout=120)
        r.raise_for_status()
        return r.content, r.headers.get("content-type", "audio/mpeg")


class ElevenLabsProvider(AudioProvider):
    """POST /v1/text-to-speech/{voice_id} with the xi-api-key header; the emotion
    rides as an inline [tag] (v3 audio tags). voice = their concrete voice_id."""

    def speak(self, text, voice, emotion="", game_id=""):
        emotion = self._emotion(emotion)
        body = {"text": f"[{emotion}] {text}" if emotion else text,
                "model_id": self.cfg.model}
        r = httpx.post(f"{self.cfg.base_url}/v1/text-to-speech/{voice}", json=body,
                       headers={"xi-api-key": self.cfg.api_key} if self.cfg.api_key else {},
                       timeout=120)
        r.raise_for_status()
        return r.content, r.headers.get("content-type", "audio/mpeg")


class FalProvider(AudioProvider):
    """fal-hosted Maya1 over the queue dialect (fal-ai/maya/batch):
    {texts: [line], prompts: [voice design]} -> audios[0].url -> bytes. The emotion
    is a leading <tag>, identical to Maya1's native angle tags."""

    poll_interval = 1.0
    poll_timeout = 120.0

    def speak(self, text, voice, emotion="", game_id=""):
        emotion = self._emotion(emotion)
        payload = {"texts": [f"<{emotion}> {text}" if emotion else text],
                   "prompts": [voice]}
        result = fal_queue_run(self.cfg, self.cfg.model, payload,
                               timeout=self.poll_timeout, interval=self.poll_interval)
        if not result:
            return None
        first = (result.get("audios") or [{}])[0]
        if not first.get("url"):
            return None
        a = httpx.get(first["url"], timeout=60)
        a.raise_for_status()
        return a.content, first.get("content_type") or "audio/wav"


_PROVIDERS = {"local": LocalProvider, "openai": OpenAIProvider,
              "elevenlabs": ElevenLabsProvider, "fal": FalProvider}


def get_provider(cfg: ProviderConfig) -> AudioProvider:
    cls = _PROVIDERS.get(cfg.provider)
    if not cls:
        raise ValueError(f"unknown audio provider: {cfg.provider!r}")
    return cls(cfg)


def default_voice(cfg: ProviderConfig) -> str:
    """A sensible voice when the caller names none (the admin TEST button, a bare
    /audio/speak): the local preset, a deterministic named voice, or a design."""
    from .. import voice_design
    from ..integrate.voice import NARRATOR_VOICES
    if cfg.provider == "local":
        return "narrator"
    return voice_design.resolve_voice_id(cfg, "default", NARRATOR_VOICES["male"])
