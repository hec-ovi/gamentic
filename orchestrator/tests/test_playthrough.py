"""A scripted multi-turn playthrough: play as a user across several turns and
assert cumulative state, beat accumulation, and the story log. This is the
deterministic stand-in for 'play the game and see if the brain holds together'.
"""
from app import llm


WORLD = {
    "title": "The Sunken Crypt", "setting": "a flooded crypt", "tone": "grim",
    "narrator_persona": "Solemn.", "opening_scenario": "Water laps at your boots.",
    "start_location": "entrance", "player_life": 20,
    "characters": [{"name": "Mara", "persona": "A blunt scout."}],
    "quests": [{"title": "Escape the Crypt", "description": "Find a way out.",
                "objectives": ["Find the altar", "Open the tunnel"]}],
    "lore": [{"keys": ["altar"], "content": "The altar bleeds black water.", "constant": False}],
}


def test_full_playthrough(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    st = client.get(f"/games/{gid}/state").json()
    qid = st["quests"][0]["id"]
    oid0, oid1 = (o["id"] for o in st["quests"][0]["objectives"])

    # Turn 1: explore -> gain a torch + points, narrator cues Mara
    fake_llm.narrator_script = [llm.LLMReply(
        content="You find a torch guttering on the wall.",
        tool_calls=[llm.ToolCall("add_item", {"name": "torch"}),
                    llm.ToolCall("award_points", {"amount": 5, "reason": "exploration"}),
                    llm.ToolCall("cue_character", {"name": "Mara"})])]
    fake_llm.character_replies = {"Mara": llm.LLMReply(content="\"Grab it. We'll need the light.\"")}
    t1 = client.post(f"/games/{gid}/action", json={"action": "I search the entrance."}).json()
    assert any(b["kind"] == "dialogue" for b in t1["beats"])
    assert t1["state"]["player"]["points"] == 5
    assert any(i["name"] == "torch" for i in t1["state"]["player"]["inventory"])

    # Turn 2: a trap -> take damage, find the altar (objective done)
    fake_llm.narrator_script = [llm.LLMReply(
        content="A blade springs from the dark and bites your leg; ahead, an altar bleeds.",
        tool_calls=[llm.ToolCall("apply_damage", {"amount": 5}),
                    llm.ToolCall("update_objective", {"objective_id": oid0, "done": True}),
                    llm.ToolCall("move_location", {"location": "altar chamber"})])]
    t2 = client.post(f"/games/{gid}/action", json={"action": "I press deeper."}).json()
    assert t2["state"]["player"]["life"] == 15
    assert t2["state"]["player"]["location"] == "altar chamber"
    assert t2["state"]["quests"][0]["objectives"][0]["done"] is True

    # Turn 3: use the torch to open the tunnel -> consume item, finish quest, score
    fake_llm.narrator_script = [llm.LLMReply(
        content="You torch the vines; the tunnel gapes open. Daylight. You are free.",
        tool_calls=[llm.ToolCall("remove_item", {"name": "torch"}),
                    llm.ToolCall("update_objective", {"objective_id": oid1, "done": True}),
                    llm.ToolCall("complete_quest", {"quest_id": qid}),
                    llm.ToolCall("award_points", {"amount": 20, "reason": "escaped"})])]
    t3 = client.post(f"/games/{gid}/action", json={"action": "I burn the vines blocking the tunnel."}).json()
    p = t3["state"]["player"]
    assert p["points"] == 25
    assert p["inventory"] == []                       # torch consumed
    assert t3["state"]["quests"][0]["status"] == "done"
    assert all(o["done"] for o in t3["state"]["quests"][0]["objectives"])

    # The story log holds everything in order: opening + 3 turns, monotonic turn_index
    beats = client.get(f"/games/{gid}/beats").json()["beats"]
    assert beats[0]["kind"] == "narration" and "Water laps" in beats[0]["text"]
    turns = [b["turn_index"] for b in beats]
    assert turns == sorted(turns)
    assert max(turns) >= 3
    assert sum(1 for b in beats if b["speaker"] == "player") == 3


def test_state_survives_reload(client, fake_llm):
    """State is persisted (DB-backed), not in memory: a fresh GET reflects prior turns."""
    gid = client.post("/games", json=WORLD).json()["game_id"]
    fake_llm.narrator = llm.LLMReply(content="You bleed.", tool_calls=[llm.ToolCall("apply_damage", {"amount": 4})])
    client.post(f"/games/{gid}/action", json={"action": "I cut myself on glass."})
    # brand new state read
    assert client.get(f"/games/{gid}/state").json()["player"]["life"] == 16


def test_non_present_character_cannot_speak(client, fake_llm):
    """POV guard: a character who has left the scene cannot be cued into speaking."""
    from app import db
    gid = client.post("/games", json=WORLD).json()["game_id"]
    with db.get_conn() as conn:
        conn.execute("UPDATE characters SET present=0 WHERE game_id=?", (gid,))
    fake_llm.narrator = llm.LLMReply(content="The room is empty.",
                                     tool_calls=[llm.ToolCall("cue_character", {"name": "Mara"})])
    d = client.post(f"/games/{gid}/action", json={"action": "I call for Mara."}).json()
    assert not any(b["kind"] == "dialogue" for b in d["beats"])


def test_two_characters_capped_reactions(client, fake_llm, monkeypatch):
    """The reaction cap holds: never more dialogue beats than the configured max."""
    from app.config import settings
    monkeypatch.setattr(settings, "MAX_CHARACTER_REACTIONS", 1)
    world = dict(WORLD)
    world["characters"] = [{"name": "Mara", "persona": "a"}, {"name": "Bron", "persona": "b"}]
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = llm.LLMReply(content="Both turn to you.", tool_calls=[
        llm.ToolCall("cue_character", {"name": "Mara"}),
        llm.ToolCall("cue_character", {"name": "Bron"})])
    fake_llm.character_replies = {"Mara": llm.LLMReply(content="hi"), "Bron": llm.LLMReply(content="hi")}
    d = client.post(f"/games/{gid}/action", json={"action": "I greet them."}).json()
    assert sum(1 for b in d["beats"] if b["kind"] == "dialogue") == 1
