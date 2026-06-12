"""Ownership-based media cleanup (owner decision 2026-06-11: NO retention timers -
when our /media copy of a render lands, the image-api staging copy dies that instant;
when an adventure dies, every file it produced dies with it, staging folder and wav
cache included). Network is mocked at the media facade (route-level tests) or at
media.httpx (wire-shape tests); the conftest autouse stub keeps every OTHER test
inert so a suite run can never empty the dev box's REAL staging folder."""
import json

from app import db, media, repo
from app.config import settings
# the REAL functions, captured at import time - the conftest autouse safety stub
# replaces the module attributes before each test runs
from app.media import (delete_staging_image as real_delete_staging_image,
                       purge_all_audio as real_purge_all_audio,
                       purge_all_staging_images as real_purge_all_staging_images,
                       purge_game_audio as real_purge_game_audio)


class _Resp:
    def __init__(self, payload=None):
        self._payload = payload or {}
    def raise_for_status(self): pass
    def json(self): return self._payload


def _enable_images(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))


# ---------- delete-on-persist: the core seam (storage._persist) ----------

def test_persist_success_frees_the_staging_file(client, fake_llm, world,
                                                monkeypatch, tmp_path):
    """The moment our /media copy is written, the staging file it came from is
    garbage and _persist fires the DELETE for exactly that file."""
    _enable_images(monkeypatch, tmp_path)
    deleted = []
    monkeypatch.setattr(media, "delete_staging_image", deleted.append)
    monkeypatch.setattr(media, "generate_character_images",
                        lambda d, style="", seed=None: None)
    monkeypatch.setattr(media, "generate_scene_image",
                        lambda prompt, seed=None, width=None, height=None, references=None:
                        {"image_url": "/image/file?filename=view_1.png&subfolder=&type=output"})
    monkeypatch.setattr(media, "fetch_image_bytes", lambda url: b"PNG")
    gid = client.post("/games", json=world).json()["game_id"]
    deleted.clear()                       # creation scene art persisted too; not the target
    r = client.post(f"/games/{gid}/view", json={})
    assert r.status_code == 200
    assert deleted == ["/image/file?filename=view_1.png&subfolder=&type=output"]


def test_persist_failure_keeps_the_staging_file(client, fake_llm, world,
                                                monkeypatch, tmp_path):
    """When the download fails the staging file IS the live copy (the fallback URL
    stored in the DB points at it) - deleting it would kill the only render."""
    _enable_images(monkeypatch, tmp_path)
    deleted = []
    monkeypatch.setattr(media, "delete_staging_image", deleted.append)
    monkeypatch.setattr(media, "generate_character_images",
                        lambda d, style="", seed=None: {
                            "face_url": "/image/file?filename=f", "body_front_url": "/image/file?filename=bf",
                            "body_side_url": "/image/file?filename=bs", "seed": 1})
    monkeypatch.setattr(media, "generate_scene_image", lambda prompt, **k: None)
    monkeypatch.setattr(media, "fetch_image_bytes", lambda url: None)   # download fails
    gid = client.post("/games", json=world).json()["game_id"]
    mara = client.get(f"/games/{gid}/state").json()["characters"][0]
    assert mara["face_url"] == "/image/file?filename=f"     # the fallback survives...
    assert deleted == []                                    # ...because nothing was deleted


def test_character_views_each_free_their_own_staging_file(client, fake_llm, world,
                                                          monkeypatch, tmp_path):
    """The /image/character 3-view set flows through _persist per view, so each view
    cleans its own staging file (verified, not assumed - the contract demanded it)."""
    _enable_images(monkeypatch, tmp_path)
    deleted = []
    monkeypatch.setattr(media, "delete_staging_image", deleted.append)
    monkeypatch.setattr(media, "generate_character_images",
                        lambda d, style="", seed=None: {
                            "face_url": "/image/file?filename=f.png", "body_front_url": "/image/file?filename=bf.png",
                            "body_side_url": "/image/file?filename=bs.png", "seed": 1})
    monkeypatch.setattr(media, "generate_scene_image", lambda prompt, **k: None)
    monkeypatch.setattr(media, "fetch_image_bytes", lambda url: b"PNG")
    client.post("/games", json=world)
    assert sorted(deleted) == ["/image/file?filename=bf.png",
                               "/image/file?filename=bs.png",
                               "/image/file?filename=f.png"]


# ---------- game delete: sweep the fallback URLs + this game's wavs ----------

def test_game_delete_sweeps_fallback_urls_and_this_games_wavs(client, fake_llm, world,
                                                              monkeypatch):
    """Fallback '/image/file?' URLs in the DB mean the staging file is the only copy;
    deleting the game must free every one of them (scenes, character views, beats,
    item images in player/scene/character inventories) and release the game's wavs."""
    deleted, purged = [], []
    monkeypatch.setattr(media, "delete_staging_image", deleted.append)
    monkeypatch.setattr(media, "purge_game_audio", purged.append)
    gid = client.post("/games", json=world).json()["game_id"]
    with db.get_conn() as conn:
        sid = repo.current_scene(conn, gid)["id"]
        conn.execute("UPDATE scenes SET image_url=?, items=? WHERE id=?",
                     ("/image/file?filename=scene.png&subfolder=&type=output",
                      json.dumps([{"id": "i1", "name": "lamp", "description": "",
                                   "image_url": "/image/file?filename=lamp.png"}]),
                      sid))
        cid = repo.get_characters(conn, gid)[0]["id"]
        conn.execute("UPDATE characters SET face_url=?, body_front_url=?, inventory=? WHERE id=?",
                     ("/image/file?filename=face.png",
                      f"/media/{gid}/char-front.png",      # persisted: NOT staging, never swept
                      json.dumps([{"name": "coin", "description": "", "qty": 1,
                                   "image_url": "/image/file?filename=coin.png"}]),
                      cid))
        conn.execute("UPDATE player_state SET inventory=? WHERE game_id=?",
                     (json.dumps([{"name": "key", "description": "", "qty": 1,
                                   "image_url": "/image/file?filename=key.png"}]), gid))
        repo.add_beat(conn, gid, "narrator", None, "image", "a view", "crypt entrance",
                      image_url="/image/file?filename=beat.png")
    assert client.delete(f"/games/{gid}").status_code == 200
    assert set(deleted) == {"/image/file?filename=scene.png&subfolder=&type=output",
                            "/image/file?filename=lamp.png",
                            "/image/file?filename=face.png",
                            "/image/file?filename=coin.png",
                            "/image/file?filename=key.png",
                            "/image/file?filename=beat.png"}
    assert purged == [gid]                                  # the voice per-game purge fired


# ---------- wipe-all: both service purges + the response counts ----------

def test_wipe_all_purges_both_services_and_reports_counts(client, fake_llm, world,
                                                          monkeypatch):
    monkeypatch.setattr(media, "purge_all_staging_images", lambda: 7)
    monkeypatch.setattr(media, "purge_all_audio", lambda: 3)
    client.post("/games", json=world)
    body = client.delete("/games?confirm=wipe").json()
    assert body["wiped_games"] == 1
    assert body["wiped_staging_files"] == 7
    assert body["wiped_audio_files"] == 3


def test_wipe_all_survives_dead_services_and_reports_minus_one(client, fake_llm, world,
                                                               monkeypatch):
    """A dead media service must NEVER fail the wipe: the games still die, and the
    counts read -1 (couldn't confirm) instead of erroring."""
    monkeypatch.setattr(media, "purge_all_staging_images", lambda: None)
    monkeypatch.setattr(media, "purge_all_audio", lambda: None)
    gid = client.post("/games", json=world).json()["game_id"]
    r = client.delete("/games?confirm=wipe")
    assert r.status_code == 200
    body = r.json()
    assert body["wiped_games"] == 1
    assert body["wiped_staging_files"] == -1
    assert body["wiped_audio_files"] == -1
    assert client.get(f"/games/{gid}/state").status_code == 404


# ---------- wire shapes: the real facade functions over mocked httpx ----------

def test_delete_staging_image_wire_shape_and_skips(monkeypatch):
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    calls = []
    monkeypatch.setattr(media.httpx, "delete",
                        lambda url, params=None, timeout=None:
                        calls.append((url, params)) or _Resp({"deleted": True}))
    real_delete_staging_image("/image/file?filename=view_1.png&subfolder=staging&type=output")
    assert calls == [(f"{settings.IMAGE_API_URL}/image/file",
                      {"filename": "view_1.png", "subfolder": "staging", "type": "output"})]
    calls.clear()
    real_delete_staging_image("/image/file?filename=x.png")  # bare URL: defaults ride along
    assert calls == [(f"{settings.IMAGE_API_URL}/image/file",
                      {"filename": "x.png", "subfolder": "", "type": "output"})]
    calls.clear()
    # non-image-api sources leave no staging file: data: payloads, our own /media
    # copies, cloud-provider URLs, and a query with no filename all skip silently
    for url in (None, "", "data:image/png;base64,aGk=", "/media/g1/x.png",
                "https://fal.media/files/x.png", "/image/file?filename=",
                "/image/file?subfolder=staging"):
        real_delete_staging_image(url)
    assert calls == []

    def _boom(*a, **k): raise RuntimeError("image-api down")
    monkeypatch.setattr(media.httpx, "delete", _boom)
    real_delete_staging_image("/image/file?filename=x.png")  # swallowed: never breaks a render

    monkeypatch.setattr(settings, "IMAGE_ENABLED", False)
    monkeypatch.setattr(media.httpx, "delete",
                        lambda *a, **k: calls.append(a) or _Resp())
    real_delete_staging_image("/image/file?filename=x.png")
    assert calls == []                       # disabled = inert, like every media call


def test_purge_endpoints_wire_shapes_and_graceful_failure(monkeypatch):
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "VOICE_ENABLED", True)
    calls = []
    monkeypatch.setattr(media.httpx, "delete",
                        lambda url, params=None, timeout=None:
                        calls.append((url, params)) or _Resp({"deleted": 5}))
    assert real_purge_all_staging_images() == 5
    assert calls[-1] == (f"{settings.IMAGE_API_URL}/image/files", {"confirm": "all"})
    assert real_purge_all_audio() == 5
    assert calls[-1] == (f"{settings.VOICE_API_URL}/audio", {"confirm": "all"})
    real_purge_game_audio("g-1")
    assert calls[-1] == (f"{settings.VOICE_API_URL}/voice/games/g-1", None)

    def _boom(*a, **k): raise RuntimeError("service down")
    monkeypatch.setattr(media.httpx, "delete", _boom)
    assert real_purge_all_staging_images() is None           # None -> the route reports -1
    assert real_purge_all_audio() is None
    real_purge_game_audio("g-1")                             # swallowed


def test_purges_are_inert_when_the_services_are_disabled(monkeypatch):
    monkeypatch.setattr(settings, "IMAGE_ENABLED", False)
    monkeypatch.setattr(settings, "VOICE_ENABLED", False)
    calls = []
    monkeypatch.setattr(media.httpx, "delete", lambda *a, **k: calls.append(a) or _Resp())
    assert real_purge_all_staging_images() is None
    assert real_purge_all_audio() is None
    real_purge_game_audio("g-1")
    assert calls == []
