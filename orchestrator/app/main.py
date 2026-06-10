"""FastAPI app: the orchestrator REST surface (docs/SPECS.md section 7).

Plain REST, sequential. One POST /games/{id}/action returns a fully-resolved turn.
"""
import os
import re
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import db, repo, engine, creator, integrate, prompts, llm, constants, transfer
from .config import settings
from .models import (WorldSheet, ActionIn, ContinueIn, CreateMessageIn, GameState,
                     GameSettingsIn, TurnOut, ViewIn, ExplainIn)


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


@app.get("/games/{gid}/export")
def export_game(gid: str, kind: str = "template"):
    """Download an adventure. kind=template: the world as designed, playable fresh by
    anyone. kind=checkpoint: the full save (state + story log) to resume or share this
    exact moment. Media binaries are not bundled; see the import notes."""
    if kind not in ("template", "checkpoint"):
        raise HTTPException(422, "kind must be 'template' or 'checkpoint'")
    with db.get_conn() as conn:
        data = (transfer.export_template(conn, gid) if kind == "template"
                else transfer.export_checkpoint(conn, gid))
        title = repo.get_game(conn, gid)["title"] if data else ""
    if not data:
        raise HTTPException(404, "game not found")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower() or "adventure"
    return JSONResponse(data, headers={
        "Content-Disposition": f'attachment; filename="{slug}-{kind}.json"'})


@app.post("/games/import")
def import_game(payload: dict, background_tasks: BackgroundTasks):
    """Create a NEW game from an exported file (template or checkpoint). Always a fresh
    game id; importing the same file twice gives two independent games. Missing media
    regenerates in the background where possible."""
    with db.get_conn() as conn:
        try:
            gid = transfer.import_payload(conn, payload)
        except ValueError as e:
            raise HTTPException(400, str(e))
        integrate.assign_voices_for_game(conn, gid)
        scene = repo.current_scene(conn, gid)
        need_scene_art = settings.IMAGE_ENABLED and not scene["image_url"]
        scene_id = scene["id"]
    if settings.IMAGE_ENABLED:
        background_tasks.add_task(integrate.generate_images_for_game, gid)  # missing portraits
    if need_scene_art:
        background_tasks.add_task(integrate.generate_scene_image, gid, scene_id)
    return {"game_id": gid}


@app.get("/games/{gid}/state", response_model=GameState)
def get_state(gid: str):
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            raise HTTPException(404, "game not found")
        return repo.game_state(conn, gid)


@app.delete("/games")
def wipe_everything(confirm: str = ""):
    """The settings 'wipe all memory' button: delete EVERY game (state, history,
    characters), release every voice-registry entry, drop creator sessions, and remove
    every generated media folder INCLUDING orphans left by older delete races. Requires
    ?confirm=wipe (a destructive endpoint must never fire by accident)."""
    if confirm != "wipe":
        raise HTTPException(400, "pass ?confirm=wipe to wipe everything")
    with db.get_conn() as conn:
        gids = [r["id"] for r in repo.list_games(conn)]
        char_ids = [c["id"] for gid in gids for c in repo.get_characters(conn, gid)]
        for gid in gids:
            repo.delete_game(conn, gid)
        conn.execute("DELETE FROM creator_sessions")
    folders = integrate.delete_all_media()           # all folders, orphans included
    integrate.release_game_voices(char_ids)
    return {"wiped_games": len(gids), "wiped_media_folders": folders}


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
              "text", "location", "image_url", "audio_url", "private_with", "emotion")
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            raise HTTPException(404, "game not found")
        rows = repo.all_beats(conn, gid, since)
    return {"beats": [{k: r[k] for k in fields} for r in rows]}


def _resolved_turn(gid: str, background_tasks: BackgroundTasks, text: str = "",
                   segments=None, continue_story: bool = False,
                   wish: str | None = None) -> dict:
    """Run one full turn and schedule its background art (shared by action/continue)."""
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            raise HTTPException(404, "game not found")
        echo = None
        if text and not segments:
            # typed freeform: the agentic interpreter structures it (say/do/attack/give/
            # whisper with targets) so it gets routing + adjudication; raw text on failure
            segments = engine.interpret_action(conn, gid, text)
            if segments:
                echo = text  # the player beat keeps THEIR exact words, never a paraphrase
                text = ""    # the segments ARE the action now (else a whisper-only
                             # message would still open a public turn with the raw text)
        result = engine.run_turn(conn, gid, action_text=text, segments=segments,
                                 continue_story=continue_story, wish=wish, echo_text=echo)
        if result.get("spawned"):
            integrate.assign_voices_for_game(conn, gid)      # voice for the newcomer (inline)
        scene = repo.current_scene(conn, gid)
        scene_id = scene["id"]
        need_scene_art = settings.IMAGE_ENABLED and not scene["image_url"]
        # portrait self-heal: a crashed background job leaves characters without their
        # reference set; any later turn notices and re-schedules (idempotent: done
        # characters are skipped, files on disk are relinked, not re-rendered)
        need_portraits = settings.IMAGE_ENABLED and any(
            c["alive"] and not repo.character_has_images(c)
            for c in repo.get_characters(conn, gid))
    if settings.IMAGE_ENABLED and (result.get("spawned") or need_portraits):
        background_tasks.add_task(integrate.generate_images_for_game, gid)  # portraits (background)
    if need_scene_art:
        background_tasks.add_task(integrate.generate_scene_image, gid, scene_id)  # new-scene art
    shot = result.pop("image_request", None)                 # the narrator's show_image call
    if settings.IMAGE_ENABLED and shot:
        background_tasks.add_task(integrate.generate_directed_image, gid,
                                  shot["description"], shot["caption"])
    fallback = result.pop("view_fallback", None)             # a look the narrator didn't render
    if settings.IMAGE_ENABLED and fallback is not None:
        background_tasks.add_task(integrate.generate_view_snapshot, gid, fallback or None)
    new_items = result.pop("new_items", None) or []          # items newly visible this turn
    if settings.IMAGE_ENABLED and settings.IMAGE_ITEMS:
        # self-heal like portraits: pick up items whose card never rendered (per-turn cap
        # overflow, a failed render, or pre-feature acquisitions), newest first
        if len(new_items) < settings.IMAGE_MAX_ITEMS_PER_TURN:
            with db.get_conn() as conn:
                missing = [v for v in repo.visible_item_index(conn, gid).values()
                           if not v.get("image_url")
                           and v["name"] not in [n["name"] for n in new_items]]
            new_items = new_items + missing
        for it in new_items[: settings.IMAGE_MAX_ITEMS_PER_TURN]:
            background_tasks.add_task(integrate.generate_item_image, gid, it["name"])
    if settings.SUMMARY_ENABLED:
        background_tasks.add_task(engine.maybe_update_summary, gid)  # fold old chapters
    return result


@app.post("/games/{gid}/action", response_model=TurnOut)
def action(gid: str, body: ActionIn, background_tasks: BackgroundTasks):
    segments = [s.model_dump() for s in body.segments] if body.segments else None
    text = (body.action or "").strip()
    if not segments and not text:
        raise HTTPException(400, "empty action")
    return _resolved_turn(gid, background_tasks, text=text, segments=segments, wish=body.wish)


@app.post("/games/{gid}/continue", response_model=TurnOut)
def continue_story(gid: str, background_tasks: BackgroundTasks, body: ContinueIn | None = None):
    """The 'Continue' button: no player input. The narrator advances the story on its own
    (the world shifts, a character acts, something surfaces) - a full turn, minus the
    player beat. An optional wish rides along ('what I'd like to happen next')."""
    return _resolved_turn(gid, background_tasks, continue_story=True,
                          wish=body.wish if body else None)


@app.patch("/games/{gid}/settings")
def update_settings(gid: str, body: GameSettingsIn):
    """Live-changeable game settings. difficulty (easy|normal|hard) switches the narrator
    flexibility mode on the NEXT turn: easy lets the player lead (and leans into wishes),
    hard makes the world strict and punishing. narrator_gender (female|male, '' = preset)
    redesigns the narrator's voice; takes effect on the next spoken line."""
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            raise HTTPException(404, "game not found")
        if body.difficulty is not None:
            if body.difficulty not in constants.DIFFICULTIES:
                raise HTTPException(422, f"difficulty must be one of {constants.DIFFICULTIES}")
            repo.set_difficulty(conn, gid, body.difficulty)
        if body.narrator_gender is not None:
            if body.narrator_gender not in ("", "female", "male"):
                raise HTTPException(422, "narrator_gender must be '', 'female' or 'male'")
            integrate.apply_narrator_gender(conn, gid, body.narrator_gender)
        if body.history_beats is not None:
            # 0 = back to the default; otherwise a generous but bounded verbatim window
            if body.history_beats != 0 and not (8 <= body.history_beats <= 400):
                raise HTTPException(422, "history_beats must be 0 (default) or 8..400")
            repo.set_history_beats(conn, gid, body.history_beats)
        if body.summary_every is not None:
            if body.summary_every != 0 and not (2 <= body.summary_every <= 50):
                raise HTTPException(422, "summary_every must be 0 (default) or 2..50")
            repo.set_summary_every(conn, gid, body.summary_every)
        if body.context_tokens is not None:
            if body.context_tokens != 0 and not (4000 <= body.context_tokens <= 120000):
                raise HTTPException(422, "context_tokens must be 0 (off) or 4000..120000")
            repo.set_context_tokens(conn, gid, body.context_tokens)
        g = repo.get_game(conn, gid)
        return {"settings": {"narrator_gender": g["narrator_gender"] or "",
                             "difficulty": g["difficulty"] or "normal",
                             "history_beats": repo.effective_history_beats(g),
                             "summary_every": repo.effective_summary_every(g),
                             "context_tokens": repo.effective_context_tokens(g)},
                "narrator_voice_id": g["narrator_voice_id"]}


@app.get("/games/{gid}/characters/{cid}/profile")
def character_profile(gid: str, cid: str):
    """The full-screen character view: public card data, traits unlocked through play,
    the moments shared with the player (including private exchanges), and story images
    as memories. Spoiler-safe: persona and private knowledge never leave the DB."""
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            raise HTTPException(404, "game not found")
        prof = repo.character_profile(conn, gid, cid)
    if not prof:
        raise HTTPException(404, "character not found")
    return prof


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


@app.post("/games/{gid}/explain")
def explain(gid: str, body: ExplainIn):
    """'Ask what this is': in-world explanation of a tapped thing (item, character, scene,
    quest, goal, or a system beat), generated from PLAYER-VISIBLE facts only (spoiler-safe).
    One short LLM call (~1-2s); 404 when nothing visible matches the tap."""
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            raise HTTPException(404, "game not found")
        messages = prompts.build_explain_messages(conn, gid, body.kind, body.key, body.beat_id)
    if not messages:
        raise HTTPException(404, "nothing like that in sight")
    reply = llm.chat(messages, temperature=0.6, max_tokens=160)
    return {"text": (reply.content or "").strip() or "There is little more to say about it."}


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
