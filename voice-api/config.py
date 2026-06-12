"""Runtime config for the voice service. Everything is overridable by env so the
container and local runs share one source of truth."""
from __future__ import annotations

import os
from pathlib import Path

# The Maya1 token server: a llama.cpp server-vulkan instance holding the GGUF.
# In compose this is the llm-voice service; locally it is whatever port you ran it on.
MAYA1_URL = os.environ.get("MAYA1_URL", "http://localhost:9091")
MAYA1_TIMEOUT = float(os.environ.get("MAYA1_TIMEOUT", "120"))

# SNAC neural codec decoder (CPU, ~80MB). Resolved through the HF cache; the
# Docker image bakes the weights in so the container never hits the network.
SNAC_MODEL = os.environ.get("SNAC_MODEL", "hubertsiuzdak/snac_24khz")

# Sampling defaults from the maya1 model card.
MAYA1_TEMPERATURE = float(os.environ.get("MAYA1_TEMPERATURE", "0.4"))
MAYA1_TOP_P = float(os.environ.get("MAYA1_TOP_P", "0.9"))
MAYA1_REPEAT_PENALTY = float(os.environ.get("MAYA1_REPEAT_PENALTY", "1.1"))
MAYA1_MAX_TOKENS = int(os.environ.get("MAYA1_MAX_TOKENS", "2048"))

# Writable data dir: generated audio and the character registry.
DATA_DIR = Path(os.environ.get("VOICE_DATA_DIR", str(Path(__file__).parent / "data")))
AUDIO_DIR = DATA_DIR / "audio"
CHARACTERS_FILE = DATA_DIR / "characters.json"
# Game -> wav ownership manifest, beside the wavs it describes (deletion
# contract 2026-06-11: ownership-based deletion, no retention timers).
MANIFEST_FILE = AUDIO_DIR / "games.json"

SAMPLE_RATE = 24000  # SNAC 24kHz codec, fixed by the model
DEFAULT_VOICE = os.environ.get(
    "VOICE_DEFAULT",
    "Male voice, 40s, warm medium pitch, measured storyteller pacing, engaging narrator tone")

def ensure_dirs() -> None:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
