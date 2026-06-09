"""Emotion approximation for a non-expressive engine.

Kokoro has no native emotion tags, so we approximate at the service layer. Text
may contain inline ``[tag]`` markers. Two kinds:

  - TONE tags set the delivery of the speech that follows (speed + gain), until
    the next tone tag or end of line: ``[angry] [sad] [happy] [excited]
    [whisper] [shout] [scared] [calm] [neutral]``.
  - VOCALIZATION tags insert a short non-speech sound in place:
    ``[laugh] [chuckle] [sigh] [gasp] [cough] [sob] [scream]`` plus ``[pause]``.
    If a real clip exists in the vocalizations dir (e.g. ``laugh.wav``) it is used;
    otherwise we synth a crude onomatopoeia fallback. Drop in real clips for quality.

The parser turns a line into an ordered list of ops the synth engine renders and
concatenates. Unknown ``[...]`` markers are dropped so they are never spoken.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# tone -> (speed multiplier, gain in dB)
TONE = {
    "neutral": (1.00, 0.0),
    "calm": (0.96, -1.0),
    "happy": (1.06, 1.0),
    "excited": (1.15, 2.0),
    "angry": (1.10, 3.0),
    "shout": (1.08, 4.0),
    "scared": (1.12, 0.0),
    "sad": (0.88, -2.0),
    "whisper": (0.95, -8.0),
}

# vocalization -> (onomatopoeia text, speed) synth fallback when no clip file exists
VOCAL = {
    "laugh": ("Ha ha ha ha!", 1.05),
    "chuckle": ("Heh heh.", 0.98),
    "sigh": ("Haaah.", 0.7),
    "gasp": ("Ah!", 1.1),
    "cough": ("Khh, khh.", 1.0),
    "sob": ("Huh, huh, huh.", 0.85),
    "scream": ("Aaaah!", 1.1),
}

# Some friendly aliases map onto the canonical tags above.
ALIASES = {
    "laughing": "laugh", "laughs": "laugh", "lol": "laugh",
    "sighs": "sigh", "gasps": "gasp", "coughs": "cough",
    "crying": "sob", "sobbing": "sob", "screaming": "scream",
    "yell": "shout", "yelling": "shout", "shouting": "shout",
    "whispering": "whisper", "furious": "angry", "mad": "angry",
    "afraid": "scared", "terrified": "scared", "joyful": "happy",
}

# A bare [pause] or [pause:500] inserts silence (default 350ms, or N ms).
DEFAULT_PAUSE_MS = 350

_TAG_RE = re.compile(r"\[([a-zA-Z]+)(?::([0-9]+))?\]")


@dataclass
class Speak:
    text: str
    speed_mult: float
    gain_db: float


@dataclass
class Vocal:
    tag: str  # canonical vocalization name


@dataclass
class Silence:
    ms: int


Op = Speak | Vocal | Silence


def parse(text: str, base_tone: str = "neutral") -> list[Op]:
    """Parse a line into render ops. ``base_tone`` seeds the delivery (a character's
    default emotion) before any inline tag overrides it."""
    speed, gain = TONE.get(base_tone, TONE["neutral"])
    ops: list[Op] = []
    pos = 0
    buf: list[str] = []

    def flush():
        chunk = "".join(buf).strip()
        buf.clear()
        if chunk:
            ops.append(Speak(text=chunk, speed_mult=speed, gain_db=gain))

    for m in _TAG_RE.finditer(text):
        buf.append(text[pos:m.start()])
        pos = m.end()
        raw = m.group(1).lower()
        arg = m.group(2)
        tag = ALIASES.get(raw, raw)
        if tag == "pause":
            flush()
            ops.append(Silence(ms=int(arg) if arg else DEFAULT_PAUSE_MS))
        elif tag in TONE:
            flush()
            speed, gain = TONE[tag]
        elif tag in VOCAL:
            flush()
            ops.append(Vocal(tag=tag))
        # unknown tag -> dropped (not appended to buf), never spoken
    buf.append(text[pos:])
    flush()
    if not ops:  # all-tags or empty input: emit nothing speakable
        return []
    return ops


def strip_tags(text: str) -> str:
    """Plain text with every ``[tag]`` removed. Useful for logging / captions."""
    return _TAG_RE.sub("", text).strip()
