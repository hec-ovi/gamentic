"""Registry tests: voice assignment, persistence, and the idempotency guarantee
(re-creating a character must not reshuffle its established voice). No model needed."""
from __future__ import annotations

from characters import Registry

POOL = ["af_heart", "af_bella", "af_sky", "am_adam", "am_echo", "bm_george", "bf_emma"]


def _reg(tmp_path):
    return Registry(path=tmp_path / "characters.json")


def test_autoassign_then_idempotent_recreate(tmp_path):
    r = _reg(tmp_path)
    a = r.upsert(available_voices=POOL, char_id="a", name="A", description="a young female rogue")
    # fill the registry so the exclude/order would change a re-assignment
    r.upsert(available_voices=POOL, char_id="b", name="B", description="an old male king")
    r.upsert(available_voices=POOL, char_id="c", name="C", description="an adult female sage")
    # re-creating "a" with no explicit voice must keep the SAME voice + speed
    a2 = r.upsert(available_voices=POOL, char_id="a", name="A", description="a young female rogue")
    assert a2.voice_id == a.voice_id
    assert a2.speed == a.speed


def test_recreate_keeps_voice_even_if_description_changes(tmp_path):
    r = _reg(tmp_path)
    a = r.upsert(available_voices=POOL, char_id="a", name="A", description="a young female rogue")
    a2 = r.upsert(available_voices=POOL, char_id="a", name="A", description="now an old male wizard")
    assert a2.voice_id == a.voice_id  # established voice is sticky


def test_explicit_voice_overrides(tmp_path):
    r = _reg(tmp_path)
    r.upsert(available_voices=POOL, char_id="a", name="A", description="a young female rogue")
    a2 = r.upsert(available_voices=POOL, char_id="a", name="A", voice_id="bm_george")
    assert a2.voice_id == "bm_george"


def test_distinct_voices_for_distinct_characters(tmp_path):
    r = _reg(tmp_path)
    voices = [r.upsert(available_voices=POOL, char_id=f"c{i}", name=f"C{i}",
                       description="a male warrior").voice_id for i in range(3)]
    assert len(set(voices)) == 3  # exclude logic spreads them


def test_persistence_across_instances(tmp_path):
    r = _reg(tmp_path)
    a = r.upsert(available_voices=POOL, char_id="a", name="A", description="an elder female sage")
    r2 = _reg(tmp_path)  # reload from disk
    loaded = r2.get("a")
    assert loaded is not None
    assert loaded.voice_id == a.voice_id
    assert loaded.speed == a.speed


def test_age_maps_to_speed(tmp_path):
    r = _reg(tmp_path)
    young = r.upsert(available_voices=POOL, char_id="y", name="Y", description="a young female rogue")
    adult = r.upsert(available_voices=POOL, char_id="ad", name="Ad", description="an adult female merchant")
    elder = r.upsert(available_voices=POOL, char_id="e", name="E", description="an elder female sage")
    assert young.speed > adult.speed > elder.speed
