"""Beats: the story log, plus the model-facing transcript windows."""
from .base import _id


def next_turn_index(conn, gid: str) -> int:
    row = conn.execute("SELECT COALESCE(MAX(turn_index), 0) AS t FROM beats WHERE game_id=?", (gid,)).fetchone()
    return row["t"] + 1


def add_beat(conn, gid, speaker, speaker_name, kind, text, location,
             turn_index=None, seq=None, private_with=None, image_url=None) -> dict:
    if turn_index is None:
        turn_index = next_turn_index(conn, gid)
    if seq is None:
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), -1) AS s FROM beats WHERE game_id=? AND turn_index=?",
            (gid, turn_index)).fetchone()
        seq = row["s"] + 1
    bid = _id()
    conn.execute(
        "INSERT INTO beats (id, game_id, turn_index, seq, speaker, speaker_name, kind, text, location, private_with, image_url) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (bid, gid, turn_index, seq, speaker, speaker_name, kind, text, location, private_with, image_url),
    )
    return {"id": bid, "turn_index": turn_index, "seq": seq, "speaker": speaker,
            "speaker_name": speaker_name, "kind": kind, "text": text, "location": location,
            "image_url": image_url, "audio_url": None, "private_with": private_with}


def all_beats(conn, gid: str, since_turn: int = 0):
    rows = conn.execute(
        "SELECT * FROM beats WHERE game_id=? AND turn_index>? ORDER BY turn_index, seq",
        (gid, since_turn)).fetchall()
    return rows


def clear_beats(conn, gid: str) -> None:
    """Clear the story log (history) of a game, keeping its current state. The rolling
    recap is history too, so it resets with the log."""
    conn.execute("DELETE FROM beats WHERE game_id=?", (gid,))
    conn.execute("UPDATE games SET story_summary='', summarized_through=0 WHERE id=?", (gid,))


def beats_between(conn, gid: str, after_turn: int, through_turn: int):
    """Public+private beats in (after_turn, through_turn], oldest first, images excluded.
    The summarizer's source window (the narrator is omniscient, so privates fold in too)."""
    return conn.execute(
        "SELECT * FROM beats WHERE game_id=? AND turn_index>? AND turn_index<=? "
        "AND kind!='image' ORDER BY turn_index, seq",
        (gid, after_turn, through_turn)).fetchall()


def last_image_turn(conn, gid: str):
    """The turn_index of the most recent NARRATOR image beat (None if none yet). Used to
    pace the narrator's spontaneous show_image so images stay special. System image beats
    (small item unlock cards) don't count against the narrator's pacing."""
    row = conn.execute(
        "SELECT MAX(turn_index) AS t FROM beats WHERE game_id=? AND kind='image' "
        "AND speaker='narrator'",
        (gid,)).fetchone()
    return row["t"]


# Model-facing transcript windows exclude kind='image' (a snapshot beat is a URL for the
# UI; to the model it is an empty line that wastes a slot of the history budget).

def recent_beats(conn, gid: str, limit: int):
    rows = conn.execute(
        "SELECT * FROM beats WHERE game_id=? AND kind!='image' "
        "ORDER BY turn_index DESC, seq DESC LIMIT ?",
        (gid, limit)).fetchall()
    return list(reversed(rows))


def recent_beats_at(conn, gid: str, location: str, limit: int):
    rows = conn.execute(
        "SELECT * FROM beats WHERE game_id=? AND location=? AND kind!='image' "
        "ORDER BY turn_index DESC, seq DESC LIMIT ?",
        (gid, location, limit)).fetchall()
    return list(reversed(rows))


def scene_beats_for_character(conn, gid: str, location: str, char_id: str, limit: int):
    """A character's POV: public beats at the location PLUS private beats addressed to THEM.
    Private beats meant for other characters are excluded (knowledge stays where it belongs)."""
    rows = conn.execute(
        "SELECT * FROM beats WHERE game_id=? AND location=? AND kind!='image' "
        "AND (private_with IS NULL OR private_with=?) "
        "ORDER BY turn_index DESC, seq DESC LIMIT ?",
        (gid, location, char_id, limit)).fetchall()
    return list(reversed(rows))
