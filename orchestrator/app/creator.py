"""Story-creator agent: interview the user, then emit a structured WorldSheet.

Sessions are persisted in SQLite (they used to be an in-memory dict, which meant any
orchestrator restart silently killed an in-progress creation and finalize failed with
"unknown session"). The conversation is free-form; the output of record is structured
JSON produced by a final tool call, then persisted by repo.create_game.
"""
import json
import re

from . import engine, prompts, llm, repo, db
from .engine import parsing
from .models import WorldSheet

ORIGIN_MIN_CHARS = 220   # ~3 short sentences; anything thinner gets the enrichment pass

# The creator's readiness signal (owner: the begin button stays LOCKED until the
# world-builder is genuinely ready - it used to sit clickable the whole chat and
# bounce with a 409). The prompt asks for the exact marker [ready]; the prose
# fallback honors the house rule - parse the intent, never demand the protocol
# (the prompt has always made the model SAY it is ready in words).
_READY_MARK = re.compile(r"\[\s*ready\s*\]", re.I)
_READY_PROSE = re.compile(r"\bready\b[^.!?\n]{0,60}\b(?:start|begin|forge)\b", re.I)


def is_ready(text: str) -> bool:
    """Does this creator reply signal the world is complete enough to forge?"""
    return bool(_READY_MARK.search(text or "") or _READY_PROSE.search(text or ""))


def strip_ready(text: str) -> str:
    """Display form of a stored creator reply: the marker is plumbing, never prose."""
    return _READY_MARK.sub("", text or "").strip()


def enrich_origins(gid: str) -> None:
    """Background (scheduled at every creation path): give each character with a thin
    backstory a real one, one focused LLM call each. Never blocks or fails creation;
    a character whose call fails simply keeps the thin origin."""
    with db.get_conn() as conn:
        g = repo.get_game(conn, gid)
        if not g:
            return
        work = [(c["id"], prompts.build_origin_messages(g, c))
                for c in repo.get_characters(conn, gid)
                if c["alive"] and len((c["origin"] or "").strip()) < ORIGIN_MIN_CHARS]
    for cid, messages in work:
        try:
            reply = llm.chat(messages, temperature=0.7)
        except Exception:
            continue
        text = engine.clean_prose(reply.content or "")
        if reply.finish_reason == "length":
            text = engine.trim_to_sentence(text)   # a cut biography ends on a sentence
        with db.get_conn() as conn:
            c = repo.get_character(conn, cid)
            # only ever upgrade: never downgrade a richer origin (idempotent, race-safe)
            if c and text and len(text) > len((c["origin"] or "").strip()):
                repo.set_character_origin(conn, cid, text)


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
    )
    # Sanitize BEFORE storing or returning (static-confirmed: this path shipped raw model
    # content): a leaked think-span or tool-call line would otherwise reach the player AND
    # persist in the session history, re-fed to the model on every later creator turn.
    # Readiness reads the RAW reply first: clean_prose would eat a lone "[ready]" line
    # (it looks like a JSON line), and the marker must never reach the display anyway.
    raw = parsing._strip_think(reply.content or "")
    ready = is_ready(raw)
    text = engine.clean_prose(_READY_MARK.sub("", raw)).strip()
    history.append({"role": "user", "content": user_message})
    # The marker is RE-APPENDED to the stored copy (live: the model said "when YOU are
    # ready" - no prose signal - so a refresh lost the unlocked button; the stored
    # marker is the durable truth, stripped again at every display edge).
    history.append({"role": "assistant", "content": text + ("\n[ready]" if ready else "")})
    with db.get_conn() as conn:
        _save(conn, session_id, history)
    return {"reply": text, "ready": ready}


def get_session(conn, session_id: str) -> list[dict] | None:
    row = conn.execute("SELECT history FROM creator_sessions WHERE id=?", (session_id,)).fetchone()
    return db.loads(row["history"], []) if row else None


def seed_sheet_extras(conn, gid: str, sheet: WorldSheet) -> None:
    """Make the sheet's opening fiction TRUE in state at creation (live 2026-06-11: the
    creator's opening prose put a sealed ledger in the player's satchel and quested about
    it, but the inventory started empty and the narrator never managed to reify it; and
    the clock sat at its default morning while the established fiction was a rainy
    evening). Validated-tool doctrine: the sheet declares, code seeds."""
    for it in sheet.player_items:
        repo.add_item(conn, gid, it.name, it.description)
    minutes = repo.start_minutes(sheet.start_time_of_day)
    if minutes:
        repo.advance_time(conn, gid, minutes)
    # keep the DESIGNED opening state on the game row: the pack and the clock move on
    # from here, and the template export restates the world as designed, not as played
    conn.execute(
        "UPDATE games SET opening_items=?, opening_time_of_day=? WHERE id=?",
        (json.dumps([{"name": it.name, "description": it.description}
                     for it in sheet.player_items]),
         (sheet.start_time_of_day or "").strip().lower(), gid))


def finalize(conn, session_id: str) -> str:
    history = _history(conn, session_id)
    if not history:
        raise ValueError("unknown or empty creator session")
    # Uncapped on purpose: the save_world tool JSON carries the whole world bible, and
    # a token ceiling here truncated rich worlds into unparseable JSON (finish_reason
    # 'length' -> args {} -> WorldSheet ValidationError), failing the primary flow.
    reply = llm.chat(
        prompts.build_finalize_messages(history),
        tools=prompts.FINALIZE_TOOL,
        tool_choice="auto",
        temperature=0.4,
    )
    call = next((tc for tc in reply.tool_calls if tc.name == "save_world"), None)
    if not call:
        raise ValueError("creator did not produce a world; keep chatting and try again")
    sheet = WorldSheet(**call.arguments)
    gid = repo.create_game(conn, sheet)
    seed_sheet_extras(conn, gid, sheet)
    conn.execute("DELETE FROM creator_sessions WHERE id=?", (session_id,))
    return gid
