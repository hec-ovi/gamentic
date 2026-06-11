"""Character identity: gender is a SINGLE stored truth feeding image, prose and voice
(live bug: Vex rendered male but the narrator wrote 'she' - both were guessing
independently); origin is a private backstory the narrator and the character know,
discoverable piece by piece into the profile; dialogue loses its wrapping quotes."""
from app import llm, media, db, repo, integrate
from app.models import CharacterIn


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


WORLD = {
    "title": "Idworld", "setting": "a derelict station", "tone": "tense",
    "narrator_persona": "x", "opening_scenario": "The airlock seals behind you.",
    "start_location": "airlock", "player_life": 20,
    "characters": [
        # the Vex case: NO description, NO appearance, persona without pronouns,
        # but an explicit sex from the creator
        {"name": "Vex", "persona": "A wary scavenger who knows the station.",
         "sex": "male",
         "origin": "Grew up in the orbital shipbreaking yards; deserted the salvage guild after the Calder wreck."},
        # gender inferred once from the sheet's pronouns when not explicit
        {"name": "Mara", "persona": "A scout. She is loyal but blunt."},
    ],
    "quests": [{"title": "x", "objectives": ["x"]}], "lore": [],
}


# ---------- gender: one stored truth ----------

def test_explicit_sex_is_stored_and_served(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    chars = {c["name"]: c for c in client.get(f"/games/{gid}/state").json()["characters"]}
    assert chars["Vex"]["gender"] == "male"      # explicit from the creator
    assert chars["Mara"]["gender"] == "female"   # inferred ONCE from her sheet, then stored


def test_gender_reaches_every_consumer(client, fake_llm, monkeypatch):
    monkeypatch.setattr(integrate.media, "list_voice_ids", lambda: ["narrator"])
    from app.config import settings
    monkeypatch.setattr(settings, "VOICE_ENABLED", True)
    gid = client.post("/games", json=WORLD).json()["game_id"]
    # voice: the engine-composed design used the stored gender, not a fresh guess
    # (the persona has no pronouns, so only the stored field can say "male")
    with db.get_conn() as conn:
        vex_row = repo.find_character_by_name(conn, gid, "Vex")
    assert vex_row["voice_design"].startswith("Male voice, ")
    # image: the descriptor leads with the stored gender despite a cue-less sheet
    with db.get_conn() as conn:
        vex = repo.find_character_by_name(conn, gid, "Vex")
    assert integrate.character_descriptor(vex).startswith("male,")
    # prose: the narrator's state block carries it, so pronouns can't drift
    fake_llm.narrator = _nar(content="Vex nods.")
    client.post(f"/games/{gid}/action", json={"action": "I nod at Vex."})
    system = fake_llm.narrator_calls()[-1]["system"]
    assert "Vex (male, neutral" in system
    # the character agent itself is told
    fake_llm.narrator = _nar(T("cue_character", name="Vex"), content="Vex looks over.")
    client.post(f"/games/{gid}/action", json={"action": "Vex?"})
    assert "You are a man." in fake_llm.character_calls()[-1]["system"]


def test_spawn_demands_and_stores_sex(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    spawn = next(t for t in fake_llm.narrator_calls() or [None] if t) if False else None
    fake_llm.narrator = _nar(T("spawn_character", name="Korr", persona="a dock guard",
                               sex="female", origin="Raised on the lower decks."),
                             content="A guard steps out.")
    d = client.post(f"/games/{gid}/action", json={"action": "I knock."}).json()
    korr = next(c for c in d["state"]["characters"] if c["name"] == "Korr")
    assert korr["gender"] == "female"
    # the schema itself demands sex (small models follow required fields)
    schema = next(t for t in fake_llm.narrator_calls()[-1]["tools"]
                  if t["function"]["name"] == "spawn_character")
    assert "sex" in schema["function"]["parameters"]["required"]


def test_sheet_without_any_cue_stays_neutral(client, fake_llm):
    world = dict(WORLD, characters=[{"name": "Ash", "persona": "Keeps the ledger."}])
    gid = client.post("/games", json=world).json()["game_id"]
    ash = client.get(f"/games/{gid}/state").json()["characters"][0]
    assert ash["gender"] == ""                   # never invented, only declared or evidenced


def test_creator_sex_field_maps_to_gender():
    assert CharacterIn(name="x", persona="p", sex="female").gender == "female"


# ---------- origin: private backstory, discoverable ----------

def test_origin_feeds_narrator_and_the_character_but_not_the_player(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    fake_llm.narrator = _nar(T("cue_character", name="Vex"), content="Vex grunts.")
    client.post(f"/games/{gid}/action", json={"action": "Vex, you been here long?"})
    nar_sys = fake_llm.narrator_calls()[-1]["system"]
    assert "PAST: Grew up in the orbital shipbreaking yards" in nar_sys   # narrator knows
    char_sys = fake_llm.character_calls()[-1]["system"]
    assert "YOUR PAST" in char_sys and "shipbreaking yards" in char_sys   # he knows his own
    cid = next(c["id"] for c in client.get(f"/games/{gid}/state").json()["characters"]
               if c["name"] == "Vex")
    prof = client.get(f"/games/{gid}/characters/{cid}/profile").json()
    assert prof["origin"] == []                                           # nothing learned yet
    assert "shipbreaking" not in str(prof)                                # full origin never leaks


def test_reveal_origin_unlocks_into_the_profile(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    fake_llm.narrator = _nar(
        T("reveal_origin", name="Vex", fact="he deserted the salvage guild after the Calder wreck"),
        content="Vex's jaw tightens as he tells it.")
    d = client.post(f"/games/{gid}/action", json={"action": "What happened on the Calder?"}).json()
    assert any(b["kind"] == "system" and
               b["text"] == "You learn of Vex's past: he deserted the salvage guild after the Calder wreck."
               for b in d["beats"])
    cid = next(c["id"] for c in d["state"]["characters"] if c["name"] == "Vex")
    prof = client.get(f"/games/{gid}/characters/{cid}/profile").json()
    assert [o["text"] for o in prof["origin"]] == ["he deserted the salvage guild after the Calder wreck"]
    assert prof["origin"][0]["learned"].startswith("Day ")
    # duplicates unlock silently once
    d = client.post(f"/games/{gid}/action", json={"action": "Tell me again."}).json()
    assert not any("Vex's past" in b["text"] for b in d["beats"] if b["kind"] == "system")


# ---------- dialogue quotes ----------

def test_wrapping_quotes_are_stripped_from_dialogue(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara turns.")
    fake_llm.character_replies = {
        "Mara": llm.LLMReply(content='[say]"Far enough, stranger."[/say][do]She rests a hand on her sword.[/do]')}
    d = client.post(f"/games/{gid}/action", json={"action": "I step closer."}).json()
    line = next(b for b in d["beats"] if b["kind"] == "dialogue")
    assert line["text"] == "Far enough, stranger."          # no wrapping quotes on screen
    act = next(b for b in d["beats"] if b["kind"] == "action" and b["speaker"] != "player")
    assert act["text"] == "She rests a hand on her sword."


def test_partial_quotes_are_left_alone(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara mutters.")
    fake_llm.character_replies = {
        "Mara": llm.LLMReply(content='[say]They call it "the drop" for a reason.[/say]')}
    d = client.post(f"/games/{gid}/action", json={"action": "What is this place?"}).json()
    line = next(b for b in d["beats"] if b["kind"] == "dialogue")
    assert line["text"] == 'They call it "the drop" for a reason.'
