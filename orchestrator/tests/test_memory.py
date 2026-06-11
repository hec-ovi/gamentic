"""Memory & point-of-view tests.

These pin the two hardest invariants of the brain:
  - Narrator memory: a remembered fact is re-injected into the narrator's context on later turns.
  - Character POV: a character's context contains ONLY what it WITNESSED (stamped per beat),
    including same-scene dialogue (within-scene memory) but NOT scenes it was absent from
    or hidden state. A follower keeps what it lived through across moves.
"""
from app import llm


def _user(call):
    return call["messages"][1]["content"]


def _two_char_world():
    return {
        "title": "Hollow Keep", "setting": "a ruined keep", "tone": "tense",
        "narrator_persona": "Terse.", "opening_scenario": "Dust hangs in the hall.",
        "start_location": "hall", "player_life": 20,
        "characters": [
            {"name": "Mara", "persona": "A blunt scout.", "knowledge": "A tunnel hides behind the altar."},
            {"name": "Bron", "persona": "A nervous squire."},
        ],
        "quests": [{"title": "Survive", "description": "Get out.", "objectives": ["Leave the keep"]}],
        "lore": [],
    }


def _new(client, world):
    return client.post("/games", json=world).json()["game_id"]


def test_narrator_memory_resurfaces_next_turn(client, fake_llm):
    gid = _new(client, _two_char_world())
    fact = "The east bridge is rigged to collapse."
    fake_llm.narrator_script = [
        llm.LLMReply(content="You note the bridge.", tool_calls=[llm.ToolCall("remember", {"note": fact})]),
        llm.LLMReply(content="You walk on."),
    ]
    client.post(f"/games/{gid}/action", json={"action": "I inspect the bridge."})
    client.post(f"/games/{gid}/action", json={"action": "I keep moving."})

    nar = fake_llm.narrator_calls()
    # turn 1 system was built BEFORE remember was applied -> must NOT contain the fact
    assert fact not in nar[0]["system"]
    # turn 2 system was built after -> MUST contain it (memory persisted + re-injected)
    assert fact in nar[1]["system"]


def test_character_sees_same_scene_dialogue(client, fake_llm):
    """Within-scene memory: the 2nd cued character sees what the 1st just said."""
    gid = _new(client, _two_char_world())
    fake_llm.narrator_script = [llm.LLMReply(
        content="The hall stirs.",
        tool_calls=[llm.ToolCall("cue_character", {"name": "Mara"}),
                    llm.ToolCall("cue_character", {"name": "Bron"})],
    )]
    fake_llm.character_replies = {
        "Mara": llm.LLMReply(content="I hear scratching in the walls."),
        "Bron": llm.LLMReply(content="W-what was that noise?"),
    }
    client.post(f"/games/{gid}/action", json={"action": "I freeze and listen."})

    cc = fake_llm.character_calls()
    mara_call = next(c for c in cc if c["system"].startswith("You are Mara"))
    bron_call = next(c for c in cc if c["system"].startswith("You are Bron"))
    # Bron (2nd) sees Mara's line; Mara (1st) does not see Bron's (he hadn't spoken yet)
    assert "scratching in the walls" in _user(bron_call)
    assert "what was that noise" not in _user(mara_call).lower()


def test_character_pov_excludes_unwitnessed_locations(client, fake_llm):
    """Witnessed POV: Mara (following) keeps the hall scene she lived through after the
    move; Bron (left behind in the hall) never sees what was said in the cellar."""
    from app import db
    gid = _new(client, _two_char_world())
    # Mara follows the player so she actually moves to the cellar (scene persistence)
    with db.get_conn() as conn:
        conn.execute("UPDATE characters SET following=1 WHERE game_id=? AND name='Mara'", (gid,))
    # turn 1 in the hall: Mara says something hall-specific
    fake_llm.narrator_script = [
        llm.LLMReply(content="The hall is silent.", tool_calls=[llm.ToolCall("cue_character", {"name": "Mara"})]),
        # turn 2: move to the cellar (Mara follows, Bron stays), cue Mara again
        llm.LLMReply(content="You descend into the cellar's damp gloom.",
                     tool_calls=[llm.ToolCall("move_location", {"location": "cellar"}),
                                 llm.ToolCall("cue_character", {"name": "Mara"})]),
        # turn 3: back to the hall, cue Bron
        llm.LLMReply(content="You climb back up.",
                     tool_calls=[llm.ToolCall("move_location", {"location": "hall"}),
                                 llm.ToolCall("cue_character", {"name": "Bron"})]),
    ]
    fake_llm.character_replies = {"Mara": llm.LLMReply(content="The hall reeks of old rot.")}
    client.post(f"/games/{gid}/action", json={"action": "I look around the hall."})

    fake_llm.character_replies = {"Mara": llm.LLMReply(content="CELLAR_SECRET down here.")}
    client.post(f"/games/{gid}/action", json={"action": "I take the stairs down."})

    # Mara's 2nd context (now in the cellar) KEEPS the hall scene she witnessed
    mara_calls = [c for c in fake_llm.character_calls() if c["system"].startswith("You are Mara")]
    cellar_ctx = _user(mara_calls[-1])
    assert "cellar" in cellar_ctx.lower()
    assert "reeks of old rot" in cellar_ctx              # the follower remembers

    fake_llm.character_replies = {"Bron": llm.LLMReply(content="You were gone a while.")}
    client.post(f"/games/{gid}/action", json={"action": "I head back up."})
    bron_calls = [c for c in fake_llm.character_calls() if c["system"].startswith("You are Bron")]
    bron_ctx = _user(bron_calls[-1])
    assert "CELLAR_SECRET" not in bron_ctx               # he was not there
    assert "damp gloom" not in bron_ctx                  # nor the cellar narration


def test_narrator_sees_full_history_across_locations(client, fake_llm):
    gid = _new(client, _two_char_world())
    fake_llm.narrator_script = [
        llm.LLMReply(content="A torch sputters in the HALL_MARKER.",
                     tool_calls=[llm.ToolCall("move_location", {"location": "cellar"})]),
        llm.LLMReply(content="The cellar waits."),
    ]
    client.post(f"/games/{gid}/action", json={"action": "I light a torch."})
    client.post(f"/games/{gid}/action", json={"action": "I go down."})

    # turn 2 narrator transcript (full history) still contains the turn-1 hall narration
    assert "HALL_MARKER" in _user(fake_llm.narrator_calls()[1])


def test_character_private_knowledge_in_own_context_only(client, fake_llm):
    gid = _new(client, _two_char_world())
    fake_llm.narrator_script = [llm.LLMReply(
        content="The altar looms.",
        tool_calls=[llm.ToolCall("cue_character", {"name": "Mara"}),
                    llm.ToolCall("cue_character", {"name": "Bron"})])]
    fake_llm.character_replies = {"Mara": llm.LLMReply(content="..."), "Bron": llm.LLMReply(content="...")}
    client.post(f"/games/{gid}/action", json={"action": "I approach the altar."})

    cc = fake_llm.character_calls()
    mara = next(c for c in cc if c["system"].startswith("You are Mara"))
    bron = next(c for c in cc if c["system"].startswith("You are Bron"))
    # Mara's secret is in HER system prompt, never in Bron's, never in the player-facing narrator transcript
    assert "tunnel hides behind the altar" in mara["system"]
    assert "tunnel hides behind the altar" not in bron["system"]
    assert "tunnel hides behind the altar" not in _user(fake_llm.narrator_calls()[0])
