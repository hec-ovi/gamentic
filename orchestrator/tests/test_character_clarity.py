"""The who-is-who round (live 2026-06-12, "Shadows of the Eternal Night"):

1. A whispered request for a weapon got a flawless in-prose handover and NO give_item
   call - the pack never changed. The give tool works in the whisper channel (proven
   here) and give marks written as text now lift exactly like memory marks.
2. The hero's words were credited to another guest, and a private apology was answered
   with a speech to the room. Every character call now states the roster outright
   (WITH YOU IN THE SCENE) instead of leaving the cast to be inferred from prose.
"""
from app import llm
from app.engine import parsing


def _world(chars):
    return {
        "title": "Eternal Night", "setting": "a rain-drenched mansion", "tone": "noir",
        "narrator_persona": "Terse.", "opening_scenario": "The study is silent.",
        "start_location": "study", "player_life": 20,
        "characters": chars,
        "quests": [{"title": "Survive", "description": "Don't die.", "objectives": ["Last the night"]}],
        "lore": [],
    }


def _char(name):
    return {"name": name, "persona": f"{name}, a guest of the house.", "life": 10, "max_life": 10}


def _new(client, chars):
    return client.post("/games", json=_world(chars)).json()["game_id"]


def _find(state, name):
    return next(c for c in state["characters"] if c["name"] == name)


# ---------- give works in the whisper channel, and the receipt stays private ----------

def test_whisper_give_tool_lands_in_pack_privately(client, fake_llm):
    gid = _new(client, [_char("Mara")])
    cid = _find(client.get(f"/games/{gid}/state").json(), "Mara")["id"]
    fake_llm.character_replies = {"Mara": llm.LLMReply(
        content='[say]Take it, quietly.[/say]',
        tool_calls=[llm.ToolCall("give_item", {"item": "a .44 revolver",
                                               "description": "heavy, blackened iron",
                                               "target": "player"})])}
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "target": "Mara", "text": "I need my weapon, as always."}]}).json()
    inv = d["state"]["player"]["inventory"]
    assert [i["name"] for i in inv] == ["a .44 revolver"]      # produced on the fly, landed
    receipt = next(b for b in d["beats"] if b["kind"] == "system" and "gives" in b["text"])
    assert receipt["text"] == "Mara gives a .44 revolver to you."
    assert receipt["private_with"] == cid                      # the room never hears it
    prof = client.get(f"/games/{gid}/characters/{cid}/profile").json()
    assert "Gave the player a .44 revolver" in [m["text"] for m in prof["moments"]]


# ---------- give marks written as prose land exactly like real calls ----------

def test_give_mark_in_prose_lands_like_a_call(client, fake_llm):
    gid = _new(client, [_char("Mara")])
    fake_llm.narrator = llm.LLMReply(content="Mara reaches into her coat.",
                                     tool_calls=[llm.ToolCall("cue_character", {"name": "Mara"})])
    fake_llm.character_replies = {"Mara": llm.LLMReply(
        content='[say]You will need this.[/say][do]She slides it across the table.[/do]'
                '[give_item, a blackened iron revolver]')}
    d = client.post(f"/games/{gid}/action", json={"action": "Hand it over, Mara."}).json()
    assert [i["name"] for i in d["state"]["player"]["inventory"]] == ["a blackened iron revolver"]
    assert any(b["kind"] == "system" and b["text"] == "Mara gives a blackened iron revolver to you."
               for b in d["beats"])
    assert not any("give_item" in b["text"] for b in d["beats"])   # the mark never shows


def test_give_mark_routes_to_a_named_target(client, fake_llm):
    gid = _new(client, [_char("Mara"), _char("Bron")])
    fake_llm.narrator = llm.LLMReply(content="Mara turns to Bron.",
                                     tool_calls=[llm.ToolCall("cue_character", {"name": "Mara"})])
    fake_llm.character_replies = {"Mara": llm.LLMReply(
        content='[do]She passes it over.[/do]{give_item: a silver locket to Bron}')}
    d = client.post(f"/games/{gid}/action", json={"action": "Settle it between you."}).json()
    assert d["state"]["player"]["inventory"] == []               # not the player's
    bron = _find(d["state"], "Bron")
    assert "a silver locket" in [i["name"] for i in bron["inventory"]]


def test_half_written_give_mark_is_inert(client, fake_llm):
    gid = _new(client, [_char("Mara")])
    fake_llm.narrator = llm.LLMReply(content="Mara hesitates.",
                                     tool_calls=[llm.ToolCall("cue_character", {"name": "Mara"})])
    fake_llm.character_replies = {"Mara": llm.LLMReply(
        content='[say]Perhaps later.[/say][give_item')}
    d = client.post(f"/games/{gid}/action", json={"action": "Well, Mara?"}).json()
    assert d["state"]["player"]["inventory"] == []               # nothing invented
    assert not any("give_item" in b["text"] for b in d["beats"])  # and nothing leaks


def test_give_mark_parsing_shapes():
    cleaned, marks = parsing.extract_memory_marks(
        "He nods.[give_item, a worn brass key] {give_item: a coin to Bron}")
    assert cleaned == "He nods."
    assert ("give_item", {"item": "a worn brass key", "target": "player"}) in marks
    assert ("give_item", {"item": "a coin", "target": "Bron"}) in marks
    # bare prose in brackets is narration, never a mark
    cleaned, marks = parsing.extract_memory_marks("[gives him the key]")
    assert marks == []


# ---------- every character call states the roster outright ----------

def test_character_prompt_states_the_roster(client, fake_llm):
    gid = _new(client, [_char("Mara"), _char("Bron")])
    fake_llm.narrator = llm.LLMReply(content="A pause.",
                                     tool_calls=[llm.ToolCall("cue_character", {"name": "Mara"})])
    fake_llm.character_replies = {"Mara": llm.LLMReply(content='[say]Yes?[/say]')}
    client.post(f"/games/{gid}/action", json={"action": "Mara, a word."})
    sys = fake_llm.character_calls()[-1]["system"]
    assert "WITH YOU IN THE SCENE" in sys
    assert "Bron" in sys                                         # the others are named
    assert "you are only Mara" in sys                            # and the self is fenced


def test_roster_with_no_one_else_says_so(client, fake_llm):
    gid = _new(client, [_char("Mara")])
    fake_llm.character_replies = {"Mara": llm.LLMReply(content='[say]Just us.[/say]')}
    client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "target": "Mara", "text": "Are we alone?"}]})
    sys = fake_llm.character_calls()[-1]["system"]
    assert "and no one else." in sys
