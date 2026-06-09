"""Pure-unit tests: tag translation, voice design, frame unpacking. No model,
no upstream needed."""
from __future__ import annotations

import pytest

import emotion
import synth
import voices


# --- emotion.prepare ------------------------------------------------------

def test_game_tags_become_maya_tags():
    assert emotion.prepare("[angry] Get out!") == "<angry> Get out!"
    assert emotion.prepare("Ha! [laugh] Classic.") == "Ha! <laugh> Classic."


def test_aliases_collapse_to_native_vocabulary():
    assert emotion.prepare("[shout] Charge!") == "<scream> Charge!"
    assert emotion.prepare("[sob] It's over.") == "<cry> It's over."
    assert emotion.prepare("[happy] We won!") == "<excited> We won!"


def test_unknown_tags_are_dropped_not_spoken():
    assert emotion.prepare("[flibber] Hello [wobble] there") == "Hello there"


def test_pause_becomes_a_beat():
    assert emotion.prepare("Wait. [pause] Listen.") == "Wait. ... Listen."
    assert emotion.prepare("Wait. [pause:800] Listen.") == "Wait. ... Listen."


def test_closing_maya_tags_are_sanitized():
    # observed on-box: the model READS closing tags aloud ("...whisper"), so they
    # must never reach it, even if the game LLM emits them directly
    assert emotion.prepare("<whisper> quiet </whisper> now") == "<whisper> quiet now"


def test_unknown_raw_maya_tags_are_sanitized():
    assert emotion.prepare("<explode> boom") == "boom"


def test_base_emotion_prepends_once():
    assert emotion.prepare("Hello.", "angry") == "<angry> Hello."
    # already present inline -> not doubled
    assert emotion.prepare("[angry] Hello.", "angry") == "<angry> Hello."
    # unsupported base tones add nothing
    assert emotion.prepare("Hello.", "neutral") == "Hello."
    assert emotion.prepare("Hello.", "sarcastic") == "Hello."


def test_strip_tags_for_captions():
    assert emotion.strip_tags("[angry] Get <laugh> out [pause]") == "Get out"


# --- voices ----------------------------------------------------------------

def test_resolve_preset_and_freeform():
    assert voices.resolve_voice("narrator").startswith("Male voice")
    free = "Robot voice, monotone, clipped delivery"
    assert voices.resolve_voice(free) == free


def test_resolve_rejects_unknown_single_word():
    with pytest.raises(ValueError):
        voices.resolve_voice("af_heart")  # old kokoro ids are no longer valid
    with pytest.raises(ValueError):
        voices.resolve_voice("")


def test_assignment_is_deterministic():
    a1, _ = voices.assign_voice(key="npc-1", description="a young female bard")
    a2, _ = voices.assign_voice(key="npc-1", description="a young female bard")
    assert a1 == a2


def test_assignment_reads_the_character_sheet():
    v, _ = voices.assign_voice(key="x", description="an old gravelly wizard king")
    assert v.startswith("Male voice, 70 years old")
    assert "British accent" in v  # "wizard" is a british-flavored word
    v2, _ = voices.assign_voice(key="y", description="a young female rogue")
    assert v2.startswith("Female voice, early 20s")
    v3, _ = voices.assign_voice(key="z", description="an evil necromancer queen")
    assert v3.startswith("Female voice")
    assert "menacing" in v3


def test_assignment_avoids_used_voices():
    used = []
    for i in range(4):
        v, _ = voices.assign_voice(key="same-sheet", description="a male warrior", exclude=used)
        assert v not in used
        used.append(v)


def test_gender_word_boundaries():
    v, _ = voices.assign_voice(key="k", description="a female warrior")  # "male" inside "female"
    assert v.startswith("Female voice")


# --- synth helpers ----------------------------------------------------------

def test_frames_truncate_at_code_end_and_partials():
    toks = [synth.SNAC_MIN + i for i in range(16)]  # 2 full frames + 2 leftovers
    assert len(synth._frames(toks)) == 2
    with_end = toks[:7] + [synth.CODE_END] + toks[7:]
    assert len(synth._frames(with_end)) == 1  # everything after CODE_END ignored


def test_frames_ignore_non_snac_tokens():
    toks = [1, 2, 3] + [synth.SNAC_MIN + i for i in range(7)] + [99]
    assert len(synth._frames(toks)) == 1


def test_speed_pacing_fold():
    assert "slow unhurried pacing" in synth._with_pacing("X", 0.8)
    assert "fast urgent pacing" in synth._with_pacing("X", 1.3)
    assert synth._with_pacing("X", 1.0) == "X"
