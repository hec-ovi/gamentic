"""Media integration: voice assignment (inline) + character images (background task).

The media network layer is mocked, so these assert the orchestrator's glue, not the
real services. A companion check is that with media DISABLED everything still works.
"""
from app import llm, media


WORLD = {
    "title": "Emberhold", "setting": "a volcanic keep", "tone": "fiery",
    "art_style": "painterly dark fantasy", "narrator_persona": "Grim.",
    "opening_scenario": "Ash drifts down.", "start_location": "gate", "player_life": 20,
    "characters": [
        {"name": "Mara", "persona": "A scout.", "appearance": "scarred dwarf, red braid, leather armor"},
        {"name": "Bron", "persona": "A squire.", "appearance": "lanky youth, soot-stained tunic"},
    ],
    "quests": [{"title": "Hold", "description": "Survive.", "objectives": ["Bar the gate"]}],
    "lore": [],
}


def test_voice_and_image_integration(client, fake_llm, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "VOICE_ENABLED", True)
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(media, "list_voice_ids", lambda: ["af_heart", "am_adam", "bf_emma"])

    seen = {}

    def fake_char_images(descriptor, style="", seed=None):
        seen["descriptor"] = descriptor
        seen["style"] = style
        return {"face_url": "/f.png", "body_front_url": "/bf.png",
                "body_side_url": "/bs.png", "seed": 7}
    monkeypatch.setattr(media, "generate_character_images", fake_char_images)

    gid = client.post("/games", json=WORLD).json()["game_id"]
    s = client.get(f"/games/{gid}/state").json()

    # narrator + each character got a distinct voice (inline assignment)
    assert s["narrator_voice_id"] == "af_heart"
    char_voices = {c["name"]: c["voice_id"] for c in s["characters"]}
    assert char_voices["Mara"] and char_voices["Bron"]
    assert char_voices["Mara"] != char_voices["Bron"]
    assert s["narrator_voice_id"] not in char_voices.values()

    # the background task generated and stored the 3-image reference set per character
    for c in s["characters"]:
        assert c["face_url"] == "/f.png"
        assert c["body_front_url"] == "/bf.png"
        assert c["body_side_url"] == "/bs.png"

    # the appearance descriptor + world art style were passed through
    assert "soot-stained" in seen["descriptor"] or "scarred dwarf" in seen["descriptor"]
    assert seen["style"] == "painterly dark fantasy"


def test_media_disabled_is_harmless(client, fake_llm, monkeypatch):
    """With media off (the default), creation works and assigns nothing - still playable."""
    from app.config import settings
    monkeypatch.setattr(settings, "VOICE_ENABLED", False)
    monkeypatch.setattr(settings, "IMAGE_ENABLED", False)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    s = client.get(f"/games/{gid}/state").json()
    assert s["narrator_voice_id"] is None
    assert all(c["voice_id"] is None for c in s["characters"])
    assert all(c["face_url"] is None for c in s["characters"])
    # the game is fully playable regardless
    fake_llm.narrator = llm.LLMReply(content="The gate shudders.")
    r = client.post(f"/games/{gid}/action", json={"action": "I brace the gate."})
    assert r.status_code == 200
    assert any(b["kind"] == "narration" for b in r.json()["beats"])


def test_voice_service_down_does_not_break_creation(client, fake_llm, monkeypatch):
    """If /voices errors, assignment is skipped, creation still succeeds."""
    from app.config import settings
    monkeypatch.setattr(settings, "VOICE_ENABLED", True)
    monkeypatch.setattr(media, "list_voice_ids", lambda: [])   # simulates an unreachable service
    monkeypatch.setattr(settings, "IMAGE_ENABLED", False)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    assert client.get(f"/games/{gid}/state").json()["narrator_voice_id"] is None
