"""Story-creator agent: interview the user, then emit a structured WorldSheet.

Sessions are persisted in SQLite (they used to be an in-memory dict, which meant any
orchestrator restart silently killed an in-progress creation and finalize failed with
"unknown session"). The conversation is free-form; the output of record is structured
JSON produced by a final tool call, then persisted by repo.create_game.
"""
import json

from . import prompts, llm, repo, db
from .models import WorldSheet


def _history(conn, session_id: str) -> list[dict]:
    row = conn.execute("SELECT history FROM creator_sessions WHERE id=?", (session_id,)).fetchone()
    return db.loads(row["history"], []) if row else []


def _save(conn, session_id: str, history: list[dict]) -> None:
    conn.execute(
        "INSERT INTO creator_sessions (id, history, updated_at) VALUES (?,?,datetime('now')) "
        "ON CONFLICT(id) DO UPDATE SET history=excluded.history, updated_at=excluded.updated_at",
        (session_id, json.dumps(history)))


def message(session_id: str, user_message: str) -> dict:
    with db.get_conn() as conn:
        history = _history(conn, session_id)
    reply = llm.chat(
        prompts.build_creator_messages(history, user_message),
        temperature=0.8,
        max_tokens=400,
    )
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": reply.content})
    with db.get_conn() as conn:
        _save(conn, session_id, history)
    return {"reply": reply.content}


def get_session(conn, session_id: str) -> list[dict] | None:
    row = conn.execute("SELECT history FROM creator_sessions WHERE id=?", (session_id,)).fetchone()
    return db.loads(row["history"], []) if row else None


def finalize(conn, session_id: str) -> str:
    history = _history(conn, session_id)
    if not history:
        raise ValueError("unknown or empty creator session")
    reply = llm.chat(
        prompts.build_finalize_messages(history),
        tools=prompts.FINALIZE_TOOL,
        tool_choice="auto",
        temperature=0.4,
        max_tokens=1200,
    )
    call = next((tc for tc in reply.tool_calls if tc.name == "save_world"), None)
    if not call:
        raise ValueError("creator did not produce a world; keep chatting and try again")
    sheet = WorldSheet(**call.arguments)
    gid = repo.create_game(conn, sheet)
    conn.execute("DELETE FROM creator_sessions WHERE id=?", (session_id,))
    return gid
