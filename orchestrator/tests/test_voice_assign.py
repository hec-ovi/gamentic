"""Voice assignment via the Maya1 registry: at creation each character gets a DESIGNED
voice composed from their sheet (one character = one stored voice, gender-correct), the
narrator gets a preset, the round-robin presets remain the fallback, and wiping a game
releases its registry entries. All best-effort: voice down never breaks the game."""
from app import media, llm


WORLD = {
    "title": "Voiceworld", "setting": "a town", "tone": "calm",
    "narrator_persona": "Plain.", "opening_scenario": "A square.",
    "start_location": "square", "player_life": 20,
    "characters": [{"name": "Vex", "persona": "a wary scout, blunt",
                    "description": "A sharp-eyed woman."}],
    "quests": [{"title": "x", "objectives": ["x"]}], "lore": [],
}

DESIGNED = "Female voice, early 20s, low smoky pitch, dry sardonic tone"


def _enable_voice(monkeypatch, register=None):
    from app.config import settings
    monkeypatch.setattr(settings, "VOICE_ENABLED", True)
    monkeypatch.setattr(media, "list_voice_ids", lambda: ["narrator", "adult_male"])
    calls = []

    def _register(char_id, name, description, gender=""):
        calls.append({"char_id": char_id, "name": name,
                      "description": description, "gender": gender})
        return register
    monkeypatch.setattr(media, "register_character_voice", _register)
    return calls


def test_characters_get_designed_registry_voices_at_creation(client, fake_llm, monkeypatch):
    calls = _enable_voice(monkeypatch, register=DESIGNED)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    st = client.get(f"/games/{gid}/state").json()

    assert st["narrator_voice_id"] == "narrator"            # narrator keeps a preset
    vex = next(c for c in st["characters"] if c["name"] == "Vex")
    assert vex["voice_id"] == DESIGNED                      # designed, not round-robin

    call = calls[0]
    assert call["char_id"] == vex["id"]                     # one character = one stored voice
    assert "sharp-eyed woman" in call["description"]        # the sheet drives the design
    assert "wary scout" in call["description"]
    assert call["gender"] == "female"                       # gender net feeds the registry


def test_registry_down_falls_back_to_preset_round_robin(client, fake_llm, monkeypatch):
    _enable_voice(monkeypatch, register=None)               # registry unavailable
    gid = client.post("/games", json=WORLD).json()["game_id"]
    vex = client.get(f"/games/{gid}/state").json()["characters"][0]
    assert vex["voice_id"] == "adult_male"                  # voices[(0+1) % 2]


def test_spawned_characters_also_get_registry_voices(client, fake_llm, monkeypatch):
    calls = _enable_voice(monkeypatch, register=DESIGNED)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    fake_llm.narrator = llm.LLMReply(content="Someone arrives.", tool_calls=[
        llm.ToolCall("spawn_character", {"name": "Bron", "persona": "a bored guard, he naps"})])
    client.post(f"/games/{gid}/action", json={"action": "I wait."})
    assert any(c["name"] == "Bron" and c["gender"] == "male" for c in calls)


def test_wiping_a_game_releases_its_voice_registry_entries(client, fake_llm, monkeypatch):
    from app.config import settings
    _enable_voice(monkeypatch, register=DESIGNED)
    released = []
    monkeypatch.setattr(media, "delete_character_voice", released.append)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    vex_id = client.get(f"/games/{gid}/state").json()["characters"][0]["id"]
    client.delete(f"/games/{gid}")
    assert vex_id in released


def test_register_character_voice_wire_shape(monkeypatch):
    """The HTTP layer: POST /characters with id/name/description (+gender when known)."""
    from app.config import settings
    monkeypatch.setattr(settings, "VOICE_ENABLED", True)
    captured = {}

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"voice_id": DESIGNED}

    monkeypatch.setattr(media.httpx, "post",
                        lambda url, json=None, timeout=None: captured.update(url=url, body=json) or _Resp())
    out = media.register_character_voice("c1", "Vex", "a sharp-eyed woman scout", gender="female")
    assert out == DESIGNED
    assert captured["url"].endswith("/characters")
    assert captured["body"] == {"id": "c1", "name": "Vex",
                                "description": "a sharp-eyed woman scout", "gender": "female"}

    monkeypatch.setattr(settings, "VOICE_ENABLED", False)
    assert media.register_character_voice("c1", "Vex", "x") is None   # gated off = silent no-op
