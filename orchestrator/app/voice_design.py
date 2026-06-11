"""Voice DESIGN + per-provider voice identity (engine-owned).

The composer is ported from voice-api/voices.py: Maya1 conditions on a natural-
language voice description, so each character gets a deterministic, distinct
description composed from their sheet (gender / age / accent words in the free
text) plus hash-picked timbre and personality traits, spaced apart within the
cast. The design is stored on the character row (voice_design) and NEVER moves
with the provider.

Per provider the design resolves to a voice_id the active provider understands:
  - local / fal (Maya1): the design text itself;
  - openai: a deterministic pick from their documented voices, seeded by the
    character id so re-assignment is stable;
  - elevenlabs: a deterministic pick from the configurable AUDIO_VOICE_POOL id
    list, else the design as-is (their voice-design endpoint can take prose).
Switching providers re-resolves every character ONCE and stores the new mapping;
a character never changes voice within a provider.
"""
from __future__ import annotations

import hashlib
import re

# The 11 documented steerable voices of the speech endpoint (gpt-4o-mini-tts).
OPENAI_VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable",
                 "nova", "onyx", "sage", "shimmer", "verse"]


# --- design composition (verbatim port of voice-api/voices.py assign_voice) ---

# Description keywords that bias voice design. Matched as whole words (see
# _has): "male" must NOT fire inside "female", "man" must NOT fire inside "woman".
_OLD_WORDS = ("old", "elder", "ancient", "elderly", "aged", "grandfather", "grandmother", "venerable")
_YOUNG_WORDS = ("young", "child", "girl", "boy", "small", "fairy", "teen", "kid", "little")
_DEEP_WORDS = ("deep", "gravelly", "gruff", "low", "booming", "giant", "ogre", "rough", "husky")
_BRIGHT_WORDS = ("high", "bright", "cheerful", "squeaky", "sweet", "soft")
_MALE_WORDS = ("man", "male", "king", "wizard", "warrior", "lord", "father", "boy", "he", "his", "him", "knight", "monk", "ogre", "dwarf", "prince")
_FEMALE_WORDS = ("woman", "female", "queen", "witch", "lady", "mother", "girl", "she", "her", "hers", "sorceress", "priestess", "maiden", "princess")
_BRITISH_WORDS = ("noble", "royal", "posh", "british", "english", "knight", "lord", "lady", "wizard")
_DARK_WORDS = ("villain", "evil", "dark", "cruel", "sinister", "menacing", "demon", "necromancer", "assassin")

# Trait pools the hash picks from, so different characters with the same sheet
# still sound distinct. Measured on-box (speaker embeddings over interleaved
# lines): DISTINCTIVE descriptions anchor a consistent voice across lines while
# generic ones ("medium pitch, conversational") audibly drift, so every pool
# entry is a strong, specific anchor and same-gender picks are spaced far apart.
_PITCH = {
    "male": ["very deep rumbling bass pitch", "low gravelly rough pitch",
             "rich resonant baritone pitch", "higher clear tenor pitch"],
    "female": ["low smoky husky pitch", "warm mellow rounded pitch",
               "bright crisp clear pitch", "high airy delicate pitch"],
}
_PERSONALITY = [
    "confident steady tone", "warm friendly tone", "dry sardonic tone",
    "earnest sincere tone", "playful mischievous tone", "stern commanding tone",
    "gentle thoughtful tone", "brisk no-nonsense tone",
]
_PACING = ["natural conversational pacing", "measured deliberate pacing", "quick lively pacing"]
_ACCENT = ["American accent", "British accent"]


def _has(text: str, words) -> bool:
    """Whole-word membership test (so 'male' does not match 'female')."""
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def compose_design(
    *,
    key: str,
    description: str = "",
    gender: str | None = None,
    accent: str | None = None,
    exclude: list[str] | None = None,
) -> str:
    """Deterministically compose a distinct Maya1-style voice description for a new
    character. Stable hash of ``key`` (the character id) picks the traits, so the
    same character always gets the same design. ``exclude`` (designs already in use
    within the cast) bumps the hash until the result is fresh."""
    d = (description or "").lower()
    female = _has(d, _FEMALE_WORDS)
    male = _has(d, _MALE_WORDS)
    if not gender:
        if female and not male:
            gender = "female"
        elif male and not female:
            gender = "male"
    excluded = set(exclude or [])

    voice = ""
    for salt in range(8):
        h = int(hashlib.sha256(f"{key}\x1f{salt}".encode("utf-8")).hexdigest(), 16)
        g = gender or ("female" if h % 2 else "male")

        if _has(d, _OLD_WORDS):
            age = "70 years old"
        elif _has(d, _YOUNG_WORDS):
            age = "early 20s"
        else:
            age = ["30s", "40s", "50s"][h // 2 % 3]

        if _has(d, _DEEP_WORDS):
            pitch = "very deep gravelly pitch" if g == "male" else "low smoky pitch"
        elif _has(d, _BRIGHT_WORDS):
            pitch = "bright clear pitch"
        else:
            pitch = _PITCH[g][h // 7 % len(_PITCH[g])]

        if _has(d, _DARK_WORDS):
            personality = "cold menacing tone"
        else:
            personality = _PERSONALITY[h // 31 % len(_PERSONALITY)]

        pacing = _PACING[h // 311 % len(_PACING)]
        # always name an accent: it is one more anchor for cross-line consistency
        if (accent or "").lower() == "british" or (not accent and _has(d, _BRITISH_WORDS)):
            acc = ", British accent"
        elif (accent or "").lower() not in ("", "none"):
            acc = f", {accent} accent"
        else:
            acc = f", {_ACCENT[h // 1009 % len(_ACCENT)]}"

        noun = "Male voice" if g == "male" else "Female voice"
        voice = f"{noun}, {age}, {pitch}, {pacing}, {personality}{acc}"
        if voice not in excluded:
            return voice
    return voice  # pools exhausted for this sheet; reuse is acceptable


# --- per-provider resolution ----------------------------------------------

def _stable_pick(options: list[str], key: str) -> str:
    h = int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16)
    return options[h % len(options)]


def resolve_voice_id(cfg, key: str, design: str) -> str:
    """Resolve a stored design to a voice_id the active audio provider understands.
    Deterministic per (provider, key): re-running never reshuffles a voice."""
    if cfg.provider == "openai":
        return _stable_pick(OPENAI_VOICES, key)
    if cfg.provider == "elevenlabs":
        pool = [v.strip() for v in (cfg.voice_pool or "").split(",") if v.strip()]
        return _stable_pick(pool, key) if pool else design
    return design   # local / fal-hosted Maya1: the design text IS the voice
