"""Engine fixes from the 2026-06-11 live e2e audit + 24-agent static review:
1. deterministic movement router (move_location fired once in 40 live turns; an
   exit-button click produced traveling prose but no move, corrupting scene state),
2. mixed public+whisper typed input leaked the whispered words in the public echo,
3. whispers at bad targets were silently swallowed (200, zero beats),
4. private mode:do echo grammar ('you I slide the ledger...'),
5. a death turn ended with status 'active' (the narrator reverted the flip in-reply),
6. client attack amounts were unbounded (typed 'for 999999' = instakill),
7. the resolve pass ran without the narrator's stop list / length trim,
8. 'There is no the lighthouse keeper here.' (article glitch)."""
from app import llm


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def _world(chars=None, start="the inn", life=20):
    return {
        "title": "Graywater", "setting": "a fog-bound port town", "tone": "grim",
        "narrator_persona": "Plain.", "opening_scenario": "Rain on the inn's windows.",
        "start_location": start, "player_life": life, "characters": chars or [],
        "quests": [{"title": "x", "objectives": ["x"]}], "lore": [],
    }


def _new(client, chars=None, start="the inn", life=20):
    return client.post("/games", json=_world(chars, start, life)).json()["game_id"]


def _systems(d):
    return [b["text"] for b in d["beats"] if b["kind"] == "system"]


def _char(state, name):
    return next(c for c in state["characters"] if c["name"] == name)


def _reveal_exit(client, fake_llm, gid, label="the lighthouse path", target="the lighthouse"):
    fake_llm.narrator = _nar(T("add_exit", label=label, target=target))
    client.post(f"/games/{gid}/action", json={"action": "I scan the cliffs."})


# ---- 1. deterministic movement router ----

def test_exit_button_click_moves_before_the_narrator(client, fake_llm):
    gid = _new(client)
    _reveal_exit(client, fake_llm, gid)
    # the FE exit-button contract: {type:"do", text:"go to <label>"}; the narrator
    # calls NO tool (the live failure mode: traveling prose, zero move_location)
    fake_llm.narrator = llm.LLMReply(content="The lighthouse door looms before you.")
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "do", "text": "go to the lighthouse path"}]}).json()
    assert d["state"]["player"]["location"] == "the lighthouse"
    assert "You move to the lighthouse." in _systems(d)
    # the narrator call was built AFTER the move: it narrates the ARRIVAL at a NEW place
    sys = fake_llm.narrator_calls()[-1]["system"]
    assert "LOCATION: the lighthouse" in sys
    assert "NEW PLACE" in sys


def test_returning_through_an_exit_gets_the_returning_block_this_turn(client, fake_llm):
    gid = _new(client)
    fake_llm.narrator = _nar(T("move_location", location="the docks"))
    client.post(f"/games/{gid}/action", json={"action": "I head out."})
    # the move left a back-exit; clicking it is a deterministic RETURN
    fake_llm.narrator = llm.LLMReply(content="The inn's warmth takes you back.")
    client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "do", "text": "go to back to the inn"}]})
    sys = fake_llm.narrator_calls()[-1]["system"]
    assert "RETURNING: The player was last here" in sys   # arrival machinery, SAME turn


def test_typed_text_naming_a_revealed_exit_moves(client, fake_llm):
    gid = _new(client)
    _reveal_exit(client, fake_llm, gid)
    fake_llm.narrator = llm.LLMReply(content="You climb into the wind.")
    d = client.post(f"/games/{gid}/action", json={
        "action": "I follow the lighthouse path up the cliffs."}).json()
    assert d["state"]["player"]["location"] == "the lighthouse"
    assert "You move to the lighthouse." in _systems(d)


def test_movement_language_without_an_exit_match_changes_nothing(client, fake_llm):
    gid = _new(client)
    _reveal_exit(client, fake_llm, gid)
    fake_llm.narrator = llm.LLMReply(content="The harbor is a wall of fog.")
    d = client.post(f"/games/{gid}/action", json={"action": "I wander toward the harbor."}).json()
    assert d["state"]["player"]["location"] == "the inn"   # discovery stays the narrator's
    assert not any(t.startswith("You move to") for t in _systems(d))


def test_say_and_look_segments_never_trigger_the_router(client, fake_llm):
    gid = _new(client, chars=[{"name": "Mara", "persona": "a scout"}])
    _reveal_exit(client, fake_llm, gid)
    fake_llm.narrator = llm.LLMReply(content="Mara nods at the cliffs.")
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "say", "text": "shall we go to the lighthouse path?"},
        {"type": "look", "text": "the lighthouse path"}]}).json()
    assert d["state"]["player"]["location"] == "the inn"
    assert not any(t.startswith("You move to") for t in _systems(d))


def test_one_move_per_turn_first_match_wins(client, fake_llm):
    gid = _new(client)
    fake_llm.narrator = _nar(T("add_exit", label="the cellar stairs", target="the cellar"),
                             T("add_exit", label="the rooftop ladder", target="the roof"))
    client.post(f"/games/{gid}/action", json={"action": "I look for ways out."})
    fake_llm.narrator = llm.LLMReply(content="Down you go.")
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "do", "text": "go to the cellar stairs"},
        {"type": "do", "text": "go to the rooftop ladder"}]}).json()
    assert d["state"]["player"]["location"] == "the cellar"
    assert sum(1 for t in _systems(d) if t.startswith("You move to")) == 1


def test_narrator_restating_the_routed_move_lands_one_receipt(client, fake_llm):
    gid = _new(client)
    _reveal_exit(client, fake_llm, gid)
    # the narrator redundantly calls move_location to the same place: deduped
    fake_llm.narrator = _nar(T("move_location", location="the lighthouse"),
                             content="You arrive at the tower.")
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "do", "text": "go to the lighthouse path"}]}).json()
    assert d["state"]["player"]["location"] == "the lighthouse"
    assert _systems(d).count("You move to the lighthouse.") == 1


# ---- 2. mixed public+whisper echo must not leak the whisper ----

def test_mixed_public_whisper_echo_uses_the_public_only_text(client, fake_llm):
    gid = _new(client, chars=[{"name": "Mara", "persona": "a conspirator"}])
    typed = "I stack the crates, and whisper to Mara that the key is under the floorboard"
    fake_llm.interpret = llm.LLMReply(content="", tool_calls=[T(
        "submit_segments", segments=[
            {"type": "do", "text": "stack the crates by the door"},
            {"type": "whisper", "text": "the key is under the floorboard", "target": "Mara"},
        ])])
    fake_llm.character_replies = {"Mara": llm.LLMReply(content='[say]"Understood."[/say]')}
    d = client.post(f"/games/{gid}/action", json={"action": typed}).json()
    public_player = [b for b in d["beats"] if b["speaker"] == "player" and not b["private_with"]]
    assert public_player and public_player[0]["text"] == "stack the crates by the door"
    assert all("floorboard" not in b["text"] for b in d["beats"] if not b["private_with"])
    # the whisper itself still landed, privately
    assert any(b["private_with"] and "floorboard" in b["text"] for b in d["beats"])


# ---- 3. whispers at bad targets bounce, never swallow ----

def test_whisper_to_unknown_name_bounces_publicly(client, fake_llm):
    gid = _new(client, chars=[{"name": "Mara", "persona": "a scout"}])
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "text": "psst, over here", "target": "Zorblax"}]}).json()
    b = next(b for b in d["beats"] if b["kind"] == "system")
    assert b["text"] == "There is no one called Zorblax here."
    assert not b["private_with"]                 # no channel exists to land it in


def test_whisper_to_a_dead_character_bounces_into_the_private_thread(client, fake_llm):
    gid = _new(client, chars=[{"name": "Mara", "persona": "a scout"}])
    mid = _char(client.get(f"/games/{gid}/state").json(), "Mara")["id"]
    fake_llm.narrator = _nar(T("kill_character", name="Mara"), content="She slumps.")
    client.post(f"/games/{gid}/action", json={"action": "I watch her fall."})
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "text": "Mara? say something", "target": "Mara"}]}).json()
    b = next(b for b in d["beats"] if b["kind"] == "system")
    assert b["text"] == "Mara can no longer hear you."
    assert b["private_with"] == mid
    assert not any(x["kind"] == "dialogue" for x in d["beats"])   # the dead do not answer


def test_whisper_to_a_character_elsewhere_bounces_into_the_private_thread(client, fake_llm):
    gid = _new(client, chars=[{"name": "Mara", "persona": "a scout"}])
    mid = _char(client.get(f"/games/{gid}/state").json(), "Mara")["id"]
    fake_llm.narrator = _nar(T("move_location", location="the flooded vault"),
                             content="You wade on alone.")
    client.post(f"/games/{gid}/action", json={"action": "I press on alone."})
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "text": "do you see this?", "target": "Mara"}]}).json()
    b = next(b for b in d["beats"] if b["kind"] == "system")
    assert b["text"] == "Mara is not here."
    assert b["private_with"] == mid


# ---- 4. private mode:do echo keeps the player's first-person words ----

def test_private_do_echo_keeps_the_players_words(client, fake_llm):
    gid = _new(client, chars=[{"name": "Mara", "persona": "an innkeeper"}])
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "mode": "do",
         "text": "I slide the ledger across the table", "target": "Mara"}]}).json()
    pb = next(b for b in d["beats"] if b["speaker"] == "player")
    assert pb["text"] == "(only Mara notices) I slide the ledger across the table"


# ---- 5. a death turn ends LOST, whatever the model says ----

def test_death_turn_ends_lost_even_if_the_narrator_reverts_status(client, fake_llm):
    """Live shape: lethal damage printed the fall receipt, then a set_game_status
    ('active') later in the SAME reply silently reverted the flip."""
    gid = _new(client, life=10)   # 10 = the sheet clamp's floor (models.WorldSheet)
    fake_llm.narrator = _nar(T("apply_damage", amount=6, target="player"),
                             T("apply_damage", amount=4, target="player"),
                             T("set_scene_status", status="dangerous"),
                             T("set_game_status", status="active"),
                             content="The rocks rush up to meet you.")
    d = client.post(f"/games/{gid}/action", json={
        "action": "I hurl myself off the cliff edge."}).json()
    assert d["state"]["player"]["life"] == 0
    assert any("Life: 0. You fall." in t for t in _systems(d))
    assert d["state"]["status"] == "lost"


def test_damage_at_zero_in_a_lost_game_does_not_replay_the_fall(client, fake_llm):
    gid = _new(client, life=10)   # 10 = the sheet clamp's floor (models.WorldSheet)
    fake_llm.narrator = _nar(T("apply_damage", amount=6, target="player"),
                             T("apply_damage", amount=4, target="player"), content="Black.")
    client.post(f"/games/{gid}/action", json={"action": "I fall."})
    fake_llm.narrator = _nar(T("apply_damage", amount=3, target="player"),
                             content="The waves grind you against the rocks.")
    d = client.post(f"/games/{gid}/action", json={"action": "I open my eyes."}).json()
    assert d["state"]["status"] == "lost"
    assert any("You take 3 damage. Life: 0." in t for t in _systems(d))
    assert not any("You fall." in t for t in _systems(d))   # the fall happened once


# ---- 6. client attack amounts are clamped at the entry seam ----

def test_client_attack_amount_clamps_to_the_cap(client, fake_llm):
    gid = _new(client, chars=[{"name": "Brute", "persona": "a thug"}])
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "attack", "target": "Brute", "amount": 999}]}).json()
    assert _char(d["state"], "Brute")["life"] == 4            # 10 - DAMAGE_CAP(6)
    assert any("6 damage" in t for t in _systems(d))
    # the narrator adjudicated the SANE amount, never the raw one
    user = fake_llm.narrator_calls()[-1]["messages"][-1]["content"]
    assert "attack Brute (6 damage)" in user and "999" not in user


def test_zero_negative_or_junk_amounts_fall_back_to_the_narrator_default(client, fake_llm):
    # API-shaped zero (pydantic now rejects negatives at the boundary, ge=0)
    gid = _new(client, chars=[{"name": "Brute", "persona": "a thug"}])
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "attack", "target": "Brute", "amount": 0}]}).json()
    assert _char(d["state"], "Brute")["life"] == 7            # default 3
    # the interpreter path is model-written JSON, never pydantic-checked: negatives
    # and junk arrive at the engine seam directly
    for bad in (-5, "savage"):
        fake_llm.interpret = llm.LLMReply(content="", tool_calls=[T(
            "submit_segments", segments=[
                {"type": "attack", "target": "Brute", "amount": bad}])])
        client.post(f"/games/{gid}/action", json={"action": "I hit Brute hard."})
    st = client.get(f"/games/{gid}/state").json()
    assert _char(st, "Brute")["life"] == 1                    # 3 + 3 more, never abs(-5)


def test_clamped_amount_still_backfills_a_narrator_accept(client, fake_llm):
    gid = _new(client, chars=[{"name": "Brute", "persona": "a thug"}])
    # the narrator accepts the strike without naming force: the player's CLAMPED amount wins
    fake_llm.narrator = _nar(T("apply_damage", target="Brute"), content="Your blow lands.")
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "attack", "target": "Brute", "amount": 50}]}).json()
    assert _char(d["state"], "Brute")["life"] == 4            # 6 once, not 6 + default
    assert sum(1 for t in _systems(d) if "damage" in t) == 1


# ---- 7. the resolve pass shares the narrator's defenses ----

def test_resolve_pass_gets_the_stop_list_and_a_length_trim(client, fake_llm):
    gid = _new(client, chars=[{"name": "Mara", "persona": "a scout"}])
    fake_llm.narrator = _nar(T("add_item", name="rope"), content="")   # no prose -> resolve
    fake_llm.resolve = llm.LLMReply(
        content="Your fingers close on rough hemp. The coil drags you tow",
        finish_reason="length")
    d = client.post(f"/games/{gid}/action", json={"action": "I grab the rope."}).json()
    rcall = next(c for c in fake_llm.calls
                 if c["system"].startswith("You narrate the immediate outcome"))
    ncall = fake_llm.narrator_calls()[-1]
    assert rcall["stop"] == ncall["stop"] and rcall["stop"]   # same scaffold + cast stops
    nar = next(b for b in d["beats"] if b["kind"] == "narration")
    assert nar["text"] == "Your fingers close on rough hemp."  # mid-word cut trimmed


# ---- 8. article-safe impossible-target bounce ----

def test_impossible_target_bounce_is_article_safe(client, fake_llm):
    gid = _new(client)
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "attack", "target": "the lighthouse keeper"}]}).json()
    assert any(t == "You see no sign of the lighthouse keeper here." for t in _systems(d))


# ---- the attack's HOW reaches the echo and the adjudication line ----

def test_attack_description_rides_into_echo_and_attempt_line(client, fake_llm):
    """Live replay: 'I grab her wrist' composed to a bare 'you attack Mira' and the
    narrator invented a bloody slap; the stated force must reach both surfaces."""
    gid = _new(client, chars=[{"name": "Brute", "persona": "a thug"}])
    fake_llm.narrator = _nar(content="You close the distance.")
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "attack", "target": "Brute", "amount": 2,
         "text": "I grab his wrist and hold it"}]}).json()
    pb = next(b for b in d["beats"] if b["speaker"] == "player")
    assert "you attack Brute: I grab his wrist and hold it" in pb["text"]
    user_blob = "".join(str(m) for m in fake_llm.narrator_calls()[-1]["messages"])
    assert 'attack Brute "I grab his wrist and hold it" (2 damage)' in user_blob


# ---- the stranded-companion net ----

def test_prose_walking_a_stayed_character_along_lands_a_next_turn_note(client, fake_llm):
    """Live replay: 'Basir falls into step behind you' into the stables while
    set_following never fired; the discrepancy must reach the narrator's next turn."""
    gid = _new(client, chars=[{"name": "Basir", "persona": "an old guard"}])
    fake_llm.narrator = _nar(T("move_location", location="The Stables"),
                             content="Basir falls into step behind you as you enter the stables.")
    client.post(f"/games/{gid}/action", json={"action": "Walk with me, Basir."})
    fake_llm.narrator = _nar(content="The hay smells of dust.")
    client.post(f"/games/{gid}/action", json={"action": "I look at the stalls."})
    blob = "".join(str(m) for m in fake_llm.narrator_calls()[-1]["messages"])
    assert "set_following('Basir', true)" in blob


def test_following_companions_and_far_mentions_trigger_no_note(client, fake_llm):
    gid = _new(client, chars=[{"name": "Basir", "persona": "an old guard"}])
    fake_llm.narrator = _nar(T("set_following", name="Basir", following=True),
                             T("move_location", location="The Stables"),
                             content="Basir falls into step behind you. You think of Kaelen far away.")
    client.post(f"/games/{gid}/action", json={"action": "Walk with me, Basir."})
    fake_llm.narrator = _nar(content="Quiet.")
    client.post(f"/games/{gid}/action", json={"action": "I wait."})
    blob = "".join(str(m) for m in fake_llm.narrator_calls()[-1]["messages"])
    assert "set_following('Basir'" not in blob   # he truly came along
