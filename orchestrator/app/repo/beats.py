"""Beats: the story log, plus the model-facing transcript windows."""
import json

from .base import _id


def next_turn_index(conn, gid: str) -> int:
    row = conn.execute("SELECT COALESCE(MAX(turn_index), 0) AS t FROM beats WHERE game_id=?", (gid,)).fetchone()
    return row["t"] + 1


def _witnesses(conn, gid: str, location: str, private_with) -> list[str]:
    """Who can later REMEMBER this beat. A private beat belongs to its addressee alone;
    a public/system beat to every living character standing at the beat's location when
    it lands. The player and narrator are implicit, never listed. Stamped at insert so
    a character arriving later can never 'remember' it, and a follower never loses it."""
    if private_with:
        return [private_with]
    from . import characters   # function-level: beats<->characters<->games import cycle
    return [c["id"] for c in characters.present_characters(conn, gid, location) if c["alive"]]


def add_beat(conn, gid, speaker, speaker_name, kind, text, location,
             turn_index=None, seq=None, private_with=None, image_url=None,
             emotion="") -> dict:
    if turn_index is None:
        turn_index = next_turn_index(conn, gid)
    if seq is None:
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), -1) AS s FROM beats WHERE game_id=? AND turn_index=?",
            (gid, turn_index)).fetchone()
        seq = row["s"] + 1
    bid = _id()
    witnesses = json.dumps(_witnesses(conn, gid, location, private_with))
    conn.execute(
        "INSERT INTO beats (id, game_id, turn_index, seq, speaker, speaker_name, kind, text, location, private_with, image_url, emotion, witnesses) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (bid, gid, turn_index, seq, speaker, speaker_name, kind, text, location, private_with, image_url, emotion or "", witnesses),
    )
    return {"id": bid, "turn_index": turn_index, "seq": seq, "speaker": speaker,
            "speaker_name": speaker_name, "kind": kind, "text": text, "location": location,
            "image_url": image_url, "audio_url": None, "private_with": private_with,
            "emotion": emotion or ""}


def all_beats(conn, gid: str, since_turn: int = 0):
    rows = conn.execute(
        "SELECT * FROM beats WHERE game_id=? AND turn_index>? ORDER BY turn_index, seq",
        (gid, since_turn)).fetchall()
    return rows


def clear_beats(conn, gid: str) -> None:
    """Clear the story log (history) of a game, keeping its current state. The rolling
    recaps are history too, so they reset with the log: the game's AND every character's
    (their memory_summary is folded from these very beats)."""
    conn.execute("DELETE FROM beats WHERE game_id=?", (gid,))
    conn.execute("UPDATE games SET story_summary='', summarized_through=0 WHERE id=?", (gid,))
    conn.execute("UPDATE characters SET memory_summary='', summarized_through=0 WHERE game_id=?",
                 (gid,))


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


# Witnessed windows: membership in the stamped witnesses list (ids are 12-hex, so the
# quote-delimited LIKE is an exact membership test). Legacy rows (witnesses IS NULL,
# stamped before the column existed) fall back to the old location-match rule against
# the character's CURRENT location, so existing games keep working unchanged.

def _witness_clause(conn, gid: str, char_id: str) -> tuple[str, tuple]:
    ch = conn.execute("SELECT location FROM characters WHERE id=?", (char_id,)).fetchone()
    loc = ch["location"] if ch else ""
    clause = ("(witnesses LIKE ? OR (witnesses IS NULL AND location=? "
              "AND (private_with IS NULL OR private_with=?)))")
    return clause, (f'%"{char_id}"%', loc, char_id)


def witnessed_beats_for_character(conn, gid: str, char_id: str, limit: int):
    """A character's verbatim memory: the newest beats THEY personally witnessed, oldest
    first. Replaces the location-only window: a follower keeps the previous scenes it
    lived through, and a late arrival can never 'remember' talk from before it entered."""
    clause, params = _witness_clause(conn, gid, char_id)
    rows = conn.execute(
        f"SELECT * FROM beats WHERE game_id=? AND kind!='image' AND {clause} "
        "ORDER BY turn_index DESC, seq DESC LIMIT ?",
        (gid, *params, limit)).fetchall()
    return list(reversed(rows))


def witnessed_beats_between(conn, gid: str, char_id: str, after_turn: int, through_turn: int):
    """Witnessed beats in (after_turn, through_turn], oldest first, images excluded.
    The per-character recap's source window: another character's whispers can never
    enter because the witnesses stamp already excludes them."""
    clause, params = _witness_clause(conn, gid, char_id)
    return conn.execute(
        f"SELECT * FROM beats WHERE game_id=? AND turn_index>? AND turn_index<=? "
        f"AND kind!='image' AND {clause} ORDER BY turn_index, seq",
        (gid, after_turn, through_turn, *params)).fetchall()
