"""M1 (evolve branch): EVERY image spins up the per-image art director with the whole
live context, bounded only by the encoder (klein's Qwen3-4B window, ~350 words), with
the deterministic templates as the net. Directed shots, item cards, background scene
art, the creation main image's identity references, and the template-import art pass."""
import json

from app import db, llm, media, repo
from app.config import settings
from app.integrate import image_prompts, jobs


WORLD = {
    "title": "Viewport", "setting": "a port town", "tone": "warm",
    "art_style": "painterly dark-fantasy illustration",
    "narrator_persona": "x", "opening_scenario": "Gulls wheel overhead.",
    "start_location": "harbor", "player_life": 20,
    "characters": [
        {"name": "Vex", "persona": "a scout", "description": "A sharp-eyed woman.",
         "appearance": "tall, scarred, wears leather armor"},
    ],
    "quests": [{"title": "x", "objectives": ["x"]}], "lore": [],
}


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def _enable(monkeypatch, tmp_path, captured):
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(media, "generate_character_images", lambda d, style="", seed=None: None)

    def _gen(prompt, seed=None, width=None, height=None, references=None):
        captured.append({"prompt": prompt, "references": references})
        return {"image_url": "/image/file?filename=x"}
    monkeypatch.setattr(media, "generate_scene_image", _gen)
    monkeypatch.setattr(media, "fetch_image_bytes", lambda url: b"PNG")


def _director_calls(fake_llm):
    return [c for c in fake_llm.calls
            if c["system"].startswith("You write a single image-generation prompt")]


def test_harden_clips_at_the_encoder_boundary():
    long = " ".join(f"word{i}" for i in range(500))
    hard = image_prompts._harden_image_prompt(long)
    # clipped to the 350-word encoder boundary, then the no-text guard appended
    assert len(hard.split()) <= image_prompts.ENCODER_WORD_BOUNDARY + len(
        image_prompts.NO_TEXT_GUARD.split())
    assert hard.rstrip(".").endswith("no signage")
    # and a rich-but-legal prompt passes untouched except the guard
    rich = " ".join(f"word{i}" for i in range(300))
    assert image_prompts._harden_image_prompt(rich).startswith(rich)


def test_directed_shot_is_artdirected_with_the_whole_context(client, fake_llm,
                                                             monkeypatch, tmp_path):
    captured = []
    _enable(monkeypatch, tmp_path, captured)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    fake_llm.image_prompt = llm.LLMReply(
        content="Detailed shot of a rusted crane over the quay, cold dawn light.")
    jobs.generate_directed_image(gid, "the rusted crane looming over the quay")

    call = _director_calls(fake_llm)[-1]
    ctx = call["messages"][1]["content"]
    assert "WORLD: Viewport" in ctx                        # the whole context rides
    assert "THE SHOT THE NARRATOR WANTS: the rusted crane looming over the quay" in ctx
    assert "Vex" in ctx                                    # present characters listed
    assert captured[-1]["prompt"].startswith("Detailed shot of a rusted crane")
    assert "no signage" in captured[-1]["prompt"]          # hardened


def test_directed_shot_falls_back_to_the_hardened_description(client, fake_llm,
                                                              monkeypatch, tmp_path):
    captured = []
    _enable(monkeypatch, tmp_path, captured)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    fake_llm.image_prompt = llm.LLMReply(content="")       # the director whiffed
    jobs.generate_directed_image(gid, "the rusted crane looming over the quay")
    assert captured[-1]["prompt"].startswith("the rusted crane looming over the quay")
    assert "painterly dark-fantasy illustration" in captured[-1]["prompt"]


def test_item_card_is_artdirected_and_framed_as_a_card(client, fake_llm, world,
                                                       monkeypatch, tmp_path):
    captured = []
    _enable(monkeypatch, tmp_path, captured)
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.image_prompt = llm.LLMReply(
        content="Close-up of a single tarnished brass key on dark velvet, soft rim light.")
    fake_llm.narrator = _nar(T("add_item", name="brass key",
                               description="a small tarnished key"))
    client.post(f"/games/{gid}/action", json={"action": "I search the silt."})

    call = _director_calls(fake_llm)[-1]
    ctx = call["messages"][1]["content"]
    assert "the item card of a single brass key" in ctx
    assert "FRAME: a small unlock card" in ctx
    shot = next(c for c in captured if "brass key" in c["prompt"])
    assert shot["prompt"].startswith("Close-up of a single tarnished brass key on dark velvet")


def test_item_card_falls_back_to_the_template(client, fake_llm, world,
                                              monkeypatch, tmp_path):
    captured = []
    _enable(monkeypatch, tmp_path, captured)
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.image_prompt = llm.LLMReply(content="")       # director whiffed -> template
    fake_llm.narrator = _nar(T("add_item", name="brass key",
                               description="a small tarnished key"))
    client.post(f"/games/{gid}/action", json={"action": "I search the silt."})
    shot = next(c for c in captured if "brass key" in c["prompt"])
    assert "Close-up of a single brass key" in shot["prompt"]


def test_left_behind_scene_art_uses_that_scenes_context_without_people(
        client, fake_llm, monkeypatch, tmp_path):
    captured = []
    _enable(monkeypatch, tmp_path, captured)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    with db.get_conn() as conn:
        sc = repo.get_or_create_scene(conn, gid, "smugglers' cellar",
                                      "A low brick cellar stacked with crates.")
        scene_id = sc["id"]
    fake_llm.image_prompt = llm.LLMReply(
        content="Wide shot of a low brick cellar stacked with crates, lantern light.")
    jobs.generate_scene_image(gid, scene_id)               # player still at the harbor

    ctx = _director_calls(fake_llm)[-1]["messages"][1]["content"]
    assert "smugglers' cellar" in ctx                      # THIS scene's place, not the player's
    assert "CHARACTERS PRESENT" not in ctx                 # scene art is the place alone
    assert captured[-1]["prompt"].startswith("Wide shot of a low brick cellar")


def test_creation_main_image_rides_the_fresh_portraits(client, fake_llm,
                                                       monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    fake_llm.artdirector = llm.LLMReply(content=json.dumps({
        "characters": [{"name": "Vex", "descriptor": "A tall scarred woman in leather armor"}],
        "main_image": "Vex stands on the harbor quay at dawn, gulls wheeling",
    }))
    captured = []

    def _char_gen(descriptor, style="", seed=None):
        return {"face_url": "/image/file?filename=f", "body_front_url": "/image/file?filename=b",
                "body_side_url": "/image/file?filename=s"}

    def _scene_gen(prompt, seed=None, width=None, height=None, references=None):
        captured.append({"prompt": prompt, "references": references})
        return {"image_url": "/image/file?filename=main"}
    monkeypatch.setattr(media, "generate_character_images", _char_gen)
    monkeypatch.setattr(media, "generate_scene_image", _scene_gen)
    monkeypatch.setattr(media, "fetch_image_bytes", lambda url: b"PNG")

    gid = client.post("/games", json=WORLD).json()["game_id"]
    main = next(c for c in captured if c["prompt"].startswith("Vex stands on the harbor"))
    assert main["references"], "the opening image must be conditioned on the fresh portraits"
    assert any("-front" in r for r in main["references"])


def test_template_import_runs_the_creation_art_pass(client, fake_llm, world,
                                                    monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    from app import integrate
    passes = []
    monkeypatch.setattr(integrate, "generate_creation_art",
                        lambda gid, sid: passes.append(("creation", gid)))
    monkeypatch.setattr(integrate, "generate_images_for_game",
                        lambda gid, direction=None: passes.append(("heal", gid)))
    monkeypatch.setattr(integrate, "generate_scene_image",
                        lambda gid, sid, prompt_override="", references=None: passes.append(("scene", gid)))

    gid = client.post("/games", json=world).json()["game_id"]
    template = client.get(f"/games/{gid}/export?kind=template").json()
    passes.clear()
    client.post("/games/import", json=template)
    kinds = [k for k, _ in passes]
    assert "creation" in kinds                             # a template gets first sight
    assert "heal" not in kinds

    # a checkpoint resumes mid-story: heal only, never the opening pass
    ckpt = client.get(f"/games/{gid}/export?kind=checkpoint").json()
    passes.clear()
    client.post("/games/import", json=ckpt)
    kinds = [k for k, _ in passes]
    assert "creation" not in kinds
    assert "heal" in kinds
