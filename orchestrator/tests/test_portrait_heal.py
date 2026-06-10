"""Portrait resilience (live bug: a 'database is locked' on one character's commit
killed the whole portrait loop, leaving every face null forever):
- files already on disk are RELINKED, never re-rendered,
- one character's failure never costs the others their portraits,
- any later turn self-heals by re-scheduling the (idempotent) job."""
import os

from app import llm, media, db, repo, integrate
from app.config import settings


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(media, "generate_scene_image",
                        lambda *a, **k: {"image_url": "/image/file?filename=x"})
    monkeypatch.setattr(media, "fetch_image_bytes", lambda url: b"PNG")
    # creation schedules a portrait job; stub it so no test touches the live service
    monkeypatch.setattr(media, "generate_character_images", lambda d, style="", seed=None: None)


WORLD = {
    "title": "Healtown", "setting": "x", "tone": "x", "narrator_persona": "x",
    "opening_scenario": "It begins.", "start_location": "square", "player_life": 20,
    "characters": [{"name": "Ana", "persona": "a guide", "sex": "female"},
                   {"name": "Bo", "persona": "a porter", "sex": "male"}],
    "quests": [{"title": "x", "objectives": ["x"]}], "lore": [],
}


def _char(client, gid, name):
    return next(c for c in client.get(f"/games/{gid}/state").json()["characters"]
                if c["name"] == name)


def test_files_on_disk_are_relinked_not_rerendered(client, fake_llm, monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    ana = _char(client, gid, "Ana")
    assert ana["face_url"] is None
    # simulate the crashed run: files exist, DB never committed
    d = os.path.join(str(tmp_path), gid, "images")
    os.makedirs(d, exist_ok=True)
    for view in ("face", "front", "side"):
        with open(os.path.join(d, f"char-{ana['id']}-{view}.png"), "wb") as f:
            f.write(b"PNG")

    def _maybe(descriptor, style="", seed=None):
        if "female" in descriptor:
            raise AssertionError("must not re-render Ana: her files already exist")
        return None    # Bo has no files; his render legitimately runs (and yields nothing)
    monkeypatch.setattr(media, "generate_character_images", _maybe)
    integrate.generate_images_for_game(gid)
    ana = _char(client, gid, "Ana")
    assert ana["face_url"] == f"/media/{gid}/char-{ana['id']}-face.png"
    assert ana["body_front_url"] == f"/media/{gid}/char-{ana['id']}-front.png"
    assert ana["body_side_url"] == f"/media/{gid}/char-{ana['id']}-side.png"  # full set relinked


def test_one_characters_failure_never_blocks_the_next(client, fake_llm, monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    gid = client.post("/games", json=WORLD).json()["game_id"]

    def _gen(descriptor, style="", seed=None):
        if "female" in descriptor:                      # Ana's render blows up
            raise RuntimeError("render died")
        return {"face_url": "/image/file?f=bo-face", "body_front_url": "/image/file?f=bo-front",
                "body_side_url": "/image/file?f=bo-side"}
    monkeypatch.setattr(media, "generate_character_images", _gen)
    integrate.generate_images_for_game(gid)
    assert _char(client, gid, "Ana")["face_url"] is None        # hers failed...
    assert _char(client, gid, "Bo")["face_url"] is not None     # ...his still landed


def test_turns_self_heal_missing_portraits(client, fake_llm, monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(media, "generate_character_images", lambda d, style="", seed=None: None)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    scheduled = []
    monkeypatch.setattr(integrate, "generate_images_for_game", lambda g: scheduled.append(g))
    client.post(f"/games/{gid}/action", json={"action": "I look around."})
    assert gid in scheduled                            # missing portraits -> re-scheduled


_FULL_SET = {"face_url": "/image/file?f=face", "body_front_url": "/image/file?f=front",
             "body_side_url": "/image/file?f=side"}


def test_partial_url_set_is_rescheduled_and_completed(client, fake_llm, monkeypatch, tmp_path):
    """A partial reference set (one url committed, the rest crashed) counts as MISSING:
    the per-turn self-heal re-schedules the job and the render completes the full set."""
    _setup(monkeypatch, tmp_path)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    ana = _char(client, gid, "Ana")
    with db.get_conn() as conn:
        repo.set_character_images(conn, ana["id"], face_url=f"/media/{gid}/x-face.png")
    heal = integrate.generate_images_for_game            # keep the real job callable
    scheduled = []
    monkeypatch.setattr(integrate, "generate_images_for_game", lambda g: scheduled.append(g))
    client.post(f"/games/{gid}/action", json={"action": "I look around."})
    assert gid in scheduled                              # a face alone is not a set
    monkeypatch.setattr(media, "generate_character_images",
                        lambda d, style="", seed=None: dict(_FULL_SET))
    heal(gid)
    ana = _char(client, gid, "Ana")
    assert ana["face_url"] and ana["body_front_url"] and ana["body_side_url"]


def test_partial_files_on_disk_rerender_the_full_set(client, fake_llm, monkeypatch, tmp_path):
    """A partial set ON DISK re-renders the full set (the renderer overwrites the partial
    files; _persist writes fixed names). Relinking it would re-schedule forever without
    ever completing the set."""
    _setup(monkeypatch, tmp_path)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    ana = _char(client, gid, "Ana")
    d = os.path.join(str(tmp_path), gid, "images")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"char-{ana['id']}-face.png"), "wb") as f:
        f.write(b"PNG")                                  # face only: an interrupted run
    rendered = []

    def _gen(descriptor, style="", seed=None):
        rendered.append(descriptor)
        return dict(_FULL_SET)
    monkeypatch.setattr(media, "generate_character_images", _gen)
    integrate.generate_images_for_game(gid)
    assert any("female" in r for r in rendered)          # Ana re-rendered, not relinked
    ana = _char(client, gid, "Ana")
    assert ana["face_url"] and ana["body_front_url"] and ana["body_side_url"]
