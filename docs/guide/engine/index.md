# Engine — agent-ready

How the turn engine wires the browser frontend to the backend services: REST + SSE, the `run_turn` pipeline, the validated tool dispatcher, the SQLite source of truth, per-call provider resolution, and the inference services.

> Paired with the interactive view: [`engine` in the docs site](../index.html#engine) (Graphs / Text). This file mirrors it node-for-node; the page is the same data drawn.
> **Read this first, then load ONLY the file the task needs.** Each file under `guide/` is deliberately fat and self-contained: opening one fully answers a class of question. Never bulk-read the folder.

**Lanes:** `frontend` · `api+engine` · `data` · `external services`

**Orientation.** `POST /games/{id}/action` → `interpret_action` → `run_turn` (build prompts → `llm.chat` narrator → `apply_tool` writes SQLite → character cascade) → returns `{beats, state}` synchronously. Slow media is queued as background tasks and announced over the `/events` SSE stream, which the browser answers by refetching `/state` or `/beats?since=`.

## Nodes

### Browser frontend — `browser`  ·  _frontend_

The static vanilla-JS app (served by nginx on :5173/:80) that calls the orchestrator REST API cross-origin and opens one EventSource per game for media-ready pushes.

- **Reads / inputs:** createApi(backendUrl) in frontend/src/api.js (default http://localhost:8000); mapGameState/mapBeats/mapProfile in frontend/src/adapters.js (wire -> view model); EventSource(`${api.base}/games/{id}/events`) in frontend/src/app/mediastream.js:watchMedia
- **Generates / outputs:** turn requests (segments or freeform action + optional wish); view-model objects for the renderer; TTS playback via same-origin /voice proxy (voice.js, not in api.js)
- **Writes / mutates:** localStorage pm-seen markers (adapters.js: savePmSeen); no server state directly; all mutation goes through REST
- **Owned by (code):** frontend/src/api.js: createApi/request; frontend/src/adapters.js: mapGameState/mapBeat/mapProfile/voiceForBeat; frontend/src/app/mediastream.js: watchMedia/refreshArt/pullBeats
- **Key point:** Media (image/voice/audio) is NOT in api.js: it is served same-origin via the nginx proxy with RELATIVE urls (/image, /voice, /audio). Only game JSON goes to backendUrl :8000.
- **IN:** `restApi` (TurnOut / GameState JSON); `sseStream` (push {kind: scene|portrait|item|beat})
- **OUT:** `restApi` (POST /games/{id}/action); `sseStream` (EventSource /games/{id}/events); `restApi` (FE refetch on SSE hint)

<details><summary>JSON shape</summary>

```json
{
  "backendUrl": "http://localhost:8000",
  "READ_TIMEOUT_MS": 20000,
  "LLM_TIMEOUT_MS": 330000,
  "IMPORT_TIMEOUT_MS": 60000
}
```
</details>

### REST API surface — `restApi`  ·  _api_

FastAPI app (orchestrator, :8000) exposing the full game REST surface: games CRUD, state/beats reads, action/continue turns, settings, view/explain, creator, audio, import/export, media files.

- **Reads / inputs:** db.get_conn / repo.* (every route opens a per-request SQLite conn); settings (config.py) for IMAGE_ENABLED, GAMES_DATA_DIR, EVENTS_KEEPALIVE_S; providers.resolve / voice_enabled for /audio/speak
- **Generates / outputs:** TurnOut {beats, state, spawned} (action/continue); GameState (get_state); {beats:[...]} (get_beats); {game_id} (create/import/finalize); audio bytes (audio_speak); SSE stream (game_events_stream)
- **Writes / mutates:** schedules BackgroundTasks (enrich_origins, generate_creation_art, generate_images_for_game, generate_scene_image, generate_directed_image, generate_view_snapshot, generate_item_image, maybe_update_summary, maybe_update_character_summaries); mutates DB via repo/engine inside route bodies
- **Owned by (code):** main.py: create_game POST /games; main.py: get_state GET /games/{gid}/state; main.py: get_beats GET /games/{gid}/beats; main.py: action POST /games/{gid}/action; main.py: continue_story POST /games/{gid}/continue; main.py: _resolved_turn (shared turn runner + bg art scheduling); main.py: update_settings PATCH /games/{gid}/settings; main.py: view_scene POST /games/{gid}/view; main.py: explain POST /games/{gid}/explain; main.py: audio_speak POST /audio/speak; main.py: media_file GET /media/{gid}/{name}; main.py: import_game/export_game/delete_game/wipe_everything/clear_history; main.py: create_message/create_session/create_finalize
- **Key point:** POST /games/{gid}/action is the one hot path: it calls engine.interpret_action (typed freeform) then engine.run_turn synchronously, returns the fully-resolved turn, and queues slow media as BackgroundTasks delivered later by SSE.
- **IN:** `browser` (POST /games/{id}/action); `browser` (FE refetch on SSE hint)
- **OUT:** `browser` (TurnOut / GameState JSON); `turnEngine` (engine.run_turn / interpret_action); `repoDb` (repo.game_state / get_beats); `mediaJobs` (BackgroundTasks.add_task(generate_*)); `voiceApi` (POST /audio/speak -> provider.speak)

<details><summary>JSON shape</summary>

```json
{
  "routes": [
    "GET /health",
    "POST /games",
    "GET /games",
    "GET /games/{gid}/export?kind=template|checkpoint",
    "POST /games/import",
    "GET /games/{gid}/events (SSE)",
    "GET /games/{gid}/state",
    "GET /games/{gid}/beats?since=",
    "DELETE /games/{gid}/beats",
    "DELETE /games?confirm=wipe (wipe all memory)",
    "DELETE /games/{gid}",
    "POST /games/{gid}/action",
    "POST /games/{gid}/continue",
    "PATCH /games/{gid}/settings",
    "GET /games/{gid}/characters/{cid}/profile",
    "POST /games/{gid}/view",
    "POST /games/{gid}/explain",
    "POST /create/message",
    "GET /create/{session_id}",
    "POST /create/finalize",
    "POST /audio/speak",
    "GET /media/{gid}/{name}"
  ]
}
```
</details>

### SSE events stream — `sseStream`  ·  _api_

Per-game server-sent-event endpoint: background media jobs publish to an in-process bus and this route streams 'media ready' hints so the browser re-fetches /state or /beats?since= instead of polling blind.

- **Reads / inputs:** game_events.subscribe(gid) -> asyncio.Queue (integrate/events.py); repo.get_game (404 if missing); settings.EVENTS_KEEPALIVE_S (ping cadence)
- **Generates / outputs:** text/event-stream: 'retry: 3000', 'data: {kind,...}', ': ping' keepalive
- **Writes / mutates:** registers/unregisters a subscriber queue in integrate/events._subscribers
- **Owned by (code):** main.py: game_events_stream; integrate/events.py: subscribe/unsubscribe/publish
- **Key point:** In-process by design (one uvicorn worker owns the game). Jobs run in worker threads and hop to the event loop via loop.call_soon_threadsafe; event payload carries only a kind hint (scene|portrait|item|beat), never the media.
- **IN:** `browser` (EventSource /games/{id}/events); `mediaJobs` (events.publish(gid, scene|portrait|item|beat))
- **OUT:** `browser` (push {kind: scene|portrait|item|beat})

<details><summary>JSON shape</summary>

```json
{
  "kind": "scene",
  "scene_id": "abc",
  "_alt_kinds": [
    "portrait char_id=",
    "item name=",
    "beat (private_with optional)"
  ]
}
```
</details>

### Turn engine (run_turn) — `turnEngine`  ·  _engine_

The bounded multi-actor event loop: records the player beat, runs the deterministic movement router + adjudication pre-checks, calls the narrator LLM with tools, processes the character reaction cascade, handles the private whisper channel, and returns new beats + state.

- **Reads / inputs:** repo.* (scenes, players, characters, beats, game row, item index); prompts.build_narrator_messages / build_character_messages / build_narrator_resolve_messages / build_interpret_messages; tools.narrator_tools / CHARACTER_TOOLS; settings (NARRATOR_TEMPERATURE, TURN_MAX_ACTOR_STEPS, DAMAGE_CAP, history/turn dials, NARRATOR_THINKING)
- **Generates / outputs:** {beats, state, spawned} plus optional image_request / view_fallback / private_looks / new_items keys popped by main.py for bg scheduling
- **Writes / mutates:** beats (emit -> repo.add_beat); state via tools.apply_tool (damage, items, move, spawn/kill, quests, scene); game row: advance_time, set_context_used, set_last_tool_errors, set_game_status('lost'), set_scene_description, clear_arrival_note
- **Owned by (code):** engine/turn.py: run_turn; engine/turn.py: _compose (segments -> action text + directed); engine/turn.py: _why_impossible / _match_exit (deterministic pre-checks/movement); engine/turn.py: _character_reply (one character POV+tools); engine/turn.py: interpret_action (freeform -> segments via LLM); engine/__init__.py re-exports run_turn et al
- **Key point:** Directed actions (attack/give) are NOT applied immediately: the narrator adjudicates (accept via matching tool / veto via reject_attempt), and anything left untouched is default-applied after the reply. Player death is engine-owned (life==0 -> status 'lost'), overriding the model.
- **IN:** `restApi` (engine.run_turn / interpret_action)
- **OUT:** `promptsAssembly` (build_narrator/character/resolve messages); `llmText` (llm.chat(messages, tools, stop, thinking)); `toolDispatcher` (tools.apply_tool(name, args, actor)); `repoDb` (emit beats + game-row dials)

<details><summary>JSON shape</summary>

```json
{
  "beats": [
    {
      "id": "b1",
      "turn_index": 4,
      "seq": 0,
      "speaker": "narrator|player|<char_id>|system",
      "speaker_name": "Narrator",
      "kind": "narration|dialogue|action|system|image",
      "text": "...",
      "private_with": null,
      "emotion": ""
    }
  ],
  "state": "<GameState>",
  "spawned": [],
  "image_request": {
    "description": "...",
    "caption": "..."
  }
}
```
</details>

### Tool dispatcher — `toolDispatcher`  ·  _engine_

The model's ONLY way to change state: a validated dispatcher over NARRATOR_TOOLS and CHARACTER_TOOLS that scrubs args, routes to per-domain handlers, and returns a typed result (state|cue|spawn|reject|image|kill|invalid).

- **Reads / inputs:** tools.base.HANDLERS / SCHEMAS (registered by @tool decorator); LLMReply.tool_calls from llm.chat (narrator + character calls); repo.* inside each handler
- **Generates / outputs:** {kind, text, reactions, cue} result dicts consumed by run_turn; system/state beats (receipts), cues that queue characters, spawn cast, image requests
- **Writes / mutates:** all game-state mutation: repo writes for damage/heal/items/quests/move/scene/disposition/spawn/kill via the handler modules
- **Owned by (code):** tools/__init__.py: apply_tool / narrator_tools / NARRATOR_TOOLS / CHARACTER_TOOLS; tools/base.py: HANDLERS/SCHEMAS/_invalid/clean_arg; tools/{combat,items,characters,scene,world,narrative,progression}.py: handlers
- **Key point:** narrator_tools(adjudicating, images) conditionally adds reject_attempt (only when attempts pend) and show_image (only when IMAGE_ENABLED). Unknown names / bad arg types return kind='invalid' and get one deterministic intra-reply retry.
- **IN:** `turnEngine` (tools.apply_tool(name, args, actor))
- **OUT:** `repoDb` (handler mutates state)

<details><summary>JSON shape</summary>

```json
{
  "narrator_order": [
    "apply_damage",
    "heal",
    "add_item",
    "move_location",
    "cue_character",
    "spawn_character",
    "kill_character",
    "describe_scene",
    "show_image(conditional)",
    "reject_attempt(conditional)"
  ],
  "character_tools": [
    "attack",
    "give_item",
    "share_past",
    "mark_moment",
    "admit_trait"
  ],
  "result": {
    "kind": "state|cue|spawn|reject|image|kill|invalid",
    "text": "receipt",
    "reactions": [
      "<char_id>"
    ],
    "cue": {}
  }
}
```
</details>

### Prompts assembly — `promptsAssembly`  ·  _engine_

Builds the message arrays for every LLM call (narrator, character, resolve, interpret, explain, art-director) from DB state, history window, lore budget, and tool scaffolding.

- **Reads / inputs:** repo.* (game row, beats history, characters, scenes, lore, summaries); settings (LORE_BUDGET, history/char-history windows); engine state (attempts, looking, wish) passed by run_turn
- **Generates / outputs:** list[dict] OpenAI-style messages + INTERPRET_TOOL/INTERPRET_TOOL schemas
- **Writes / mutates:** nothing (read-only assembly)
- **Owned by (code):** prompts.build_narrator_messages; prompts.build_character_messages; prompts.build_narrator_resolve_messages; prompts.build_interpret_messages; prompts.build_explain_messages; prompts.build_artdirector_messages
- **Key point:** Each character agent has its OWN context (its prompt feeds only its per-character meter); the global context meter tracks the narrator's biggest prompt this turn only.
- **IN:** `turnEngine` (build_narrator/character/resolve messages)
- **OUT:** `repoDb` (read state for prompt)

<details><summary>JSON shape</summary>

```json
{
  "messages": [
    {
      "role": "system",
      "content": "<world bible + scene + history + tools scaffold>"
    },
    {
      "role": "user",
      "content": "<composed action / impulse>"
    }
  ]
}
```
</details>

### Integrate media jobs — `mediaJobs`  ·  _engine_

The stateful generate_* background orchestrators: each opens its own DB conns around the slow render call, re-checks the game still exists before persisting, lands results as beats/row updates, and publishes an SSE event.

- **Reads / inputs:** repo.* (game, scene, characters, item index, current scene); image_prompts.* (prompt building, hardening, context); media.generate_scene_image / generate_character_images; settings (IMAGE_* sizes, IMAGE_AGENTIC_PROMPTS, IMAGE_ART_DIRECTOR, IMAGE_ITEMS)
- **Generates / outputs:** persisted image files under GAMES_DATA_DIR/{gid}/images; image beats (repo.add_beat kind=image); row updates: set_scene_image, set_character_images, set_item_image
- **Writes / mutates:** beats + scene/character/item image_url columns; /media files on disk (storage._persist); events.publish(gid, scene|portrait|item|beat)
- **Owned by (code):** integrate/jobs.py: generate_view_snapshot (SYNC, the See button); integrate/jobs.py: generate_directed_image (narrator show_image); integrate/jobs.py: generate_item_image; integrate/jobs.py: generate_scene_image / generate_images_for_game; integrate/jobs.py: art_direction / generate_creation_art; integrate/events.py: publish
- **Key point:** All run as BackgroundTasks EXCEPT generate_view_snapshot (synchronous, POST /games/{gid}/view, the player watches a loader). Every persisted job calls events.publish so the SSE stream pushes the FE a refetch hint.
- **IN:** `restApi` (BackgroundTasks.add_task(generate_*))
- **OUT:** `imageApi` (media.generate_scene_image / character_images); `repoDb` (persist image beats + url columns); `sseStream` (events.publish(gid, scene|portrait|item|beat))

<details><summary>JSON shape</summary>

```json
{
  "persisted_url": "/media/{gid}/scene-<id>.png",
  "beat": {
    "kind": "image",
    "image_url": "/media/...",
    "text": "<caption/concept>",
    "private_with": null
  },
  "sse_event": {
    "kind": "scene",
    "scene_id": "<id>"
  }
}
```
</details>

### Providers layer — `providers`  ·  _providers_


- **Generates / outputs:** ProviderConfig per modality; ImageProvider / AudioProvider instances (comfy|openai|gemini|fal ; local|openai|elevenlabs|fal)
- **Writes / mutates:** nothing (pure resolution)
- **IN:** `llmText` (providers.resolve('text')); `imageApi` (providers.resolve('image') -> get_provider); `voiceApi` (providers.resolve('audio') -> get_provider)

<details><summary>JSON shape</summary>

```json
{
  "ProviderConfig": {
    "modality": "text",
    "provider": "local",
    "base_url": "http://gamentic-llm-text:8080/v1",
    "api_key": "",
    "model": "gemma-4-12b-heretic",
    "supports_seed": false,
    "supports_references": false,
    "emotion_mode": "none",
    "max_stops": 8,
    "supports_thinking": true
  },
  "DIALECTS": {
    "text": [
      "local",
      "openai"
    ],
    "audio": [
      "local",
      "openai",
      "elevenlabs",
      "fal"
    ],
    "image": [
      "comfy",
      "openai",
      "gemini",
      "fal"
    ]
  }
}
```
</details>

### Repo / SQLite — `repoDb`  ·  _data_

The authoritative game state in SQLite (WAL, stdlib, no ORM). repo/state.py projects the GameState the UI renders; tool handlers and the engine are the only writers.

- **Reads / inputs:** db.connect (settings.DB_PATH, WAL, busy_timeout 330s); tables: games, player_state, characters, quests, objectives, lore, beats, scenes, creator_sessions
- **Generates / outputs:** GameState dict (repo/state.game_state); beat rows, scene/character/item updates, game-row dials
- **Writes / mutates:** every game-state table; schema + _MIGRATIONS in db.py applied on init_db()
- **Owned by (code):** db.py: init_db / connect / get_conn / _migrate / loads; repo/state.py: game_state; repo/* domain modules: add_beat, advance_time, set_*_image, set_context_used, set_game_status, etc.
- **Key point:** The model never owns state; it only proposes changes through validated tools. WAL + a 330s busy_timeout (sized to outlast a worst-case turn at LLM_TIMEOUT) lets background media persists queue behind a long turn transaction instead of raising 'database is locked'.
- **IN:** `promptsAssembly` (read state for prompt); `toolDispatcher` (handler mutates state); `turnEngine` (emit beats + game-row dials); `restApi` (repo.game_state / get_beats); `mediaJobs` (persist image beats + url columns)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "GameState": {
    "game_id": "g1",
    "title": "...",
    "status": "active|won|lost",
    "scene": {
      "id": "s1",
      "name": "...",
      "image_url": null,
      "exits": [],
      "items": []
    },
    "characters": [
      {
        "id": "c1",
        "voice_id": "...",
        "context": {
          "used": 0,
          "max": 131072
        }
      }
    ],
    "player": {
      "life": 20,
      "location": "start",
      "inventory": []
    },
    "time": {
      "label": "Day 1, morning"
    },
    "images_enabled": true,
    "narrator_voice_id": "..."
  }
}
```
</details>

### llm.chat -> llm-text — `llmText`  ·  _service_

Thin httpx client for the llama.cpp OpenAI-compatible /chat/completions endpoint; the single text brain behind narrator, character, interpret, explain, art-director, summary calls.

- **Reads / inputs:** providers.resolve('text') -> base_url/model/key/capabilities; settings.LLM_TIMEOUT (300s); messages + tools + stop + thinking from the engine/prompts
- **Generates / outputs:** LLMReply {content, tool_calls[ToolCall], finish_reason, usage{prompt_tokens,...}}
- **Writes / mutates:** nothing locally; POSTs to the text service
- **Owned by (code):** llm.py: chat (builds payload, posts {base_url}/chat/completions, parses tool_calls, one connect-retry)
- **IN:** `turnEngine` (llm.chat(messages, tools, stop, thinking))
- **OUT:** `providers` (providers.resolve('text'))

<details><summary>JSON shape</summary>

```json
{
  "url": "{base_url}/chat/completions",
  "local_base_url": "http://gamentic-llm-text:8080/v1",
  "payload": {
    "model": "gemma-4-26b-a4b-heretic",
    "messages": [],
    "temperature": 0.8,
    "tools": [],
    "tool_choice": "auto",
    "stop": [],
    "chat_template_kwargs": {
      "enable_thinking": true
    }
  },
  "deployed_model": "gemma-4-26b-a4b-heretic (compose LLM_MODEL=${LLM_ALIAS})",
  "config_default_model": "gemma-4-12b-heretic (bare fallback, overridden by compose)"
}
```
</details>

### media.py -> image-api — `imageApi`  ·  _service_

Best-effort HTTP client to the active image provider (default comfy = the image-api adapter in front of ComfyUI) for scene/view/item/character renders, guarded so a dead service never breaks the game.

- **Reads / inputs:** providers.resolve('image') / image_providers.get_provider; settings.IMAGE_API_URL (http://gamentic-image-api:9001), IMAGE_ENABLED; _RENDER_GATE (one render at a time orchestrator-wide)
- **Generates / outputs:** {image_url} (data: URL or path) and {face_url, body_front_url, body_side_url, seed}; fetched image bytes (fetch_image_bytes) for per-game persistence
- **Writes / mutates:** nothing locally; persistence happens in integrate/jobs via storage._persist; deletes staging files on image-api (delete_staging_image / purge_all_staging_images)
- **Owned by (code):** media.py: generate_scene_image / generate_character_images / fetch_image_bytes / _provider; media.py: delete_staging_image / purge_all_staging_images; providers/image.py: ComfyProvider.generate POST /image/generate, .character_set POST /image/character
- **Key point:** ComfyProvider hits {base}/image/generate and {base}/image/character; cloud dialects (openai /v1/images/*, gemini generateContent, fal queue) implement the same interface. Host port 9001; in-container the orchestrator uses http://gamentic-image-api:9001.
- **IN:** `mediaJobs` (media.generate_scene_image / character_images)
- **OUT:** `providers` (providers.resolve('image') -> get_provider)

<details><summary>JSON shape</summary>

```json
{
  "base_url": "http://gamentic-image-api:9001",
  "generate_req": {
    "prompt": "...",
    "width": 768,
    "height": 768,
    "references": [],
    "seed": null
  },
  "generate_resp": {
    "image_url": "/image/file?filename=...&subfolder=&type=output"
  }
}
```
</details>

### media.py -> voice-api — `voiceApi`  ·  _service_

Best-effort HTTP client to the active audio provider (default local = the Maya1 voice-api): /audio/speak resolves the provider server-side and returns audio bytes so API keys never reach the browser.

- **Reads / inputs:** providers.resolve('audio') / audio_providers.get_provider / voice_enabled(); settings.VOICE_API_URL (http://gamentic-voice-api:8080), VOICE_ENABLED; SpeakIn {text, voice_id, emotion, game_id} from POST /audio/speak
- **Generates / outputs:** (audio bytes, content_type) returned as a Response; wav-cache ownership tags (game_id -> manifest) in local mode
- **Writes / mutates:** nothing locally; purges/cleanup hit voice-api (purge_game_audio, purge_all_audio, delete/register character voice)
- **Owned by (code):** main.py: audio_speak POST /audio/speak; media.py: list_voice_ids / register_character_voice / delete_character_voice / purge_game_audio / purge_all_audio; providers/audio.py: LocalProvider.speak POST /voice/speak then GET audio_url
- **IN:** `restApi` (POST /audio/speak -> provider.speak)
- **OUT:** `providers` (providers.resolve('audio') -> get_provider)

<details><summary>JSON shape</summary>

```json
{
  "base_url": "http://gamentic-voice-api:8080",
  "speak_req": {
    "text": "...",
    "voice_id": "narrator",
    "emotion": "whisper",
    "game_id": "g1"
  },
  "speak_resp": {
    "audio_url": "/voice/file/xyz.wav"
  }
}
```
</details>

## Edges (IN → OUT)

| from | to | kind | label |
|---|---|---|---|
| `browser` | `restApi` | rest | POST /games/{id}/action |
| `restApi` | `browser` | rest | TurnOut / GameState JSON |
| `browser` | `sseStream` | sse | EventSource /games/{id}/events |
| `sseStream` | `browser` | sse | push {kind: scene|portrait|item|beat} |
| `browser` | `restApi` | rest | FE refetch on SSE hint |
| `restApi` | `turnEngine` | call | engine.run_turn / interpret_action |
| `turnEngine` | `promptsAssembly` | call | build_narrator/character/resolve messages |
| `turnEngine` | `llmText` | call | llm.chat(messages, tools, stop, thinking) |
| `promptsAssembly` | `repoDb` | read | read state for prompt |
| `turnEngine` | `toolDispatcher` | call | tools.apply_tool(name, args, actor) |
| `toolDispatcher` | `repoDb` | write | handler mutates state |
| `turnEngine` | `repoDb` | write | emit beats + game-row dials |
| `restApi` | `repoDb` | read | repo.game_state / get_beats |
| `restApi` | `mediaJobs` | call | BackgroundTasks.add_task(generate_*) |
| `mediaJobs` | `imageApi` | call | media.generate_scene_image / character_images |
| `mediaJobs` | `repoDb` | write | persist image beats + url columns |
| `mediaJobs` | `sseStream` | call | events.publish(gid, scene|portrait|item|beat) |
| `restApi` | `voiceApi` | call | POST /audio/speak -> provider.speak |
| `llmText` | `providers` | call | providers.resolve('text') |
| `imageApi` | `providers` | call | providers.resolve('image') -> get_provider |
| `voiceApi` | `providers` | call | providers.resolve('audio') -> get_provider |
