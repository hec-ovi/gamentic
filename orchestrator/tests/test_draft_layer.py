"""The draft/pending layer: leaving a scene stamps WHEN (story clock) and can carry a
narrator note of open threads (note_scene). Returning hands the narrator the elapsed
fictional time + the note (RETURNING block), for exactly one full turn."""
from app import llm


def _world(chars=None):
    return {
        "title": "Draftworld", "setting": "a town", "tone": "calm",
        "narrator_persona": "Plain.", "opening_scenario": "A quiet square.",
        "start_location": "square", "player_life": 20, "characters": chars or [],
        "quests": [{"title": "Look", "objectives": ["Explore"]}], "lore": [],
    }


def _new(client, chars=None):
    return client.post("/games", json=_world(chars)).json()["game_id"]


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _last_narrator_system(fake_llm):
    return fake_llm.narrator_calls()[-1]["system"]


def test_returning_shows_elapsed_time_and_draft_note(client, fake_llm):
    gid = _new(client)
    # leave a note on the square, then leave for the tavern
    fake_llm.narrator = _nar(T("note_scene", note="A beggar promised information at dusk."),
                             T("move_location", location="tavern"))
    client.post(f"/games/{gid}/action", json={"action": "I head to the tavern."})
    # a day passes elsewhere
    fake_llm.narrator = _nar(T("advance_time", amount=1, unit="days"))
    client.post(f"/games/{gid}/action", json={"action": "I drink and sleep."})
    # come back to the square
    fake_llm.narrator = _nar(T("move_location", location="square"))
    client.post(f"/games/{gid}/action", json={"action": "I return to the square."})
    # the NEXT narrator call (the one with tools) sees the RETURNING block
    fake_llm.narrator = _nar(content="The square has changed.")
    client.post(f"/games/{gid}/action", json={"action": "I look around."})
    sys = _last_narrator_system(fake_llm)
    assert "RETURNING: The player was last here" in sys
    assert "1d" in sys                                  # elapsed fictional time
    assert "beggar promised information" in sys         # the draft note survived

    # ...and it expires after that one full turn
    fake_llm.narrator = _nar(content="...")
    client.post(f"/games/{gid}/action", json={"action": "I wait."})
    assert "RETURNING: The player was last here" not in _last_narrator_system(fake_llm)


def test_first_visit_has_no_returning_block(client, fake_llm):
    gid = _new(client)
    fake_llm.narrator = _nar(T("move_location", location="docks"))
    client.post(f"/games/{gid}/action", json={"action": "I walk to the docks."})
    fake_llm.narrator = _nar(content="...")
    client.post(f"/games/{gid}/action", json={"action": "I look."})
    assert "RETURNING: The player was last here" not in _last_narrator_system(fake_llm)


def test_return_without_note_still_reports_elapsed(client, fake_llm):
    gid = _new(client)
    fake_llm.narrator = _nar(T("move_location", location="tavern"))
    client.post(f"/games/{gid}/action", json={"action": "I head to the tavern."})
    fake_llm.narrator = _nar(T("move_location", location="square"))
    client.post(f"/games/{gid}/action", json={"action": "I go back."})
    fake_llm.narrator = _nar(content="...")
    client.post(f"/games/{gid}/action", json={"action": "I look."})
    sys = _last_narrator_system(fake_llm)
    assert "RETURNING: The player was last here" in sys
    assert "Note from then" not in sys                  # no draft was left
