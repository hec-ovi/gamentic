"""Adventure portability: GET /games/{gid}/export (template = the world as designed;
checkpoint = the full save) and POST /games/import (always a NEW game, ids remapped,
missing media scrubbed)."""
import json
import os

from app import llm, db, repo


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def _play_a_bit(client, fake_llm, gid):
    fake_llm.narrator = _nar(T("add_item", name="brass key"),
                             T("note_trait", name="Mara", trait="blunt"),
                             content="A key, and a look from Mara.")
    client.post(f"/games/{gid}/action", json={"action": "I search the fountain."})


def test_template_export_is_the_world_as_designed(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    _play_a_bit(client, fake_llm, gid)
    r = client.get(f"/games/{gid}/export?kind=template")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    data = r.json()
    assert data["gamentic"] == "adventure" and data["version"] == 1
    w = data["world"]
    assert w["title"] == "The Sunken Crypt"
    assert w["start_location"] == "crypt entrance"
    mara = next(c for c in w["characters"] if c["name"] == "Mara")
    assert mara["persona"] and "secret tunnel" in mara["knowledge"]
    assert w["quests"][0]["objectives"] == ["Find the altar", "Open the tunnel"]
    assert "beats" not in data and "player" not in data       # no progress in a template


def test_template_import_starts_fresh(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    _play_a_bit(client, fake_llm, gid)
    template = client.get(f"/games/{gid}/export?kind=template").json()
    new_gid = client.post("/games/import", json=template).json()["game_id"]
    assert new_gid != gid
    st = client.get(f"/games/{new_gid}/state").json()
    assert st["player"]["inventory"] == []                    # progress did not travel
    assert st["player"]["life"] == 20
    beats = client.get(f"/games/{new_gid}/beats").json()["beats"]
    assert len(beats) == 1 and "crypt door groans" in beats[0]["text"]   # opening only


def test_checkpoint_roundtrip_resumes_the_exact_moment(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    _play_a_bit(client, fake_llm, gid)
    cp = client.get(f"/games/{gid}/export?kind=checkpoint").json()
    assert cp["gamentic"] == "checkpoint"
    new_gid = client.post("/games/import", json=cp).json()["game_id"]
    assert new_gid != gid

    old, new = (client.get(f"/games/{g}/state").json() for g in (gid, new_gid))
    assert [i["name"] for i in new["player"]["inventory"]] == ["brass key"]
    new_mara = next(c for c in new["characters"] if c["name"] == "Mara")
    old_mara = next(c for c in old["characters"] if c["name"] == "Mara")
    assert [t["text"] for t in new_mara["traits"]] == ["blunt"]
    assert new_mara["id"] != old_mara["id"]                   # ids remapped
    assert new["time"]["minutes"] == old["time"]["minutes"]   # the story clock traveled

    old_beats = client.get(f"/games/{gid}/beats").json()["beats"]
    new_beats = client.get(f"/games/{new_gid}/beats").json()["beats"]
    assert [b["text"] for b in new_beats] == [b["text"] for b in old_beats]
    # the original is untouched and both games are independent
    assert {g["id"] for g in client.get("/games").json()["games"]} >= {gid, new_gid}


def test_same_checkpoint_imports_twice_without_collisions(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    cp = client.get(f"/games/{gid}/export?kind=checkpoint").json()
    a = client.post("/games/import", json=cp).json()["game_id"]
    b = client.post("/games/import", json=cp).json()["game_id"]
    assert len({gid, a, b}) == 3


def test_checkpoint_import_scrubs_media_that_did_not_travel(client, fake_llm, world,
                                                            monkeypatch, tmp_path):
    from app.config import settings
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    gid = client.post("/games", json=world).json()["game_id"]
    with db.get_conn() as conn:
        sc = repo.current_scene(conn, gid)
        repo.set_scene_image(conn, sc["id"], f"/media/{gid}/scene-{sc['id']}.png")
        conn.execute("UPDATE beats SET kind='image', image_url=? WHERE game_id=?",
                     (f"/media/{gid}/shot-t9.png", gid))      # fake a story image beat
    cp = client.get(f"/games/{gid}/export?kind=checkpoint").json()
    new_gid = client.post("/games/import", json=cp).json()["game_id"]
    st = client.get(f"/games/{new_gid}/state").json()
    assert st["scene"]["image_url"] is None                   # scrubbed -> regenerates
    beats = client.get(f"/games/{new_gid}/beats").json()["beats"]
    assert beats == []                                        # fileless image beat dropped


def test_checkpoint_import_carries_media_on_the_same_box(client, fake_llm, world,
                                                         monkeypatch, tmp_path):
    from app.config import settings
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    gid = client.post("/games", json=world).json()["game_id"]
    d = os.path.join(str(tmp_path), gid, "images")
    os.makedirs(d)
    with open(os.path.join(d, "scene-x.png"), "wb") as f:
        f.write(b"PNG")
    with db.get_conn() as conn:
        sc = repo.current_scene(conn, gid)
        repo.set_scene_image(conn, sc["id"], f"/media/{gid}/scene-x.png")
    cp = client.get(f"/games/{gid}/export?kind=checkpoint").json()
    new_gid = client.post("/games/import", json=cp).json()["game_id"]
    st = client.get(f"/games/{new_gid}/state").json()
    assert st["scene"]["image_url"] == f"/media/{new_gid}/scene-x.png"
    assert os.path.isfile(os.path.join(str(tmp_path), new_gid, "images", "scene-x.png"))


def test_export_import_validation(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    assert client.get(f"/games/{gid}/export?kind=zip").status_code == 422
    assert client.get("/games/nope/export").status_code == 404
    assert client.post("/games/import", json={"hello": 1}).status_code == 400
    assert client.post("/games/import", json={"gamentic": "adventure",
                                              "world": {}}).status_code == 400
