"""Inline emotion tags for Maya1.

The game (and the SPECS contract) writes emotion as ``[tag]`` markers in the
line. Maya1 understands native inline ``<tag>`` markers, so this layer is now a
thin translation instead of an approximation: ``[angry]`` becomes ``<angry>``,
aliases collapse onto the model's vocabulary, and anything the model does not
know is dropped so it is never read aloud.

Two Maya1 gotchas encoded here (both observed on the box):
  - Tags are single inline markers. A closing ``</whisper>`` is NOT syntax; the
    model speaks it as the word "whisper". So only opening forms are emitted.
  - ``[pause]`` has no Maya1 tag; an ellipsis produces a natural beat instead.
"""
from __future__ import annotations

import re

# Maya1's native inline tags (the documented set we rely on; verified on-box:
# laugh, giggle, whisper, angry, gasp, scream).
NATIVE = {
    "laugh", "giggle", "chuckle", "sigh", "whisper",
    "angry", "gasp", "cry", "scream", "excited", "sad",
}

# Friendly aliases from game text onto the native vocabulary.
ALIASES = {
    "laughing": "laugh", "laughs": "laugh", "lol": "laugh",
    "sighs": "sigh", "gasps": "gasp",
    "sob": "cry", "sobbing": "cry", "crying": "cry",
    "screaming": "scream", "shout": "scream", "yell": "scream",
    "yelling": "scream", "shouting": "scream",
    "whispering": "whisper", "furious": "angry", "mad": "angry",
    "happy": "excited", "joyful": "excited",
    "scared": "gasp", "afraid": "gasp", "terrified": "gasp",
}

_TAG_RE = re.compile(r"\[([a-zA-Z]+)(?::([0-9]+))?\]")
_MAYA_TAG_RE = re.compile(r"</?([a-zA-Z_]+)>")


def canonical(tag: str) -> str | None:
    """Map a raw tag word to a native Maya1 tag, or None if unsupported."""
    t = tag.lower()
    t = ALIASES.get(t, t)
    return t if t in NATIVE else None


def prepare(text: str, base_emotion: str = "neutral") -> str:
    """Turn game text into Maya1 input: translate ``[tag]`` markers, sanitize any
    raw ``<tag>`` the LLM may have emitted itself, and lead with the base emotion
    when it maps to a native tag."""

    def replace(m: re.Match) -> str:
        raw = m.group(1).lower()
        if raw == "pause":
            return "..."
        tag = canonical(raw)
        return f"<{tag}>" if tag else ""

    def sanitize(m: re.Match) -> str:
        # keep valid opening tags, drop closing/unknown forms entirely
        if m.group(0).startswith("</"):
            return ""
        return m.group(0) if m.group(1).lower() in NATIVE else ""

    out = _MAYA_TAG_RE.sub(sanitize, _TAG_RE.sub(replace, text))
    out = re.sub(r"[ \t]{2,}", " ", out).strip()
    base = canonical(base_emotion)
    if base and f"<{base}>" not in out:
        out = f"<{base}> {out}"
    return out


def strip_tags(text: str) -> str:
    """Plain text with every ``[tag]`` and ``<tag>`` removed. For logs/captions."""
    return re.sub(r"[ \t]{2,}", " ", _MAYA_TAG_RE.sub("", _TAG_RE.sub("", text))).strip()
