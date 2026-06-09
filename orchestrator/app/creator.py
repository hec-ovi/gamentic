"""Story-creator agent: interview the user, then emit a structured WorldSheet.

Sessions are kept in memory (v1, single process). The conversation is free-form;
the output of record is structured JSON produced by a final tool call, then
persisted by repo.create_game.
"""
from . import prompts, llm, repo
from .config import settings
from .models import WorldSheet

# session_id -> list[{role, content}]
_SESSIONS: dict[str, list[dict]] = {}


def message(session_id: str, user_message: str) -> dict:
    history = _SESSIONS.setdefault(session_id, [])
    reply = llm.chat(
        prompts.build_creator_messages(history, user_message),
        temperature=0.8,
        max_tokens=400,
    )
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": reply.content})
    return {"reply": reply.content}


def finalize(conn, session_id: str) -> str:
    history = _SESSIONS.get(session_id)
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
    _SESSIONS.pop(session_id, None)
    return gid
