"""Look is a STORY action (not just an image request): it runs a narrator turn that can
trigger reactions and discoveries, and the narrator decides whether the view earns an
image via its show_image tool. Spontaneous show_image (no player look) is paced."""
from app import llm, media, db, repo
from app.config import settings


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def _enable_images(monkeypatch, tmp_path, captured):
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(media, "generate_character_images", lambda d, style="", seed=None: None)

    def _gen(prompt, seed=None, width=None, height=None, references=None):
        captured.append({"prompt": prompt, "width": width, "height": height,
                         "references": references})
        return {"image_url": "/image/file?filename=shot"}
    monkeypatch.setattr(media, "generate_scene_image", _gen)
    monkeypatch.setattr(media, "fetch_image_bytes", lambda url: b"PNG")


# ---------- look as an action ----------

def test_look_segment_is_a_story_action(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(content="The hatch is rusted but ajar.")
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "look", "text": "the rusted hatch"}]}).json()
    player = next(b for b in d["beats"] if b["speaker"] == "player")
    assert player["text"] == "you look at the rusted hatch"     # readable, 'at' added
    user = fake_llm.narrator_calls()[-1]["messages"][1]["content"]
    assert "you look at the rusted hatch" in user


def test_look_turn_injects_the_looking_protocol(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    client.post(f"/games/{gid}/action", json={"segments": [{"type": "look", "text": ""}]})
    system = fake_llm.narrator_calls()[-1]["system"]
    assert "The player is LOOKING" in system
    assert "show_image" in system and "reveal_item" in system
    # ...and a plain non-look turn does NOT carry it
    client.post(f"/games/{gid}/action", json={"action": "I sit down."})
    assert "The player is LOOKING" not in fake_llm.narrator_calls()[-1]["system"]


def test_interpreter_can_classify_a_typed_look(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.interpret = _nar(T("submit_segments",
                                segments=[{"type": "look", "text": "for a way out"}]))
    d = client.post(f"/games/{gid}/action", json={"action": "I search for a way out."}).json()
    player = next(b for b in d["beats"] if b["speaker"] == "player")
    assert player["text"] == "you look for a way out"


def test_show_image_tool_only_offered_when_images_enabled(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]      # tests run images-off
    client.post(f"/games/{gid}/action", json={"action": "I look around."})
    assert "show_image" not in fake_llm.narrator_calls()[-1]["names"]


# ---------- show_image: render in the background, land as an image beat ----------

def _image_beats(client, gid):
    return [b for b in client.get(f"/games/{gid}/beats").json()["beats"]
            if b["kind"] == "image"]


def test_look_with_show_image_lands_a_captioned_image_beat(client, fake_llm, world,
                                                           monkeypatch, tmp_path):
    captured = []
    _enable_images(monkeypatch, tmp_path, captured)
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(
        T("show_image", description="A rusted coal hatch high on the left wall, grey light leaking through."),
        content="Behind the crates, the dull gleam of a hatch.")
    client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "look", "text": "the rusted hatch"}]})
    assert "show_image" in fake_llm.narrator_calls()[-1]["names"]   # tool offered images-on
    beats = _image_beats(client, gid)
    assert len(beats) == 1
    # the look leads the caption; the narrator's description is the moment's concept
    assert beats[0]["text"].startswith("the rusted hatch.")
    assert "coal hatch" in beats[0]["text"]
    assert beats[0]["image_url"].startswith(f"/media/{gid}/")
    shot = captured[-1]                                            # the directed render
    assert "rusted coal hatch high on the left wall" in shot["prompt"]
    assert "plain unmarked surfaces, no signage" in shot["prompt"]


def test_show_image_conditions_on_named_characters_identity(client, fake_llm, world,
                                                            monkeypatch, tmp_path):
    captured = []
    _enable_images(monkeypatch, tmp_path, captured)
    gid = client.post("/games", json=world).json()["game_id"]
    with db.get_conn() as conn:
        mara = repo.find_character_by_name(conn, gid, "Mara")
        repo.set_character_images(conn, mara["id"], body_front_url="/media/x/mara-front.png")
    fake_llm.narrator = _nar(
        T("show_image", description="Mara crouched in the center, studying the altar."),
        content="She kneels.")
    client.post(f"/games/{gid}/action", json={"segments": [{"type": "look", "text": "Mara"}]})
    refs = captured[-1]["references"]
    assert refs and refs[0].endswith("/media/x/mara-front.png") and refs[0].startswith("http")


def test_spontaneous_show_image_is_paced(client, fake_llm, world, monkeypatch, tmp_path):
    """Without a player look, narrator-initiated images respect the cooldown; a look
    bypasses it."""
    captured = []
    _enable_images(monkeypatch, tmp_path, captured)
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("show_image", description="A black ship sliding out of the fog."),
                             content="A shape moves in the fog.")
    client.post(f"/games/{gid}/action", json={"action": "I wait."})
    assert len(_image_beats(client, gid)) == 1                     # first one renders
    client.post(f"/games/{gid}/action", json={"action": "I keep waiting."})
    assert len(_image_beats(client, gid)) == 1                     # too soon: dropped
    client.post(f"/games/{gid}/action", json={"segments": [{"type": "look", "text": "the ship"}]})
    assert len(_image_beats(client, gid)) == 2                     # a look always earns it
