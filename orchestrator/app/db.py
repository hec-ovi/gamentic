"""SQLite layer. Stdlib only, no ORM. JSON columns for flexible nested state.

The DB is the authoritative game state. The model never owns state; it only
proposes changes through tools that this layer validates and persists.
"""
import json
import sqlite3
from contextlib import contextmanager

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    setting TEXT,
    tone TEXT,
    narrator_persona TEXT,
    opening_scenario TEXT,
    art_style TEXT DEFAULT '',        -- world art style/theme, composed into every image prompt
    narrator_voice_id TEXT,          -- TTS voice for narration beats (see docs/voice-requirements.md)
    memory TEXT DEFAULT '',          -- rolling durable notes the narrator chooses to keep
    status TEXT DEFAULT 'active',    -- story FSM: active | won | lost
    scene_status TEXT DEFAULT 'calm',  -- current scene mood FSM: calm | tense | dangerous
    current_goal TEXT DEFAULT '',    -- the player's current goal; starts empty, narrator sets it
    context_used INTEGER DEFAULT 0,  -- last turn's prompt tokens, for the context-usage meter
    time_minutes INTEGER DEFAULT 0,  -- FICTIONAL story time elapsed (narrator-driven, never wall clock)
    arrival_note TEXT DEFAULT '',    -- transient: 'you were last here X ago' shown to the narrator on return
    narrator_gender TEXT DEFAULT '', -- narrator voice gender ('' = preset default, 'female' | 'male')
    difficulty TEXT DEFAULT 'normal',-- narrator flexibility mode: easy | normal | hard (live-changeable)
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS player_state (
    game_id TEXT PRIMARY KEY REFERENCES games(id),
    life INTEGER DEFAULT 20,
    max_life INTEGER DEFAULT 20,
    points INTEGER DEFAULT 0,
    location TEXT DEFAULT 'start',
    inventory TEXT DEFAULT '[]',      -- JSON list of {name, description, qty}
    flags TEXT DEFAULT '{}'           -- JSON dict
);

CREATE TABLE IF NOT EXISTS characters (
    id TEXT PRIMARY KEY,
    game_id TEXT REFERENCES games(id),
    name TEXT NOT NULL,
    persona TEXT NOT NULL,            -- the system context for this character agent
    description TEXT DEFAULT '',       -- one-line public bio shown in the UI
    knowledge TEXT DEFAULT '',        -- private, persistent things only this character knows
    appearance TEXT DEFAULT '',       -- visual descriptor used to generate the reference set
    face_url TEXT,                    -- 3-image reference set (see docs/image-requirements.md)
    body_front_url TEXT,
    body_side_url TEXT,
    voice_id TEXT,
    color TEXT,
    talkativeness REAL DEFAULT 0.5,
    location TEXT DEFAULT 'start',
    present INTEGER DEFAULT 1,
    life INTEGER DEFAULT 10,          -- characters can be attacked, hurt, and killed
    max_life INTEGER DEFAULT 10,
    alive INTEGER DEFAULT 1,
    inventory TEXT DEFAULT '[]',      -- characters can hold/receive items (JSON list)
    disposition TEXT DEFAULT 'neutral',  -- friendly | neutral | hostile | unknown (FSM)
    following INTEGER DEFAULT 0,      -- moves with the player between scenes
    offers TEXT DEFAULT '[]',         -- narrator-offered contextual actions (JSON list of {id,label})
    context_used INTEGER DEFAULT 0,   -- this character agent's last prompt size (own context meter)
    traits TEXT DEFAULT '[]'          -- personality traits UNLOCKED through play (JSON list of {id,text,minutes})
);

CREATE TABLE IF NOT EXISTS quests (
    id TEXT PRIMARY KEY,
    game_id TEXT REFERENCES games(id),
    title TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'active'      -- active | done | failed
);

CREATE TABLE IF NOT EXISTS objectives (
    id TEXT PRIMARY KEY,
    quest_id TEXT REFERENCES quests(id),
    text TEXT NOT NULL,
    done INTEGER DEFAULT 0,
    progress TEXT
);

CREATE TABLE IF NOT EXISTS lore (
    id TEXT PRIMARY KEY,
    game_id TEXT REFERENCES games(id),
    keys TEXT DEFAULT '[]',           -- JSON list of trigger keywords
    content TEXT NOT NULL,
    constant INTEGER DEFAULT 0,       -- always inject
    priority INTEGER DEFAULT 0,
    discovered INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS beats (
    id TEXT PRIMARY KEY,
    game_id TEXT REFERENCES games(id),
    turn_index INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    speaker TEXT NOT NULL,            -- 'narrator' | 'player' | character_id | 'system'
    speaker_name TEXT,
    kind TEXT NOT NULL,              -- narration | dialogue | action | system
    text TEXT NOT NULL,
    location TEXT,
    image_url TEXT,
    audio_url TEXT,
    private_with TEXT,               -- if set, a private beat only this character (+ player + narrator) sees
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scenes (
    id TEXT PRIMARY KEY,
    game_id TEXT REFERENCES games(id),
    name TEXT NOT NULL,              -- the location key (player.location points here)
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'calm',      -- scene mood FSM
    image_url TEXT,
    exits TEXT DEFAULT '[]',         -- JSON list of {id,label,target}  (max 3)
    items TEXT DEFAULT '[]',         -- JSON list of {id,name,description,image_url,hidden} (max 6)
    offers TEXT DEFAULT '[]',        -- narrator-offered scene actions (JSON list of {id,label}, max 3 total)
    visited INTEGER DEFAULT 1,
    left_at_minutes INTEGER,         -- story-clock stamp of when the player last left (draft layer)
    draft TEXT DEFAULT '',           -- narrator's note of open threads left here (note_scene)
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS creator_sessions (
    id TEXT PRIMARY KEY,              -- client-chosen session id
    history TEXT DEFAULT '[]',        -- the interview chat (JSON list of {role, content})
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_scenes_game ON scenes(game_id, name);
CREATE INDEX IF NOT EXISTS idx_beats_game ON beats(game_id, turn_index, seq);
CREATE INDEX IF NOT EXISTS idx_chars_game ON characters(game_id);
CREATE INDEX IF NOT EXISTS idx_quests_game ON quests(game_id);
CREATE INDEX IF NOT EXISTS idx_lore_game ON lore(game_id);
"""


def connect() -> sqlite3.Connection:
    # A turn holds its transaction for seconds (LLM calls happen inside it), while
    # background tasks (image persists) write concurrently. WAL lets readers proceed
    # and the long busy timeout makes writers QUEUE instead of raising
    # "database is locked" (seen live when a scene-art persist hit a running turn).
    conn = sqlite3.connect(settings.DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 60000")
    return conn


# Columns added after the initial schema; ALTER them in on existing DBs.
_MIGRATIONS = {
    "characters": {
        "life": "INTEGER DEFAULT 10",
        "max_life": "INTEGER DEFAULT 10",
        "alive": "INTEGER DEFAULT 1",
        "inventory": "TEXT DEFAULT '[]'",
        "disposition": "TEXT DEFAULT 'neutral'",
        "following": "INTEGER DEFAULT 0",
        "description": "TEXT DEFAULT ''",
        "offers": "TEXT DEFAULT '[]'",       # narrator-offered contextual actions (JSON)
        "context_used": "INTEGER DEFAULT 0",
        "traits": "TEXT DEFAULT '[]'",       # personality traits unlocked through play (JSON)
    },
    "games": {
        "scene_status": "TEXT DEFAULT 'calm'",
        "current_goal": "TEXT DEFAULT ''",
        "context_used": "INTEGER DEFAULT 0",
        "time_minutes": "INTEGER DEFAULT 0",
        "arrival_note": "TEXT DEFAULT ''",   # transient: shown to the narrator on returning somewhere
        "narrator_gender": "TEXT DEFAULT ''",
        "difficulty": "TEXT DEFAULT 'normal'",
    },
    "beats": {
        "private_with": "TEXT",
    },
    "scenes": {
        "left_at_minutes": "INTEGER",
        "draft": "TEXT DEFAULT ''",
    },
}


def _migrate(conn) -> None:
    for table, cols in _MIGRATIONS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for col, decl in cols.items():
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_conn():
    """Per-request connection. Commits on success, rolls back on error."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def loads(value, default):
    try:
        return json.loads(value) if value else default
    except (json.JSONDecodeError, TypeError):
        return default
