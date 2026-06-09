"""Kokoro synthesis engine: voice resolution, emotion-op rendering, caching.

The engine loads the model once and is shared across requests. onnxruntime's
Run is thread-safe, but kokoro-onnx builds per-call state, so we guard create()
with a lock; synthesis is fast enough that the lock is never a real bottleneck
for a single-player game.
"""
from __future__ import annotations

import hashlib
import io
import threading
from pathlib import Path

import numpy as np
import soundfile as sf

import config
import emotion
import voices as voicelib


class KokoroEngine:
    def __init__(self, model: str = config.KOKORO_MODEL, voices_file: str = config.KOKORO_VOICES,
                 threads: int | None = None):
        from kokoro_onnx import Kokoro

        threads = config.KOKORO_THREADS if threads is None else threads
        if threads and threads > 0:
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = threads
            opts.inter_op_num_threads = 1
            sess = ort.InferenceSession(model, sess_options=opts, providers=["CPUExecutionProvider"])
            self._k = Kokoro.from_session(sess, voices_file)
        else:
            self._k = Kokoro(model, voices_file)
        self._lock = threading.Lock()
        self._style_cache: dict[str, np.ndarray] = {}
        self._vocal_cache: dict[str, np.ndarray] = {}
        self._available = set(self._k.get_voices())

    # --- voice resolution -------------------------------------------------

    def available_voices(self) -> list[str]:
        return sorted(self._available)

    def _style_for(self, voice_id: str) -> np.ndarray | str:
        """Resolve a voice_id to a Kokoro voice arg: a plain name passes through
        as a str; a blend spec returns a weighted-sum style ndarray."""
        parts = voicelib.parse_voice_id(voice_id)  # may raise ValueError
        for name, _ in parts:
            if name not in self._available:
                raise ValueError(f"unknown voice: {name!r}")
        if len(parts) == 1 and parts[0][1] == 1.0:
            return parts[0][0]  # plain name, let kokoro handle it
        key = voice_id
        if key not in self._style_cache:
            blend = None
            for name, w in parts:
                s = self._k.get_voice_style(name).astype(np.float32) * np.float32(w)
                blend = s if blend is None else blend + s
            self._style_cache[key] = blend
        return self._style_cache[key]

    # --- low-level synth --------------------------------------------------

    def _create(self, text: str, voice, speed: float, lang: str) -> np.ndarray:
        with self._lock:
            samples, _sr = self._k.create(text, voice=voice, speed=speed, lang=lang)
        return np.asarray(samples, dtype=np.float32)

    def _vocalization(self, tag: str, voice, lang: str) -> np.ndarray:
        """A real clip from the vocalizations dir if present, else a cached synth
        fallback. Real clips win and are voice-independent; the fallback is keyed
        per voice so it matches the speaker."""
        clip = config.VOCAL_DIR / f"{tag}.wav"
        if clip.exists():
            data, sr = sf.read(str(clip), dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)
            return _resample(np.asarray(data, dtype=np.float32), sr, config.SAMPLE_RATE)
        key = f"{tag}:{_voice_key(voice)}"
        if key not in self._vocal_cache:
            phrase, vspeed = emotion.VOCAL[tag]
            self._vocal_cache[key] = self._create(phrase, voice, vspeed, lang)
        return self._vocal_cache[key]

    # --- public render ----------------------------------------------------

    def render(
        self,
        text: str,
        voice_id: str,
        *,
        speed: float = 1.0,
        base_emotion: str = "neutral",
        lang: str | None = None,
    ) -> np.ndarray:
        """Render a possibly tag-laden line to a single float32 waveform at 24kHz."""
        voice = self._style_for(voice_id)
        lang = lang or _lang_for(voice_id)
        ops = emotion.parse(text, base_tone=base_emotion)
        if not ops:
            return np.zeros(0, dtype=np.float32)
        gap = np.zeros(int(0.06 * config.SAMPLE_RATE), dtype=np.float32)  # 60ms between ops
        pieces: list[np.ndarray] = []
        for op in ops:
            if isinstance(op, emotion.Speak):
                wav = self._create(op.text, voice, speed * op.speed_mult, lang)
                wav = _apply_gain(wav, op.gain_db)
            elif isinstance(op, emotion.Vocal):
                wav = self._vocalization(op.tag, voice, lang)
            else:  # Silence
                wav = np.zeros(int(op.ms / 1000 * config.SAMPLE_RATE), dtype=np.float32)
            if pieces:
                pieces.append(gap)
            pieces.append(wav)
        return np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.float32)

    async def render_stream(self, text: str, voice_id: str, *, speed: float = 1.0,
                            base_emotion: str = "neutral", lang: str | None = None):
        """Yield float32 chunks as they are produced. Tone is applied per chunk;
        vocalizations/silences are emitted whole. First chunk arrives fast, which
        is what makes playback feel near-instant."""
        voice = self._style_for(voice_id)
        lang = lang or _lang_for(voice_id)
        for op in emotion.parse(text, base_tone=base_emotion):
            if isinstance(op, emotion.Speak):
                with self._lock:
                    agen = self._k.create_stream(op.text, voice=voice,
                                                 speed=speed * op.speed_mult, lang=lang)
                    async for samples, _sr in agen:
                        yield _apply_gain(np.asarray(samples, dtype=np.float32), op.gain_db)
            elif isinstance(op, emotion.Vocal):
                yield self._vocalization(op.tag, voice, lang)
            else:
                yield np.zeros(int(op.ms / 1000 * config.SAMPLE_RATE), dtype=np.float32)


# --- helpers --------------------------------------------------------------

def _apply_gain(wav: np.ndarray, gain_db: float) -> np.ndarray:
    if gain_db == 0.0 or wav.size == 0:
        return wav
    factor = float(10.0 ** (gain_db / 20.0))
    return np.clip(wav * factor, -1.0, 1.0).astype(np.float32)


def _resample(wav: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr or wav.size == 0:
        return wav
    n = int(round(wav.size * dst_sr / src_sr))
    x = np.linspace(0.0, 1.0, num=wav.size, endpoint=False)
    xi = np.linspace(0.0, 1.0, num=n, endpoint=False)
    return np.interp(xi, x, wav).astype(np.float32)


def _voice_key(voice) -> str:
    if isinstance(voice, str):
        return voice
    return hashlib.sha1(np.ascontiguousarray(voice).tobytes()).hexdigest()[:12]


def _lang_for(voice_id: str) -> str:
    first = voicelib.parse_voice_id(voice_id)[0][0]
    return voicelib.voice_info(first).lang_code


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
