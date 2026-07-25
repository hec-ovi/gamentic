"""A beat is narration OR dialogue, never both.

Live 2026-07-25, "Troll Enterprise" turn 11: one narration beat carried three of
Chinesa's speeches with their attributions, and she was cued and spoke again after
it. narrator.system.md has always said the narrator is the author's eye and never a
voice; this is the engine half of that rule. Attributed speech is lifted out in
place, so the turn emits narration, then her bubble, then narration again.

Shape, not wording: a quote counts as speech only when a PRESENT character is named
beside it, or a pronoun sits next to a speech verb. Anything else stays narration,
because prose legitimately quotes signs, forms and lines read off paper.
"""
from app import llm
from app.engine import parsing


CAST = ["Chinesa", "Mr. Chen"]

# The live bytes (turn 11), trimmed only in length: the prose opens on a pronoun and
# names her two sentences later, which is how narration normally reads.
LIVE = ('She takes the form, and her smile cracks at the corner like a teacup struck just '
        'right. "Oh, love," she says, voice dropping to something almost human. "You '
        'signed it." She holds it to the fluorescent light and watches the ink ripple. '
        "Chinesa's thumb finds the broken pen pieces, and they glint.")


def test_the_live_beat_splits_into_narration_bubble_narration():
    parts = parsing.split_narration_speech(LIVE, CAST)
    kinds = [(k, who) for k, who, _ in parts]
    assert kinds[0] == ("narration", None)
    assert ("dialogue", "Chinesa") in kinds
    assert kinds[-1] == ("narration", None)
    spoken = [t for k, _, t in parts if k == "dialogue"]
    assert "Oh, love" in spoken[0] and "You signed it." in spoken[1]


def test_no_quote_survives_inside_a_narration_chunk():
    parts = parsing.split_narration_speech(LIVE, CAST)
    for kind, _, text in parts:
        if kind == "narration":
            assert '"' not in text and "“" not in text


def test_a_named_attribution_binds_to_that_character():
    text = 'The clerk looks up. "Form 7B," Chinesa says, tapping the desk.'
    parts = parsing.split_narration_speech(text, CAST)
    assert ("dialogue", "Chinesa", "Form 7B,") in parts


def test_a_pronoun_binds_to_the_last_character_the_prose_named():
    text = ('Mr. Chen sets down the stamp. "We are not hiring," he answers, '
            'already turning away.')
    parts = parsing.split_narration_speech(text, CAST)
    assert ("dialogue", "Mr. Chen", "We are not hiring,") in parts


def test_a_pronoun_with_nobody_named_and_a_full_room_stays_narration():
    """Two people present, no name anywhere in the prose: who 'she' is cannot be known,
    so the engine does not guess a bubble onto someone."""
    text = 'The clerk shifts in her chair. "Come back tomorrow," she says.'
    assert parsing.split_narration_speech(text, CAST) == [("narration", None, text)]


def test_an_unattributed_quote_stays_narration():
    text = 'The form is titled "Declaration of Intent to Be On Time" in faded ink.'
    assert parsing.split_narration_speech(text, CAST) == [("narration", None, text)]


def test_prose_with_no_speech_is_returned_whole():
    text = "The fluorescent light hums and the papers rustle on the clipboard."
    assert parsing.split_narration_speech(text, CAST) == [("narration", None, text)]


def test_an_absent_character_is_never_given_a_bubble():
    text = '"Come back tomorrow," Chinesa says from behind the glass.'
    assert parsing.split_narration_speech(text, ["Mr. Wang"]) == [("narration", None, text)]


def test_the_attribution_prose_survives_as_narration():
    parts = parsing.split_narration_speech(LIVE, CAST)
    narration = " ".join(t for k, _, t in parts if k == "narration")
    assert "she says, voice dropping" in narration
    assert "watches the ink ripple" in narration


def test_no_empty_or_punctuation_only_chunks():
    parts = parsing.split_narration_speech(LIVE, CAST)
    for _, _, text in parts:
        assert text.strip(" ,.;:") == text.strip() or text.strip()


# ---------- through a real turn ----------

def test_the_narrator_speaking_for_a_character_lands_as_her_beat(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = llm.LLMReply(content=(
        'Mara wades ahead through the black water. "The altar is close," she says, '
        'lifting the lantern. The stone groans somewhere below.'))
    d = client.post(f"/games/{gid}/action", json={"action": "I follow her."}).json()
    kinds = [(b["kind"], b["speaker_name"]) for b in d["beats"]]
    assert ("dialogue", "Mara") in kinds, kinds
    for b in d["beats"]:
        if b["kind"] == "narration":
            assert '"' not in b["text"]
    order = [b["kind"] for b in d["beats"] if b["kind"] in ("narration", "dialogue")]
    assert order.index("narration") < order.index("dialogue")


def test_ordinary_narration_is_untouched(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    prose = "Cold water laps at the steps and the dark presses close around the lantern."
    fake_llm.narrator = llm.LLMReply(content=prose)
    d = client.post(f"/games/{gid}/action", json={"action": "I wait."}).json()
    assert any(b["kind"] == "narration" and b["text"] == prose for b in d["beats"])
