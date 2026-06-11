"""Character depth (owner's #1): each character gets their own WHOLE context, bounded.
- WITNESS STAMPING: every beat records WHO perceived it, so a late arrival can never
  'remember' talk from before they entered and a follower never forgets prior scenes.
- PER-CHARACTER ROLLING RECAP: witnessed beats older than the recent turns fold into a
  private second-person memory (one background LLM call, only past the cadence threshold).
- YOUR STATE / MOMENTS / TRAIT ANCHOR: what they feel, carry, remember and ARE reaches
  exactly the right agent's prompt - and the narrator stages them with their traits."""
import json

import pytest

from app import db, llm, repo
from app.config import settings


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def _user(call):
    return call["messages"][1]["content"]


def _cid(client, gid, name="Mara"):
    st = client.get(f"/games/{gid}/state").json()
    return next(c["id"] for c in st["characters"] if c["name"] == name)


def _two_char_world():
    return {
        "title": "Whisper Hall", "setting": "a hall", "tone": "tense",
        "narrator_persona": "Terse.", "opening_scenario": "Two figures wait.",
        "start_location": "hall", "player_life": 20,
        "characters": [{"name": "Mara", "persona": "a conspirator", "description": "Sharp-eyed."},
                       {"name": "Bron", "persona": "a guard", "description": "Bored."}],
        "quests": [{"title": "x", "description": "", "objectives": ["x"]}], "lore": [],
    }


@pytest.fixture
def fast_char_summary(monkeypatch):
    monkeypatch.setattr(settings, "CHAR_SUMMARY_EVERY", 3)
    monkeypatch.setattr(settings, "CHAR_SUMMARY_KEEP_TURNS", 1)


def _fold_calls(fake_llm, name):
    return [c for c in fake_llm.calls
            if c["system"].startswith(f"You maintain the private memory of {name}")]


def _char_calls(fake_llm, name):
    return [c for c in fake_llm.character_calls()
            if c["system"].startswith(f"You are {name}")]


# ---------- witness stamping ----------

def test_beats_are_stamped_with_present_witnesses(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    cid = _cid(client, gid)
    client.post(f"/games/{gid}/action", json={"action": "I step inside."})
    with db.get_conn() as conn:
        rows = conn.execute("SELECT * FROM beats WHERE game_id=? ORDER BY turn_index, seq",
                            (gid,)).fetchall()
    for b in rows:   # opening narration + player action + narrator reply, all public
        assert json.loads(b["witnesses"]) == [cid]


def test_whisper_is_witnessed_only_by_its_character(client, fake_llm):
    gid = client.post("/games", json=_two_char_world()).json()["game_id"]
    mara = _cid(client, gid)
    client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "text": "The tunnel. Tonight.", "target": "Mara"}]})
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM beats WHERE game_id=? AND private_with IS NOT NULL", (gid,)).fetchall()
    assert rows   # the whisper and Mara's reply
    for b in rows:
        assert json.loads(b["witnesses"]) == [mara]   # never Bron, despite him standing there


def test_late_arrival_does_not_inherit_earlier_beats(client, fake_llm, world):
    """The knowledge-leak fix: the old window was location-keyed, so a character arriving
    later 'remembered' everything said in the room before they existed."""
    gid = client.post("/games", json=world).json()["game_id"]
    client.post(f"/games/{gid}/action", json={"action": "I bury the OLD_MARKER under the flagstone."})
    fake_llm.narrator = _nar(T("spawn_character", name="Rena", persona="a drifter", sex="female"),
                             content="A stranger steps from the dark.")
    fake_llm.character_replies = {"Rena": llm.LLMReply(content='[say]"Evening."[/say]')}
    client.post(f"/games/{gid}/action", json={"action": "I look up."})
    rena_ctx = _user(_char_calls(fake_llm, "Rena")[-1])
    assert "OLD_MARKER" not in rena_ctx                      # before her time: gone
    assert "A stranger steps from the dark." in rena_ctx     # her own arrival: witnessed


def test_legacy_null_witnesses_fall_back_to_location_rule(client, fake_llm):
    """Beats stamped before the witnesses column existed read NULL; the old location-match
    POV (privacy included) still applies, so existing games keep working."""
    gid = client.post("/games", json=_two_char_world()).json()["game_id"]
    client.post(f"/games/{gid}/action", json={"action": "I mention the HALL_MARKER."})
    client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "text": "BRON_SECRET", "target": "Bron"}]})
    with db.get_conn() as conn:
        conn.execute("UPDATE beats SET witnesses=NULL WHERE game_id=?", (gid,))
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara stirs.")
    client.post(f"/games/{gid}/action", json={"action": "Mara?"})
    ctx = _user(_char_calls(fake_llm, "Mara")[-1])
    assert "HALL_MARKER" in ctx                  # public hall beats still reach her
    assert "BRON_SECRET" not in ctx              # another's whisper still never does


def test_checkpoint_import_keeps_witnessed_memory(client, fake_llm, world):
    """Import remaps character ids; the witness stamps must follow, or the imported
    cast would silently lose its memory of every pre-import beat."""
    gid = client.post("/games", json=world).json()["game_id"]
    client.post(f"/games/{gid}/action", json={"action": "I show Mara the RELIC_MARKER."})
    cp = client.get(f"/games/{gid}/export?kind=checkpoint").json()
    new_gid = client.post("/games/import", json=cp).json()["game_id"]
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara nods.")
    client.post(f"/games/{new_gid}/action", json={"action": "Remember that?"})
    assert "RELIC_MARKER" in _user(_char_calls(fake_llm, "Mara")[-1])


# ---------- the per-character rolling recap ----------

def test_character_recap_folds_once_and_reaches_their_prompt(client, fake_llm, world,
                                                             fast_char_summary):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.charsummary = llm.LLMReply(content="- You remember the player arriving wet and afraid.")
    for i in range(3):
        client.post(f"/games/{gid}/action", json={"action": f"step {i}"})
    folds = _fold_calls(fake_llm, "Mara")
    assert len(folds) == 1                                   # threshold crossed exactly once
    assert "step 0" in _user(folds[0])                       # the fold saw the witnessed beats
    with db.get_conn() as conn:
        c = repo.get_character(conn, _cid(client, gid))
    assert c["memory_summary"] == "- You remember the player arriving wet and afraid."
    assert c["summarized_through"] > 0
    # the recap rides her NEXT prompt, above the scene window, fenced as memory
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara turns.")
    client.post(f"/games/{gid}/action", json={"action": "Mara, talk to me."})
    ctx = _user(_char_calls(fake_llm, "Mara")[-1])
    assert "WHAT YOU REMEMBER OF EARLIER" in ctx and "wet and afraid" in ctx
    assert ctx.index("WHAT YOU REMEMBER OF EARLIER") < ctx.index("CURRENT SCENE")


def test_character_recap_is_scrubbed_before_it_becomes_memory(client, fake_llm, world,
                                                              fast_char_summary):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.charsummary = llm.LLMReply(
        content='- You remember the bridge.\ncue_character("Mara")\n- You remember the fall.')
    for i in range(3):
        client.post(f"/games/{gid}/action", json={"action": f"step {i}"})
    with db.get_conn() as conn:
        c = repo.get_character(conn, _cid(client, gid))
    assert "cue_character" not in c["memory_summary"]
    assert "You remember the bridge." in c["memory_summary"]
    assert "You remember the fall." in c["memory_summary"]


def test_stale_character_fold_is_skipped(client, fake_llm, world, fast_char_summary,
                                         monkeypatch):
    """The fold reads its window, calls the LLM, then writes on a second connection. If a
    rival fold (or a history reset) moved the character's cursor in between, the result
    is stale and must never overwrite the fresher memory."""
    gid = client.post("/games", json=world).json()["game_id"]
    cid = _cid(client, gid)

    def _racy(messages, **kw):
        sys = messages[0]["content"] if messages else ""
        if sys.startswith("You maintain the private memory"):
            with db.get_conn() as conn:      # a rival fold lands while this one runs
                repo.set_character_summary(conn, cid, "- The rival fold landed first.", 99)
            return llm.LLMReply(content="- The stale fold result.")
        return fake_llm(messages, **kw)
    monkeypatch.setattr(llm, "chat", _racy)
    for i in range(3):
        client.post(f"/games/{gid}/action", json={"action": f"step {i}"})
    with db.get_conn() as conn:
        c = repo.get_character(conn, cid)
    assert c["memory_summary"] == "- The rival fold landed first."   # stale write skipped
    assert c["summarized_through"] == 99


def test_dead_characters_never_fold(client, fake_llm, fast_char_summary):
    gid = client.post("/games", json=_two_char_world()).json()["game_id"]
    fake_llm.narrator = _nar(T("kill_character", name="Bron"), content="Bron drops.")
    client.post(f"/games/{gid}/action", json={"action": "It happens fast."})
    fake_llm.narrator = llm.LLMReply(content="The hall settles.")
    for i in range(3):
        client.post(f"/games/{gid}/action", json={"action": f"step {i}"})
    assert _fold_calls(fake_llm, "Mara")                     # the living fold
    assert not _fold_calls(fake_llm, "Bron")                 # the dead never do


def test_whispers_to_others_never_enter_a_fold(client, fake_llm, fast_char_summary):
    gid = client.post("/games", json=_two_char_world()).json()["game_id"]
    client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "text": "EAVES_SECRET", "target": "Bron"}]})
    for i in range(4):
        client.post(f"/games/{gid}/action", json={"action": f"step {i}"})
    folds = _fold_calls(fake_llm, "Mara")
    assert folds
    for f in folds:
        assert "EAVES_SECRET" not in _user(f)    # the witnesses stamp keeps it out


def test_clearing_history_resets_character_memory(client, fake_llm, world, fast_char_summary):
    gid = client.post("/games", json=world).json()["game_id"]
    for i in range(3):
        client.post(f"/games/{gid}/action", json={"action": f"step {i}"})
    cid = _cid(client, gid)
    with db.get_conn() as conn:
        assert repo.get_character(conn, cid)["memory_summary"]   # a fold landed
    client.delete(f"/games/{gid}/beats")
    with db.get_conn() as conn:
        c = repo.get_character(conn, cid)
    assert c["memory_summary"] == "" and c["summarized_through"] == 0


# ---------- YOUR STATE ----------

def test_your_state_speaks_in_words_never_numbers(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("add_item", name="silver locket"), content="A locket glints.")
    client.post(f"/games/{gid}/action", json={"action": "I pocket the locket."})
    fake_llm.narrator = llm.LLMReply(content="She takes it.")   # default-accept transfers it
    client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "give", "item": "silver locket", "target": "Mara"}]})
    fake_llm.narrator = _nar(T("apply_damage", target="Mara", amount=4),   # two blows under
                             T("apply_damage", target="Mara", amount=3),   # DAMAGE_CAP: 3/10 left
                             T("set_disposition", name="Mara", disposition="friendly"),
                             T("cue_character", name="Mara"),
                             content="The blow lands; she still smiles.")
    client.post(f"/games/{gid}/action", json={"action": "Hold on, Mara."})
    system = _char_calls(fake_llm, "Mara")[-1]["system"]
    assert "YOUR STATE:" in system
    assert "you are badly wounded" in system
    assert "you carry silver locket" in system
    assert "you feel friendly toward the one you are with" in system
    assert "3/10" not in system and "3 hp" not in system     # felt, never counted


def test_your_state_is_lean_when_nothing_to_say(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara waits.")
    client.post(f"/games/{gid}/action", json={"action": "I wait too."})
    system = _char_calls(fake_llm, "Mara")[-1]["system"]
    assert "you feel neutral toward the one you are with" in system  # disposition always speaks
    assert "you carry" not in system                         # empty-handed: omitted
    for words in ("roughed up", "you are hurt", "badly wounded"):
        assert words not in system                           # full life: omitted


# ---------- moments ----------

def test_moment_eviction_keeps_the_newest(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    cid = _cid(client, gid)
    fake_llm.narrator = _nar(*[T("note_moment", name="Mara", event=f"Moment {i}")
                               for i in range(21)], content="A long day.")
    client.post(f"/games/{gid}/action", json={"action": "Everything happens."})
    prof = client.get(f"/games/{gid}/characters/{cid}/profile").json()
    texts = [m["text"] for m in prof["moments"]]
    assert len(texts) == 20                                  # cap holds
    assert "Moment 0" not in texts                           # the OLDEST yielded
    assert texts[-1] == "Moment 20"                          # the newest landed
    # dedupe survives eviction: replaying an existing moment changes nothing
    fake_llm.narrator = _nar(T("note_moment", name="Mara", event="Moment 20"), content="...")
    client.post(f"/games/{gid}/action", json={"action": "Again."})
    prof = client.get(f"/games/{gid}/characters/{cid}/profile").json()
    assert [m["text"] for m in prof["moments"]].count("Moment 20") == 1


def test_newest_moments_render_in_their_prompt_only(client, fake_llm):
    gid = client.post("/games", json=_two_char_world()).json()["game_id"]
    fake_llm.narrator = _nar(*[T("note_moment", name="Mara", event=f"Moment {i}")
                               for i in range(10)],
                             T("cue_character", name="Mara"),
                             T("cue_character", name="Bron"), content="Much has passed.")
    client.post(f"/games/{gid}/action", json={"action": "I think back."})
    mara_ctx = _user(_char_calls(fake_llm, "Mara")[-1])
    assert "Pivotal moments:" in mara_ctx
    assert "- Moment 9 (Day 1, morning)" in mara_ctx         # story-clock label rides along
    assert "Moment 2" in mara_ctx                            # newest 8 = moments 2..9
    assert "Moment 1" not in mara_ctx and "Moment 0" not in mara_ctx
    bron_ctx = _user(_char_calls(fake_llm, "Bron")[-1])
    assert "Pivotal moments:" not in bron_ctx                # HER memories, not his
    assert "Moment 9" not in bron_ctx


# ---------- trait anchor + trait-in-action example ----------

def test_traits_anchor_the_final_line_and_a_worked_example(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("note_trait", name="Mara", trait="distrusts authority"),
                             T("note_trait", name="Mara", trait="blunt"),
                             T("cue_character", name="Mara"), content="Mara scowls.")
    client.post(f"/games/{gid}/action", json={"action": "The guards approach."})
    call = _char_calls(fake_llm, "Mara")[-1]
    # recency anchor: the traits are the LAST thing the model reads
    assert _user(call).rstrip().endswith(
        "Respond now, in character, as Mara - distrusts authority; blunt.")
    # the TOP trait frames the format example as a direction, never spliced into the
    # spoken line (static-confirmed: the old spliced example invited trait recitation)
    assert 'Your trait "distrusts authority" is a stance, never a script' in call["system"]
    assert "[say]You know how I am" not in call["system"]
    assert '[say]"Make it quick."[/say]' in call["system"]
    assert call["system"].count("is a stance, never a script") == 1


def test_no_traits_means_no_anchor_and_no_example(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara waits.")
    client.post(f"/games/{gid}/action", json={"action": "I nod."})
    call = _char_calls(fake_llm, "Mara")[-1]
    assert _user(call).rstrip().endswith("Respond now, in character, as Mara.")
    assert "is a stance, never a script" not in call["system"]


# ---------- narrator staging ----------

def test_narrator_state_block_carries_traits_capped_at_four(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    with db.get_conn() as conn:
        for t in ("trait one", "trait two", "trait three", "trait four", "trait five"):
            repo.add_trait(conn, _cid(client, gid), t, settings.CHAR_TRAIT_CAP)
    client.post(f"/games/{gid}/action", json={"action": "I look at Mara."})
    system = fake_llm.narrator_calls()[-1]["system"]
    assert "; traits: trait one, trait two, trait three, trait four)" in system
    assert "trait five" not in system                        # display cap


def test_narrator_state_block_stays_compact_without_traits(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    client.post(f"/games/{gid}/action", json={"action": "I look around."})
    assert "; traits:" not in fake_llm.narrator_calls()[-1]["system"]
