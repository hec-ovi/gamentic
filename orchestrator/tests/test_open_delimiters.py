"""Delimiters the model opens and never closes.

Live 2026-07-25, "Troll Enterprise" turn 10: a dialogue beat was stored as
'"This smile?"[giggle'. The reply ended INSIDE a Maya1 emotion tag, and every
tag-shaped scrub in parsing.py matches on the CLOSING bracket, so the fragment
walked through all of them onto the screen. The same cut leaves quotes hanging.

Two repairs, opposite directions: markup the model opened is DROPPED (it was
never speech), punctuation it opened is CLOSED (the words are real, only the
closer is missing). Both run on every path that stores or displays model text.
"""
from app import llm
from app.engine import parsing


# ---------- the live failure, byte for byte ----------

def test_the_giggle_fragment_never_reaches_the_screen():
    segs = parsing.parse_character_output('[say]"This smile?"[giggle')
    assert segs == [("say", "This smile?", "")]


def test_the_same_fragment_in_narration():
    emotion, text = parsing._scrub_narration("The pen stops mid-tap.[whisper")
    assert text == "The pen stops mid-tap."
    assert emotion == ""


def test_an_unterminated_angle_tag_dies_too():
    assert parsing.repair_delimiters("She turns away.<sigh") == "She turns away."


def test_a_bare_open_bracket_at_the_end_dies():
    assert parsing.repair_delimiters("He counted the forms again.[") == \
        "He counted the forms again."


# ---------- what must SURVIVE (the scrub is not allowed to eat prose) ----------

def test_balanced_brackets_are_legitimate_text():
    assert parsing.repair_delimiters("She reads the note [signed by Mara] twice.") == \
        "She reads the note [signed by Mara] twice."


def test_a_less_than_sign_in_prose_survives():
    assert parsing.repair_delimiters("The gap was < a hand wide.") == \
        "The gap was < a hand wide."
    assert parsing.repair_delimiters("counted 5 <10 coins") == "counted 5 <10 coins"


def test_a_leading_emotion_tag_still_becomes_the_tone():
    segs = parsing.parse_character_output('[say][giggle]"This smile?"[/say]')
    assert segs == [("say", "This smile?", "giggle")]


# ---------- the quote half: closed, never trimmed ----------

def test_an_unclosed_double_quote_is_closed_not_cut():
    assert parsing.repair_delimiters('"You came for the interview') == \
        '"You came for the interview"'


def test_an_unclosed_typographic_quote_is_closed():
    assert parsing.repair_delimiters("“Form 7B, retroactively") == \
        "“Form 7B, retroactively”"


def test_an_apostrophe_is_never_mistaken_for_an_open_quote():
    text = "Chinesa's smile doesn't waver, and the grandmother's sign isn't wrong."
    assert parsing.repair_delimiters(text) == text


def test_a_single_quoted_line_that_never_closes_is_closed():
    assert parsing.repair_delimiters("'Do not file that one") == "'Do not file that one'"


def test_a_balanced_quote_is_left_alone():
    text = 'She said "no" and meant it.'
    assert parsing.repair_delimiters(text) == text


# ---------- through the real turn, stored and returned ----------

def test_a_cut_character_reply_stores_clean(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = llm.LLMReply(content="Mara taps the wet stone.",
                                     tool_calls=[llm.ToolCall("cue_character",
                                                              {"name": "Mara",
                                                               "impulse": "answer"})])
    fake_llm.character = llm.LLMReply(content='[say]"This smile?"[giggle')
    d = client.post(f"/games/{gid}/action", json={"action": "I ask about her name."}).json()
    said = [b for b in d["beats"] if b["kind"] == "dialogue"]
    assert said, "the character must still speak"
    for b in said:
        assert "[" not in b["text"] and "giggle" not in b["text"]
        assert b["text"].count('"') % 2 == 0


def test_a_cut_narration_stores_clean(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = llm.LLMReply(content='The fluorescent light hums. "Sign here,[whisper')
    d = client.post(f"/games/{gid}/action", json={"action": "I look around."}).json()
    for b in d["beats"]:
        if b["kind"] == "narration":
            assert "[whisper" not in b["text"]
            assert b["text"].count('"') % 2 == 0
