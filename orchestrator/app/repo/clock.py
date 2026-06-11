"""The FICTIONAL story clock (narrator-driven, never the wall clock)."""
from ..config import settings
from . import games


def advance_time(conn, gid: str, minutes: int) -> int:
    """Advance the story clock by a fictional duration. Returns the new total minutes."""
    g = games.get_game(conn, gid)
    new = max(0, (g["time_minutes"] or 0) + int(minutes))
    conn.execute("UPDATE games SET time_minutes=? WHERE id=?", (new, gid))
    return new


def _part_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 22:
        return "evening"
    return "night"


# The creator's start_time_of_day -> in-fiction start hour. Single source: the enum the
# finalize tool offers IS this mapping's keys. Hours are chosen so time_at() labels them
# correctly on Day 1 and a night's sleep lands on a sane next morning (live 2026-06-11:
# the creator's rainy-evening opening started the clock at the default morning, and the
# first night's sleep read "Day 1, afternoon").
START_HOURS = {"morning": 8, "afternoon": 13, "evening": 19, "night": 22}


def start_minutes(part: str) -> int:
    """The story-minute stamp that makes time_at() label the given part of day on Day 1.
    Unknown or empty parts map to 0 (the DAY_START_HOUR default); so does a configured
    DAY_START_HOUR already past the asked-for hour (minutes never go negative)."""
    hour = START_HOURS.get((part or "").strip().lower())
    if hour is None:
        return 0
    return max(0, (hour - settings.DAY_START_HOUR) * 60)


def time_at(minutes: int) -> dict:
    """Derive {day, hour, part, label} for a given story-minute stamp."""
    absolute = settings.DAY_START_HOUR * 60 + (minutes or 0)
    day = absolute // 1440 + 1
    hour = (absolute // 60) % 24
    part = _part_of_day(hour)
    return {"day": day, "hour": hour, "part": part, "label": f"Day {day}, {part}"}


def elapsed_text(minutes: int) -> str:
    """A compact human duration: '2d 3h', '4h 10m', '25m'."""
    minutes = max(0, int(minutes or 0))
    d, rem = divmod(minutes, 1440)
    h, m = divmod(rem, 60)
    parts = [f"{d}d" if d else "", f"{h}h" if h else "", f"{m}m" if (m and not d) else ""]
    return " ".join(p for p in parts if p) or "moments"


def game_time(conn, gid: str) -> dict:
    """The fictional clock, derived from elapsed minutes + the story's start hour:
    {minutes, day, hour, part, label} with label like 'Day 2, afternoon'."""
    minutes = games.get_game(conn, gid)["time_minutes"] or 0
    return {"minutes": minutes, **time_at(minutes)}
