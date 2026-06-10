"""Live game settings (PATCH /games/{gid}/settings): narrator flexibility mode
(easy/normal/hard, instruction-hardened blocks) + narrator voice gender. Plus the wish
channel: 'what I'd like to happen next' rides along with actions and Continue, weighed
by the mode."""
from app import llm


def _patch(client, gid, **body):
    return client.patch(f"/games/{gid}/settings", json=body)


def test_difficulty_switches_the_narrator_mode_block(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    client.post(f"/games/{gid}/action", json={"action": "I wait."})
    sysmsg = fake_llm.narrator_calls()[-1]["system"]
    assert "MODE:" not in sysmsg                               # normal injects nothing

    assert _patch(client, gid, difficulty="hard").status_code == 200
    client.post(f"/games/{gid}/action", json={"action": "I wait."})
    sysmsg = fake_llm.narrator_calls()[-1]["system"]
    assert "MODE: STRICT" in sysmsg and "reject_attempt" in sysmsg

    _patch(client, gid, difficulty="easy")
    client.post(f"/games/{gid}/action", json={"action": "I wait."})
    sysmsg = fake_llm.narrator_calls()[-1]["system"]
    assert "MODE: FLEXIBLE" in sysmsg and "Default to YES" in sysmsg


def test_settings_persist_into_state(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    st = client.get(f"/games/{gid}/state").json()
    assert st["settings"] == {"narrator_gender": "", "difficulty": "normal"}
    _patch(client, gid, difficulty="hard", narrator_gender="female")
    st = client.get(f"/games/{gid}/state").json()
    assert st["settings"] == {"narrator_gender": "female", "difficulty": "hard"}


def test_narrator_gender_redesigns_the_voice(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    r = _patch(client, gid, narrator_gender="female").json()
    assert r["narrator_voice_id"].startswith("Female voice")
    r = _patch(client, gid, narrator_gender="male").json()
    assert r["narrator_voice_id"].startswith("Male voice")
    assert client.get(f"/games/{gid}/state").json()["narrator_voice_id"].startswith("Male voice")


def test_settings_validation(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    assert _patch(client, gid, difficulty="nightmare").status_code == 422
    assert _patch(client, gid, narrator_gender="robot").status_code == 422
    assert client.patch("/games/nope/settings", json={"difficulty": "easy"}).status_code == 404


# ---------- the wish channel ----------

def test_wish_reaches_the_narrator_as_a_hope_not_an_action(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    d = client.post(f"/games/{gid}/action",
                    json={"action": "I open the door.",
                          "wish": "I hope there is a market beyond"}).json()
    user = fake_llm.narrator_calls()[-1]["messages"][1]["content"]
    assert "PLAYER WISH" in user and "market beyond" in user
    assert "NOT an action" in user
    assert not any("market" in b["text"] for b in d["beats"] if b["speaker"] == "player")


def test_wish_rides_along_with_continue(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    client.post(f"/games/{gid}/continue", json={"wish": "let Mara open up a little"})
    user = fake_llm.narrator_calls()[-1]["messages"][1]["content"]
    assert "PLAYER WISH" in user and "Mara open up" in user


def test_no_wish_means_no_wish_block(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    client.post(f"/games/{gid}/action", json={"action": "I wait."})
    assert "PLAYER WISH" not in fake_llm.narrator_calls()[-1]["messages"][1]["content"]
