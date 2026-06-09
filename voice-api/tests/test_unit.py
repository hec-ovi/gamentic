"""Pure-unit tests for the tag parser and voice policy. No model required."""
from __future__ import annotations

import emotion as emo
import voices as voicelib


def test_tone_tag_sets_delivery():
    ops = emo.parse("[angry] How dare you")
    assert len(ops) == 1
    assert isinstance(ops[0], emo.Speak)
    assert ops[0].text == "How dare you"
    assert ops[0].speed_mult == emo.TONE["angry"][0]
    assert ops[0].gain_db == emo.TONE["angry"][1]


def test_vocalization_becomes_its_own_op():
    ops = emo.parse("Ha. [laugh] Got you.")
    kinds = [type(o).__name__ for o in ops]
    assert kinds == ["Speak", "Vocal", "Speak"]
    assert ops[1].tag == "laugh"


def test_aliases_and_pause():
    ops = emo.parse("[furious] Stop! [pause:500] [laughing] done")
    assert ops[0].speed_mult == emo.TONE["angry"][0]  # furious -> angry
    silences = [o for o in ops if isinstance(o, emo.Silence)]
    assert silences and silences[0].ms == 500
    vocals = [o for o in ops if isinstance(o, emo.Vocal)]
    assert vocals and vocals[0].tag == "laugh"  # laughing -> laugh


def test_unknown_tag_is_dropped_not_spoken():
    ops = emo.parse("Hello [bogus] world")
    assert len(ops) == 1
    assert ops[0].text == "Hello  world".replace("  ", " ") or "bogus" not in ops[0].text
    assert "bogus" not in emo.strip_tags("Hello [bogus] world")


def test_base_emotion_seeds_tone():
    ops = emo.parse("just text", base_tone="sad")
    assert ops[0].speed_mult == emo.TONE["sad"][0]


def test_empty_after_tags_yields_no_ops():
    assert emo.parse("[angry][whisper]") == []


def test_parse_plain_voice():
    assert voicelib.parse_voice_id("af_heart") == [("af_heart", 1.0)]


def test_parse_blend_normalizes_weights():
    parts = voicelib.parse_voice_id("af_heart:0.6,am_adam:0.4")
    names = [p[0] for p in parts]
    weights = [p[1] for p in parts]
    assert names == ["af_heart", "am_adam"]
    assert abs(sum(weights) - 1.0) < 1e-6
    assert abs(weights[0] - 0.6) < 1e-6


def test_bad_voice_spec_raises():
    import pytest
    with pytest.raises(ValueError):
        voicelib.parse_voice_id("NOT A VOICE")


def test_voice_info_prefix_metadata():
    vi = voicelib.voice_info("bm_george")
    assert vi.gender == "male"
    assert vi.lang_code == "en-gb"
    assert "British" in vi.language


def test_assign_is_deterministic_and_respects_description():
    pool = ["af_heart", "am_adam", "bm_george", "bf_emma", "am_echo"]
    v1, sp1 = voicelib.assign_voice(pool, key="Grimgar", description="a deep old ogre")
    v2, sp2 = voicelib.assign_voice(pool, key="Grimgar", description="a deep old ogre")
    assert (v1, sp1) == (v2, sp2)          # deterministic
    assert voicelib.voice_info(v1).gender == "male"  # ogre -> male bias
    assert sp1 < 1.0                        # "deep/old" -> slower delivery


def test_female_description_gets_female_voice():
    # regression: "female" must not trigger the male bias via the "male" substring,
    # nor "woman" via "man".
    pool = ["af_heart", "af_bella", "am_adam", "am_echo", "bf_emma", "bm_george"]
    for desc in ("a young cheerful female rogue", "a wise old woman"):
        v, _ = voicelib.assign_voice(pool, key="C", description=desc)
        assert voicelib.voice_info(v).gender == "female", f"{desc!r} -> {v}"


def test_male_description_gets_male_voice():
    pool = ["af_heart", "af_bella", "am_adam", "am_echo", "bf_emma", "bm_george"]
    v, _ = voicelib.assign_voice(pool, key="C", description="a gruff male warrior")
    assert voicelib.voice_info(v).gender == "male"


def test_assign_excludes_used_voices_when_possible():
    pool = ["am_adam", "am_echo"]
    first, _ = voicelib.assign_voice(pool, key="A", gender="male")
    second, _ = voicelib.assign_voice(pool, key="B", gender="male", exclude=[first])
    assert second != first
