"""Voice identity, engine-owned (the inference-providers fold): at creation each
character gets a DESIGNED voice composed in the engine from their sheet (gender-aware,
spaced within the cast) and stored on their row; the design resolves to a voice_id per
the ACTIVE audio provider (local/fal = the design text, openai = a deterministic named
voice, elevenlabs = a pick from AUDIO_VOICE_POOL). Switching providers re-resolves
ONCE from the stored design; within a provider a voice never reshuffles. voice-api's
/characters registry is no longer called. Voice down/disabled never breaks the game."""
from app import db, llm, media, repo, voice_design
from app.integrate import voice as integrate_voice


WORLD = {
    "title": "Voiceworld", "setting": "a town", "tone": "calm",
    "narrator_persona": "Plain.", "opening_scenario": "A square.",
    "start_location": "square", "player_life": 20,
    "characters": [{"name": "Vex", "persona": "a wary scout, blunt",
                    "description": "A sharp-eyed woman."}],
    "quests": [{"title": "x", "objectives": ["x"]}], "lore": [],
}


def _enable_voice(monkeypatch, voices=("narrator", "adult_male")):
    from app.config import settings
    monkeypatch.setattr(settings, "VOICE_ENABLED", True)
    monkeypatch.setattr(media, "list_voice_ids", lambda: list(voices))
    registry_calls = []
    monkeypatch.setattr(media, "register_character_voice",
                        lambda *a, **k: registry_calls.append((a, k)) or None)
    return registry_calls


def _vex_row(gid):
    with db.get_conn() as conn:
        return dict(repo.get_characters(conn, gid)[0])


def test_characters_get_engine_composed_designs_at_creation(client, fake_llm, monkeypatch):
    registry_calls = _enable_voice(monkeypatch)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    st = client.get(f"/games/{gid}/state").json()

    assert st["narrator_voice_id"] == "narrator"            # narrator keeps a preset
    vex = _vex_row(gid)
    assert vex["voice_design"].startswith("Female voice, ")  # gender-aware design stored
    assert vex["voice_id"] == vex["voice_design"]            # local: the design IS the voice
    assert vex["voice_provider"] == "local"
    assert registry_calls == []                              # voice-api registry: never called


def test_designs_are_deterministic_and_spaced_within_the_cast(client, fake_llm, monkeypatch):
    _enable_voice(monkeypatch)
    world = dict(WORLD, characters=[
        {"name": "Ana", "persona": "a quiet healer", "description": "A young woman."},
        {"name": "Bea", "persona": "a quiet healer", "description": "A young woman."},
    ])
    gid = client.post("/games", json=world).json()["game_id"]
    with db.get_conn() as conn:
        chars = {c["name"]: dict(c) for c in repo.get_characters(conn, gid)}
    assert chars["Ana"]["voice_design"] != chars["Bea"]["voice_design"]  # same sheet, spaced apart
    # deterministic: re-composing with the same id + exclusions gives the same design
    again = voice_design.compose_design(
        key=chars["Ana"]["id"], description="a quiet healer A young woman.".lower(),
        gender="female", exclude=[])
    assert again == voice_design.compose_design(
        key=chars["Ana"]["id"], description="a quiet healer A young woman.".lower(),
        gender="female", exclude=[])


def test_spawned_characters_also_get_designed_voices(client, fake_llm, monkeypatch):
    _enable_voice(monkeypatch)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    fake_llm.narrator = llm.LLMReply(content="Someone arrives.", tool_calls=[
        llm.ToolCall("spawn_character", {"name": "Bron", "persona": "a bored guard, he naps"})])
    client.post(f"/games/{gid}/action", json={"action": "I wait."})
    with db.get_conn() as conn:
        bron = next(dict(c) for c in repo.get_characters(conn, gid) if c["name"] == "Bron")
    assert bron["voice_design"].startswith("Male voice, ")   # gender net feeds the design
    assert bron["voice_id"] == bron["voice_design"]


def test_voice_service_down_is_graceful_designs_still_assigned(client, fake_llm, monkeypatch):
    """Local provider with voice-api down: the narrator preset lookup fails softly,
    but character designs are composed locally so they still land."""
    _enable_voice(monkeypatch, voices=())                   # /voices unreachable
    gid = client.post("/games", json=WORLD).json()["game_id"]
    st = client.get(f"/games/{gid}/state").json()
    assert st["narrator_voice_id"] is None                  # no preset reachable
    vex = _vex_row(gid)
    assert vex["voice_design"] and vex["voice_id"] == vex["voice_design"]


def test_voice_disabled_assigns_nothing(client, fake_llm, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "VOICE_ENABLED", False)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    vex = _vex_row(gid)
    assert vex["voice_id"] is None and vex["voice_design"] == ""


def test_openai_provider_resolves_deterministic_named_voice(client, fake_llm, monkeypatch):
    _enable_voice(monkeypatch)
    monkeypatch.setenv("AUDIO_PROVIDER", "openai")
    gid = client.post("/games", json=WORLD).json()["game_id"]
    vex = _vex_row(gid)
    assert vex["voice_design"].startswith("Female voice, ")  # the design is provider-neutral
    assert vex["voice_id"] in voice_design.OPENAI_VOICES     # resolved to a named voice
    assert vex["voice_provider"] == "openai"
    # stable: the pick is seeded by the character id
    assert vex["voice_id"] == voice_design._stable_pick(voice_design.OPENAI_VOICES, vex["id"])
    st = client.get(f"/games/{gid}/state").json()
    assert st["narrator_voice_id"] in voice_design.OPENAI_VOICES


def test_elevenlabs_pool_pick_and_designless_fallback(client, fake_llm, monkeypatch):
    _enable_voice(monkeypatch)
    monkeypatch.setenv("AUDIO_PROVIDER", "elevenlabs")
    monkeypatch.setenv("AUDIO_VOICE_POOL", "v-alpha, v-beta ,v-gamma")
    gid = client.post("/games", json=WORLD).json()["game_id"]
    vex = _vex_row(gid)
    assert vex["voice_id"] in ("v-alpha", "v-beta", "v-gamma")
    # without a pool the design itself rides through
    monkeypatch.delenv("AUDIO_VOICE_POOL")
    gid2 = client.post("/games", json=WORLD).json()["game_id"]
    vex2 = _vex_row(gid2)
    assert vex2["voice_id"] == vex2["voice_design"]


def test_switching_provider_reresolves_once_and_stays_stable(client, fake_llm, monkeypatch):
    _enable_voice(monkeypatch)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    before = _vex_row(gid)
    assert before["voice_id"] == before["voice_design"]      # local mapping

    monkeypatch.setenv("AUDIO_PROVIDER", "openai")           # .env change, next call
    assert integrate_voice.reresolve_voices() == 1           # one character re-mapped
    after = _vex_row(gid)
    assert after["voice_design"] == before["voice_design"]   # the design never moves
    assert after["voice_id"] in voice_design.OPENAI_VOICES
    assert after["voice_provider"] == "openai"

    assert integrate_voice.reresolve_voices() == 0           # deterministic no-op re-run
    assert _vex_row(gid)["voice_id"] == after["voice_id"]

    monkeypatch.delenv("AUDIO_PROVIDER", raising=False)      # switch back home
    integrate_voice.reresolve_voices()
    assert _vex_row(gid)["voice_id"] == before["voice_design"]


def test_legacy_rows_keep_their_registry_voice_as_the_design(client, fake_llm, monkeypatch):
    """Pre-fold games: voice_id holds the registry-composed design, voice_design is
    empty. The fold adopts the existing voice as the design so nothing changes."""
    _enable_voice(monkeypatch)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    legacy = "Female voice, early 20s, low smoky pitch, dry sardonic tone"
    with db.get_conn() as conn:
        cid = repo.get_characters(conn, gid)[0]["id"]
        conn.execute("UPDATE characters SET voice_id=?, voice_design='', voice_provider='' "
                     "WHERE id=?", (legacy, cid))
    with db.get_conn() as conn:
        integrate_voice.assign_voices_for_game(conn, gid)
    vex = _vex_row(gid)
    assert vex["voice_id"] == legacy and vex["voice_design"] == legacy
    assert vex["voice_provider"] == "local"


def test_wiping_a_game_releases_its_legacy_voice_registry_entries(client, fake_llm, monkeypatch):
    _enable_voice(monkeypatch)
    released = []
    monkeypatch.setattr(media, "delete_character_voice", released.append)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    vex_id = client.get(f"/games/{gid}/state").json()["characters"][0]["id"]
    client.delete(f"/games/{gid}")
    assert vex_id in released


def test_register_character_voice_wire_shape(monkeypatch):
    """Back-compat only: the facade fn still speaks the old registry contract for any
    external caller, though the engine itself no longer calls it."""
    from app.config import settings
    monkeypatch.setattr(settings, "VOICE_ENABLED", True)
    captured = {}
    designed = "Female voice, early 20s, low smoky pitch, dry sardonic tone"

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"voice_id": designed}

    monkeypatch.setattr(media.httpx, "post",
                        lambda url, json=None, timeout=None: captured.update(url=url, body=json) or _Resp())
    out = media.register_character_voice("c1", "Vex", "a sharp-eyed woman scout", gender="female")
    assert out == designed
    assert captured["url"].endswith("/characters")
    assert captured["body"] == {"id": "c1", "name": "Vex",
                                "description": "a sharp-eyed woman scout", "gender": "female"}

    monkeypatch.setattr(settings, "VOICE_ENABLED", False)
    assert media.register_character_voice("c1", "Vex", "x") is None   # gated off = silent no-op
