"""FastAPI app: the orchestrator REST surface (docs/SPECS.md section 7).

Plain REST, sequential. One POST /games/{id}/action returns a fully-resolved turn.
"""
import os
import re
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import db, repo, engine, creator, integrate
from .config import settings
from .models import WorldSheet, ActionIn, CreateMessageIn, GameState, TurnOut, ViewIn


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Gamentic Orchestrator", version="0.1", lifespan=lifespan)

# Dev-friendly: the vanilla frontend is served from another origin.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/games")
def create_game(sheet: WorldSheet, background_tasks: BackgroundTasks):
    with db.get_conn() as conn:
        gid = repo.create_game(conn, sheet)
        integrate.assign_voices_for_game(conn, gid)          # fast, inline, best-effort
        scene_id = repo.current_scene(conn, gid)["id"]
    if settings.IMAGE_ENABLED:                               # images are optional
        background_tasks.add_task(integrate.generate_images_for_game, gid)  # character portraits
        background_tasks.add_task(integrate.generate_scene_image, gid, scene_id)  # scene art
    return {"game_id": gid}


@app.get("/media/{gid}/{name}")
def media_file(gid: str, name: str):
    """Serve a game's persisted image from its per-game folder."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        raise HTTPException(404, "not found")
    path = os.path.join(settings.GAMES_DATA_DIR, gid, "images", name)
    if not os.path.isfile(path):
        raise HTTPException(404, "not found")
    return FileResponse(path)


@app.get("/games")
def list_games():
    with db.get_conn() as conn:
        rows = repo.list_games(conn)
    return {"games": [dict(r) for r in rows]}


@app.get("/games/{gid}/state", response_model=GameState)
def get_state(gid: str):
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            raise HTTPException(404, "game not found")
        return repo.game_state(conn, gid)


@app.delete("/games/{gid}")
def delete_game(gid: str):
    """Wipe an entire game session (and all its characters, scenes, quests, history)."""
    with db.get_conn() as conn:
        char_ids = ([c["id"] for c in repo.get_characters(conn, gid)]
                    if repo.get_game(conn, gid) else [])
        if not repo.delete_game(conn, gid):
            raise HTTPException(404, "game not found")
    integrate.delete_game_images(gid)        # wipe the per-game image folder too
    integrate.release_game_voices(char_ids)  # free their voice-registry entries too
    return {"deleted": gid}


@app.delete("/games/{gid}/beats")
def clear_history(gid: str):
    """Clear a game's story log (history) while keeping its current state."""
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            raise HTTPException(404, "game not found")
        repo.clear_beats(conn, gid)
    return {"cleared": gid}


@app.get("/games/{gid}/beats")
def get_beats(gid: str, since: int = 0):
    """The story log. Use since=<last turn_index> to fetch only new beats."""
    fields = ("id", "turn_index", "seq", "speaker", "speaker_name", "kind",
              "text", "location", "image_url", "audio_url", "private_with")
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            raise HTTPException(404, "game not found")
        rows = repo.all_beats(conn, gid, since)
    return {"beats": [{k: r[k] for k in fields} for r in rows]}


@app.post("/games/{gid}/action", response_model=TurnOut)
def action(gid: str, body: ActionIn, background_tasks: BackgroundTasks):
    segments = [s.model_dump() for s in body.segments] if body.segments else None
    text = (body.action or "").strip()
    if not segments and not text:
        raise HTTPException(400, "empty action")
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            raise HTTPException(404, "game not found")
        if text and not segments:
            # typed freeform: the agentic interpreter structures it (say/do/attack/give/
            # whisper with targets) so it gets routing + adjudication; raw text on failure
            segments = engine.interpret_action(conn, gid, text)
            if segments:
                text = ""    # the segments ARE the action now (else a whisper-only
                             # message would still open a public turn with the raw text)
        result = engine.run_turn(conn, gid, action_text=text, segments=segments)
        if result.get("spawned"):
            integrate.assign_voices_for_game(conn, gid)      # voice for the newcomer (inline)
        scene = repo.current_scene(conn, gid)
        scene_id = scene["id"]
        need_scene_art = settings.IMAGE_ENABLED and not scene["image_url"]
    if settings.IMAGE_ENABLED and result.get("spawned"):
        background_tasks.add_task(integrate.generate_images_for_game, gid)  # portraits (background)
    if need_scene_art:
        background_tasks.add_task(integrate.generate_scene_image, gid, scene_id)  # new-scene art
    return result


@app.post("/games/{gid}/view")
def view_scene(gid: str, body: ViewIn | None = None):
    """The 'See' button: generate an image of the current scene WITH the characters present
    in it, grounded in actual state. Synchronous (5-10s; the frontend shows a loader). The
    image also lands as an image beat in the story flow, so it persists with the game.
    Optional body {focus}: what the player wants to look at steers the shot."""
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            raise HTTPException(404, "game not found")
    if not settings.IMAGE_ENABLED:
        raise HTTPException(409, "images are disabled")
    beat = integrate.generate_view_snapshot(gid, focus=body.focus if body else None)
    if not beat:
        raise HTTPException(502, "image generation unavailable")
    return {"beat": beat, "image_url": beat["image_url"]}


@app.post("/create/message")
def create_message(body: CreateMessageIn):
    return creator.message(body.session_id, body.message)


@app.get("/create/{session_id}")
def create_session(session_id: str):
    """The creator chat so far (sessions persist in the DB and survive restarts).
    Lets the frontend restore an in-progress creation after a refresh."""
    with db.get_conn() as conn:
        history = creator.get_session(conn, session_id)
    if history is None:
        raise HTTPException(404, "unknown creator session")
    return {"session_id": session_id, "history": history}


@app.post("/create/finalize")
def create_finalize(body: dict, background_tasks: BackgroundTasks):
    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(400, "session_id required")
    try:
        with db.get_conn() as conn:
            gid = creator.finalize(conn, session_id)
            integrate.assign_voices_for_game(conn, gid)
            scene_id = repo.current_scene(conn, gid)["id"]
    except ValueError as e:
        raise HTTPException(409, str(e))
    if settings.IMAGE_ENABLED:
        background_tasks.add_task(integrate.generate_images_for_game, gid)   # character portraits
        background_tasks.add_task(integrate.generate_scene_image, gid, scene_id)  # opening-scene art
    return {"game_id": gid}
