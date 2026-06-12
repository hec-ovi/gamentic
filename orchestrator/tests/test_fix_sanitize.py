"""Sanitizer fixes from the 2026-06-11 live e2e audit + 24-agent static review. The
scaffold-regression fixes were narrator-only by design; the audit proved every other
path leaks: a raw HTML state panel stored in a narration beat (turn-19), a character
think span shipped as a visible do beat, a stray ']' in a dialogue beat (edge-C), a
first-line screenplay impersonation no stop or scrub caught, folds and /explain passing
model text near-raw, and clean_prose silencing legitimate lines. Raw bytes pinned from
docs/brain/e2e-2026-06-11/."""
import pytest

from app import db, llm, repo
from app.config import settings
from app.engine import parsing
from app.providers.base import ProviderConfig


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


# ---- 1. markup guard (live turn-19: a raw HTML state panel STORED in a narration beat) ----

TURN19_PROSE = (
    "The heavy fog of Graywater swallows the path behind you, leaving only the sound of "
    "the churning sea far below. The cliff path is slick with salt and moisture, making "
    "every step a gamble against the jagged stone. Ahead, the silhouette of the "
    "lighthouse looms, a broken tooth against the grey sky.\n\n"
    "The path is empty for now, save for the wind.")
# exact live bytes ('salt-sprified' sic): every line of the panel opens with a tag
TURN19_PANEL = (
    '<div style="display: flex; justify-content: space-between;">\n'
    '<div style="flex: 1;">\n'
    '<strong>Exits:</strong>\n'
    '<ul>\n'
    '<li>the salt-sprified cliff path -> The Lighthouse Path</li>\n'
    '</ul>\n'
    '</div>\n'
    '<div style="flex: 1;">\n'
    '<strong>Items in Scene:</strong>\n'
    '<ul>\n'
    '<li>nothing in view</li>\n'
    '</ul>\n'
    '</div>\n'
    '</div>')


def test_state_panel_reduces_to_nothing_and_prose_survives(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(content=TURN19_PROSE + "\n\n" + TURN19_PANEL)
    d = client.post(f"/games/{gid}/action", json={"action": "I walk the cliff path."}).json()
    nar = next(b for b in d["beats"] if b["kind"] == "narration")
    assert nar["text"] == TURN19_PROSE
    for b in d["beats"]:
        t = b["text"] or ""
        assert "<" not in t and "Exits" not in t and "nothing in view" not in t


def test_markup_only_reply_falls_through_to_the_resolve_pass(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(content=TURN19_PANEL)
    d = client.post(f"/games/{gid}/action", json={"action": "I look ahead."}).json()
    texts = [b["text"] or "" for b in d["beats"]]
    assert all("<" not in t and "Exits" not in t for t in texts)
    assert any("The moment settles" in t for t in texts)   # the resolve pass voiced the turn


def test_inline_tag_in_prose_loses_only_the_tag():
    _, t = parsing._scrub_narration("The log lies open. <em>Beware the third tide.</em>")
    assert t == "The log lies open. Beware the third tide."


def test_character_segment_markup_is_scrubbed():
    segs = parsing.parse_character_output(
        '[say]The exits are <strong>two</strong>.[/say]\n<div class="panel">Items: none</div>')
    assert segs == [("say", "The exits are two.", "")]


def test_angle_emotion_tag_survives_the_markup_guard():
    segs = parsing.parse_character_output("[say]<whisper> They are watching us.[/say]")
    assert segs == [("say", "They are watching us.", "whisper")]


def test_leading_angle_emotion_tag_still_lifts_in_narration():
    e, t = parsing._scrub_narration("<whisper> The dark stirs.")
    assert e == "whisper" and t == "The dark stirs."


# ---- 2. character-path think/scaffold strip (was narrator-only by design) ----

def test_leading_think_never_becomes_a_do_beat():
    # the static review's exact repro: the parenthetical splitter CONVERTED the think
    # span into a player-visible action beat
    segs = parsing.parse_character_output(
        "(think: the player is lying, deflect) [say]I have no idea what you mean.[/say]")
    assert segs == [("say", "I have no idea what you mean.", "")]


def test_think_inside_a_say_body_is_deleted_not_reclassified():
    segs = parsing.parse_character_output('[say](think: stay calm) "It was not me."[/say]')
    assert segs == [("say", "It was not me.", "")]


def test_stage_direction_parenthetical_still_splits_into_a_do_beat():
    # the splitter's legitimate job is untouched: a NON-think parenthetical is an action
    segs = parsing.parse_character_output('[say](She studies the stone) "A whetstone."[/say]')
    assert segs == [("do", "She studies the stone", ""), ("say", "A whetstone.", "")]


def test_scaffold_block_in_a_character_reply_dies_whole():
    segs = parsing.parse_character_output(
        '[say]"Fine. Take it."[/say]\ntools: {\n  give_item: {item: "whetstone"}\n}')
    assert segs == [("say", "Fine. Take it.", "")]


def test_xml_think_in_a_character_reply_dies_whole():
    segs = parsing.parse_character_output(
        '<think>lie about the keeper</think>[say]"Nothing happened."[/say]')
    assert segs == [("say", "Nothing happened.", "")]


def test_private_whisper_reply_strips_think_and_keeps_emotion(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.character_replies = {"Mara": llm.LLMReply(
        content="(think: hide the fear) [say][whisper] He is gone. Do not ask.[/say]")}
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "target": "Mara", "text": "what happened to the keeper?"}]}).json()
    line = next(b for b in d["beats"]
                if b["kind"] == "dialogue" and b["speaker_name"] == "Mara")
    assert line["text"] == "He is gone. Do not ask."
    assert line["emotion"] == "whisper"
    assert line["private_with"]
    assert not [b for b in d["beats"] if "think" in (b["text"] or "")]


# ---- 3. trailing tag debris (live edge-C: a dialogue beat stored as 'The keeper?!]') ----

def test_edge_c_stray_close_bracket_is_stripped():
    # the live shape: once the leading [angry] lifts, its half-formed twin's ']' remained
    segs = parsing.parse_character_output(
        '[say]"[angry] The keeper?!]"[/say][do]She grips the rusted lantern.[/do]')
    assert segs == [("say", "The keeper?!", "angry"),
                    ("do", "She grips the rusted lantern.", "")]


def test_leading_bracket_remnant_is_stripped():
    segs = parsing.parse_character_output("[say][Keeper take you all.[/say]")
    assert segs == [("say", "Keeper take you all.", "")]


def test_balanced_brackets_in_speech_survive():
    segs = parsing.parse_character_output("[say]Take the vial [the blue one] and run.[/say]")
    assert segs == [("say", "Take the vial [the blue one] and run.", "")]


# ---- 4. first-line screenplay impersonation (every name-colon stop starts with '\n') ----

def test_first_line_screenplay_impersonation_is_dropped():
    _, t = parsing._scrub_narration('Vane: "Movement. Now."\nThe alley empties out.')
    assert t == "The alley empties out."


def test_multiword_name_screenplay_only_reply_reduces_to_nothing():
    _, t = parsing._scrub_narration('Vane Korr: "Movement. Now."')
    assert t == ""


def test_prose_with_a_mid_sentence_colon_survives():
    raw = "He checks his pack: rope, flint, and the brass medallion."
    _, t = parsing._scrub_narration(raw)
    assert t == raw


def test_route_narration_drops_a_first_line_impersonation(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(content='Mara: "Stay close."\nThe crypt door groans shut.')
    d = client.post(f"/games/{gid}/action", json={"action": "I step in."}).json()
    nar = next(b for b in d["beats"] if b["kind"] == "narration")
    assert nar["text"] == "The crypt door groans shut."


# ---- 5. clean_prose over-deletion (tool-name verb + parens silenced a character) ----

def test_tool_verb_with_a_parenthetical_survives_clean_prose():
    raw = "We attack (quietly) at dawn, before the watch changes."
    assert parsing.clean_prose(raw) == raw


def test_tool_verb_parenthetical_survives_in_a_character_segment():
    segs = parsing.parse_character_output("[say]We attack (quietly) at dawn.[/say]")
    assert segs == [("say", "We attack (quietly) at dawn.", "")]


def test_full_line_call_shapes_still_die():
    raw = ('The standoff tightens.\n'
           'attack(amount=10, target="player")\n'
           'move_location {"name": "the docks"}')
    assert parsing.clean_prose(raw) == "The standoff tightens."


def test_full_line_call_in_a_segment_still_dies():
    assert parsing.parse_character_output("[do]attack(amount=10)[/do]") == []


# ---- 6. fold sanitization (stored recaps are re-fed to prompts every turn) ----

SCAFFOLDED_FOLD = ('(think: condense the chapter)\n'
                   'tools: {\n'
                   '  set_scene_status: "tense"\n'
                   '}\n'
                   '<div class="recap">\n'
                   'Prose: - The player crossed the bridge and met the keeper.')


@pytest.fixture
def fast_summary(monkeypatch):
    monkeypatch.setattr(settings, "SUMMARY_EVERY_TURNS", 2)
    monkeypatch.setattr(settings, "SUMMARY_KEEP_TURNS", 1)


@pytest.fixture
def fast_char_summary(monkeypatch):
    monkeypatch.setattr(settings, "CHAR_SUMMARY_EVERY", 3)
    monkeypatch.setattr(settings, "CHAR_SUMMARY_KEEP_TURNS", 1)


def test_story_fold_strips_think_scaffold_and_markup(client, fake_llm, world, fast_summary):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.summary = llm.LLMReply(content=SCAFFOLDED_FOLD)
    for i in range(4):
        client.post(f"/games/{gid}/action", json={"action": f"step {i}"})
    with db.get_conn() as conn:
        g = repo.get_game(conn, gid)
    assert g["story_summary"] == "- The player crossed the bridge and met the keeper."


def test_character_fold_strips_think_and_scaffold(client, fake_llm, world, fast_char_summary):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.charsummary = llm.LLMReply(
        content="(think: her view of events)\n- You remember the player arriving.")
    for i in range(3):
        client.post(f"/games/{gid}/action", json={"action": f"step {i}"})
    st = client.get(f"/games/{gid}/state").json()
    cid = next(c["id"] for c in st["characters"] if c["name"] == "Mara")
    with db.get_conn() as conn:
        c = repo.get_character(conn, cid)
    assert c["memory_summary"] == "- You remember the player arriving."


# ---- 7. /explain output is scrubbed (was returned raw) ----

def test_explain_output_is_scrubbed(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.explain = llm.LLMReply(content=(
        "(think: keep it spoiler-safe) <think>the altar secret stays hidden</think>\n"
        "<div><strong>Item:</strong></div>\n"
        "A worn brass key, smoothed by many hands."))
    r = client.post(f"/games/{gid}/explain", json={"kind": "scene"})
    assert r.status_code == 200
    assert r.json()["text"] == "A worn brass key, smoothed by many hands."


def test_explain_that_scrubs_to_nothing_returns_the_fallback(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.explain = llm.LLMReply(content="(think: nothing visible to say")
    r = client.post(f"/games/{gid}/explain", json={"kind": "scene"})
    assert r.json()["text"] == "There is little more to say about it."


# ---- 8. stop-list truncation keeps the scaffold guard (built first, sliced from the front) ----

SCAFFOLD_STOPS = ["(think:", "\ntools:", "\nTools:", "\nProse:"]
NAME_STOPS = [f"\nName{i}:" for i in range(8)]


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _capture_post(captured):
    def post(url, **kw):
        captured.append(kw["json"])
        return _Resp({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                      "usage": {}})
    return post


def test_local_truncation_keeps_scaffold_priority(monkeypatch):
    captured = []
    monkeypatch.setattr(llm.httpx, "post", _capture_post(captured))
    llm.chat([{"role": "user", "content": "hi"}], stop=SCAFFOLD_STOPS + NAME_STOPS)
    sent = captured[0]["stop"]
    assert len(sent) == 8                       # the local budget (providers/base.py)
    assert sent[:4] == SCAFFOLD_STOPS           # the front of the list survives the cut


def test_cloud_truncation_keeps_exactly_the_scaffold_stops(monkeypatch):
    cfg = ProviderConfig(modality="text", provider="openai",
                         base_url="http://cloud", model="gpt", max_stops=4)
    monkeypatch.setattr(llm.providers, "resolve", lambda m: cfg)
    captured = []
    monkeypatch.setattr(llm.httpx, "post", _capture_post(captured))
    llm.chat([{"role": "user", "content": "hi"}], stop=SCAFFOLD_STOPS + NAME_STOPS)
    assert captured[0]["stop"] == SCAFFOLD_STOPS


def test_uncapped_budget_sends_the_whole_list(monkeypatch):
    cfg = ProviderConfig(modality="text", provider="local",
                         base_url="http://local", model="m", max_stops=0)
    monkeypatch.setattr(llm.providers, "resolve", lambda m: cfg)
    captured = []
    monkeypatch.setattr(llm.httpx, "post", _capture_post(captured))
    llm.chat([{"role": "user", "content": "hi"}], stop=SCAFFOLD_STOPS + NAME_STOPS)
    assert captured[0]["stop"] == SCAFFOLD_STOPS + NAME_STOPS


# ---- 9. XML-form thinking ('<think>...</think>', not just '(think:') ----

def test_xml_think_span_dies_whole():
    _, t = parsing._scrub_narration(
        "<think>The player is stalling. Escalate.</think>The door splinters.")
    assert t == "The door splinters."


def test_unclosed_xml_think_takes_the_tail():
    _, t = parsing._scrub_narration("The door holds.\n<think>maybe I should stall")
    assert t == "The door holds."


def test_markup_guard_never_unwraps_a_think_span():
    # order matters: if the generic tag strip ran first, the think tags would die and
    # the reasoning would stand as plain prose
    _, t = parsing._scrub_narration(
        "<think>plan: <div>panel</div> escalate</think>The fog rolls in.")
    assert t == "The fog rolls in."


def test_bare_tool_label_lines_die_in_any_spelling():
    """Live showcase 2026-06-11: a narration ended in a stranded 'call_tools:' line -
    the snake_case label dodged the '\\ntools:' stop and the brace-block rule."""
    from app.engine import parsing
    for label in ("call_tools:", "tools:", "Tools:", "tool calls:", "Tool_Calls:"):
        cleaned = parsing.strip_reasoning(f"The fire crackles low.\n\n{label}")
        assert cleaned.strip() == "The fire crackles low.", label
    # a colon that ends a real sentence lead-in survives
    kept = parsing.strip_reasoning("He counted what they had:")
    assert kept.strip() == "He counted what they had:"


def test_separator_only_lines_are_never_prose():
    """Live showcase 2026-06-11: a narration beat was the literal string '---'."""
    from app.engine import parsing
    assert parsing.clean_prose("---") == ""
    assert parsing.clean_prose("The bell tolls.\n---\nNo one answers.") == \
        "The bell tolls.\nNo one answers."
    # the real pipeline (turn.py, both narrator and resolve) runs clean_prose FIRST,
    # so an all-separator reply reaches _scrub_narration as "" and the resolve pass fires
    emotion, text = parsing._scrub_narration(parsing.clean_prose("---"))
    assert text == ""


# ---- 5. the [whisper] span vs the legacy inner-whisper emotion tone ----
# [whisper] is OVERLOADED (owner: "characters should be able to also whisper"). A
# top-level [whisper]...[/whisper] is a private span (kind 'whisper'); an INNER [whisper]
# (the Maya1 idiom [say]"[whisper] ..." or [do][sigh] [whisper] "...") is just the
# emotion tone the extractor lifts. The parser must keep the two apart by nesting.

def test_top_level_whisper_span_parses_as_a_whisper_kind():
    segs = parsing.parse_character_output(
        '[say]"All is well."[/say][whisper]They listen. Say nothing.[/whisper]')
    assert segs == [("say", "All is well.", ""),
                    ("whisper", "They listen. Say nothing.", "")]


def test_inner_whisper_inside_quotes_stays_a_say_with_whisper_tone():
    # the old idiom: [whisper] sits INSIDE the say's quotes -> it is the tone, not a span
    segs = parsing.parse_character_output('[say]"[whisper] Not here. Follow me."[/say]')
    assert segs == [("say", "Not here. Follow me.", "whisper")]


def test_inner_whisper_after_another_tone_in_a_do_stays_a_say():
    # [do][sigh] [whisper] "..." -> reclassified say, first tone wins, no private span
    segs = parsing.parse_character_output(
        '[do][sigh] [whisper] "Do not waste your breath."[/do]')
    assert segs == [("say", "Do not waste your breath.", "sigh")]


def test_two_whisper_spans_in_a_row_both_parse_as_whispers():
    segs = parsing.parse_character_output(
        '[whisper]The bridge is a trap.[/whisper][whisper]Wait for my signal.[/whisper]')
    assert segs == [("whisper", "The bridge is a trap.", ""),
                    ("whisper", "Wait for my signal.", "")]
