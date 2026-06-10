"""'Continue': POST /games/{gid}/continue runs a full narrator turn with NO player input,
so the story can advance on its own (the world moves, characters act)."""
from app import llm


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def test_continue_advances_the_story_without_a_player_beat(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(content="Somewhere deeper in the crypt, stone grinds on stone.")
    d = client.post(f"/games/{gid}/continue").json()
    kinds = [b["kind"] for b in d["beats"]]
    assert "narration" in kinds
    assert not any(b["speaker"] == "player" for b in d["beats"])     # nothing attributed to the player


def test_continue_tells_the_narrator_to_drive(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    client.post(f"/games/{gid}/continue")
    user = fake_llm.narrator_calls()[-1]["messages"][1]["content"]
    assert "Continue the story" in user
    assert "no player input" in user


def test_continue_can_cue_characters_and_change_state(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("set_scene_status", status="tense"),
                             T("cue_character", name="Mara"),
                             content="The torch gutters.")
    fake_llm.character_replies = {"Mara": llm.LLMReply(content='[say]"Did you hear that?"[/say]')}
    d = client.post(f"/games/{gid}/continue").json()
    assert any(b["kind"] == "dialogue" and "hear that" in b["text"] for b in d["beats"])
    assert d["state"]["scene_status"] == "tense"


def test_continue_ticks_the_story_clock(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    before = client.get(f"/games/{gid}/state").json()["time"]["minutes"]
    after = client.post(f"/games/{gid}/continue").json()["state"]["time"]["minutes"]
    assert after > before


def test_continue_unknown_game_404(client, fake_llm):
    assert client.post("/games/nope/continue").status_code == 404
