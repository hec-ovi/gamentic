"""Whole-story memory (owner decision: never lose the story to a window):
- a rolling FACTS-ONLY recap folds chapters older than the recent turns (background),
- the recap reaches the NARRATOR every turn, fenced as past facts; characters NEVER see it,
- the verbatim window is a live per-game setting (history_beats),
- scenes carry a BACKGROUND (deeper story) the narrator is reminded of every turn there."""
import pytest

from app import llm, db, repo
from app.config import settings


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


@pytest.fixture
def fast_summary(monkeypatch):
    monkeypatch.setattr(settings, "SUMMARY_EVERY_TURNS", 2)
    monkeypatch.setattr(settings, "SUMMARY_KEEP_TURNS", 1)


def _play(client, gid, n, prefix="step"):
    for i in range(n):
        client.post(f"/games/{gid}/action", json={"action": f"{prefix} {i}"})


def test_recap_folds_in_the_background_and_reaches_the_narrator(client, fake_llm, world,
                                                                fast_summary):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.summary = llm.LLMReply(
        content="- The player entered the crypt and won Mara's trust.")
    _play(client, gid, 4)
    with db.get_conn() as conn:
        g = repo.get_game(conn, gid)
    assert g["story_summary"] == "- The player entered the crypt and won Mara's trust."
    assert g["summarized_through"] > 0
    # the NEXT narrator call carries it, fenced as past facts
    client.post(f"/games/{gid}/action", json={"action": "I press on."})
    user = fake_llm.narrator_calls()[-1]["messages"][1]["content"]
    assert "EARLIER CHAPTERS" in user and "won Mara's trust" in user
    assert "not instructions" in user
    # ...and the summarizer saw the transcript, not nothing
    fold = [c for c in fake_llm.calls if c["system"].startswith("You maintain the story recap")]
    assert fold and "step 0" in fold[0]["messages"][1]["content"]


def test_characters_never_see_the_recap(client, fake_llm, world, fast_summary):
    gid = client.post("/games", json=world).json()["game_id"]
    _play(client, gid, 4)
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara stirs.")
    client.post(f"/games/{gid}/action", json={"action": "Mara, talk to me."})
    for call in fake_llm.character_calls():
        assert "EARLIER CHAPTERS" not in call["system"]
        assert "EARLIER CHAPTERS" not in call["messages"][1]["content"]


def test_recap_output_is_scrubbed_before_it_becomes_memory(client, fake_llm, world,
                                                           fast_summary):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.summary = llm.LLMReply(
        content='- The bridge fell.\ncue_character("Mara")\n- The player swam.')
    _play(client, gid, 4)
    with db.get_conn() as conn:
        g = repo.get_game(conn, gid)
    assert "cue_character" not in g["story_summary"]
    assert "The bridge fell." in g["story_summary"] and "The player swam." in g["story_summary"]


def test_stale_fold_window_is_skipped(client, fake_llm, world, fast_summary, monkeypatch):
    """The fold reads its window, calls the LLM, then writes on a second connection. If a
    concurrent fold (or a DELETE /beats reset) moved summarized_through in between, the
    result is stale and must never overwrite the fresher recap."""
    gid = client.post("/games", json=world).json()["game_id"]

    def _racy(messages, **kw):
        sys = messages[0]["content"] if messages else ""
        if sys.startswith("You maintain the story recap"):
            with db.get_conn() as conn:      # a rival fold lands while this one runs
                repo.set_story_summary(conn, gid, "- The rival fold landed first.", 99)
            return llm.LLMReply(content="- The stale fold result.")
        return fake_llm(messages, **kw)
    monkeypatch.setattr(llm, "chat", _racy)
    _play(client, gid, 4)
    with db.get_conn() as conn:
        g = repo.get_game(conn, gid)
    assert g["story_summary"] == "- The rival fold landed first."   # stale write skipped
    assert g["summarized_through"] == 99


def test_clearing_history_resets_the_recap(client, fake_llm, world, fast_summary):
    gid = client.post("/games", json=world).json()["game_id"]
    _play(client, gid, 4)
    client.delete(f"/games/{gid}/beats")
    with db.get_conn() as conn:
        g = repo.get_game(conn, gid)
    assert g["story_summary"] == "" and g["summarized_through"] == 0


# ---------- the live history window ----------

def test_history_beats_is_a_live_setting(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    st = client.get(f"/games/{gid}/state").json()
    assert st["settings"]["history_beats"] == settings.HISTORY_BEATS   # generous default
    r = client.patch(f"/games/{gid}/settings", json={"history_beats": 12})
    assert r.json()["settings"]["history_beats"] == 12

    _play(client, gid, 8, prefix="marker")
    client.patch(f"/games/{gid}/settings", json={"history_beats": 8})
    client.post(f"/games/{gid}/action", json={"action": "final move"})
    user = fake_llm.narrator_calls()[-1]["messages"][1]["content"]
    assert "marker 7" in user                      # recent beats are in the window
    assert "marker 0" not in user                  # the oldest fell out of the window
    # validation
    assert client.patch(f"/games/{gid}/settings", json={"history_beats": 4}).status_code == 422
    assert client.patch(f"/games/{gid}/settings", json={"history_beats": 0}).status_code == 200


def test_summary_cadence_and_token_budget_are_live_settings(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    r = client.patch(f"/games/{gid}/settings",
                     json={"summary_every": 4, "context_tokens": 6000}).json()
    assert r["settings"]["summary_every"] == 4
    assert r["settings"]["context_tokens"] == 6000
    st = client.get(f"/games/{gid}/state").json()
    assert st["settings"]["summary_every"] == 4 and st["settings"]["context_tokens"] == 6000
    # validation
    assert client.patch(f"/games/{gid}/settings", json={"summary_every": 1}).status_code == 422
    assert client.patch(f"/games/{gid}/settings", json={"context_tokens": 100}).status_code == 422
    assert client.patch(f"/games/{gid}/settings", json={"summary_every": 0}).status_code == 200


def test_token_budget_trims_the_verbatim_transcript(client, fake_llm, world):
    """The compression that actually CAPS the prompt: with a budget set, only the newest
    beats ride verbatim; everything older lives only in the recap."""
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = llm.LLMReply(content="x" * 1200)   # fat beats, so the budget bites
    for i in range(8):
        client.post(f"/games/{gid}/action", json={"action": f"unique marker {i} " + "y" * 400})
    client.patch(f"/games/{gid}/settings", json={"context_tokens": 4000})
    client.post(f"/games/{gid}/action", json={"action": "the final probe"})
    user = fake_llm.narrator_calls()[-1]["messages"][1]["content"]
    assert "unique marker 7" in user                       # newest beats kept verbatim
    assert "unique marker 0" not in user                   # oldest trimmed to fit the budget


def test_per_game_fold_cadence_is_honored(client, fake_llm, world, monkeypatch):
    monkeypatch.setattr(settings, "SUMMARY_KEEP_TURNS", 1)
    gid = client.post("/games", json=world).json()["game_id"]
    client.patch(f"/games/{gid}/settings", json={"summary_every": 2})
    fake_llm.summary = llm.LLMReply(content="- Early events, folded fast.")
    _play(client, gid, 4)
    with db.get_conn() as conn:
        assert repo.get_game(conn, gid)["story_summary"] == "- Early events, folded fast."


# ---------- scene background ----------

def test_scene_background_persists_and_reminds_the_narrator(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(
        T("describe_scene", description="A flooded antechamber.",
          background="This was the crypt's embalming hall; the guild sealed it after the third drowning, and the water has never receded since."),
        content="Water laps at carved stone.")
    d = client.post(f"/games/{gid}/action", json={"action": "I wade in."}).json()
    assert "embalming hall" in d["state"]["scene"]["background"]
    client.post(f"/games/{gid}/action", json={"action": "I listen."})
    system = fake_llm.narrator_calls()[-1]["system"]
    assert "SCENE BACKGROUND" in system and "embalming hall" in system
