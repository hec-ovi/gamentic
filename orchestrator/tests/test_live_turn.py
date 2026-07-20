"""The live turn feed and the stop flag, end to end through the real routes: a turn
publishes phases, live beats, streaming text and a final turn_done over the event bus;
POST /stop cuts a running turn short without losing what was already applied. The bus
is captured at integrate.events.publish (its SSE delivery is pinned by the existing
events tests); everything else - routes, engine, SQLite - is real."""
import json

import pytest

from app import llm
from app.engine import live
from app.integrate import events


@pytest.fixture
def feed(monkeypatch):
    """Capture every published live event, decoded."""
    captured = []

    def _publish(gid, kind, **data):
        captured.append({"gid": gid, "kind": kind, **json.loads(json.dumps(data))})
    monkeypatch.setattr(events, "publish", _publish)
    return captured


def _kinds(feed):
    return [e["kind"] for e in feed]


# Realistic lengths matter: the stream view holds back a first line while it could
# still be a screenplay/scaffold shape (~41 chars), so a one-line miniature never
# streams - by design. Real narrator prose clears the window inside the first second.
_PROSE = ("The dust settles over the square as you take stock of the exits, "
          "the faces, the light. Nothing moves first; the town is waiting.")
_SAY = ("[say]Stay close to the wall and keep your voice down until we are "
        "past the gatehouse and its lanterns.[/say]")


def test_a_turn_streams_phases_live_beats_and_prose(client, world, fake_llm, feed):
    fake_llm.narrator = llm.LLMReply(content=_PROSE)
    gid = client.post("/games", json=world).json()["game_id"]
    feed.clear()
    d = client.post(f"/games/{gid}/action", json={"action": "I look around."}).json()

    assert "phase" in _kinds(feed) and "turn_done" in _kinds(feed)
    # every beat the response returned was also announced live, same ids, same order
    live_ids = [e["beat"]["id"] for e in feed if e["kind"] == "live_beat"]
    assert live_ids == [b["id"] for b in d["beats"]]
    # narrator prose streamed as live_text before its beat landed, and closed after
    texts = [e for e in feed if e["kind"] == "live_text" and e["speaker"] == "narrator"]
    assert texts, "narration must stream as live_text"
    joined = "".join(t["text"] for t in texts if t["op"] == "append")
    narration = next(b for b in d["beats"] if b["kind"] == "narration")
    assert narration["text"].startswith(joined) and joined
    sid = texts[0]["sid"]
    order = [(e["kind"], e.get("sid")) for e in feed
             if e["kind"] in ("live_text_done",) or
             (e["kind"] == "live_beat" and e["beat"]["kind"] == "narration")]
    assert order.index(("live_beat", None)) < order.index(("live_text_done", sid))
    # the turn_done event is the LAST event and carries the committed turn index
    assert feed[-1]["kind"] == "turn_done"
    assert feed[-1]["turn_index"] == d["beats"][-1]["turn_index"]
    assert d["stopped"] is False


def test_character_speech_streams_into_the_same_route_as_its_beat(client, world, fake_llm, feed):
    fake_llm.narrator = llm.LLMReply(
        content=_PROSE,
        tool_calls=[llm.ToolCall(name="cue_character", arguments={"name": "Mara"})])
    fake_llm.character = llm.LLMReply(content=_SAY)
    gid = client.post("/games", json=world).json()["game_id"]
    feed.clear()
    d = client.post(f"/games/{gid}/action", json={"action": "I greet the guard."}).json()
    ctexts = [e for e in feed if e["kind"] == "live_text" and e["speaker"] != "narrator"]
    assert ctexts, "character speech must stream"
    assert all(e["beat_kind"] == "dialogue" for e in ctexts)
    dialogue = [b for b in d["beats"] if b["kind"] == "dialogue"]
    assert dialogue and dialogue[0]["text"].startswith(
        "".join(e["text"] for e in ctexts if e["op"] == "append"))


def test_stop_before_the_narrator_keeps_the_echo_and_skips_all_generation(
        client, world, fake_llm, feed):
    gid = client.post("/games", json=world).json()["game_id"]
    live.request_stop(gid)          # pressed between turns: cleared by the next begin
    d = client.post(f"/games/{gid}/action", json={"action": "I look around."}).json()
    assert any(b["kind"] == "narration" for b in d["beats"])   # stale stop was cleared
    assert d["stopped"] is False


def test_stop_mid_narration_cancels_the_whole_turn(client, world, fake_llm, feed):
    fake_llm.narrator = llm.LLMReply(content=_PROSE)
    gid = client.post("/games", json=world).json()["game_id"]
    before = client.get(f"/games/{gid}/beats").json()["beats"]
    clock_before = client.get(f"/games/{gid}/state").json()["time"]
    feed.clear()

    # the stop button fires the moment the first prose fragment reaches the screen
    prior = events.publish

    def _publish(g, kind, **data):
        prior(g, kind, **data)
        if kind == "live_text":
            live.request_stop(gid)
    events.publish = _publish
    try:
        d = client.post(f"/games/{gid}/action", json={"action": "I look around."}).json()
    finally:
        events.publish = prior

    # the turn never happened: no beats (not even the echo), story and clock untouched
    assert d["stopped"] is True and d["beats"] == []
    assert "turn_stopped" in _kinds(feed)
    got = client.get(f"/games/{gid}/beats").json()["beats"]
    assert [b["id"] for b in got] == [b["id"] for b in before]
    assert client.get(f"/games/{gid}/state").json()["time"] == clock_before
    # and the NEXT turn is untouched by the stale flag
    d2 = client.post(f"/games/{gid}/continue", json={}).json()
    assert d2["stopped"] is False
    assert any(b["kind"] == "narration" for b in d2["beats"])


def test_stop_mid_cascade_cancels_narration_and_receipts_too(client, world, fake_llm, feed):
    fake_llm.narrator = llm.LLMReply(
        content=_PROSE,
        tool_calls=[llm.ToolCall(name="cue_character", arguments={"name": "Mara"})])
    fake_llm.character = llm.LLMReply(content=_SAY)
    gid = client.post("/games", json=world).json()["game_id"]
    before = client.get(f"/games/{gid}/beats").json()["beats"]
    feed.clear()
    prior = events.publish

    def _publish(g, kind, **data):
        prior(g, kind, **data)
        # stop the moment the character starts speaking: narration was already
        # streamed - the rollback takes it back anyway (a half-turn is no turn)
        if kind == "live_text" and data.get("speaker") != "narrator":
            live.request_stop(gid)
    events.publish = _publish
    try:
        d = client.post(f"/games/{gid}/action", json={"action": "Step aside."}).json()
    finally:
        events.publish = prior
    assert d["stopped"] is True and d["beats"] == []
    got = client.get(f"/games/{gid}/beats").json()["beats"]
    assert [b["id"] for b in got] == [b["id"] for b in before]


def test_stop_endpoint_is_idempotent_and_validates_the_game(client, world, fake_llm):
    gid = client.post("/games", json=world).json()["game_id"]
    assert client.post(f"/games/{gid}/stop").json() == {"stopping": True}
    assert client.post(f"/games/{gid}/stop").json() == {"stopping": True}
    assert client.post("/games/nope/stop").status_code == 404
    # the flag is game-scoped state only; the next turn clears it and runs whole
    d = client.post(f"/games/{gid}/continue", json={}).json()
    assert d["stopped"] is False and any(b["kind"] == "narration" for b in d["beats"])
