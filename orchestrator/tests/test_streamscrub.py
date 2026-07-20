"""The streaming view over parsing.py's hygiene. Two invariants rule everything:
(1) finalize() is byte-identical to the batch pipeline on the full text, at every
chunking - streaming can never change what gets stored; (2) no junk the batch rules
would eat is ever visible in the live view, at any moment, at any chunking. The
corpus is the museum of live leaks documented in parsing.py itself."""
import pytest

from app.engine import parsing, streamscrub

# --- narration corpus: (raw, substrings that must NEVER be visible) ---------------
PROSE_CASES = [
    ("(think: they seem lost) The dust settles over the square, slow and gray.",
     ["(think"]),
    ("<think>weighing the exits and the guard's mood</think>The keeper rises to meet you.",
     ["<think", "weighing the exits"]),
    ("The lantern gutters once.  (think: the player is stalling, press them",
     ["(think", "stalling"]),
    ("The gate creaks open.\ntools: {\n  set_scene_status: \"breached\"\n}\nBeyond it, darkness waits.",
     ["tools:", "set_scene_status"]),
    ("A narration line about the storm rolling in from the west hills.\ncall_tools:\nMore prose follows after.",
     ["call_tools"]),
    ("Vane: \"Movement. Now.\"\nThe alley holds its breath around you both.",
     ["Vane:"]),
    ("<div style=\"border:1px\"><strong>Exits:</strong> north, east</div>\nThe road forks at the dead oak.",
     ["<div", "<strong", "Exits:"]),
    ("He lunges without warning. [attack{amount:10,target: \"player\"}] The blow grazes your shoulder.",
     ["[attack{"]),
    ("move_location(\"the docks\")\nThe docks stink of tar and old rope tonight.",
     ["move_location("]),
    ("set_distance(distance=\"close\") # Implicit in the standoff.\nHe steps closer than comfort allows.",
     ["set_distance("]),
    ("---\nThe morning comes gray and reluctant over the rooftops.",
     []),
    ("```json\n{\"scene\": \"dock\"}\n```\nDay breaks over the harbor in thin gold lines.",
     ["```", "{\"scene\""]),
    ("[whisper] The dark answers back before you finish speaking.",
     ["[whisper]"]),
    ("{\"scene\": \"dock\", \"mood\": \"tense\"}\nWaves slap the pier below the warehouse.",
     ["{\"scene\""]),
    ("The keeper studies you for a long moment. His eyes narrow slowly, weighing "
     "something unsaid. Outside, rain begins against the shutters.\n\nNobody moves first.",
     []),
]

CHUNKINGS = (1, 3, 7, 999999)


def _replay_prose(raw, size):
    ps = streamscrub.ProseStream()
    ops_log = []
    for i in range(0, len(raw), size):
        ops_log.extend(ps.feed(raw[i:i + size]))
    display, trace = "", []       # append accumulates, replace resets
    for op, text in ops_log:
        display = display + text if op == "append" else text
        trace.append(display)
    return ps, ops_log, trace


@pytest.mark.parametrize("size", CHUNKINGS)
@pytest.mark.parametrize("raw,forbidden", PROSE_CASES)
def test_prose_stream_matches_batch_and_never_shows_junk(raw, forbidden, size):
    ps, ops, trace = _replay_prose(raw, size)
    emotion, final = ps.finalize()
    # invariant 1: byte-identical to the turn's batch pipeline (turn.py narrator path)
    assert (emotion, final) == parsing._scrub_narration(parsing.clean_prose(raw))
    for shown in trace:                                        # invariant 2
        for junk in forbidden:
            assert junk not in shown, f"visible junk {junk!r} in {shown!r}"
    if trace:
        assert final.startswith(trace[-1])   # live view is always a prefix of canonical
    assert not [op for op, _ in ops if op == "replace"]        # safety valve stays cold


def test_prose_stream_is_actually_live():
    raw = PROSE_CASES[-1][0]
    ps = streamscrub.ProseStream()
    first_at = None
    for i in range(0, len(raw), 5):
        if ps.feed(raw[i:i + 5]):
            first_at = i
            break
    assert first_at is not None and first_at < len(raw) * 0.6, \
        "streaming must show prose well before the generation ends"


# --- character corpus -------------------------------------------------------------
CHAR_CASES = [
    ('[say]"Stay close," she whispers into the dark of the stairwell.[/say]',
     ["[say]", "[/say]"]),
    ("[say][angry] You dare come back here?[/say][do]draws her blade slowly[/do]",
     ["[angry]", "[say]", "[do]"]),
    ("[whisper]The vault key sits under the altar stone, third from the wall.[/whisper]",
     ["[whisper]"]),
    ('[do][sigh] [whisper] "Do not waste your breath on the dead."[/do]',
     ["[sigh]", "[do]"]),
    ("(think: keep it vague) [say]Yes. For now.[/say]",
     ["(think", "keep it vague"]),
    ("She hesitates at the door frame. [say]Fine. But only until dawn.[/say]",
     []),
    ('[say]I was born at sea, if you must know. {piece: "born at sea"}[/say]',
     ["{piece"]),
    ("Her voice drops, sudden trust in it.[admit_trait, burdened by the past.",
     ["admit_trait"]),
    ("Just a bare untagged line of speech from a laconic guard.",
     []),
    ('[say](She looks at the whetstone on the bench) "A whetstone. You came prepared."[/say]',
     []),
]


@pytest.mark.parametrize("size", CHUNKINGS)
@pytest.mark.parametrize("raw,forbidden", CHAR_CASES)
def test_character_stream_matches_batch_and_never_shows_junk(raw, forbidden, size):
    cs = streamscrub.CharacterStream()
    views = []
    for i in range(0, len(raw), size):
        views.append(cs.feed(raw[i:i + size]))
    segs, marks = cs.finalize()
    assert (segs, marks) == parsing.parse_character_output_with_marks(raw)  # invariant 1
    for done, tail in views:                                                # invariant 2
        visible = [t for _, t, _ in done] + ([tail[1]] if tail else [])
        for text in visible:
            for junk in forbidden:
                assert junk not in text, f"visible junk {junk!r} in {text!r}"
            assert not text.startswith('"')          # leading quotes never flash
    # done segments reported mid-stream must be real batch segments
    for done, _ in views:
        for seg in done:
            assert seg in segs


def test_character_do_segments_never_stream_text():
    raw = "[do]crosses the room in three long strides, boots loud on the boards[/do]"
    cs = streamscrub.CharacterStream()
    for i in range(0, len(raw), 4):
        _, tail = cs.feed(raw[i:i + 4])
        if tail:
            assert tail[0] == "do" and tail[1] == ""
    segs, _ = cs.finalize()
    assert segs == parsing.parse_character_output(raw)


def test_character_untagged_reply_stays_unstreamed_until_finalize():
    raw = "A bare reply with no tags that could still grow a tag later on."
    cs = streamscrub.CharacterStream()
    for i in range(0, len(raw), 6):
        done, tail = cs.feed(raw[i:i + 6])
        assert done == [] and tail is None   # lead could be reclassified: hold it all
    segs, _ = cs.finalize()
    assert segs and segs[0][0] == "say"


def test_say_tail_streams_before_the_span_closes():
    raw = '[say]The road east is watched. Take the river path after the bell tolls twice.[/say]'
    cs = streamscrub.CharacterStream()
    grew = False
    for i in range(0, len(raw) - 8, 5):      # stop feeding before [/say] arrives
        _, tail = cs.feed(raw[i:i + 5])
        if tail and tail[0] == "say" and len(tail[1]) > 10:
            grew = True
    assert grew, "a say span must stream its interior before its closer arrives"
