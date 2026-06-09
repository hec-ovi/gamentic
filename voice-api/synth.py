"""Maya1 synthesis engine: llama.cpp generates SNAC tokens, SNAC decodes on CPU.

The 3B Maya1 GGUF runs in a llama.cpp server-vulkan container (the iGPU path
that measured ~realtime on the box); this service builds the prompt, collects
the generated SNAC codec tokens over HTTP and decodes them to 24kHz audio with
the ~80MB SNAC decoder on CPU. Prompt layout (from the maya1 model card):

    [SOH][BOS]<description="..."> text[EOT][EOH][SOA][SOS]

Generated tokens in [128266, 156937] are SNAC codes, 7 per audio frame
(~2048 samples). Generation ends at CODE_END (128258).
"""
from __future__ import annotations

import hashlib
import io
import json
import threading
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf
import torch

import config
import emotion
import voices as voicelib

SOH, BOS, EOT, EOH, SOA, SOS = 128259, 128000, 128009, 128260, 128261, 128257
CODE_END = 128258
SNAC_MIN, SNAC_MAX = 128266, 156937
OFFSET = 128266
FRAME = 7
SAMPLES_PER_FRAME = 2048
WARMUP_SAMPLES = 2048  # SNAC decoder warmup, trimmed from the head
STREAM_WINDOW = 4      # frames per sliding-window decode in streaming mode


class Maya1Engine:
    def __init__(self, base_url: str = config.MAYA1_URL, snac_model: str = config.SNAC_MODEL):
        from snac import SNAC

        self._base = base_url.rstrip("/")
        self._snac = SNAC.from_pretrained(snac_model).eval()
        self._lock = threading.Lock()  # SNAC decode is not thread-safe
        self._client = httpx.Client(timeout=config.MAYA1_TIMEOUT)

    # --- upstream (llama.cpp) ----------------------------------------------

    def upstream_ok(self) -> bool:
        try:
            return self._client.get(f"{self._base}/health").status_code == 200
        except httpx.HTTPError:
            return False

    def _tokenize(self, text: str) -> list[int]:
        r = self._client.post(f"{self._base}/tokenize",
                              json={"content": text, "add_special": False})
        r.raise_for_status()
        return r.json()["tokens"]

    def _prompt_tokens(self, text: str, description: str) -> list[int]:
        formatted = f'<description="{description}"> {text}'
        return [SOH, BOS] + self._tokenize(formatted) + [EOT, EOH, SOA, SOS]

    def _sampling(self) -> dict:
        return {
            "n_predict": config.MAYA1_MAX_TOKENS,
            "temperature": config.MAYA1_TEMPERATURE,
            "top_p": config.MAYA1_TOP_P,
            "repeat_penalty": config.MAYA1_REPEAT_PENALTY,
            "return_tokens": True,
            "cache_prompt": False,
        }

    # --- SNAC decode ---------------------------------------------------------

    def _decode_frames(self, frames: list[list[int]]) -> np.ndarray:
        l1, l2, l3 = [], [], []
        for s in frames:
            c = [(t - OFFSET) % 4096 for t in s]
            l1.append(c[0])
            l2 += [c[1], c[4]]
            l3 += [c[2], c[3], c[5], c[6]]
        codes = [torch.tensor(l, dtype=torch.long).unsqueeze(0) for l in (l1, l2, l3)]
        with self._lock, torch.no_grad():
            return self._snac.decode(codes).squeeze().numpy().astype(np.float32)

    # --- public render --------------------------------------------------------

    def render(self, text: str, voice_id: str, *, speed: float = 1.0,
               base_emotion: str = "neutral") -> np.ndarray:
        """Render a possibly tag-laden line to a single float32 waveform at 24kHz."""
        description = _with_pacing(voicelib.resolve_voice(voice_id), speed)
        prepared = emotion.prepare(text, base_emotion)
        if not emotion.strip_tags(prepared):
            return np.zeros(0, dtype=np.float32)
        try:
            body = {"prompt": self._prompt_tokens(prepared, description), **self._sampling()}
            r = self._client.post(f"{self._base}/completion", json=body)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise UpstreamError(f"maya1 upstream failed: {e}") from e
        toks = r.json().get("tokens", [])
        frames = _frames(toks)
        if not frames:
            raise UpstreamError("maya1 produced no audio frames")
        return self._decode_frames(frames)[WARMUP_SAMPLES:]

    async def render_stream(self, text: str, voice_id: str, *, speed: float = 1.0,
                            base_emotion: str = "neutral"):
        """Yield float32 chunks as frames arrive. Sliding-window decode: each new
        frame is decoded with the previous STREAM_WINDOW-1 frames as context and
        only its own samples are emitted, so chunks join seamlessly while the
        first audio lands after just a few frames (~hundreds of ms)."""
        description = _with_pacing(voicelib.resolve_voice(voice_id), speed)
        prepared = emotion.prepare(text, base_emotion)
        if not emotion.strip_tags(prepared):
            return
        body = {"prompt": self._prompt_tokens(prepared, description),
                **self._sampling(), "stream": True}
        snac_toks: list[int] = []
        emitted = 0  # frames whose samples have been yielded
        async with httpx.AsyncClient(timeout=config.MAYA1_TIMEOUT) as client:
            async with client.stream("POST", f"{self._base}/completion", json=body) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = json.loads(line[6:])
                    for t in payload.get("tokens", []):
                        if t == CODE_END:
                            break
                        if SNAC_MIN <= t <= SNAC_MAX:
                            snac_toks.append(t)
                    total = len(snac_toks) // FRAME
                    while emitted < total:
                        if emitted > 0:  # frame 0 is the decoder warmup, same as the batch trim
                            lo = max(0, emitted + 1 - STREAM_WINDOW)
                            window = [snac_toks[i * FRAME:(i + 1) * FRAME]
                                      for i in range(lo, emitted + 1)]
                            wav = self._decode_frames(window)
                            # left context in the window absorbs the warmup, so the
                            # window's last frame is clean
                            yield wav[-SAMPLES_PER_FRAME:]
                        emitted += 1
                    if payload.get("stop"):
                        return


class UpstreamError(RuntimeError):
    """The maya1 token server is unreachable or returned garbage."""


# --- helpers --------------------------------------------------------------

def _frames(tokens: list[int]) -> list[list[int]]:
    if CODE_END in tokens:
        tokens = tokens[:tokens.index(CODE_END)]
    snac_toks = [t for t in tokens if SNAC_MIN <= t <= SNAC_MAX]
    n = (len(snac_toks) // FRAME) * FRAME
    return [snac_toks[i:i + FRAME] for i in range(0, n, FRAME)]


def _with_pacing(description: str, speed: float) -> str:
    """Maya1 has no numeric speed; fold the contract's speed into pacing words."""
    if speed <= 0.9:
        return f"{description}, slow unhurried pacing"
    if speed >= 1.15:
        return f"{description}, fast urgent pacing"
    return description


def wav_bytes(wav: np.ndarray, sample_rate: int = config.SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, wav, sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def content_hash(*parts: str) -> str:
    h = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return h[:20]


def duration_s(wav: np.ndarray, sample_rate: int = config.SAMPLE_RATE) -> float:
    return round(wav.size / sample_rate, 3) if wav.size else 0.0


def write_wav(wav: np.ndarray, name: str) -> Path:
    config.ensure_dirs()
    path = config.AUDIO_DIR / name
    sf.write(str(path), wav, config.SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return path
