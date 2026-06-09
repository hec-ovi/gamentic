"""The 'See' button: POST /games/{gid}/view renders the current scene WITH the characters
present in it, grounded in actual state, and lands the image as a beat in the story flow.
The prompt follows the FLUX.2 klein recipe: subjects first, one positionally anchored
sentence per character, style once, positive no-text phrasing."""
from app import media, integrate, db, repo


WORLD = {
    "title": "Viewport", "setting": "a port town", "tone": "warm",
    "art_style": "painterly dark-fantasy illustration",
    "narrator_persona": "x", "opening_scenario": "Gulls wheel overhead.",
    "start_location": "harbor", "player_life": 20,
    "characters": [
        {"name": "Vex", "persona": "a scout", "description": "A sharp-eyed woman.",
         "appearance": "tall, scarred, wears leather armor"},
        {"name": "Bron", "persona": "a bored guard, he naps standing up",
         "appearance": "broad-shouldered, shaved head"},
    ],
    "quests": [{"title": "x", "objectives": ["x"]}], "lore": [],
}


def _enable(monkeypatch, tmp_path, captured):
    from app.config import settings
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(media, "generate_character_images", lambda descriptor, style="", seed=None: None)

    def _gen(prompt, seed=None, width=None, height=None):
        captured.update(prompt=prompt, width=width, height=height)
        return {"image_url": "/image/file?filename=v"}
    monkeypatch.setattr(media, "generate_scene_image", _gen)
    monkeypatch.setattr(media, "fetch_image_bytes", lambda url: b"PNG")


def test_view_renders_present_characters_from_state(client, fake_llm, monkeypatch, tmp_path):
    from app.config import settings
    captured = {}
    _enable(monkeypatch, tmp_path, captured)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    with db.get_conn() as conn:
        repo.set_scene_description(conn, gid, 'Crowded stone quay. A sign reads "The Salt Star".')

    r = client.post(f"/games/{gid}/view")
    assert r.status_code == 200
    body = r.json()
    assert body["image_url"].startswith(f"/media/{gid}/")

    p = captured["prompt"]
    assert p.startswith("Wide full-body shot of two people in Crowded stone quay.")
    assert "On the left, female, tall, scarred" in p     # gender net applies per character
    assert "On the right, male, broad-shouldered" in p   # one anchored sentence each
    assert "The Salt Star" not in p                      # quoted sign text stripped
    assert "soft morning light" in p                     # story clock grounds the lighting
    assert "painterly dark-fantasy illustration" in p    # world style governs the frame
    assert integrate.NO_TEXT_GUARD in p
    assert captured["width"] == settings.IMAGE_VIEW_W and captured["height"] == settings.IMAGE_VIEW_H

    # the snapshot persists as an image beat in the story flow
    beats = client.get(f"/games/{gid}/beats").json()["beats"]
    img = [b for b in beats if b["kind"] == "image"]
    assert len(img) == 1 and img[0]["image_url"] == body["image_url"]


def test_view_of_an_empty_scene_is_a_plain_wide_shot(client, fake_llm, monkeypatch, tmp_path):
    captured = {}
    _enable(monkeypatch, tmp_path, captured)
    world = dict(WORLD, characters=[])
    gid = client.post("/games", json=world).json()["game_id"]
    assert client.post(f"/games/{gid}/view").status_code == 200
    # the start scene's description is seeded from the setting at creation
    assert captured["prompt"].startswith("Wide shot of a port town.")
    assert "full-body" not in captured["prompt"]


def test_agentic_mode_lets_the_model_write_the_prompt_with_guards(client, fake_llm, monkeypatch, tmp_path):
    """IMAGE_AGENTIC_PROMPTS=true: the text model writes the image prompt from live context
    (looks, mood, the just-happened action), and CODE still enforces the invariants
    (quotes stripped, no-text tail appended)."""
    from app import llm as llmmod
    from app.config import settings
    captured = {}
    _enable(monkeypatch, tmp_path, captured)
    monkeypatch.setattr(settings, "IMAGE_AGENTIC_PROMPTS", True)
    fake_llm.image_prompt = llmmod.LLMReply(
        content='"Wide full-body shot of two people on a stone quay, the woman offering a coin."')
    gid = client.post("/games", json=WORLD).json()["game_id"]

    assert client.post(f"/games/{gid}/view").status_code == 200
    p = captured["prompt"]
    assert p.startswith("Wide full-body shot of two people on a stone quay")  # quotes stripped
    assert integrate.NO_TEXT_GUARD in p                                       # tail enforced by code

    # the prompt-writing call carried the real context and ONLY then the skill (never in story calls)
    call = [c for c in fake_llm.calls
            if c["system"].startswith("You write a single image-generation prompt")][-1]
    user = call["messages"][1]["content"]
    assert "female, tall, scarred" in user            # gender-netted looks
    assert "Gulls wheel overhead." in user            # the just-happened beat for poses
    assert "painterly dark-fantasy illustration" in user
    nar = [c for c in fake_llm.calls if "cue_character" in c["names"]]
    assert all("image-generation prompt" not in c["system"] for c in nar)


def test_agentic_mode_falls_back_to_the_template(client, fake_llm, monkeypatch, tmp_path):
    from app import llm as llmmod
    from app.config import settings
    captured = {}
    _enable(monkeypatch, tmp_path, captured)
    monkeypatch.setattr(settings, "IMAGE_AGENTIC_PROMPTS", True)
    fake_llm.image_prompt = llmmod.LLMReply(content="")          # the model whiffed
    gid = client.post("/games", json=WORLD).json()["game_id"]
    assert client.post(f"/games/{gid}/view").status_code == 200
    assert captured["prompt"].startswith("Wide full-body shot of two people in")  # template net


def test_image_beats_stay_out_of_model_transcripts(client, fake_llm, monkeypatch, tmp_path):
    """The snapshot beat is for the UI (a URL); the model-facing history windows must skip
    it (an empty line that would waste a slot of the beat budget). The story log keeps it."""
    captured = {}
    _enable(monkeypatch, tmp_path, captured)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    client.post(f"/games/{gid}/view")
    with db.get_conn() as conn:
        assert all(b["kind"] != "image" for b in repo.recent_beats(conn, gid, 50))
        assert all(b["kind"] != "image" for b in
                   repo.scene_beats_for_character(conn, gid, "harbor", "whoever", 50))
        assert any(b["kind"] == "image" for b in repo.all_beats(conn, gid))   # FE still gets it


def test_view_refuses_when_images_are_disabled(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    assert client.post(f"/games/{gid}/view").status_code == 409     # IMAGE_ENABLED=false in tests
    assert client.post("/games/nope/view").status_code == 404


def test_view_fails_soft_when_generation_is_down(client, fake_llm, monkeypatch, tmp_path):
    captured = {}
    _enable(monkeypatch, tmp_path, captured)
    monkeypatch.setattr(media, "generate_scene_image", lambda prompt, seed=None, width=None, height=None: None)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    r = client.post(f"/games/{gid}/view")
    assert r.status_code == 502                                     # explicit, FE can toast it
    beats = client.get(f"/games/{gid}/beats").json()["beats"]
    assert not [b for b in beats if b["kind"] == "image"]           # no half-beat left behind
