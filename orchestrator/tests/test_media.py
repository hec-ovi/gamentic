"""Image persistence: generated images are downloaded into a per-game folder, served
under /media, and deleted when the game is wiped. Network/image-api is mocked."""
import os

from app import media


WORLD = {
    "title": "Portraits", "setting": "A studio.", "tone": "warm", "art_style": "oil painting",
    "narrator_persona": "x", "opening_scenario": "Light.", "start_location": "studio",
    "characters": [{"name": "Mara", "persona": "a sitter", "appearance": "red-haired woman"}],
    "quests": [{"title": "x", "description": "", "objectives": ["x"]}], "lore": [],
}


def test_images_persisted_served_and_deleted(client, fake_llm, monkeypatch, tmp_path):
    from app.config import settings
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(media, "generate_character_images",
                        lambda descriptor, style="", seed=None: {
                            "face_url": "/image/file?filename=f", "body_front_url": "/image/file?filename=bf",
                            "body_side_url": "/image/file?filename=bs", "seed": 1})
    monkeypatch.setattr(media, "generate_scene_image", lambda prompt, seed=None: None)  # skip scene art noise
    monkeypatch.setattr(media, "fetch_image_bytes", lambda url: b"PNGBYTES")

    gid = client.post("/games", json=WORLD).json()["game_id"]
    mara = client.get(f"/games/{gid}/state").json()["characters"][0]

    # the stored URL points at our per-game /media route, not image-api
    assert mara["face_url"].startswith(f"/media/{gid}/")
    name = mara["face_url"].rsplit("/", 1)[-1]

    # the file exists on disk and is served
    assert os.path.isdir(os.path.join(str(tmp_path), gid, "images"))
    r = client.get(f"/media/{gid}/{name}")
    assert r.status_code == 200 and r.content == b"PNGBYTES"

    # path-traversal is rejected
    assert client.get(f"/media/{gid}/..%2f..%2fsecret").status_code in (404, 400)

    # wiping the game deletes its image folder
    assert client.delete(f"/games/{gid}").status_code == 200
    assert not os.path.isdir(os.path.join(str(tmp_path), gid))
    assert client.get(f"/media/{gid}/{name}").status_code == 404


def test_character_generation_sends_portrait_dimensions(monkeypatch):
    """The orchestrator drives character art size (tall full-body for the cards) by sending
    IMAGE_BODY_W/H to image-api. The image layer (ComfyUI/FLUX) is not touched."""
    from app.config import settings
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    captured = {}

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"face_url": "f", "body_front_url": "bf", "body_side_url": "bs", "seed": 1}

    def _post(url, json=None, timeout=None):
        captured["url"], captured["body"] = url, json
        return _Resp()

    monkeypatch.setattr(media.httpx, "post", _post)
    out = media.generate_character_images("a scarred knight", style="oil painting")
    assert captured["url"].endswith("/image/character")
    assert captured["body"]["width"] == settings.IMAGE_BODY_W
    assert captured["body"]["height"] == settings.IMAGE_BODY_H
    assert out["body_front_url"] == "bf"


def test_persist_falls_back_when_download_fails(client, fake_llm, monkeypatch, tmp_path):
    """If the image bytes can't be fetched, we fall back to the image-api URL (still works)."""
    from app.config import settings
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(media, "generate_character_images",
                        lambda descriptor, style="", seed=None: {
                            "face_url": "/image/file?filename=f", "body_front_url": "/image/file?filename=bf",
                            "body_side_url": "/image/file?filename=bs", "seed": 1})
    monkeypatch.setattr(media, "generate_scene_image", lambda prompt, seed=None: None)
    monkeypatch.setattr(media, "fetch_image_bytes", lambda url: None)   # download fails

    gid = client.post("/games", json=WORLD).json()["game_id"]
    mara = client.get(f"/games/{gid}/state").json()["characters"][0]
    assert mara["face_url"] == "/image/file?filename=f"     # fell back to the image-api URL
