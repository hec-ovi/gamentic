"""Player death and the way back (owner spec: aftermath play is a feature, not a bug):
- the player dropping to 0 life flips the story to 'lost' and a system beat lands,
- a heal from 0 on a lost game stages the rescue: status back to 'active',
- the narrator's state block carries a STORY line ONLY while the game is not active,
- turns stay allowed on won/lost games."""
from app import llm


WORLD = {
    "title": "Last Stand", "setting": "a ruined keep", "tone": "grim",
    "narrator_persona": "Terse.", "opening_scenario": "The gate splinters.",
    "start_location": "keep", "player_life": 10,
    "characters": [{"name": "Vex", "persona": "Vex, a raider captain.", "sex": "female"},
                   {"name": "Rook", "persona": "Rook, a raider.", "sex": "male"}],
    "quests": [{"title": "Hold", "objectives": ["Survive the night"]}], "lore": [],
}


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def _new(client):
    return client.post("/games", json=WORLD).json()["game_id"]


def _systems(d):
    return [b["text"] for b in d["beats"] if b["kind"] == "system"]


def test_character_attack_dropping_player_to_zero_loses_the_game(client, fake_llm):
    gid = _new(client)
    fake_llm.narrator = _nar(T("cue_character", name="Vex"), content="Vex closes in.")
    fake_llm.character_replies = {"Vex": llm.LLMReply(
        content="[do]She drives the blade home.[/do]",
        tool_calls=[T("attack", target="player", amount=10)])}
    d = client.post(f"/games/{gid}/action", json={"action": "I stand my ground."}).json()
    assert d["state"]["status"] == "lost"
    assert d["state"]["player"]["life"] == 0
    assert any("Life: 0. You fall." in t for t in _systems(d))


def test_overshoot_damage_clamps_to_zero_and_still_triggers(client, fake_llm):
    gid = _new(client)
    fake_llm.narrator = _nar(T("apply_damage", amount=8, target="player"), content="It tears.")
    client.post(f"/games/{gid}/action", json={"action": "I take the hit."})
    fake_llm.narrator = _nar(T("apply_damage", amount=10, target="player"), content="Black.")
    d = client.post(f"/games/{gid}/action", json={"action": "I stagger."}).json()
    assert d["state"]["player"]["life"] == 0                  # 10 dmg at 2 hp clamps
    assert d["state"]["status"] == "lost"
    assert any("You fall." in t for t in _systems(d))


def test_heal_from_zero_on_a_lost_game_revives_the_story(client, fake_llm):
    gid = _new(client)
    fake_llm.narrator = _nar(T("apply_damage", amount=10, target="player"), content="Dark.")
    client.post(f"/games/{gid}/action", json={"action": "I fall."})
    # turns stay allowed on a lost game; the narrator stages the rescue
    fake_llm.narrator = _nar(T("heal", amount=3, target="player"), content="Hands pull you up.")
    r = client.post(f"/games/{gid}/action", json={"action": "...light?"})
    assert r.status_code == 200
    d = r.json()
    assert d["state"]["status"] == "active"
    assert "You recover 3. Life: 3. You are back from the brink." in _systems(d)
    # an ordinary heal (not from 0) carries no brink line
    fake_llm.narrator = _nar(T("heal", amount=2, target="player"), content="Warmth spreads.")
    d = client.post(f"/games/{gid}/action", json={"action": "I rest."}).json()
    assert "You recover 2. Life: 5." in _systems(d)


def test_state_block_carries_story_line_only_when_not_active(client, fake_llm):
    gid = _new(client)
    client.post(f"/games/{gid}/action", json={"action": "I look around."})
    assert "STORY:" not in fake_llm.narrator_calls()[-1]["system"]   # lean while active

    fake_llm.narrator = _nar(T("apply_damage", amount=10, target="player"), content="Dark.")
    client.post(f"/games/{gid}/action", json={"action": "I charge."})
    fake_llm.narrator = _nar(content="The cold floor holds you.")
    client.post(f"/games/{gid}/action", json={"action": "Am I dead?"})
    system = fake_llm.narrator_calls()[-1]["system"]
    assert "STORY: lost." in system
    assert "fallen" in system and "path back" in system              # the narrator's cue

    fake_llm.narrator = _nar(T("heal", amount=5, target="player"), content="Air returns.")
    client.post(f"/games/{gid}/action", json={"action": "I gasp."})
    fake_llm.narrator = _nar(content="...")
    client.post(f"/games/{gid}/action", json={"action": "I stand."})
    assert "STORY:" not in fake_llm.narrator_calls()[-1]["system"]   # active again: gone


def test_death_mid_cascade_still_completes_the_turn(client, fake_llm):
    gid = _new(client)
    fake_llm.narrator = _nar(T("cue_character", name="Vex"), T("cue_character", name="Rook"),
                             content="They close in together.")
    fake_llm.character_replies = {
        "Vex": llm.LLMReply(content="[say]Down you go.[/say]",
                            tool_calls=[T("attack", target="player", amount=25)]),
        "Rook": llm.LLMReply(content="[do]He spits on the stones beside you.[/do]"),
    }
    r = client.post(f"/games/{gid}/action", json={"action": "I face them."})
    assert r.status_code == 200
    d = r.json()
    assert d["state"]["status"] == "lost"
    assert any("You fall." in t for t in _systems(d))
    # the cascade went on after the kill: the second raider still acted, beats returned
    assert any(b["speaker_name"] == "Rook" and b["kind"] == "action" for b in d["beats"])
