"""Runtime config for the voice service. Everything is overridable by env so the
container and local runs share one source of truth."""
from __future__ import annotations

import os
from pathlib import Path

# Model files (mounted read-only in the container). Defaults match the host layout.
KOKORO_MODEL = os.environ.get("KOKORO_MODEL", "/home/hec/models/kokoro/kokoro-v1.0.onnx")
KOKORO_VOICES = os.environ.get("KOKORO_VOICES", "/home/hec/models/kokoro/voices-v1.0.bin")

# Writable data dir: generated audio, the character registry, and optional real
# vocalization clips that override the synthesized fallbacks.
DATA_DIR = Path(os.environ.get("VOICE_DATA_DIR", str(Path(__file__).parent / "data")))
AUDIO_DIR = DATA_DIR / "audio"
VOCAL_DIR = Path(os.environ.get("VOICE_VOCAL_DIR", str(DATA_DIR / "vocalizations")))
CHARACTERS_FILE = DATA_DIR / "characters.json"

SAMPLE_RATE = 24000  # Kokoro output rate, fixed by the model
DEFAULT_VOICE = os.environ.get("VOICE_DEFAULT", "af_heart")
DEFAULT_LANG = os.environ.get("VOICE_LANG", "en-us")

# onnxruntime intra-op threads. The model is tiny, so a few threads already run
# several times faster than realtime; capping keeps voice a good neighbour to the
# LLM/image work. 0 = let onnxruntime decide (uses all cores).
KOKORO_THREADS = int(os.environ.get("KOKORO_THREADS", "4"))

# How long to keep generated audio before it can be cleaned up (best-effort).
AUDIO_TTL_SECONDS = int(os.environ.get("VOICE_AUDIO_TTL", "3600"))


def ensure_dirs() -> None:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    VOCAL_DIR.mkdir(parents=True, exist_ok=True)
