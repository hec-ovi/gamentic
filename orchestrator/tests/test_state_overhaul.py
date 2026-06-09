"""State-overhaul invariants: fixed-vs-loose items, goal seeding, the no-dead-air
resolve pass, the NEW-place signal in the narrator's context, and image-optional gating.
All exercised through the real entry points with the LLM faked at app.llm.chat."""
from app import llm, integrate
from app.config import settings


def _world(chars=None, start="hall", quests=None):
    return {
        "title": "Overhaul", "setting": "a keep", "tone": "grim",
        "narrator_persona": "Plain.", "opening_scenario": "A cold hall.",
        "start_location": start, "player_life": 20, "characters": chars or [],
        "quests": quests or [{"title": "Get out", "description": "", "objectives": ["Find the gate"]}],
        "lore": [],
    }


def _new(client, **kw):
    return client.post("/games", json=_world(**kw)).json()["game_id"]


def _state(client, gid):
    return client.get(f"/games/{gid}/state").json()


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


# ---------- fixed scenery vs loose loot ----------

def test_fixed_scenery_cannot_be_pocketed_but_loot_can(client, fake_llm):
    gid = _new(client)
    fake_llm.narrator = _nar(
        T("place_item", target="scene", name="Ancient Altar", description="bleeds black water", fixed=True),
        T("place_item", target="scene", name="brass key", description="cold", fixed=False),
    )
    client.post(f"/games/{gid}/action", json={"action": "I look around."})
    sc = _state(client, gid)["scene"]
    altar = next(i for i in sc["items"] if i["name"] == "Ancient Altar")
    assert altar["fixed"] is True
    assert next(i for i in sc["items"] if i["name"] == "brass key")["fixed"] is False

    # taking the loot works; taking the fixture is refused in-world (flow continues, not a hard error)
    fake_llm.narrator = _nar(T("take_item", name="brass key"), T("take_item", name="Ancient Altar"))
    out = client.post(f"/games/{gid}/action", json={"action": "I grab what I can."}).json()
    s = _state(client, gid)
    inv = {i["name"] for i in s["player"]["inventory"]}
    assert "brass key" in inv and "Ancient Altar" not in inv          # furniture stays put
    assert {i["name"] for i in s["scene"]["items"]} == {"Ancient Altar"}
    assert any("won't come with you" in b["text"] for b in out["beats"])  # graceful refusal beat


# ---------- goal seeding ----------

def test_goal_seeded_from_first_quest_objective(client, fake_llm):
    gid = _new(client, quests=[{"title": "Escape", "objectives": ["Reach the surface"]}])
    assert _state(client, gid)["current_goal"] == "Reach the surface"


def test_goal_falls_back_to_quest_title_when_no_objectives(client, fake_llm):
    gid = _new(client, quests=[{"title": "Survive the night", "objectives": []}])
    assert _state(client, gid)["current_goal"] == "Survive the night"


# ---------- no dead air: the resolve pass ----------

def test_tool_only_turn_still_narrates(client, fake_llm):
    # The narrator changes state (a move) but writes NO prose: a resolve pass must still
    # produce a narration beat, so the turn is never dead air.
    gid = _new(client)
    fake_llm.narrator = _nar(T("move_location", location="cellar"), content="")  # empty prose + tool
    fake_llm.resolve = llm.LLMReply(content="You descend into the dripping cellar.")
    out = client.post(f"/games/{gid}/action", json={"action": "I go down to the cellar."}).json()
    narrations = [b for b in out["beats"] if b["kind"] == "narration"]
    assert any("cellar" in b["text"].lower() for b in narrations)
    # and the player is never left with a turn that has no voice at all
    assert any(b["kind"] in ("narration", "dialogue", "action") and b["speaker"] != "player"
               for b in out["beats"])


def test_narration_present_is_not_overridden(client, fake_llm):
    # When the narrator DOES write prose, the resolve pass must not fire / duplicate.
    gid = _new(client)
    fake_llm.narrator = _nar(T("move_location", location="cellar"), content="A real narration line.")
    fake_llm.resolve = llm.LLMReply(content="SHOULD-NOT-APPEAR")
    out = client.post(f"/games/{gid}/action", json={"action": "I go down."}).json()
    texts = [b["text"] for b in out["beats"] if b["kind"] == "narration"]
    assert "A real narration line." in texts
    assert all("SHOULD-NOT-APPEAR" not in t for t in texts)


# ---------- internal state-transition reasoning (in the prompt, never in output) ----------

def test_narrator_prompt_has_internal_transition_reasoning(client, fake_llm):
    # The narrator reasons about the transition (state now -> what happened -> what the player
    # did -> next state: changes/kept/transitions) INTERNALLY. The scaffold must be in the
    # system prompt and framed as silent (never printed to the player).
    gid = _new(client)
    client.post(f"/games/{gid}/action", json={"action": "I look around."})
    sys = fake_llm.narrator_calls()[-1]["system"]
    assert "NEXT state" in sys
    assert "what CHANGES" in sys and "what is KEPT" in sys and "TRANSITIONS" in sys
    assert "Never print these questions" in sys  # the questions guide tools/prose, not output


def test_internal_questions_do_not_leak_into_beats(client, fake_llm):
    # A normal turn's player-visible beats never contain the internal scaffold text.
    gid = _new(client)
    out = client.post(f"/games/{gid}/action", json={"action": "I look around."}).json()
    for b in out["beats"]:
        assert "NEXT state" not in b["text"] and "Never print" not in b["text"]


# ---------- the NEW-place signal in the narrator's context ----------

def test_new_place_is_flagged_to_narrator(client, fake_llm):
    gid = _new(client, start="hall")
    # move to a brand-new, undescribed scene
    fake_llm.narrator = _nar(T("move_location", location="dungeon"))
    client.post(f"/games/{gid}/action", json={"action": "I enter the dungeon."})
    # next turn, the narrator's state block should flag the fresh scene as NEW
    fake_llm.narrator = _nar(content="...")
    client.post(f"/games/{gid}/action", json={"action": "I look."})
    sys = fake_llm.narrator_calls()[-1]["system"]
    assert "NEW PLACE" in sys and "dungeon" in sys

    # once described, the NEW flag is gone (it is established)
    fake_llm.narrator = _nar(T("describe_scene", description="A black stone cell."), content="...")
    client.post(f"/games/{gid}/action", json={"action": "I study it."})
    fake_llm.narrator = _nar(content="...")
    client.post(f"/games/{gid}/action", json={"action": "I wait."})
    assert "NEW PLACE" not in fake_llm.narrator_calls()[-1]["system"]


def test_characters_elsewhere_shown_to_narrator(client, fake_llm):
    gid = _new(client, chars=[{"name": "Mara", "persona": "a guard"}], start="hall")
    # Mara is NOT following; the player leaves -> Mara is left behind, and the narrator
    # must be told she is elsewhere (so it stays consistent / can recall her).
    fake_llm.narrator = _nar(T("move_location", location="yard"))
    client.post(f"/games/{gid}/action", json={"action": "I step out to the yard alone."})
    fake_llm.narrator = _nar(content="...")
    client.post(f"/games/{gid}/action", json={"action": "I look around."})
    sys = fake_llm.narrator_calls()[-1]["system"]
    assert "CHARACTERS ELSEWHERE" in sys and "Mara" in sys and "hall" in sys


# ---------- image generation is optional ----------

def test_images_not_scheduled_when_disabled(client, fake_llm, monkeypatch):
    calls = []
    monkeypatch.setattr(integrate, "generate_images_for_game", lambda gid: calls.append(gid))
    monkeypatch.setattr(integrate, "generate_scene_image", lambda gid, sid: calls.append((gid, sid)))
    monkeypatch.setattr(settings, "IMAGE_ENABLED", False)
    _new(client, chars=[{"name": "Mara", "persona": "a guard"}])
    assert calls == []                                    # nothing scheduled with images off


def test_images_scheduled_when_enabled(client, fake_llm, monkeypatch):
    calls = []
    monkeypatch.setattr(integrate, "generate_images_for_game", lambda gid: calls.append("portraits"))
    monkeypatch.setattr(integrate, "generate_scene_image", lambda gid, sid: calls.append("scene"))
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    _new(client, chars=[{"name": "Mara", "persona": "a guard"}])
    assert "portraits" in calls and "scene" in calls
