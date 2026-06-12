"""Ownership-based deletion tests (the deletion contract, 2026-06-11).

The owner killed retention timers: a wav dies when the last game claiming it is
deleted, or in the explicit purge-all sweep, never on a clock. These tests
drive the real HTTP routes (fake llama.cpp upstream from conftest, real SNAC
decoder) and assert on the manifest JSON and the files on disk, plus the unit
edges that must never crash a speak (corrupt manifest, doctored entries trying
to escape the audio dir).
"""
from __future__ import annotations

import json

import config
from manifest import Manifest

# Tests within this module share the session client and the session-wide audio
# dir; every test speaks its OWN unique lines (unique content hash -> unique
# wav) so nothing depends on another test's files. The purge-all tests are
# defined last because they wipe the whole cache.


def _speak(client, text: str, gid: str | None = None) -> str:
    """Speak a line and return the cached wav's basename."""
    body: dict = {"text": text, "voice_id": "narrator"}
    if gid is not None:
        body["game_id"] = gid
    r = client.post("/voice/speak", json=body)
    assert r.status_code == 200, r.text
    url = r.json()["audio_url"]
    assert url.startswith("/audio/")
    return url.rsplit("/", 1)[1]


def _manifest_on_disk() -> dict:
    if not config.MANIFEST_FILE.exists():
        return {}
    return json.loads(config.MANIFEST_FILE.read_text())


# --- recording claims -------------------------------------------------------

def test_speak_with_game_id_records_manifest(client):
    name = _speak(client, "The crypt door creaks open.", gid="game-rec")
    assert (config.AUDIO_DIR / name).exists()
    assert _manifest_on_disk()[name] == ["game-rec"]
    # atomic write: the tmp file never outlives the os.replace
    assert not config.MANIFEST_FILE.with_suffix(".json.tmp").exists()


def test_cache_hit_from_another_game_adds_second_claim(client):
    line = "Two parties hear the same prophecy."
    a = _speak(client, line, gid="game-one")
    b = _speak(client, line, gid="game-two")
    assert a == b  # cache hit: same content hash, same wav
    assert sorted(_manifest_on_disk()[a]) == ["game-one", "game-two"]
    # re-speak from a game already on record stays deduped
    _speak(client, line, gid="game-one")
    assert sorted(_manifest_on_disk()[a]) == ["game-one", "game-two"]


def test_blank_or_missing_game_id_claims_nothing(client):
    unclaimed = _speak(client, "Nobody owns this whisper.")
    blank = _speak(client, "Whitespace is not an owner.", gid="   ")
    m = _manifest_on_disk()
    assert unclaimed not in m
    assert blank not in m
    # the wavs themselves are still cached and served as before
    assert client.get(f"/audio/{unclaimed}").status_code == 200


def test_character_speak_carries_the_same_claim(client):
    # NPC lines are game output too; they must die with the adventure
    client.post("/characters", json={"id": "man-npc", "name": "Moth",
                                     "description": "a raspy old male herbalist"})
    r = client.post("/characters/man-npc/speak",
                    json={"text": "Roots remember everything.", "game_id": "game-npc"})
    assert r.status_code == 200
    name = r.json()["audio_url"].rsplit("/", 1)[1]
    assert _manifest_on_disk()[name] == ["game-npc"]
    client.delete("/characters/man-npc")
    client.delete("/voice/games/game-npc")


# --- per-game delete --------------------------------------------------------

def test_delete_game_removes_only_solely_owned_files(client):
    solo = _speak(client, "Only the doomed game heard this.", gid="game-doomed")
    shared_line = "Both games share this echo."
    shared = _speak(client, shared_line, gid="game-doomed")
    _speak(client, shared_line, gid="game-survivor")

    r = client.delete("/voice/games/game-doomed")
    assert r.status_code == 200
    assert r.json() == {"deleted": 1}  # only the solely-owned wav died

    assert not (config.AUDIO_DIR / solo).exists()
    assert (config.AUDIO_DIR / shared).exists()
    m = _manifest_on_disk()
    assert solo not in m
    assert m[shared] == ["game-survivor"]  # just lost the gid, kept the file
    assert client.get(f"/audio/{solo}").status_code == 404
    assert client.get(f"/audio/{shared}").status_code == 200
    client.delete("/voice/games/game-survivor")


def test_shared_file_survives_until_its_last_owner_dies(client):
    line = "A line two adventures both cherish."
    name = _speak(client, line, gid="game-first")
    _speak(client, line, gid="game-second")

    # first owner dies: claim drops, file stays, nothing was deleted
    assert client.delete("/voice/games/game-first").json() == {"deleted": 0}
    assert (config.AUDIO_DIR / name).exists()
    assert _manifest_on_disk()[name] == ["game-second"]

    # last owner dies: now the wav goes with it
    assert client.delete("/voice/games/game-second").json() == {"deleted": 1}
    assert not (config.AUDIO_DIR / name).exists()
    assert name not in _manifest_on_disk()


def test_delete_unknown_game_is_zero_not_an_error(client):
    r = client.delete("/voice/games/never-existed")
    assert r.status_code == 200
    assert r.json() == {"deleted": 0}


# --- manifest robustness (unit level: these paths run at startup) ------------

def test_corrupt_manifest_starts_empty_and_recovers(tmp_path):
    path = tmp_path / "games.json"
    path.write_text("{ not json at all")
    m = Manifest(path=path)  # must not raise: a broken manifest never blocks speech
    assert m.owners("whatever.wav") == []
    m.claim("abc.wav", "g1")
    assert json.loads(path.read_text()) == {"abc.wav": ["g1"]}  # healed on first save


def test_doctored_manifest_entry_cannot_escape_audio_dir(tmp_path):
    # the manifest is a file on disk; if someone plants a traversal entry, a
    # game delete must refuse to unlink anything outside the audio dir
    victim = config.DATA_DIR / "manifest-escape-victim.txt"
    victim.write_text("precious")
    path = tmp_path / "games.json"
    path.write_text(json.dumps({"../manifest-escape-victim.txt": ["evil-game"]}))
    m = Manifest(path=path)
    assert m.release_game("evil-game") == 0  # claim dropped, nothing unlinked
    assert victim.exists()
    victim.unlink()


def test_claim_stores_basenames_only(tmp_path):
    m = Manifest(path=tmp_path / "games.json")
    m.claim("sub/dir/echo.wav", "g1")
    assert m.owners("echo.wav") == ["g1"]
    assert json.loads((tmp_path / "games.json").read_text()) == {"echo.wav": ["g1"]}


# --- purge-all (defined last: wipes the whole cache) -------------------------

def test_purge_without_exact_confirm_is_400_and_touches_nothing(client):
    name = _speak(client, "Do not purge me by accident.", gid="game-safe")
    assert client.delete("/audio").status_code == 400
    assert client.delete("/audio?confirm=yes").status_code == 400
    assert (config.AUDIO_DIR / name).exists()
    assert _manifest_on_disk()[name] == ["game-safe"]


def test_purge_all_clears_every_wav_and_the_manifest(client):
    _speak(client, "Claimed wav one.", gid="game-p1")
    _speak(client, "Claimed wav two.", gid="game-p2")
    _speak(client, "Unclaimed wav dies in the sweep too.")

    r = client.delete("/audio?confirm=all")
    assert r.status_code == 200
    assert r.json()["deleted"] >= 3  # ours plus whatever earlier tests cached

    assert list(config.AUDIO_DIR.glob("*.wav")) == []
    assert not config.MANIFEST_FILE.exists()
    assert client.delete("/voice/games/game-p1").json() == {"deleted": 0}

    # the service keeps working: a fresh speak rebuilds cache and manifest
    name = _speak(client, "Life after the purge.", gid="game-reborn")
    assert (config.AUDIO_DIR / name).exists()
    assert _manifest_on_disk()[name] == ["game-reborn"]
