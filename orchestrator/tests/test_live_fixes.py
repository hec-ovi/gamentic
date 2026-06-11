"""Display and persistence regressions found live during the showcase runs (2026-06-10):
a square closing tag shipped to screen as '[/whisper'; a length-cut reply whose last
segment had no completed sentence displayed mid-word; two background renders persisted
under one filename and the second silently replaced the first's image."""
from app import integrate, llm, media
from app.config import settings


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def test_square_closing_tag_never_reaches_the_screen(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara leans in.")
    fake_llm.character_replies = {"Mara": llm.LLMReply(
        content='[say][whisper] You actually got it out?[/whisper][/say]')}
    d = client.post(f"/games/{gid}/action", json={"action": "I tell her."}).json()
    line = next(b for b in d["beats"] if b["kind"] == "dialogue")
    assert line["emotion"] == "whisper"
    assert line["text"] == "You actually got it out?"


def test_sentence_less_lengthcut_fragment_is_dropped(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara flinches.")
    fake_llm.character_replies = {"Mara": llm.LLMReply(
        content="[say]Stop! Don't do that![/say]"
                "[do]She nearly falls off her stool from the sheer shock of the lig[/do]",
        finish_reason="length")}
    d = client.post(f"/games/{gid}/action", json={"action": "I open the case."}).json()
    say = next(b for b in d["beats"] if b["kind"] == "dialogue")
    assert say["text"] == "Stop! Don't do that!"
    assert not [b for b in d["beats"]
                if b["kind"] == "action" and "shock of the lig" in (b["text"] or "")]


def test_two_snapshots_same_turn_keep_distinct_files(client, fake_llm, world,
                                                     monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(media, "generate_scene_image",
                        lambda *a, **k: {"image_url": "/image/file?f=v"})
    monkeypatch.setattr(media, "fetch_image_bytes", lambda u: b"PNG")
    gid = client.post("/games", json=world).json()["game_id"]
    b1 = integrate.generate_view_snapshot(gid)
    b2 = integrate.generate_view_snapshot(gid)
    assert b1["image_url"] != b2["image_url"]   # live: both pointed at one view-t7.png


# ---------- the turn-53 scaffold regression (exact raw bytes from the live DB) ----------

TURN53 = ('(think: state = The Meeting Warehouse, dangerous, Player, The Scout, and The '
          'Buyer are present. The player attempts to grab "the person they trust" (Silas '
          'is elsewhere, so this must be The Scout) and flee. Next state: chaos.)\n'
          '\n'
          'tools: {\n'
          '  set_scene_status: "dangerous",\n'
          '  set_disposition: ["The Buyer", "neutral"],\n'
          '  set_relation: {name: "The Buyer", relation: "dangerous client"},\n'
          '  cue_character: ["The Buyer", "The Scout"]\n'
          '}\n'
          '\n'
          "Prose: The Buyer doesn't move. He stands there, a pillar of charcoal wool.")


def test_example_scaffold_never_reaches_the_screen(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(content=TURN53)
    d = client.post(f"/games/{gid}/action", json={"action": "I make my demand."}).json()
    nar = [b for b in d["beats"] if b["kind"] == "narration"]
    assert nar, "the prose part must survive"
    assert nar[0]["text"] == "The Buyer doesn't move. He stands there, a pillar of charcoal wool."
    for b in d["beats"]:
        t = b["text"] or ""
        assert "(think" not in t and "tools:" not in t and "Prose:" not in t


def test_think_with_nested_parens_strips_whole(client, fake_llm, world):
    from app.engine import parsing
    _, txt = parsing._scrub_narration(
        "(think: a plan (with a nested aside) that goes on)\nThe rain keeps falling.")
    assert txt == "The rain keeps falling."


def test_midline_think_strips(client, fake_llm, world):
    from app.engine import parsing
    _, txt = parsing._scrub_narration(
        "a cold, mechanical promise of violence. (think: state = breach) The doors buckle.")
    assert txt == "a cold, mechanical promise of violence. The doors buckle."


def test_unclosed_think_takes_the_tail(client, fake_llm, world):
    from app.engine import parsing
    _, txt = parsing._scrub_narration(
        "The fog rolls in.\n(think: an aside (nested) that never closes and rambles on")
    assert txt == "The fog rolls in."


def test_scaffold_stops_lead_the_narrator_stop_list(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    client.post(f"/games/{gid}/action", json={"action": "I look around."})
    call = fake_llm.narrator_calls()[-1]
    assert call["stop"][:4] == ["(think:", "\ntools:", "\nTools:", "\nProse:"]
