"""Wipe-all (the settings 'wipe all memory' button) + media cleanup correctness:
deleting an adventure removes its generated media, the full wipe removes EVERYTHING
including orphaned folders, and a render finishing after a delete never re-creates
a wiped game's folder."""
import os

from app import llm, media, db, repo, integrate
from app.config import settings


def _enable_images(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(media, "generate_character_images", lambda d, style="", seed=None: None)
    monkeypatch.setattr(media, "generate_scene_image",
                        lambda prompt, seed=None, width=None, height=None, references=None:
                        {"image_url": "/image/file?filename=x"})
    monkeypatch.setattr(media, "fetch_image_bytes", lambda url: b"PNG")


def test_deleting_a_game_removes_its_media_folder(client, fake_llm, world,
                                                  monkeypatch, tmp_path):
    _enable_images(monkeypatch, tmp_path)
    gid = client.post("/games", json=world).json()["game_id"]
    client.post(f"/games/{gid}/view", json={})            # persists a real file
    assert os.path.isdir(os.path.join(str(tmp_path), gid))
    client.delete(f"/games/{gid}")
    assert not os.path.exists(os.path.join(str(tmp_path), gid))


def test_wipe_everything_clears_games_sessions_and_orphans(client, fake_llm, world,
                                                           monkeypatch, tmp_path):
    _enable_images(monkeypatch, tmp_path)
    a = client.post("/games", json=world).json()["game_id"]
    b = client.post("/games", json=world).json()["game_id"]
    client.post("/create/message", json={"session_id": "s1", "message": "a haunted mill"})
    os.makedirs(os.path.join(str(tmp_path), "deadbeef0000", "images"))   # an orphan folder

    r = client.delete("/games?confirm=wipe")
    assert r.status_code == 200
    body = r.json()
    assert body["wiped_games"] == 2 and body["wiped_media_folders"] >= 1
    assert client.get("/games").json()["games"] == []
    assert client.get(f"/games/{a}/state").status_code == 404
    assert client.get(f"/games/{b}/state").status_code == 404
    assert client.get("/create/s1").status_code == 404                   # sessions gone
    assert os.listdir(str(tmp_path)) == []                               # orphans gone too


def test_wipe_requires_explicit_confirmation(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    assert client.delete("/games").status_code == 400
    assert client.delete("/games?confirm=yes").status_code == 400
    assert client.get(f"/games/{gid}/state").status_code == 200          # untouched


def test_late_render_never_resurrects_a_wiped_games_folder(client, fake_llm, world,
                                                           monkeypatch, tmp_path):
    """The race the orphans came from: art still rendering when the game is deleted."""
    _enable_images(monkeypatch, tmp_path)
    gid = client.post("/games", json=world).json()["game_id"]
    with db.get_conn() as conn:
        scene_id = repo.current_scene(conn, gid)["id"]
        conn.execute("UPDATE scenes SET image_url=NULL WHERE id=?", (scene_id,))
    client.delete(f"/games/{gid}")
    # the background tasks fire AFTER the delete (simulating a slow render finishing late)
    integrate.generate_scene_image(gid, scene_id)
    integrate.generate_directed_image(gid, "a vast hall", "")
    integrate.generate_item_image(gid, "brass key")
    integrate.generate_view_snapshot(gid)
    integrate.generate_images_for_game(gid)
    assert not os.path.exists(os.path.join(str(tmp_path), gid))          # stayed dead
