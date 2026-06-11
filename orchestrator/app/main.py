"""FastAPI app: the orchestrator REST surface (docs/SPECS.md section 7).

Plain REST, sequential. One POST /games/{id}/action returns a fully-resolved turn.
"""
import logging
import os
import re
import time
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from . import db, repo, engine, creator, integrate, prompts, llm, constants, transfer
from .config import settings
from .providers import DIALECTS, MODALITIES, capability_notes, resolve
from .providers import audio as audio_providers
from .providers import image as image_providers
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
    background_tasks.add_task(creator.enrich_origins, gid)   # imported templates may be thin too
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
    Lets the frontend restore an in-progress creation after a refresh."""
    with db.get_conn() as conn:
        history = creator.get_session(conn, session_id)
    if history is None:
        raise HTTPException(404, "unknown creator session")
    return {"session_id": session_id, "history": history}


@app.post("/audio/speak")
def audio_speak(body: SpeakIn):
    """Key-safe TTS passthrough: resolve the ACTIVE audio provider server-side and
    return the audio bytes (API keys never reach the browser). With provider=local
    this simply proxies voice-api; in cloud-audio mode the frontend's /voice proxy
    points here instead (FE work order). Emotion routes per the provider's mode."""
    if not settings.VOICE_ENABLED:
        raise HTTPException(409, "voice is disabled")
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "empty text")
    cfg = resolve("audio")
    provider = audio_providers.get_provider(cfg)
    voice = (body.voice_id or "").strip() or audio_providers.default_voice(cfg)
    try:
        out = provider.speak(text, voice, body.emotion)
    except Exception:
        out = None
    if not out:
        raise HTTPException(502, "voice synthesis unavailable")
    data, content_type = out
    return Response(content=data, media_type=content_type)


# ---------- admin panel: provider config (docs/shared/inference-providers.md) ----------

def _admin_guard(request: Request) -> None:
    """Optional bearer gate: when ADMIN_TOKEN is set, the panel page and its API
    require 'Authorization: Bearer <token>' (or ?token= for the page itself,
    since a browser cannot attach a header to the initial page load)."""
    token = settings.ADMIN_TOKEN
    if not token:
        return
    if request.headers.get("authorization", "") == f"Bearer {token}":
        return
    if request.query_params.get("token") == token:
        return
    raise HTTPException(401, "admin token required")


def _provider_view(modality: str) -> dict:
    cfg = resolve(modality)
    return {
        "provider": cfg.provider,
        "base_url": cfg.base_url,
        "model": cfg.model,
        "api_key": "********" if cfg.api_key else "",   # write-only: never echoed back
        "dialects": list(DIALECTS[modality]),
        "capabilities": {
            "supports_seed": cfg.supports_seed,
            "supports_references": cfg.supports_references,
            "emotion_mode": cfg.emotion_mode,
            "max_stops": cfg.max_stops,
            "supports_thinking": cfg.supports_thinking,
        },
        "notes": capability_notes(cfg),
    }


@app.get("/admin")
def admin_page(request: Request):
    """The provider admin panel: one static vanilla HTML file, no build step."""
    _admin_guard(request)
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "admin.html"))


@app.get("/admin/providers")
def get_providers(request: Request):
    _admin_guard(request)
    return {m: _provider_view(m) for m in MODALITIES}


_OVERRIDE_FIELDS = ("provider", "base_url", "api_key", "model", "supports_seed",
                    "supports_references", "emotion_mode", "max_stops",
                    "supports_thinking", "voice_pool")


@app.put("/admin/providers")
def put_providers(body: dict, request: Request):
    """Write admin overrides ({modality: {field: value}}). An empty value CLEARS the
    override (the env shows through again); absent fields stay untouched, so the
    write-only api_key survives every save that doesn't retype it. Providers resolve
    config at call time, so the next game call uses the new values: no restart."""
    _admin_guard(request)
    audio_before = resolve("audio").provider
    with db.get_conn() as conn:
        for modality, fields in (body or {}).items():
            if modality not in MODALITIES:
                raise HTTPException(422, f"unknown modality: {modality}")
            if not isinstance(fields, dict):
                raise HTTPException(422, f"{modality}: expected an object of fields")
            prov = (fields.get("provider") or "").strip()
            if prov and prov not in DIALECTS[modality]:
                raise HTTPException(422, f"{modality}.provider must be one of {DIALECTS[modality]}")
            for field, value in fields.items():
                if field not in _OVERRIDE_FIELDS:
                    raise HTTPException(422, f"unknown field: {modality}.{field}")
                repo.set_provider_override(conn, f"{modality}.{field}", value)
    if resolve("audio").provider != audio_before:
        # voice identity follows the provider: re-resolve every character's stored
        # design into the new voice space ONCE (deterministic; designs never move)
        integrate.reresolve_voices()
    return {m: _provider_view(m) for m in MODALITIES}


@app.post("/admin/providers/test")
def test_provider(body: dict, request: Request):
    """One real minimal call against the RESOLVED config of a modality. This is the
    live-verification path for cloud dialects (paste a key, press TEST)."""
    _admin_guard(request)
    modality = (body or {}).get("modality", "")
    if modality not in MODALITIES:
        raise HTTPException(422, f"modality must be one of {MODALITIES}")
    t0 = time.perf_counter()

    def _done(ok: bool, detail: str = "", error: str = "") -> dict:
        out = {"ok": ok, "latency_ms": int((time.perf_counter() - t0) * 1000)}
        if detail:
            out["detail"] = detail
        if error:
            out["error"] = error
        return out

    try:
        if modality == "text":
            reply = llm.chat([{"role": "user", "content": "Reply with the single word: ok"}],
                             temperature=0.0, max_tokens=8)
            return _done(True, detail=(reply.content or "")[:80] or "(empty reply)")
        if modality == "audio":
            cfg = resolve("audio")
            out = audio_providers.get_provider(cfg).speak(
                "Voice check.", audio_providers.default_voice(cfg))
            if not out or not out[0]:
                return _done(False, error="no audio in response")
            return _done(True, detail=f"{len(out[0])} audio bytes")
        cfg = resolve("image")
        out = image_providers.get_provider(cfg).generate(
            "a plain gray pebble on a white surface, studio photo", (512, 512))
        if not out or not out.get("image_url"):
            return _done(False, error="no image in response")
        return _done(True, detail="image rendered")
    except Exception as e:                       # the error itself IS the test result
        return _done(False, error=str(e)[:300] or type(e).__name__)


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
    if settings.IMAGE_ENABLED:
        background_tasks.add_task(integrate.generate_images_for_game, gid)   # character portraits
        background_tasks.add_task(integrate.generate_scene_image, gid, scene_id)  # opening-scene art
    return {"game_id": gid}
