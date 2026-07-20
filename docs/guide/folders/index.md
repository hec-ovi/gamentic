# Folders — agent-ready

Where each part of the code lives: a containment tree of the repo, one job per directory and per file, built from the owner-maintained `INDEX.md` resolver maps.

> Paired with the interactive view: [`folders` in the docs site](../index.html#folders) (Graphs / Text). This file mirrors it node-for-node; the page is the same data drawn.
> **Read this first, then load ONLY the file the task needs.** Each file under `guide/` is deliberately fat and self-contained: opening one fully answers a class of question. Never bulk-read the folder.

**Lanes:** `root` · `orchestrator` · `frontend` · `infra` · `voice+docs`

**Orientation.** One monorepo. `orchestrator/` is the brain (app/ = engine, tools, repo, integrate, providers + prompts/), `frontend/` the no-build UI, `infra/` the accessory services + setup faces, `voice-api/` the TTS service, `docs/` the docs and atlases. Each fat subtree carries its own INDEX.md.

## Nodes

### gamentic/ — `root`  ·  _root_

Self-hosted AI dungeon RPG monorepo: the game brain (orchestrator), the no-build UI (frontend), the media services (infra, voice-api), the compose stack and the setup faces, all docs.

- **Key files / dirs:** docker-compose.yml; up.sh; gamentic-setup; setup.html; README.md; CHANGELOG.md; .env.example
- **Entry / owner:** up.sh; gamentic-setup; setup.html; docker-compose.yml
- **IN:** _none_
- **OUT:** `orchestrator` (orchestrator/); `frontend` (frontend/); `infra` (infra/); `voice` (voice-api/); `docs` (docs/)

<details><summary>JSON shape</summary>

```json
{
  "services": [
    "orchestrator",
    "frontend",
    "comfyui",
    "image-api",
    "voice-api",
  ],
  "config": ".env (single layer)"
}
```
</details>

### orchestrator/ — `orchestrator`  ·  _brain_

The game brain service: FastAPI orchestrator that resolves one turn per POST, plus its Dockerfile, prompts, tests and SQLite data.

- **Key files / dirs:** app/; prompts/; tests/; Dockerfile; INDEX.md; requirements.txt
- **Entry / owner:** app/main.py
- **Produces:** one fully-resolved turn per /games/{id}/action
- **Key point:** The REST surface plus the turn loop; one turn = one commit.
- **IN:** `root` (orchestrator/)
- **OUT:** `app` (app/); `prompts` (prompts/)

<details><summary>JSON shape</summary>

```json
{
  "entrypoint": "app/main.py",
  "db": "gamentic.db"
}
```
</details>

### orchestrator/app/ — `app`  ·  _brain_

The Python package: every route, the turn engine, the tool registry, the SQL layer, media glue, prompts assembly and config; one file/subpackage per concern.

- **Key files / dirs:** main.py; prompts.py; db.py; models.py; config.py; engine/; tools/; repo/; integrate/; providers/; constants.py; voice_design.py
- **Entry / owner:** app/main.py; app/engine/turn.py
- **Produces:** resolved GameState + beats
- **Key point:** Each file has one job; the INDEX is the resolver.
- **IN:** `orchestrator` (app/)
- **OUT:** `engine` (engine/); `tools` (tools/); `repo` (repo/); `integrate` (integrate/); `providers` (providers/); `fMain` (main.py); `fPrompts` (prompts.py); `fLlm` (llm.py); `fDb` (db.py); `fModels` (models.py); `fMedia` (media.py); `fConfig` (config.py); `fCreator` (creator.py); `fTransfer` (transfer.py)

<details><summary>JSON shape</summary>

```json
{
  "facades": [
    "engine",
    "tools",
    "repo",
    "integrate",
    "providers"
  ]
}
```
</details>

### app/engine/ — `engine`  ·  _brain_

The turn loop, one module per concern: player beats, deterministic adjudication, the narrator call, the bounded character cascade, whispers, the context meter, prose scrubbing, the new-item diff, background memory folds.

- **Key files / dirs:** turn.py; parsing.py; folds.py; __init__.py; INDEX.md
- **Entry / owner:** app/engine/turn.py: run_turn; app/engine/parsing.py; app/engine/folds.py
- **Produces:** adjudicated turn, scrubbed beats, memory folds
- **Key point:** The turn loop: run_turn does everything; folds open their own conns.
- **IN:** `app` (engine/)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "modules": [
    "turn.py",
    "parsing.py",
    "folds.py"
  ],
  "key": "run_turn, interpret_action"
}
```
</details>

### app/tools/ — `tools`  ·  _brain_

The model's ONLY way to change state: one module per domain, each tool's JSON schema beside its handler, composed by a registry. A tool the schema does not describe does not exist.

- **Key files / dirs:** combat.py; items.py; characters.py; progression.py; scene.py; world.py; narrative.py; base.py; __init__.py; INDEX.md
- **Entry / owner:** app/tools/base.py: @tool registry; app/tools/__init__.py: apply_tool
- **Produces:** state-change receipts {kind,text,cue,reactions}
- **Key point:** The model's ONLY way to change state.
- **IN:** `app` (tools/)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "handler": "(conn,gid,args,actor) -> {kind,text,cue,reactions}",
  "kind": "state|cue|memory|invalid|spawn|kill|reject|image"
}
```
</details>

### app/repo/ — `repo`  ·  _brain_

All SQL, one module per domain (games, players, characters, items, scenes, quests, lore, beats, clock, state). Callers just use repo.<fn>; the engine owns the transaction.

- **Key files / dirs:** games.py; players.py; characters.py; items.py; scenes.py; quests.py; lore.py; beats.py; clock.py; state.py; base.py; INDEX.md
- **Entry / owner:** app/repo/state.py: game_state; app/repo/items.py (item-blob rules)
- **Produces:** the assembled GameState the API serves (state.py: game_state)
- **Key point:** Data access; one turn = one commit; names normalized on every write.
- **IN:** `app` (repo/)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "assembled_by": "state.py: game_state",
  "items": "JSON lists on owner rows"
}
```
</details>

### app/integrate/ — `integrate`  ·  _brain_

Glue to the media services: image prompt composition (gender net, no-text guard, identity references), voice assignment, media persistence, all background generation jobs. Best-effort: media down never breaks the game.

- **Key files / dirs:** voice.py; image_prompts.py; storage.py; jobs.py; events.py; __init__.py; INDEX.md
- **Entry / owner:** app/integrate/jobs.py; app/integrate/storage.py: _persist; app/integrate/image_prompts.py
- **Produces:** background art/voice jobs, persisted /media files
- **Key point:** Never hold a DB conn across a render; re-check the game exists before writing.
- **IN:** `app` (integrate/)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "modules": [
    "voice.py",
    "image_prompts.py",
    "storage.py",
    "jobs.py"
  ]
}
```
</details>

### app/providers/ — `providers`  ·  _brain_

Config resolves at call time (env -> default).

- **Key files / dirs:** base.py; image.py; audio.py; __init__.py; INDEX.md
- **Produces:** resolved ProviderConfig per call (text/image/audio)
- **Key point:** .env is the single config layer; defaults reproduce the local stack byte-for-byte.
- **IN:** `app` (providers/)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "modalities": [
    "text",
    "image",
    "audio"
  ],
  "dialects": [
    "comfy",
    "openai",
    "gemini",
    "fal",
    "local",
    "elevenlabs"
  ],
}
```
</details>

### orchestrator/prompts/ — `prompts`  ·  _brain_

The actual prose of every prompt (narrator core + protocol blocks, character, interpreter, explainer, image-prompt writer, creator/finalize, summaries), editable without touching code, reloaded per call.

- **Key files / dirs:** narrator.system.md; narrator.easy.md/.hard.md/.newplace.md/.returning.md/.looking.md/.attempts.md/.resolve.md; character.system.md; interpret.system.md; imageprompt.system.md; explain.system.md; creator.system.md; finalize.system.md; summary/charsummary/origin/artdirector .md
- **Entry / owner:** edit the .md prose directly
- **Produces:** the system/user messages each agent receives
- **Key point:** Protocol blocks inject ONLY when state triggers them (the resolver).
- **IN:** `orchestrator` (prompts/)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "always": "narrator.system.md",
  "conditional": [
    "narrator.easy/hard/newplace/returning/looking/attempts/resolve"
  ]
}
```
</details>

### frontend/ — `frontend`  ·  _frontend_

The UI layer: vanilla ES modules, no build step; one in-memory state, one render() that MORPHS the DOM (vendored idiomorph), delegated handlers that mutate state and re-render. Served by nginx.

- **Key files / dirs:** index.html; styles.css; themes/; vendor/idiomorph.esm.js; src/; test/; nginx.conf; Dockerfile; INDEX.md
- **Entry / owner:** src/app.js; src/app/ui.js: render
- **Produces:** the played game screen
- **Key point:** No build step; one state, one morphing render().
- **IN:** `root` (frontend/)
- **OUT:** `src` (src/); `themes` (themes/); `feTest` (test/)

<details><summary>JSON shape</summary>

```json
{
  "entry": "src/app.js",
  "render": "src/render.js + src/render/",
  "state": "src/app/ctx.js"
}
```
</details>

### frontend/src/ — `src`  ·  _frontend_

The ES module source: the boot facade (app.js), the controller package (app/), the REST client (api.js), wire->view adapters, the tagged composer, the diff engine, the voice client, and the render facade + builders.

- **Key files / dirs:** app.js; api.js; adapters.js; composer.js; transitions.js; voice.js; icons.js; render.js; app/; render/
- **Entry / owner:** src/app.js; src/adapters.js; src/api.js
- **Produces:** view models, DOM, voice synth requests
- **Key point:** Raw wire JSON -> view model -> morphed DOM.
- **IN:** `frontend` (src/)
- **OUT:** `srcApp` (app/); `srcRender` (render/)

<details><summary>JSON shape</summary>

```json
{
  "client": "api.js",
  "adapters": "mapGameState/mapBeats/mapProfile",
  "diff": "transitions.js: diffState"
}
```
</details>

### frontend/src/app/ — `srcApp`  ·  _frontend_

The controller package: the one in-memory state + voice engine + api client (ctx.js), render/delegate/action-dispatch (ui.js), the turn loop, staged reveal, library, media SSE stream, play controls, profile, composer, creator, speech, settings, cues, lightbox.

- **Key files / dirs:** ctx.js; ui.js; turns.js; reveal.js; game.js; mediastream.js; playctl.js; profilectl.js; composerctl.js; creatorctl.js; speech.js; settingsctl.js; cues.js; media.js
- **Entry / owner:** src/app/turns.js; src/app/ui.js; src/app/mediastream.js
- **Produces:** the action/continue loop, the staged reveal, SSE-driven media refresh
- **Key point:** The controller; ctx.js holds the ONE state shared as live bindings.
- **IN:** `src` (app/)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "state": "ctx.js",
  "loop": "turns.js",
  "reveal": "reveal.js",
  "sse": "mediastream.js"
}
```
</details>

### frontend/src/render/ — `srcRender`  ·  _frontend_

The render builders, one module per concern: common helpers, widgets, screens (library/creator/settings), the play deck, the story stream, the character profile, the inspect modal.

- **Key files / dirs:** common.js; widgets.js; screens.js; play.js; story.js; profile.js; inspect.js
- **Entry / owner:** src/render/play.js; src/render/story.js; src/render/profile.js
- **Produces:** HTML strings the facade morphs in
- **Key point:** One module per screen concern, behind the render facade.
- **IN:** `src` (render/)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "modules": [
    "common",
    "widgets",
    "screens",
    "play",
    "story",
    "profile",
    "inspect"
  ]
}
```
</details>

### frontend/themes/ — `themes`  ·  _frontend_

The design tokens: colors, fonts, chamfer factor, eases. A new theme = one file like hightech.css. styles.css carries STRUCTURE only (no color literals, lint-enforced).

- **Key files / dirs:** hightech.css
- **Entry / owner:** themes/hightech.css
- **Produces:** the resolved visual theme (CSS custom properties)
- **Key point:** A new theme = one file like this; no color literals outside tokens.
- **IN:** `frontend` (themes/)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "tokens": [
    "colors",
    "fonts",
    "chamfer",
    "eases"
  ]
}
```
</details>

### frontend/test/ — `feTest`  ·  _frontend_

Vitest + jsdom suite: component tests mount the real app.js via init(), drive it with @testing-library/user-event, intercept the orchestrator with MSW at the network layer; plus the theme/mobile lint contracts and the setup-page test.

- **Key files / dirs:** play.component.test.js; render.test.js; composer.test.js; interaction.test.js; creator.component.test.js; transitions.test.js; voice.test.js; api.test.js; adapters.test.js; theme.lint.test.js; mobile.lint.test.js; setuppage.test.js; setup.js; fixtures.js
- **Entry / owner:** test/setup.js (MSW default handlers); test/fixtures.js (wire builders)
- **Produces:** pass/fail signal
- **Key point:** Mount real app.js, drive with user-event, mock HTTP at the network layer (MSW).
- **IN:** `frontend` (test/)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "runner": "vitest (jsdom)",
  "mock": "MSW",
  "setup": "test/setup.js + test/fixtures.js"
}
```
</details>

### infra/ — `infra`  ·  _infra_


- **Entry / owner:** docker-compose.yml references these contexts
- **Key point:** One build context per accessory service.
- **IN:** `root` (infra/)
- **OUT:** `infraSetup` (setup/); `infraComfy` (comfyui/); `infraImageApi` (image-api/)

<details><summary>JSON shape</summary>

```json
{
  "subdirs": [
    "setup",
    "comfyui",
    "image-api",
  ]
}
```
</details>

### infra/setup/ — `infraSetup`  ·  _infra_

The two setup faces over one schema: cli.py (terminal wizard, agent flags, host doctor) and setup.js/setup.css (the setup.html page), both rendering from schema.js so the faces can never drift; the schema also generates .env.example.

- **Key files / dirs:** schema.js; cli.py; setup.js; setup.css; tests/
- **Entry / owner:** infra/setup/schema.js; infra/setup/cli.py
- **Produces:** .env (saved/downloaded by either face); .env.example
- **Key point:** Both faces render from schema.js so they can never drift apart.
- **IN:** `infra` (setup/)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "schema": "schema.js",
  "faces": [
    "cli.py",
    "setup.js/setup.html"
  ],
  "tests": [
    "test_cli.py",
    "test_doctor.py"
  ]
}
```
</details>

### infra/comfyui/ — `infraComfy`  ·  _infra_

The ComfyUI container: Dockerfile, entrypoint, the FLUX.2 Klein model fetch script, and its data dir; the GPU image backend on Strix Halo.

- **Key files / dirs:** Dockerfile; entrypoint.sh; fetch-models.sh; data/
- **Entry / owner:** infra/comfyui/Dockerfile; infra/comfyui/fetch-models.sh
- **Produces:** the ComfyUI GPU service image
- **Key point:** The local GPU image backend (FLUX.2 Klein on ComfyUI).
- **IN:** `infra` (comfyui/)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "files": [
    "Dockerfile",
    "entrypoint.sh",
    "fetch-models.sh"
  ]
}
```
</details>

### infra/image-api/ — `infraImageApi`  ·  _infra_

The image-api REST adapter in front of ComfyUI: app (main.py, comfy_client.py, workflow.py, config.py), the workflow JSONs, tests and Dockerfile.

- **Key files / dirs:** app/main.py; app/comfy_client.py; app/workflow.py; app/config.py; workflows/; tests/; Dockerfile; README.md
- **Entry / owner:** infra/image-api/app/main.py; infra/image-api/app/comfy_client.py
- **Produces:** generated image bytes/urls (~4s/img)
- **Key point:** REST face over ComfyUI; the orchestrator's media.py talks to it.
- **IN:** `infra` (image-api/)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "app": [
    "main.py",
    "comfy_client.py",
    "workflow.py",
    "config.py"
  ]
}
```
</details>

### voice-api/ — `voice`  ·  _voice_

The Maya1-3B TTS service on llama.cpp Vulkan: app.py (routes), synth.py, voices.py, characters.py (registry), emotion.py, manifest.py (per-game ownership), config.py, bench + samples + tests.

- **Key files / dirs:** app.py; synth.py; voices.py; characters.py; emotion.py; manifest.py; config.py; bench.py; tests/; README.md; CHANGELOG.md
- **Entry / owner:** voice-api/app.py; voice-api/synth.py; voice-api/manifest.py
- **Produces:** character speech wavs (RTF ~1.1-1.2, first audio ~0.3s)
- **Key point:** Maya1 on llama.cpp Vulkan; speak-not-stream, per-game ownership manifest.
- **IN:** `root` (voice-api/)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "route": "POST /voice/speak",
  "manifest": "per-game game_id ownership"
}
```
</details>

### docs/ — `docs`  ·  _docs_

The documentation. The PUBLIC site is ONE page (index.html) whose section views (overview, agents, engine, state, state-json, context, infra, folders) render as a node graph, an indented tree or grouped cards, each paired with an agent-ready guide/ twin. Everything else under docs/ stays private/gitignored.

- **Entry / owner:** docs/*.html; docs/shared/inference-providers.md
- **Produces:** the read-first developer docs + interactive atlases
- **Key point:** Where the docs live; read HANDOFF and the atlases first.
- **IN:** `root` (docs/)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "public": [
    "index.html (single page: all section views)",
    "guide/<section>/index.md (twins)",
    ".nojekyll"
  ],
  "private": [
    "HANDOFF.md",
    "shared/",
    "frontend/",
    "image/",
    "voice/",
    "feedback/"
  ]
}
```
</details>

### app/main.py — `fMain`  ·  _file_

The REST surface: every route, request gating, background-task scheduling. Nothing else.

- **Key files / dirs:** models.py; engine/; integrate/; repo/
- **Entry / owner:** app/main.py
- **Produces:** one resolved turn per POST /games/{id}/action; SSE media events
- **Key point:** The REST surface. Every route, request gating, background-task scheduling. Nothing else.
- **IN:** `app` (main.py)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "flagship": "POST /games/{id}/action",
  "events": "GET /games/{gid}/events (SSE)"
}
```
</details>

### app/prompts.py — `fPrompts`  ·  _file_

Message assembly for every agent (narrator, characters, interpreter, explainer, image-prompt writer, creator). Computes the state block and decides WHICH protocol blocks inject this turn.

- **Key files / dirs:** prompts/*.md; constants.py; repo state
- **Entry / owner:** app/prompts.py
- **Produces:** the assembled message arrays each agent receives
- **Key point:** Message assembly; computes the state block and which protocol blocks inject.
- **IN:** `app` (prompts.py)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "output": "messages[] per agent",
  "decides": "which prompts/*.md blocks to inject"
}
```
</details>

### app/llm.py — `fLlm`  ·  _file_

The one llama.cpp client function, chat(): no framework, returns the assistant message with parsed tool calls; the same server + model backs every agent, only the messages differ.

- **Key files / dirs:** providers/base.py: resolve('text')
- **Entry / owner:** app/llm.py: chat
- **Produces:** assistant message + parsed tool calls
- **Key point:** The one llama.cpp client function, chat().
- **IN:** `app` (llm.py)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "fn": "chat()",
  "returns": "{content, tool_calls}"
}
```
</details>

### app/db.py — `fDb`  ·  _file_

Schema, migrations, WAL connection settings.

- **Key files / dirs:** nothing (owns the schema)
- **Entry / owner:** app/db.py
- **Produces:** the SQLite schema + connections
- **Key point:** Schema, migrations, WAL connection settings.
- **IN:** `app` (db.py)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "db": "gamentic.db",
  "mode": "WAL"
}
```
</details>

### app/models.py — `fModels`  ·  _file_

Pydantic request/response shapes (the wire contract).

- **Key files / dirs:** nothing
- **Entry / owner:** app/models.py
- **Produces:** validated request/response objects
- **Key point:** Pydantic request/response shapes (the wire contract).
- **IN:** `app` (models.py)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "defines": "the orchestrator wire contract"
}
```
</details>

### app/media.py — `fMedia`  ·  _file_

Thin HTTP clients for image-api and voice-api; keep historical signatures but dispatch to the ACTIVE provider from app/providers/, resolved at call time.

- **Key files / dirs:** providers/image.py; providers/audio.py
- **Entry / owner:** app/media.py
- **Produces:** image/voice bytes or urls
- **Key point:** Thin HTTP clients for image-api and voice-api (provider-agnostic facade).
- **IN:** `app` (media.py)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "targets": [
    "image-api",
    "voice-api"
  ],
  "dispatch": "active provider per call"
}
```
</details>

### app/config.py — `fConfig`  ·  _file_

Every knob, env-overridable, with defaults.

- **Key files / dirs:** .env / environment
- **Entry / owner:** app/config.py
- **Produces:** resolved config values
- **Key point:** Every knob, env-overridable, with defaults.
- **IN:** `app` (config.py)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "source": "env -> default"
}
```
</details>

### app/creator.py — `fCreator`  ·  _file_

The story-creator chat sessions (persisted in SQLite) and world finalization: interview the user, then emit a structured WorldSheet.

- **Key files / dirs:** prompts/creator.system.md; prompts/finalize.system.md; db.py
- **Entry / owner:** app/creator.py
- **Produces:** a structured WorldSheet from the creation chat
- **Key point:** Story-creator chat sessions (SQLite-persisted) and world finalization.
- **IN:** `app` (creator.py)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "output": "WorldSheet",
  "sessions": "persisted in SQLite"
}
```
</details>

### app/transfer.py — `fTransfer`  ·  _file_

Export/import: adventure templates and checkpoint saves, id remapping, media scrubbing (one versioned JSON format family).

- **Key files / dirs:** repo state, media folder
- **Entry / owner:** app/transfer.py
- **Produces:** template JSON (world as designed) or checkpoint save (with progress)
- **Key point:** Export/import: adventure templates and checkpoint saves, id remapping, media scrubbing.
- **IN:** `app` (transfer.py)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "kinds": [
    "adventure template",
    "checkpoint save"
  ],
  "format": "versioned JSON"
}
```
</details>

## Edges (IN → OUT)

| from | to | kind | label |
|---|---|---|---|
| `root` | `orchestrator` | contains | orchestrator/ |
| `root` | `frontend` | contains | frontend/ |
| `root` | `infra` | contains | infra/ |
| `root` | `voice` | contains | voice-api/ |
| `root` | `docs` | contains | docs/ |
| `orchestrator` | `app` | contains | app/ |
| `orchestrator` | `prompts` | contains | prompts/ |
| `app` | `engine` | contains | engine/ |
| `app` | `tools` | contains | tools/ |
| `app` | `repo` | contains | repo/ |
| `app` | `integrate` | contains | integrate/ |
| `app` | `providers` | contains | providers/ |
| `app` | `fMain` | contains | main.py |
| `app` | `fPrompts` | contains | prompts.py |
| `app` | `fLlm` | contains | llm.py |
| `app` | `fDb` | contains | db.py |
| `app` | `fModels` | contains | models.py |
| `app` | `fMedia` | contains | media.py |
| `app` | `fConfig` | contains | config.py |
| `app` | `fCreator` | contains | creator.py |
| `app` | `fTransfer` | contains | transfer.py |
| `frontend` | `src` | contains | src/ |
| `frontend` | `themes` | contains | themes/ |
| `frontend` | `feTest` | contains | test/ |
| `src` | `srcApp` | contains | app/ |
| `src` | `srcRender` | contains | render/ |
| `infra` | `infraSetup` | contains | setup/ |
| `infra` | `infraComfy` | contains | comfyui/ |
| `infra` | `infraImageApi` | contains | image-api/ |
