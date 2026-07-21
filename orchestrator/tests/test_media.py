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
    monkeypatch.setattr(media, "generate_scene_image", lambda prompt, seed=None, **kw: None)  # skip scene art noise
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


def test_character_generation_lets_image_api_own_per_view_sizing(monkeypatch):
    """The orchestrator only describes the character; per-view sizing (square face vs tall
    full-body) is owned by the image-api. So the orchestrator must NOT send width/height to
    /image/character (that would force one size on all three views). See image-agent-contract."""
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
    assert captured["body"]["descriptor"] == "a scarred knight" and captured["body"]["style"] == "oil painting"
    assert "width" not in captured["body"] and "height" not in captured["body"]  # image-api owns per-view size
    assert out["body_front_url"] == "bf"


def test_image_descriptors_state_gender_and_ban_text(client, fake_llm, monkeypatch, tmp_path):
    """Trait clarity for the image model: every outgoing character descriptor must carry an
    explicit gender (inferred from description/persona when the appearance omits it) and the
    no-text guard, so female reads female, male reads male, and no lettering gets rendered."""
    from app import integrate
    from app.config import settings
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    calls = []
    monkeypatch.setattr(media, "generate_character_images",
                        lambda descriptor, style="", seed=None: calls.append(descriptor) or None)
    monkeypatch.setattr(media, "generate_scene_image", lambda prompt, seed=None, **kw: None)

    world = dict(WORLD, characters=[
        # appearance says nothing gendered; the description does
        {"name": "Vex", "persona": "a scout", "description": "A sharp-eyed woman.",
         "appearance": "tall, scarred, wears leather armor"},
        # appearance says nothing gendered; the persona's pronoun does
        {"name": "Bron", "persona": "a bored guard, he naps standing up",
         "appearance": "broad-shouldered, shaved head"},
        # already explicit: must not get double-prefixed
        {"name": "Mara", "persona": "a sitter", "appearance": "a red-haired young woman"},
        # genuinely ambiguous everywhere: left as written
        {"name": "Glim", "persona": "a hooded whisperer", "appearance": "a small hooded figure"},
    ])
    client.post("/games", json=world)

    vex = next(d for d in calls if "leather armor" in d)
    assert vex.startswith("female, tall, scarred")
    bron = next(d for d in calls if "shaved head" in d)
    assert bron.startswith("male, broad-shouldered")
    mara = next(d for d in calls if "red-haired" in d)
    assert mara.startswith("a red-haired young woman")       # no prefix piled on
    glim = next(d for d in calls if "hooded figure" in d)
    assert glim.startswith("a small hooded figure")          # nothing invented
    assert all(integrate.NO_TEXT_GUARD in d for d in calls)  # every image bans rendered text


def test_scene_prompt_strips_quoted_signs_and_bans_text(client, fake_llm, monkeypatch, tmp_path):
    """Quoted spans in scene prose (sign names, spoken lines) provoke garbled rendered text,
    so the background scene-art job strips them and appends the no-text guard."""
    from app import integrate, db, repo
    from app.config import settings
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(media, "generate_character_images", lambda descriptor, style="", seed=None: None)
    prompts = []
    monkeypatch.setattr(media, "generate_scene_image", lambda prompt, seed=None, **kw: prompts.append(prompt) or None)

    gid = client.post("/games", json=WORLD).json()["game_id"]
    with db.get_conn() as conn:
        repo.set_scene_description(
            conn, gid, 'A timber tavern interior. A wooden sign reads "The Gilded Goose" above the bar.')
        sid = repo.current_scene(conn, gid)["id"]
    integrate.generate_scene_image(gid, sid)        # the background-task entry point

    prompt = prompts[-1]
    assert "Gilded Goose" not in prompt                      # quoted sign text never reaches the model
    assert "timber tavern interior" in prompt
    assert prompt.startswith("studio. ")                     # the scene NAME anchors the subject
    assert "oil painting" in prompt                          # world style still composed in
    assert integrate.NO_TEXT_GUARD in prompt


def test_scene_prompt_anchors_on_the_place_not_the_cosmology(client, fake_llm, monkeypatch, tmp_path):
    """Live-found: a scene whose description was world-level prose ('a multiverse of dying
    worlds...') produced a multi-city montage with rendered text. The prompt must lead with
    the scene NAME (the concrete place) and strip single-quoted names ('Star-Strider')."""
    from app import integrate
    sc = {"name": "A desolate, high-gravity wasteland planet",
          "description": "You land the 'Star-Strider' here. A multiverse of diverse, dying worlds.",
          "status": "tense"}
    p = integrate.scene_prompt(sc, "gritty sci-fi realism")
    assert p.startswith("A desolate, high-gravity wasteland planet. You land the  here.")
    assert "Star-Strider" not in p                           # single-quoted name stripped
    assert integrate.NO_TEXT_GUARD in p


def test_art_director_writes_the_first_sight_prompts(client, fake_llm, monkeypatch, tmp_path):
    """Owner direction (2026-06-11): a dedicated art-director agent reads the whole
    world bible at creation and writes the character descriptors and the main opening
    image prompt - portraits render first, the main image last, both from ITS words."""
    import json as _json
    from app import llm
    from app.config import settings
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "IMAGE_ART_DIRECTOR", True)
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    fake_llm.artdirector = llm.LLMReply(content=_json.dumps({
        "characters": [{"name": "Mara",
                        "descriptor": "A red-haired woman in her thirties, paint-flecked apron, full body"}],
        "main_image": "A sunlit painter's studio, one red-haired sitter in the center, warm window light",
    }))
    descriptors, scene_prompts = [], []
    monkeypatch.setattr(media, "generate_character_images",
                        lambda descriptor, style="", seed=None: descriptors.append(descriptor) or None)
    monkeypatch.setattr(media, "generate_scene_image",
                        lambda prompt, **k: scene_prompts.append(prompt) or None)
    client.post("/games", json=WORLD)
    assert descriptors and descriptors[0].startswith("A red-haired woman in her thirties")
    assert scene_prompts and scene_prompts[-1].startswith("A sunlit painter's studio")
    assert "no signage" in scene_prompts[-1]          # hardened: the no-text guard rides along


def test_a_dead_art_director_costs_nothing(client, fake_llm, monkeypatch, tmp_path):
    """Garbage from the director (or no reply at all) -> the deterministic templates
    carry every render, exactly as before the agent existed."""
    from app import llm
    from app.config import settings
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "IMAGE_ART_DIRECTOR", True)
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    fake_llm.artdirector = llm.LLMReply(content="I think the studio should feel warm...")
    descriptors, scene_prompts = [], []
    monkeypatch.setattr(media, "generate_character_images",
                        lambda descriptor, style="", seed=None: descriptors.append(descriptor) or None)
    monkeypatch.setattr(media, "generate_scene_image",
                        lambda prompt, **k: scene_prompts.append(prompt) or None)
    client.post("/games", json=WORLD)
    assert descriptors and "red-haired woman" in descriptors[0]   # sheet template
    assert scene_prompts and scene_prompts[-1].startswith("studio")  # name-led template


def test_item_card_renders_for_article_led_names(client, fake_llm, monkeypatch, tmp_path):
    """Live (owner playtest): 'a heavy iron key' sat imageless in the pack forever and
    its slot showed bare initials. The visible-item index keys are article-blind
    item_keys, but the card job looked itself up by norm_name (article kept), missed
    its own entry and silently bailed - on the first render AND every self-heal sweep."""
    from app import db, media
    from app.config import settings
    from app.integrate import jobs
    from app.repo import players
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(media, "generate_scene_image",
                        lambda *a, **k: {"image_url": "data:image/png;base64,aGk="})
    gid = client.post("/games", json=WORLD).json()["game_id"]
    with db.get_conn() as conn:
        players.add_item(conn, gid, "a heavy iron key", "notched, cold")
    beat = jobs.generate_item_image(gid, "a heavy iron key")
    assert beat, "the card job must find the article-led item in its own index"
    st = client.get(f"/games/{gid}/state").json()
    key = next(i for i in st["player"]["inventory"] if "iron key" in i["name"])
    assert key["image_url"]


def test_scene_prompt_falls_back_to_background_when_description_is_empty():
    """Live-found (the verification run): a mid-game scene arrived with an empty
    description and the visual truth in `background` ('a cathedral of cooling magma...');
    the prompt was the bare name and 'vault interior' rendered a literal treasure vault.
    The prompt must fall back to the background when the description is empty."""
    from app import integrate
    sc = {"name": "vault interior", "description": "",
          "background": "The inner chamber is a cathedral of cooling magma and carved "
                        "obsidian. Great pillars of basalt rise like frozen giants.",
          "status": "tense"}
    p = integrate.scene_prompt(sc, "painterly fantasy")
    assert "cathedral of cooling magma" in p
    assert p.startswith("vault interior. ")
    sc_no_bg = {"name": "vault interior", "description": "", "status": "tense"}
    assert integrate.scene_prompt(sc_no_bg, "x").startswith("vault interior")   # no key, no crash


def test_persist_falls_back_when_download_fails(client, fake_llm, monkeypatch, tmp_path):
    """If the image bytes can't be fetched, we fall back to the image-api URL (still works)."""
    from app.config import settings
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(media, "generate_character_images",
                        lambda descriptor, style="", seed=None: {
                            "face_url": "/image/file?filename=f", "body_front_url": "/image/file?filename=bf",
                            "body_side_url": "/image/file?filename=bs", "seed": 1})
    monkeypatch.setattr(media, "generate_scene_image", lambda prompt, seed=None, **kw: None)
    monkeypatch.setattr(media, "fetch_image_bytes", lambda url: None)   # download fails

    gid = client.post("/games", json=WORLD).json()["game_id"]
    mara = client.get(f"/games/{gid}/state").json()["characters"][0]
    assert mara["face_url"] == "/image/file?filename=f"     # fell back to the image-api URL
