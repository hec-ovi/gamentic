"""Fictional story time (hybrid): every turn auto-ticks a few minutes so the clock never
freezes, and the narrator jumps it with advance_time. Never the wall clock."""
from app import llm
from app.config import settings


def _world():
    return {
        "title": "Clockworld", "setting": "a keep", "tone": "grim",
        "narrator_persona": "Plain.", "opening_scenario": "A cold hall.",
        "start_location": "hall", "player_life": 20, "characters": [],
        "quests": [{"title": "Get out", "objectives": ["Find the gate"]}], "lore": [],
    }


def _new(client):
    return client.post("/games", json=_world()).json()["game_id"]


def _state(client, gid):
    return client.get(f"/games/{gid}/state").json()


def test_clock_starts_at_zero_with_label(client, fake_llm):
    gid = _new(client)
    t = _state(client, gid)["time"]
    assert t["minutes"] == 0 and t["day"] == 1
    assert t["hour"] == settings.DAY_START_HOUR
    assert t["label"].startswith("Day 1")


def test_every_turn_auto_ticks(client, fake_llm):
    gid = _new(client)
    client.post(f"/games/{gid}/action", json={"action": "I look around."})
    client.post(f"/games/{gid}/action", json={"action": "I listen at the door."})
    t = _state(client, gid)["time"]
    assert t["minutes"] == 2 * settings.TURN_TIME_MINUTES


def test_advance_time_tool_jumps_and_rolls_the_day(client, fake_llm):
    gid = _new(client)
    fake_llm.narrator = llm.LLMReply(content="You make camp; dawn comes gray and cold.",
                                     tool_calls=[llm.ToolCall("advance_time", {"amount": 1, "unit": "days"})])
    out = client.post(f"/games/{gid}/action", json={"action": "I camp for the night."}).json()
    t = out["state"]["time"]
    assert t["day"] == 2
    assert any("Day 2" in b["text"] for b in out["beats"] if b["kind"] == "system")


def test_advance_time_rejects_bad_unit_and_zero(client, fake_llm):
    gid = _new(client)
    fake_llm.narrator = llm.LLMReply(content="...", tool_calls=[
        llm.ToolCall("advance_time", {"amount": 3, "unit": "moons"}),
        llm.ToolCall("advance_time", {"amount": 0, "unit": "hours"})])
    client.post(f"/games/{gid}/action", json={"action": "I wait."})
    t = _state(client, gid)["time"]
    assert t["minutes"] == settings.TURN_TIME_MINUTES   # only the auto-tick landed


def test_part_of_day_progresses(client, fake_llm):
    gid = _new(client)
    fake_llm.narrator = llm.LLMReply(content="Dusk falls.",
                                     tool_calls=[llm.ToolCall("advance_time", {"amount": 11, "unit": "hours"})])
    client.post(f"/games/{gid}/action", json={"action": "I travel all day."})
    t = _state(client, gid)["time"]
    assert t["part"] in ("evening", "night")            # start hour 8 + 11h -> 19:xx


def test_narrator_sees_the_clock(client, fake_llm):
    gid = _new(client)
    client.post(f"/games/{gid}/action", json={"action": "I look around."})
    sys = fake_llm.narrator_calls()[-1]["system"]
    assert "TIME: Day 1" in sys
