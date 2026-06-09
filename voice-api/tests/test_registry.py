"""Registry tests: voice assignment, persistence, and the idempotency guarantee
(re-creating a character must not reshuffle its established voice). No model needed."""
from __future__ import annotations

from characters import Registry


def _reg(tmp_path):
    return Registry(path=tmp_path / "characters.json")


def test_autoassign_then_idempotent_recreate(tmp_path):
    r = _reg(tmp_path)
    a = r.upsert(char_id="a", name="A", description="a young female rogue")
    # fill the registry so the exclude/order would change a re-assignment
    r.upsert(char_id="b", name="B", description="an old male king")
    r.upsert(char_id="c", name="C", description="an adult female sage")
    # re-creating "a" with no explicit voice must keep the SAME voice + speed
    a2 = r.upsert(char_id="a", name="A", description="a young female rogue")
    assert a2.voice_id == a.voice_id
    assert a2.speed == a.speed


def test_recreate_keeps_voice_even_if_description_changes(tmp_path):
    r = _reg(tmp_path)
    a = r.upsert(char_id="a", name="A", description="a young female rogue")
    a2 = r.upsert(char_id="a", name="A", description="now an old male wizard")
    assert a2.voice_id == a.voice_id  # established voice is sticky


def test_explicit_voice_overrides(tmp_path):
    r = _reg(tmp_path)
    r.upsert(char_id="a", name="A", description="a young female rogue")
    a2 = r.upsert(char_id="a", name="A", voice_id="elder_male")
    assert a2.voice_id == "elder_male"


def test_distinct_voices_for_distinct_characters(tmp_path):
    r = _reg(tmp_path)
    voices = [r.upsert(char_id=f"c{i}", name=f"C{i}",
                       description="a male warrior").voice_id for i in range(3)]
    assert len(set(voices)) == 3  # exclude logic spreads them


def test_assigned_voice_reflects_the_sheet(tmp_path):
    r = _reg(tmp_path)
    grim = r.upsert(char_id="g", name="Grimgar", description="a deep-voiced ogre warrior")
    assert grim.voice_id.startswith("Male voice")
    assert "deep" in grim.voice_id
    sage = r.upsert(char_id="s", name="Sage", description="an elder female sage")
    assert sage.voice_id.startswith("Female voice, 70 years old")


def test_persistence_across_instances(tmp_path):
    r = _reg(tmp_path)
    a = r.upsert(char_id="a", name="A", description="an elder female sage")
    r2 = _reg(tmp_path)  # reload from disk
    loaded = r2.get("a")
    assert loaded is not None
    assert loaded.voice_id == a.voice_id
    assert loaded.speed == a.speed


def test_legacy_kokoro_voices_migrate_on_load(tmp_path):
    # A registry written by the Kokoro-era service must keep working: ids that no
    # longer resolve are re-assigned from the character sheet on first load.
    import json
    legacy = {
        "old1": {"id": "old1", "name": "Eldrin", "voice_id": "bm_george", "speed": 0.92,
                 "base_emotion": "neutral", "description": "an old male wizard", "created_at": 1.0},
        "old2": {"id": "old2", "name": "Brisa", "voice_id": "af_kore", "speed": 1.08,
                 "base_emotion": "neutral", "description": "a young female bard", "created_at": 2.0},
    }
    (tmp_path / "characters.json").write_text(json.dumps(legacy))
    r = _reg(tmp_path)
    from voices import resolve_voice
    eldrin, brisa = r.get("old1"), r.get("old2")
    assert resolve_voice(eldrin.voice_id).startswith("Male voice, 70 years old")
    assert resolve_voice(brisa.voice_id).startswith("Female voice, early 20s")
    assert eldrin.voice_id != brisa.voice_id
    # and the migration is persisted, so a reload keeps the same voices
    r2 = _reg(tmp_path)
    assert r2.get("old1").voice_id == eldrin.voice_id
