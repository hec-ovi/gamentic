"""FastAPI app: the orchestrator REST surface.

Plain REST, sequential. One POST /games/{id}/action returns a fully-resolved turn.
While it resolves, the per-game SSE stream mirrors the work live (engine/live.py):
phases, beats as they are stored, prose as it decodes. POST /games/{id}/stop
cancels the turn whole: the transaction rolls back as if the turn was never sent.
"""
import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from . import db, repo, engine, creator, integrate, media, prompts, llm, constants, transfer
from .engine import live
from .integrate import events as game_events
from .config import settings
from .providers import resolve, voice_enabled
from .providers import audio as audio_providers
from .models import (WorldSheet, ActionIn, ContinueIn, CreateMessageIn, GameState,
                     GameSettingsIn, SpeakIn, TurnOut, ViewIn, ExplainIn)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # uvicorn's default config handles only its own loggers; this routes our named
    # loggers (gamentic.tools) to the console at INFO. No-op if root is already configured.
    logging.basicConfig(level=logging.INFO)
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
        creator._seed_sheet_extras(conn, gid, sheet)         # opening possessions + clock,
        integrate.assign_voices_for_game(conn, gid)          # exactly like the finalize path
        scene_id = repo.current_scene(conn, gid)["id"]
    # origins first: fast text calls, and the narrator's first turns deserve real pasts;
    # the slow image renders queue behind them
    background_tasks.add_task(creator.enrich_origins, gid)
    # First-sight art is ONE composed pass (integrate.generate_creation_art): the art
    # director writes the prompts from the whole world bible, then the owner's render
    # order holds - portraits first (identity references), seeded item cards, the main
    # opening image last, delivered by SSE the moment each lands.
    if settings.IMAGE_ENABLED:                               # images are optional
        background_tasks.add_task(integrate.generate_creation_art, gid, scene_id)
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
    background_tasks.add_task(creator.enrich_origins, gid)   # imported templates may be thin too
    if settings.IMAGE_ENABLED:
        background_tasks.add_task(integrate.generate_images_for_game, gid)  # missing portraits
    if need_scene_art:
        background_tasks.add_task(integrate.generate_scene_image, gid, scene_id)
    return {"game_id": gid}


@app.get("/games/{gid}/events")
async def game_events_stream(gid: str):
    """Server-sent events: a push the moment background media lands (scene art,
    portraits, item cards, late image beats), so the frontend re-fetches /state or
    /beats?since= on signal instead of polling blind (live 2026-06-11: the 40s poll
    ceiling lost a 47s scene render and only F5 recovered it). One comment ping per
    EVENTS_KEEPALIVE_S keeps proxies from idling the stream out."""
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            raise HTTPException(404, "game not found")
    q = game_events.subscribe(gid)

    async def stream():
        # no explicit disconnect poll: starlette cancels this generator when the
        # client goes away, and the finally is the only cleanup needed
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=settings.EVENTS_KEEPALIVE_S)
                    yield f"data: {evt}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            game_events.unsubscribe(gid, q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/games/{gid}/state", response_model=GameState)
def get_state(gid: str):
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            raise HTTPException(404, "game not found")
        return repo.game_state(conn, gid)


@app.delete("/games")
def wipe_everything(confirm: str = ""):
    """The settings 'wipe all memory' button: delete EVERY game (state, history,
    characters), release every voice-registry entry, drop creator sessions, remove
    every generated media folder INCLUDING orphans left by older delete races, and
    empty the accessory services' own caches (the image-api's ComfyUI staging folder,
    the voice-api's wav cache + manifest - owner decision 2026-06-11: 'wipe all
    memory' means nothing generated survives ANYWHERE). Requires ?confirm=wipe
    (a destructive endpoint must never fire by accident)."""
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
    # best-effort service purges AFTER our own state is gone: a dead media service
    # must never fail the wipe. -1 = the service could not confirm a count (down,
    # disabled, or a bad reply); the wipe itself already succeeded regardless.
    staging = media.purge_all_staging_images()
    audio = media.purge_all_audio()
    return {"wiped_games": len(gids), "wiped_media_folders": folders,
            "wiped_staging_files": -1 if staging is None else staging,
            "wiped_audio_files": -1 if audio is None else audio}


@app.delete("/games/{gid}")
def delete_game(gid: str):
    """Wipe an entire game session (and all its characters, scenes, quests, history).
    Ownership-based cleanup (owner decision 2026-06-11): every file the adventure
    produced dies with it - our /media folder, any image-api staging files still
    referenced by persist-fallback URLs in the DB, and the wavs only this game
    claims in the voice-api manifest. All service calls best-effort: a dead media
    service must NEVER fail a game delete."""
    with db.get_conn() as conn:
        exists = repo.get_game(conn, gid)
        char_ids = [c["id"] for c in repo.get_characters(conn, gid)] if exists else []
        # collected BEFORE the rows die: these are the fallback '/image/file?' URLs
        # whose only copy still sits in the image-api staging folder
        staging = integrate.remote_image_urls(conn, gid) if exists else []
        if not repo.delete_game(conn, gid):
            raise HTTPException(404, "game not found")
    integrate.delete_game_images(gid)        # wipe the per-game image folder too
    integrate.release_game_voices(char_ids)  # free their voice-registry entries too
    for url in staging:                      # free their staging files on the image-api side
        media.delete_staging_image(url)
    media.purge_game_audio(gid)              # wavs only this game claims (voice-api manifest)
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
    live.begin_turn(gid)   # a stale stop from the last turn must not kill this one
    try:
        with db.get_conn() as conn:
            if not repo.get_game(conn, gid):
                raise HTTPException(404, "game not found")
            echo = None
            if text and not segments:
                # typed freeform: the agentic interpreter structures it (say/do/attack/
                # give/whisper with targets) so it gets routing + adjudication; raw text
                # on failure
                live.phase(gid, "interpret")
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
    except llm.LLMCancelled:
        # The stop cancelled the WHOLE turn: get_conn rolled the transaction back, so
        # the turn never happened - no beats, no player echo, no clock tick, no art.
        # The client restores the typed words to the composer; state is handed back
        # fresh so the screen cannot drift.
        with db.get_conn() as conn:
            state = repo.game_state(conn, gid)
        live.publish_done(gid, None, stopped=True)
        return {"beats": [], "state": state, "stopped": True}
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
    for cid, focus in result.pop("private_looks", []):       # quiet studies -> private thread
        if settings.IMAGE_ENABLED:
            background_tasks.add_task(integrate.generate_view_snapshot, gid, focus, cid)
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
    if settings.CHAR_SUMMARY_ENABLED:
        background_tasks.add_task(engine.maybe_update_character_summaries, gid)  # per-character folds
    # The `with` block above has exited: the turn is COMMITTED. Only now may the live
    # feed declare it durable (live_beat events during the turn were provisional).
    beats = result.get("beats") or []
    live.publish_done(gid, beats[-1]["turn_index"] if beats else None, stopped=False)
    return result


@app.post("/games/{gid}/stop")
def stop_turn(gid: str):
    """Cancel the running turn. Sets the per-game stop flag: the in-flight LLM call is
    cancelled and the whole turn ROLLS BACK - no beats, no player echo, no clock tick,
    as if never sent (the pending POST returns beats=[] + stopped=true and the client
    restores the typed words). Idempotent; a stop with no turn running is cleared by
    the next turn's begin."""
    with db.get_conn() as conn:
        if not repo.get_game(conn, gid):
            raise HTTPException(404, "game not found")
    live.request_stop(gid)
    return {"stopping": True}


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
        if body.turn_voices is not None:
            if body.turn_voices != 0 and not (1 <= body.turn_voices <= 4):
                raise HTTPException(422, "turn_voices must be 0 (default) or 1..4")
            repo.set_turn_voices(conn, gid, body.turn_voices)
        if body.turn_acts is not None:
            if body.turn_acts != 0 and not (1 <= body.turn_acts <= 3):
                raise HTTPException(422, "turn_acts must be 0 (default) or 1..3")
            repo.set_turn_acts(conn, gid, body.turn_acts)
        g = repo.get_game(conn, gid)
        return {"settings": {"narrator_gender": g["narrator_gender"] or "",
                             "difficulty": g["difficulty"] or "normal",
                             "history_beats": repo.effective_history_beats(g),
                             "summary_every": repo.effective_summary_every(g),
                             "context_tokens": repo.effective_context_tokens(g),
                             "turn_voices": repo.effective_turn_voices(g),
                             "turn_acts": repo.effective_turn_acts(g)},
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
    # Same hygiene as every other model-text surface (e2e 2026-06-11: this returned
    # reply.content raw, so think spans, scaffold and markup shipped straight to the tap).
    text = engine.parsing.scrub_model_text(reply.content or "")
    return {"text": text or "There is little more to say about it."}


@app.post("/create/message")
def create_message(body: CreateMessageIn):
    return creator.message(body.session_id, body.message)


@app.get("/create/{session_id}")
def create_session(session_id: str):
    """The creator chat so far (sessions persist in the DB and survive restarts).
    Lets the frontend restore an in-progress creation after a refresh. `ready` is
    re-derived from the last builder reply (the stored text is marker-free, so the
    prose signal carries it) - a restored session keeps its unlocked begin button."""
    with db.get_conn() as conn:
        history = creator.get_session(conn, session_id)
    if history is None:
        raise HTTPException(404, "unknown creator session")
    last = next((m.get("content", "") for m in reversed(history)
                 if m.get("role") == "assistant"), "")
    shown = [{**m, "content": creator.strip_ready(m.get("content", ""))}
             if m.get("role") == "assistant" else m for m in history]
    return {"session_id": session_id, "history": shown, "ready": creator.is_ready(last)}


@app.post("/audio/speak")
def audio_speak(body: SpeakIn):
    """Key-safe TTS passthrough: resolve the ACTIVE audio provider server-side and
    return the audio bytes (API keys never reach the browser). With provider=local
    this simply proxies voice-api; in cloud-audio mode the frontend's /voice proxy
    points here instead (FE work order). Emotion routes per the provider's mode."""
    if not voice_enabled():
        raise HTTPException(409, "voice is disabled")
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "empty text")
    cfg = resolve("audio")
    provider = audio_providers.get_provider(cfg)
    voice = (body.voice_id or "").strip() or audio_providers.default_voice(cfg)
    try:
        # game_id rides through to voice-api in local mode (its wav manifest maps
        # filename -> [game_ids], so deleting that game can free its wavs); cloud
        # providers have no wav cache to tag and ignore it
        out = provider.speak(text, voice, body.emotion,
                             game_id=(body.game_id or "").strip())
    except Exception:
        out = None
    if not out:
        raise HTTPException(502, "voice synthesis unavailable")
    data, content_type = out
    return Response(content=data, media_type=content_type)


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
    background_tasks.add_task(creator.enrich_origins, gid)   # thin backstories get real ones
    # same first-sight pass as POST /games: the art director writes the prompts, then
    # portraits (identity refs), seeded item cards, the main opening image (SSE
    # delivers each the moment it lands)
    if settings.IMAGE_ENABLED:
        background_tasks.add_task(integrate.generate_creation_art, gid, scene_id)
    return {"game_id": gid}
