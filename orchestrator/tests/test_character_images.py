"""A character showing what it is doing.

Owner ask 2026-07-25: "they do not emmit images, it would be fine if once in a while
they just do something and you can see it in a picture... low frequency but should
happen", with the frequency in settings as three easy levels.

The narrator has had show_image with its own cooldown since the start; this is the same
power for the person living the moment. The shot lands as THEIR beat, conditioned on
THEIR reference set, and the pacing shares the narrator's cursor so images stay spaced
however they were asked for.
"""
import pytest

from app import llm, repo, db
from app.config import settings
from app import tools


def _world_with_cast():
    return {
        "title": "The Sunken Crypt", "setting": "a flooded dwarven crypt",
        "tone": "grim", "narrator_persona": "Solemn.",
        "opening_scenario": "Cold water laps at your boots.",
        "start_location": "crypt entrance", "player_life": 20,
        "characters": [{"name": "Mara", "persona": "A wary dwarven scout.",
                        "knowledge": "Knows a secret tunnel."}],
        "quests": [], "lore": [],
    }


@pytest.fixture(autouse=True)
def _images_on(monkeypatch):
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "IMAGE_ART_DIRECTOR", False)


def _cue_mara(fake_llm, content="Mara moves ahead."):
    fake_llm.narrator = llm.LLMReply(
        content=content,
        tool_calls=[llm.ToolCall("cue_character", {"name": "Mara", "impulse": "act"})])


# ---------- the tool is offered only when a shot is actually allowed ----------

def test_the_tool_is_absent_when_images_are_off():
    names = [t["function"]["name"] for t in tools.character_tools(images=False)]
    assert "show_self" not in names


def test_the_tool_is_present_when_a_shot_is_allowed():
    names = [t["function"]["name"] for t in tools.character_tools(images=True)]
    assert "show_self" in names
    assert "attack" in names or "give_item" in names   # the rest of the set is intact


def test_off_never_offers_it(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    _patch(client, gid, character_images="off")
    _cue_mara(fake_llm)
    client.post(f"/games/{gid}/action", json={"action": "I follow."})
    call = fake_llm.character_calls()[-1]
    assert "show_self" not in call["names"]


def test_a_level_that_allows_it_offers_it(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    _patch(client, gid, character_images="often")
    _cue_mara(fake_llm)
    client.post(f"/games/{gid}/action", json={"action": "I follow."})
    call = fake_llm.character_calls()[-1]
    assert "show_self" in call["names"]


# ---------- the shot itself ----------

def test_the_call_becomes_a_render_request_for_that_character(client, fake_llm, world,
                                                              monkeypatch):
    gid = client.post("/games", json=world).json()["game_id"]
    _patch(client, gid, character_images="often")
    _cue_mara(fake_llm)
    fake_llm.character = llm.LLMReply(
        content='[do]She kneels at the altar.[/do]',
        tool_calls=[llm.ToolCall("show_self", {
            "description": "kneeling at a wet stone altar, lantern held low, water to her ankles"})])
    sent = []
    monkeypatch.setattr("app.integrate.generate_character_shot",
                        lambda gid_, cid, desc, priv=None: sent.append((gid_, cid, desc, priv)))
    client.post(f"/games/{gid}/action", json={"action": "I follow."})
    assert len(sent) == 1, "the character's shot was never scheduled"
    _, cid, desc, _ = sent[0]
    with db.get_conn() as conn:
        mara = repo.find_character_by_name(conn, gid, "Mara")
    assert cid == mara["id"]                     # HER shot, not the narrator's
    assert "altar" in desc


def test_an_empty_description_is_refused(client, fake_llm, world, monkeypatch):
    gid = client.post("/games", json=world).json()["game_id"]
    _patch(client, gid, character_images="often")
    _cue_mara(fake_llm)
    fake_llm.character = llm.LLMReply(content='[say]"Here."[/say]',
                                      tool_calls=[llm.ToolCall("show_self", {"description": "  "})])
    sent = []
    monkeypatch.setattr("app.integrate.generate_character_shot",
                        lambda *a, **k: sent.append(a))
    client.post(f"/games/{gid}/action", json={"action": "I follow."})
    assert not sent


def test_only_one_character_shot_per_turn(client, fake_llm, world, monkeypatch):
    gid = client.post("/games", json=world).json()["game_id"]
    _patch(client, gid, character_images="often")
    with db.get_conn() as conn:
        repo.spawn_character(conn, gid, "Bron", "A gruff smith.",
                             location="crypt entrance")
    fake_llm.narrator = llm.LLMReply(
        content="Both move at once.",
        tool_calls=[llm.ToolCall("cue_character", {"name": "Mara", "impulse": "act"}),
                    llm.ToolCall("cue_character", {"name": "Bron", "impulse": "act"})])
    fake_llm.character = llm.LLMReply(
        content="[do]moves[/do]",
        tool_calls=[llm.ToolCall("show_self", {"description": "hauling a slab of stone"})])
    sent = []
    monkeypatch.setattr("app.integrate.generate_character_shot",
                        lambda *a, **k: sent.append(a))
    client.post(f"/games/{gid}/action", json={"action": "I wait."})
    assert len(sent) <= 1, "two characters rendered in the same turn"


# ---------- the render goes through the art director ----------

def test_the_art_director_writes_the_shot_from_the_description_and_the_scene(
        client, fake_llm, world, monkeypatch):
    """The description is the SHOT; the director realizes it with the live context,
    the character as the subject, and the artifacts in view."""
    monkeypatch.setattr(settings, "IMAGE_ART_DIRECTOR", True)
    gid = client.post("/games", json=world).json()["game_id"]
    with db.get_conn() as conn:
        mara = repo.find_character_by_name(conn, gid, "Mara")
        repo.character_add_item(conn, mara["id"], "a brass lantern", "dented")
        repo.add_scene_item(conn, gid, "a cracked altar stone", "wet", False,
                            settings.SCENE_INVENTORY_CAP)
    seen = {}
    def _director(context, fallback):
        seen["ctx"] = context
        return "a directed prompt"
    monkeypatch.setattr("app.integrate.image_prompts._artdirected_prompt", _director)
    monkeypatch.setattr("app.media.generate_scene_image",
                        lambda prompt, **kw: seen.update(prompt=prompt, refs=kw.get("references"))
                        or {"image_url": "http://img/x.png"})
    monkeypatch.setattr("app.integrate.storage._persist", lambda *a, **k: "/media/x.png")

    from app.integrate import jobs
    jobs.generate_character_shot(gid, mara["id"], "kneeling at the altar, lantern held low")

    ctx = seen["ctx"]
    assert "kneeling at the altar" in ctx           # the character's own description
    assert "MARA IS THE SUBJECT" in ctx             # framed on them, not the room
    assert "brass lantern" in ctx                   # what they carry
    assert "cracked altar stone" in ctx             # the scene's artifacts
    assert "PLACE:" in ctx and "TONE:" in ctx       # the usual live context
    assert seen["prompt"] == "a directed prompt"    # the director's text is what renders


def test_the_render_conditions_on_that_characters_own_reference_set(
        client, fake_llm, world, monkeypatch):
    monkeypatch.setattr(settings, "IMAGE_ART_DIRECTOR", False)
    gid = client.post("/games", json=world).json()["game_id"]
    with db.get_conn() as conn:
        mara = repo.find_character_by_name(conn, gid, "Mara")
        repo.set_character_images(conn, mara["id"], face_url="/media/face.png",
                                  body_front_url="/media/body.png")
    seen = {}
    monkeypatch.setattr("app.media.generate_scene_image",
                        lambda prompt, **kw: seen.update(refs=kw.get("references"))
                        or {"image_url": "http://img/x.png"})
    monkeypatch.setattr("app.integrate.storage._persist", lambda *a, **k: "/media/x.png")
    from app.integrate import jobs
    jobs.generate_character_shot(gid, mara["id"], "hauling a slab")
    assert seen["refs"], "the shot rendered without her identity references"


def test_the_beat_belongs_to_the_character_not_the_narrator(
        client, fake_llm, world, monkeypatch):
    monkeypatch.setattr(settings, "IMAGE_ART_DIRECTOR", False)
    gid = client.post("/games", json=world).json()["game_id"]
    with db.get_conn() as conn:
        mara = repo.find_character_by_name(conn, gid, "Mara")
    monkeypatch.setattr("app.media.generate_scene_image",
                        lambda prompt, **kw: {"image_url": "http://img/x.png"})
    monkeypatch.setattr("app.integrate.storage._persist", lambda *a, **k: "/media/x.png")
    from app.integrate import jobs
    beat = jobs.generate_character_shot(gid, mara["id"], "hauling a slab")
    assert beat and beat["speaker"] == mara["id"]
    assert beat["speaker_name"] == "Mara"
    assert beat["kind"] == "image" and beat["image_url"]


# ---------- pacing: the levels mean something ----------

def test_the_levels_are_the_three_the_settings_offer():
    assert sorted(settings.IMAGE_CHARACTER_LEVELS) == ["off", "often", "sometimes"]
    assert settings.IMAGE_CHARACTER_LEVELS["off"] == 0
    assert (settings.IMAGE_CHARACTER_LEVELS["often"]
            < settings.IMAGE_CHARACTER_LEVELS["sometimes"])   # often = a shorter gap


def test_a_fresh_recent_image_blocks_the_next_shot(client, fake_llm, world):
    from app.engine import turn as turn_engine
    gid = client.post("/games", json=world).json()["game_id"]
    _patch(client, gid, character_images="sometimes")
    with db.get_conn() as conn:
        g = repo.get_game(conn, gid)
        gap = settings.IMAGE_CHARACTER_LEVELS["sometimes"]
        repo.add_beat(conn, gid, "narrator", "Narrator", "image", "a shot",
                      "crypt entrance", turn_index=10, seq=0, image_url="/x.png")
        assert not turn_engine._character_image_pacing_ok(conn, gid, 10 + gap - 1, g)
        assert turn_engine._character_image_pacing_ok(conn, gid, 10 + gap, g)


def test_off_blocks_it_whatever_the_cursor_says(client, fake_llm, world):
    from app.engine import turn as turn_engine
    gid = client.post("/games", json=world).json()["game_id"]
    _patch(client, gid, character_images="off")
    with db.get_conn() as conn:
        g = repo.get_game(conn, gid)
        assert not turn_engine._character_image_pacing_ok(conn, gid, 9999, g)


# ---------- the setting itself ----------

def _patch(client, gid, **payload):
    r = client.patch(f"/games/{gid}/settings", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_the_setting_round_trips(client, world):
    gid = client.post("/games", json=world).json()["game_id"]
    st = client.get(f"/games/{gid}/state").json()
    assert st["settings"]["character_images"] == settings.IMAGE_CHARACTER_FREQUENCY
    _patch(client, gid, character_images="often")
    st = client.get(f"/games/{gid}/state").json()
    assert st["settings"]["character_images"] == "often"


def test_a_junk_level_is_refused(client, world):
    gid = client.post("/games", json=world).json()["game_id"]
    r = client.patch(f"/games/{gid}/settings", json={"character_images": "constantly"})
    assert r.status_code == 422


def test_an_unknown_stored_value_falls_back_to_the_default(client, world):
    """A hand-edited row must not silently disable pacing."""
    gid = client.post("/games", json=world).json()["game_id"]
    with db.get_conn() as conn:
        conn.execute("UPDATE games SET character_images=? WHERE id=?", ("whenever", gid))
        g = repo.get_game(conn, gid)
    assert repo.effective_character_images(g) in settings.IMAGE_CHARACTER_LEVELS
