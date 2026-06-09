"""Voice catalog + per-character assignment policy.

Kokoro voice ids encode language and gender in the first two letters
(e.g. ``af_heart`` = American/female, ``bm_george`` = British/male). We derive
metadata from that prefix instead of hand-maintaining a table, so the catalog
always matches whatever the loaded voices file actually contains.

A ``voice_id`` accepted everywhere can be either:
  - a plain preset name: ``"af_heart"``
  - a blend spec: ``"af_heart:0.6,am_adam:0.4"`` (weighted mix of style vectors)
The blend form multiplies the ~28 English presets into a much larger space of
distinct character voices without any cloning.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# First letter -> (language label, lang code passed to Kokoro).
_LANG = {
    "a": ("American English", "en-us"),
    "b": ("British English", "en-gb"),
    "e": ("Spanish", "es"),
    "f": ("French", "fr-fr"),
    "h": ("Hindi", "hi"),
    "i": ("Italian", "it"),
    "j": ("Japanese", "ja"),
    "p": ("Brazilian Portuguese", "pt-br"),
    "z": ("Mandarin Chinese", "zh"),
}
_GENDER = {"f": "female", "m": "male"}

# Voices we surface as game-character options by default (English only). Other
# languages stay available by exact id but are hidden from the default catalog.
ENGLISH_PREFIXES = ("af_", "am_", "bf_", "bm_")


@dataclass(frozen=True)
class VoiceInfo:
    voice_id: str
    gender: str
    accent: str
    language: str
    lang_code: str
    label: str  # human-friendly, e.g. "George (British English, male)"


def voice_info(voice_id: str) -> VoiceInfo:
    """Derive metadata for a single preset id from its prefix."""
    lang_letter = voice_id[0:1]
    gender_letter = voice_id[1:2]
    language, lang_code = _LANG.get(lang_letter, ("Unknown", "en-us"))
    gender = _GENDER.get(gender_letter, "neutral")
    accent = language
    name = voice_id.split("_", 1)[-1].capitalize()
    return VoiceInfo(
        voice_id=voice_id,
        gender=gender,
        accent=accent,
        language=language,
        lang_code=lang_code,
        label=f"{name} ({language}, {gender})",
    )


def catalog(all_voice_ids: list[str], english_only: bool = True) -> list[VoiceInfo]:
    ids = sorted(all_voice_ids)
    if english_only:
        ids = [v for v in ids if v.startswith(ENGLISH_PREFIXES)]
    return [voice_info(v) for v in ids]


# --- blend spec parsing ---------------------------------------------------

_BLEND_RE = re.compile(r"^\s*([a-z]{2}_[a-z]+)\s*(?::\s*([0-9]*\.?[0-9]+)\s*)?$")


def parse_voice_id(voice_id: str) -> list[tuple[str, float]]:
    """Parse a voice_id into a list of (preset_name, weight).

    Plain name -> [(name, 1.0)]. Blend -> normalized weights summing to 1.0.
    Raises ValueError on malformed specs so the API can return a clean 400.
    """
    parts = [p for p in voice_id.split(",") if p.strip()]
    if not parts:
        raise ValueError("empty voice_id")
    out: list[tuple[str, float]] = []
    for part in parts:
        m = _BLEND_RE.match(part)
        if not m:
            raise ValueError(f"bad voice spec: {part!r}")
        name = m.group(1)
        weight = float(m.group(2)) if m.group(2) is not None else 1.0
        out.append((name, weight))
    total = sum(w for _, w in out)
    if total <= 0:
        raise ValueError("voice weights sum to zero")
    return [(name, w / total) for name, w in out]


# --- per-character assignment policy --------------------------------------

# Description keywords that bias voice selection and default delivery speed.
# Matched as whole words (see _has): "male" must NOT fire inside "female", and
# "man" must NOT fire inside "woman".
_DEEP_WORDS = ("old", "deep", "gravelly", "gruff", "elder", "ancient", "low", "booming", "giant", "ogre")
_BRIGHT_WORDS = ("young", "child", "high", "bright", "cheerful", "girl", "boy", "small", "fairy", "squeaky")
_MALE_WORDS = ("man", "male", "king", "wizard", "warrior", "lord", "father", "boy", "he", "his", "knight", "monk", "ogre", "dwarf")
_FEMALE_WORDS = ("woman", "female", "queen", "witch", "lady", "mother", "girl", "she", "her", "sorceress", "priestess", "maiden")
_BRITISH_WORDS = ("noble", "royal", "posh", "british", "english", "knight", "lord", "lady", "wizard")


def _has(text: str, words) -> bool:
    """Whole-word membership test (so 'male' does not match 'female')."""
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def _bias_from_description(description: str) -> tuple[str | None, str | None, float]:
    """Return (gender|None, accent_letter|None, speed) inferred from free text."""
    d = description.lower()
    female = _has(d, _FEMALE_WORDS)
    male = _has(d, _MALE_WORDS)
    # Only set a gender when exactly one side matches; ambiguous -> leave to caller/hash.
    gender = None
    if female and not male:
        gender = "female"
    elif male and not female:
        gender = "male"
    accent = "b" if _has(d, _BRITISH_WORDS) else None
    speed = 1.0
    if _has(d, _DEEP_WORDS):
        speed = 0.92
    if _has(d, _BRIGHT_WORDS):
        speed = 1.08
    return gender, accent, speed


def assign_voice(
    all_voice_ids: list[str],
    *,
    key: str,
    description: str = "",
    gender: str | None = None,
    accent: str | None = None,
    exclude: list[str] | None = None,
) -> tuple[str, float]:
    """Deterministically pick a distinct English preset for a new character.

    Selection is a stable hash of ``key`` (character id or name) over the filtered
    candidate list, so the same character always gets the same voice, but different
    characters spread across the catalog. ``exclude`` (already-used voices) is
    avoided when possible. Returns ``(voice_id, default_speed)``.
    """
    exclude = set(exclude or [])
    d_gender, d_accent, speed = _bias_from_description(description)
    gender = gender or d_gender
    accent_letter = {"american": "a", "british": "b"}.get((accent or "").lower(), accent) or d_accent

    cands = [voice_info(v) for v in all_voice_ids if v.startswith(ENGLISH_PREFIXES)]
    if gender:
        g = [c for c in cands if c.gender == gender] or cands
        cands = g
    if accent_letter in ("a", "b"):
        a = [c for c in cands if c.voice_id[0] == accent_letter] or cands
        cands = a
    cands = sorted(cands, key=lambda c: c.voice_id)

    fresh = [c for c in cands if c.voice_id not in exclude] or cands
    h = int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16)
    chosen = fresh[h % len(fresh)]
    return chosen.voice_id, speed
