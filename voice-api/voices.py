"""Voice design + per-character assignment policy.

Maya1 conditions on a natural-language voice description, so a ``voice_id`` is
no longer a preset file name. It is either:

  - a free-form description: ``"Female voice, 30s, soft breathy timbre, calm"``
    (anything with whitespace is taken verbatim), or
  - a named preset from the catalog below: ``"narrator"``, ``"elder_male"``, ...
    convenient short ids for the orchestrator and the frontend.

Assignment composes a description from the character sheet (gender / age /
accent words in the free text) plus hash-picked timbre and personality traits,
so the same character always gets the same distinct voice.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceInfo:
    voice_id: str
    gender: str
    description: str
    label: str


# Short ids the rest of the stack can use without writing prose.
PRESETS: dict[str, tuple[str, str]] = {
    # id -> (gender, description)
    "narrator": ("male", "Male voice, 40s, warm medium pitch, measured storyteller pacing, engaging narrator tone"),
    "narrator_female": ("female", "Female voice, 30s, warm clear pitch, measured storyteller pacing, engaging narrator tone"),
    "elder_male": ("male", "Male voice, 70 years old, deep gravelly pitch, slow deliberate pacing, wise weathered tone"),
    "elder_female": ("female", "Female voice, 70 years old, low warm pitch, slow deliberate pacing, kind weathered tone"),
    "adult_male": ("male", "Male voice, 30s, medium pitch, natural conversational pacing, confident friendly tone"),
    "adult_female": ("female", "Female voice, 30s, medium pitch, natural conversational pacing, confident friendly tone"),
    "young_male": ("male", "Male voice, early 20s, bright energetic pitch, quick pacing, eager playful tone"),
    "young_female": ("female", "Female voice, early 20s, bright high pitch, quick pacing, lively playful tone"),
    "villain_male": ("male", "Male voice, 50s, deep cold pitch, slow menacing pacing, calculating villainous tone"),
    "villain_female": ("female", "Female voice, 40s, low silky pitch, slow menacing pacing, cruel commanding tone"),
    "child": ("female", "Child voice, around 10 years old, high small pitch, quick curious pacing, innocent tone"),
    "brute": ("male", "Male voice, 40s, very deep booming pitch, slow heavy pacing, gruff intimidating tone"),
}


def catalog() -> list[VoiceInfo]:
    return [
        VoiceInfo(voice_id=vid, gender=g, description=d,
                  label=f"{vid.replace('_', ' ').title()} ({g})")
        for vid, (g, d) in sorted(PRESETS.items())
    ]


def resolve_voice(voice_id: str) -> str:
    """Resolve a voice_id to the Maya1 description string.

    Raises ValueError on an id that is neither a preset nor a plausible
    description, so the API can return a clean 400.
    """
    v = (voice_id or "").strip()
    if not v:
        raise ValueError("empty voice_id")
    if v in PRESETS:
        return PRESETS[v][1]
    if any(c.isspace() for c in v):
        return v  # free-form description, pass through
    raise ValueError(f"unknown voice preset: {v!r} (use a preset name or a free-form description)")


# --- per-character assignment policy --------------------------------------

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


def assign_voice(
    *,
    key: str,
    description: str = "",
    gender: str | None = None,
    accent: str | None = None,
    exclude: list[str] | None = None,
) -> tuple[str, float]:
    """Deterministically compose a distinct Maya1 voice description for a new
    character. Stable hash of ``key`` (character id or name) picks the traits, so
    the same character always gets the same voice. ``exclude`` (descriptions
    already in use) bumps the hash until the result is fresh. Returns
    ``(voice_description, default_speed)``; speed is kept for contract
    compatibility (folded into pacing words by the engine).
    """
    d = (description or "").lower()
    female = _has(d, _FEMALE_WORDS)
    male = _has(d, _MALE_WORDS)
    if not gender:
        if female and not male:
            gender = "female"
        elif male and not female:
            gender = "male"
    excluded = set(exclude or [])

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
            return voice, 1.0
    return voice, 1.0  # catalog exhausted for this sheet; reuse is acceptable
