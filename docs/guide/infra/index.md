# Infra — agent-ready

The Docker stack: nine services on one bridge network. One boolean (`ANNA`) in `.env` picks which backend world starts; the app tier is always up.

> Paired with the interactive chart: [`infra-atlas.html`](../../infra-atlas.html). This file mirrors it node-for-node; the chart is the same data drawn.
> **Read this first, then load ONLY the file the task needs.** Each file under `guide/` is deliberately fat and self-contained: opening one fully answers a class of question. Never bulk-read the folder.

**Lanes:** `host & config` · `app tier` · `local inference` · `anna tier`

**Orientation.** `ANNA=false` runs the full local stack (GPU inference: llm-text, ComfyUI, image-api, llm-voice, voice-api). `ANNA=true` runs orchestrator + frontend + anna-agent + anna-api and nothing GPU-shaped. The inverted COMPOSE_PROFILES trick selects the set; `./up.sh` drives the switch and the cross-mode cleanup.

## Nodes

### .env — `env`  ·  _host_

The only config layer. The setup faces (gamentic-setup / setup.html) write it; compose reads it on the next up.

- **Lifecycle / profile:** Read at every compose up; never baked into an image.
- **Config / env / ports:** ANNA=true|false (literal only); COMPOSE_PROFILES pin; MODELS_DIR, *_PORT, *_GID; LLM_TEXT_MODEL / LLM_VOICE_MODEL; TEXT_/IMAGE_/AUDIO_ provider knobs; ANNA_BASE_URL / ANNA_API_KEY
- **Defined in:** infra/setup/schema.js -> cli.py + setup.html; .env.example is generated from the schema
- **Talks to / mounts:** docker-compose.yml interpolation; up.sh (reads ANNA); orchestrator env
- **Key point:** ANNA must be the literal true or false: any other value starts NO inference services (compose matches no profile).
- **IN:** _none_
- **OUT:** `upsh` (ANNA + ports); `orchestrator` (provider + ANNA env)

<details><summary>JSON shape</summary>

```json
{
  "ANNA": "true | false",
  "COMPOSE_PROFILES": "local-inference-anna-false,anna-agent-anna-true",
  "MODELS_DIR": "/home/.../gguf",
  "ORCHESTRATOR_PORT": 8000,
  "FRONTEND_PORT": 5173
}
```
</details>

### up.sh — `upsh`  ·  _host_

Wraps docker compose: reads ANNA, retires the other mode's leftovers, then up -d --build.

- **Lifecycle / profile:** Run by the operator: ./up.sh  (./up.sh down to stop).
- **Config / env / ports:** mode = anna if ANNA=true else local; refuses non-literal ANNA loudly; ALL_PROFILES for cross-mode cleanup
- **Defined in:** up.sh
- **Talks to / mounts:** .env (ANNA); docker compose
- **Key point:** Compose alone cannot clean up the OTHER mode's containers on a flip; up.sh does that one extra thing.
- **IN:** `env` (ANNA + ports)
- **OUT:** `profiles` (selects world)

<details><summary>JSON shape</summary>

```json
{
  "run": "./up.sh",
  "down": "./up.sh down",
  "refuses": "ANNA not in {true,false}"
}
```
</details>

### COMPOSE_PROFILES — `profiles`  ·  _host_

Service selection by profile: local services carry local-inference-anna-<ANNA>; anna services carry anna-agent-anna-<ANNA>.

- **Lifecycle / profile:** Evaluated by compose at up using .env.
- **Config / env / ports:** .env pins: local-inference-anna-false , anna-agent-anna-true; ANNA=false -> local names match -> full local stack; ANNA=true -> anna names match -> orchestrator+frontend+anna-agent+anna-api
- **Defined in:** docker-compose.yml profiles: on each service; .env COMPOSE_PROFILES
- **Talks to / mounts:** ANNA boolean
- **Key point:** Expansion not restriction: flip ANNA and the same up command restores the other world.
- **IN:** `upsh` (selects world)
- **OUT:** `llmtext` (local profile); `image` (local profile); `imageapi` (local profile); `llmvoice` (local profile); `voiceapi` (local profile); `annaagent` (anna profile); `annaapi` (anna profile)

<details><summary>JSON shape</summary>

```json
{
  "local_services": "profiles: [\"local-inference-anna-${ANNA}\"]",
  "anna_services": "profiles: [\"anna-agent-anna-${ANNA}\"]",
  "pin": "local-inference-anna-false,anna-agent-anna-true"
}
```
</details>

### gamentic network — `net`  ·  _infra_

The single user-defined bridge network. Every service joins it and resolves peers by container name.

- **Lifecycle / profile:** Created with the project.
- **Config / env / ports:** driver: bridge; DNS by container_name (gamentic-llm-text, gamentic-image-api, ...)
- **Defined in:** docker-compose.yml networks: gamentic
- **Talks to / mounts:** all 9 services
- **Key point:** Internal URLs use container names + INTERNAL ports (e.g. voice-api is :8080 inside, :9002 on the host).
- **IN:** _none_
- **OUT:** `orchestrator` (bridge (all join)); `frontend` (bridge)

<details><summary>JSON shape</summary>

```json
{
  "networks": {
    "gamentic": {
      "driver": "bridge"
    }
  }
}
```
</details>

### volumes & mounts — `vols`  ·  _infra_

Host-mounted state so nothing important lives inside a container. Mostly bind mounts; only anna-data is a named volume.

- **Lifecycle / profile:** Persist across rebuilds; data dirs gitignored.
- **Config / env / ports:** MODELS_DIR -> /models :ro (bind, gguf); COMFY_MODELS_DIR + infra/comfyui/data (bind); voice-api/data (bind); orchestrator/data: db + /media (bind); anna-data (NAMED: anna-agent_anna-data)
- **Defined in:** docker-compose.yml volumes: + per-service mounts
- **Talks to / mounts:** the services that mount them
- **Key point:** The single host dir infra/comfyui/data/output is mounted into BOTH image (writes) and image-api (serves+reclaims). Only anna-data is a named volume, aliased to the standalone agent project so a sign-in carries over.
- **IN:** _none_
- **OUT:** `llmtext` (models :ro); `llmvoice` (models :ro); `image` (comfy models+data); `imageapi` (comfy output); `voiceapi` (voice-api/data); `orchestrator` (orchestrator/data); `annaagent` (anna-data); `annaapi` (anna-data :ro)

<details><summary>JSON shape</summary>

```json
{
  "anna_data": {
    "name": "anna-agent_anna-data"
  },
  "models": "${MODELS_DIR}:/models:ro (bind)",
  "orch": "./orchestrator/data:/data (bind)"
}
```
</details>

### frontend — `frontend`  ·  _edge_

nginx serving the no-build SPA; reverse-proxies /image /voice /audio same-origin so relative media URLs resolve.

- **Lifecycle / profile:** Always up (no profile). depends_on orchestrator.
- **Config / env / ports:** port ${FRONTEND_PORT:-5173}:80; build ./frontend; image gamentic-frontend
- **Defined in:** docker-compose.yml service frontend; ./frontend/Dockerfile
- **Talks to / mounts:** orchestrator (REST+SSE, CORS); nginx /image -> image-api, /voice + /audio -> voice-api, /media -> orchestrator
- **Key point:** Talks to the orchestrator cross-origin; media is reached through the same-origin nginx proxy (resolver 127.0.0.11, lazy upstreams, so nginx starts even if a media service is down).
- **IN:** `net` (bridge)
- **OUT:** `orchestrator` (API + SSE (CORS)); `imageapi` (nginx /image); `voiceapi` (nginx /voice,/audio)

<details><summary>JSON shape</summary>

```json
{
  "container": "gamentic-frontend",
  "ports": [
    "5173:80"
  ],
  "depends_on": [
    "orchestrator"
  ]
}
```
</details>

### orchestrator — `orchestrator`  ·  _brain_

FastAPI brain: the REST+SSE API and the turn engine. Talks to inference services by container name.

- **Lifecycle / profile:** Always up (no profile). Holds state in ./orchestrator/data.
- **Config / env / ports:** port ${ORCHESTRATOR_PORT:-8000}:8000; LLM_BASE_URL=http://gamentic-llm-text:8080/v1; IMAGE_API_URL=http://gamentic-image-api:9001; VOICE_API_URL=http://gamentic-voice-api:8080; ANNA_BASE_URL=http://gamentic-anna-api:9100; DB_PATH=/data/gamentic.db; ANNA + TEXT_/IMAGE_/AUDIO_ provider knobs
- **Defined in:** docker-compose.yml service orchestrator; ./orchestrator (build); app/config.py defaults
- **Talks to / mounts:** llm-text (required:false); anna-api (required:false); image-api + voice-api best-effort
- **Key point:** depends_on uses required:false so each mode only waits for the backend it actually uses.
- **IN:** `env` (provider + ANNA env); `frontend` (API + SSE (CORS)); `vols` (orchestrator/data); `net` (bridge (all join))
- **OUT:** `llmtext` (LLM_BASE_URL :8080/v1); `imageapi` (IMAGE_API_URL :9001); `voiceapi` (VOICE_API_URL :8080); `annaapi` (ANNA_BASE_URL :9100)

<details><summary>JSON shape</summary>

```json
{
  "container": "gamentic-orchestrator",
  "ports": [
    "8000:8000"
  ],
  "volumes": [
    "./orchestrator/data:/data"
  ],
  "depends_on": {
    "llm-text": "required:false",
    "anna-api": "required:false"
  }
}
```
</details>

### llm-text — `llmtext`  ·  _inference_

The text model: Gemma 4 26B-A4B Heretic (Q4) on llama.cpp server, Vulkan backend (AMD Strix Halo).

- **Lifecycle / profile:** Profile local-inference-anna-<ANNA>. Up only when ANNA=false.
- **Config / env / ports:** image ghcr.io/ggml-org/llama.cpp:server-vulkan; port ${LLM_TEXT_PORT:-8080}:8080; devices /dev/dri ; group_add RENDER/VIDEO gid; --ctx-size 131072 (128K native) --parallel 1 --jinja  (.env; compose fallback 32768/4); enable_thinking:false (Gemma hybrid)
- **Defined in:** docker-compose.yml service llm-text
- **Talks to / mounts:** MODELS_DIR /models:ro
- **Key point:** A hybrid thinking model: thinking is disabled globally for roleplay output speed.
- **IN:** `profiles` (local profile); `orchestrator` (LLM_BASE_URL :8080/v1); `vols` (models :ro)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "container": "gamentic-llm-text",
  "ports": [
    "8080:8080"
  ],
  "model": "/models/${LLM_TEXT_MODEL}",
  "alias": "gemma-4-26b-a4b-heretic"
}
```
</details>

### image (ComfyUI) — `image`  ·  _inference_

ComfyUI (ROCm / TheRock) running FLUX.2 [klein] 4B distilled. Full GPU access on Strix Halo.

- **Lifecycle / profile:** Profile local-inference-anna-<ANNA>. Up only when ANNA=false.
- **Config / env / ports:** build ./infra/comfyui; privileged ; /dev/kfd + /dev/dri; port ${COMFY_PORT:-8188}:8188; HSA_OVERRIDE_GFX_VERSION=11.5.1, SDMA=0, SVM=0
- **Defined in:** docker-compose.yml service image; infra/comfyui/Dockerfile + entrypoint.sh
- **Talks to / mounts:** COMFY_MODELS_DIR + infra/comfyui/data/*
- **Key point:** Stability env on unified memory avoids VAE-decode checkerboard / ring timeouts.
- **IN:** `profiles` (local profile); `imageapi` (COMFY_URL :8188); `vols` (comfy models+data)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "container": "gamentic-image",
  "ports": [
    "8188:8188"
  ],
  "image": "gamentic-comfyui-strix:latest"
}
```
</details>

### image-api — `imageapi`  ·  _inference_

Thin REST adapter: turns POST /image/generate -> {image_url} into a ComfyUI prompt graph.

- **Lifecycle / profile:** Profile local-inference-anna-<ANNA>. depends_on image (healthy).
- **Config / env / ports:** build ./infra/image-api; port ${IMAGE_API_PORT:-9001}:9001; COMFY_URL=http://gamentic-image:8188; IMAGE_DEFAULT_* + per-view char sizes
- **Defined in:** docker-compose.yml service image-api; infra/image-api/app/*
- **Talks to / mounts:** image (ComfyUI) :8188; infra/comfyui/data/output (reclaim copies)
- **Key point:** Mounts the Comfy output dir so DELETE endpoints reclaim files the instant the orchestrator owns its copy.
- **IN:** `profiles` (local profile); `frontend` (nginx /image); `orchestrator` (IMAGE_API_URL :9001); `vols` (comfy output)
- **OUT:** `image` (COMFY_URL :8188)

<details><summary>JSON shape</summary>

```json
{
  "container": "gamentic-image-api",
  "ports": [
    "9001:9001"
  ],
  "depends_on": {
    "image": "service_healthy"
  }
}
```
</details>

### llm-voice — `llmvoice`  ·  _inference_

Maya1-3B (Q4) on llama.cpp server Vulkan, generating SNAC audio tokens.

- **Lifecycle / profile:** Profile local-inference-anna-<ANNA>. Up only when ANNA=false.
- **Config / env / ports:** image ghcr.io/ggml-org/llama.cpp:server-vulkan; port ${LLM_VOICE_PORT:-9091}:8080; --ctx-size 4096; devices /dev/dri
- **Defined in:** docker-compose.yml service llm-voice
- **Talks to / mounts:** MODELS_DIR /models:ro (maya1)
- **Key point:** ~80 tok/s on the box = ~1.1x realtime (SNAC needs ~83 tok/s for 1.0x).
- **IN:** `profiles` (local profile); `voiceapi` (MAYA1_URL :8080); `vols` (models :ro)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "container": "gamentic-llm-voice",
  "ports": [
    "9091:8080"
  ],
  "alias": "maya1"
}
```
</details>

### voice-api — `voiceapi`  ·  _inference_

Owns the /voice contract: builds Maya1 prompts, pulls SNAC tokens from llm-voice, decodes to 24kHz on CPU.

- **Lifecycle / profile:** Profile local-inference-anna-<ANNA>. depends_on llm-voice (healthy).
- **Config / env / ports:** build ./voice-api; port ${VOICE_API_PORT:-9002}:8080; MAYA1_URL=http://llm-voice:8080
- **Defined in:** docker-compose.yml service voice-api; voice-api/app/*
- **Talks to / mounts:** llm-voice :8080; voice-api/data (audio + voice registry)
- **Key point:** POST /voice/speak {text, voice_id} -> {audio_url}. Audio is owned per game_id.
- **IN:** `profiles` (local profile); `frontend` (nginx /voice,/audio); `orchestrator` (VOICE_API_URL :8080); `vols` (voice-api/data)
- **OUT:** `llmvoice` (MAYA1_URL :8080)

<details><summary>JSON shape</summary>

```json
{
  "container": "gamentic-voice-api",
  "ports": [
    "9002:8080"
  ],
  "depends_on": {
    "llm-voice": "service_healthy"
  }
}
```
</details>

### anna-agent — `annaagent`  ·  _anna_

The vendor Anna CLI agent in its own container (the hackathon "fit with Anna"). Sign in once at :19001.

- **Lifecycle / profile:** Profile anna-agent-anna-<ANNA>. Up only when ANNA=true.
- **Config / env / ports:** build ./infra/anna-agent; image anna-agent:1.1.0-beta.17 (pinned); port 127.0.0.1:19001:19001; volume anna-data:/data
- **Defined in:** docker-compose.yml service anna-agent; infra/anna-agent/Dockerfile
- **Talks to / mounts:** anna-data (persisted sign-in)
- **Key point:** Credentials persist on the shared anna-data volume; until signed in, text turns fail with unauthenticated.
- **IN:** `profiles` (anna profile); `annaapi` (ANNA_AGENT_URL :19001); `vols` (anna-data)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "container": "gamentic-anna-agent",
  "ports": [
    "127.0.0.1:19001:19001"
  ],
  "image": "anna-agent:1.1.0-beta.17"
}
```
</details>

### anna-api — `annaapi`  ·  _anna_

Gives the Anna agent an OpenAI-compatible face (/v1/chat/completions, /v1/models) so the brain uses it with zero changes.

- **Lifecycle / profile:** Profile anna-agent-anna-<ANNA>. depends_on anna-agent (healthy).
- **Config / env / ports:** build ./infra/anna-api; port 127.0.0.1:${ANNA_API_PORT:-9100}:9100; ANNA_AGENT_URL=http://gamentic-anna-agent:19001; ANNA_AGENT_STATE_DIR=/agent-data/.matrix
- **Defined in:** docker-compose.yml service anna-api; infra/anna-api/app/*
- **Talks to / mounts:** anna-agent :19001; anna-data:/agent-data:ro (refresh token)
- **Key point:** Image requests answer 501; the game absorbs them (text-only play by design).
- **IN:** `profiles` (anna profile); `orchestrator` (ANNA_BASE_URL :9100); `vols` (anna-data :ro)
- **OUT:** `annaagent` (ANNA_AGENT_URL :19001)

<details><summary>JSON shape</summary>

```json
{
  "container": "gamentic-anna-api",
  "ports": [
    "127.0.0.1:9100:9100"
  ],
  "depends_on": {
    "anna-agent": "service_healthy"
  }
}
```
</details>

## Edges (IN → OUT)

| from | to | kind | label |
|---|---|---|---|
| `env` | `upsh` | config | ANNA + ports |
| `upsh` | `profiles` | config | selects world |
| `env` | `orchestrator` | config | provider + ANNA env |
| `profiles` | `llmtext` | profile | local profile |
| `profiles` | `image` | profile | local profile |
| `profiles` | `imageapi` | profile | local profile |
| `profiles` | `llmvoice` | profile | local profile |
| `profiles` | `voiceapi` | profile | local profile |
| `profiles` | `annaagent` | profile | anna profile |
| `profiles` | `annaapi` | profile | anna profile |
| `frontend` | `orchestrator` | talks | API + SSE (CORS) |
| `frontend` | `imageapi` | talks | nginx /image |
| `frontend` | `voiceapi` | talks | nginx /voice,/audio |
| `orchestrator` | `llmtext` | talks | LLM_BASE_URL :8080/v1 |
| `orchestrator` | `imageapi` | talks | IMAGE_API_URL :9001 |
| `orchestrator` | `voiceapi` | talks | VOICE_API_URL :8080 |
| `orchestrator` | `annaapi` | talks | ANNA_BASE_URL :9100 |
| `imageapi` | `image` | talks | COMFY_URL :8188 |
| `voiceapi` | `llmvoice` | talks | MAYA1_URL :8080 |
| `annaapi` | `annaagent` | talks | ANNA_AGENT_URL :19001 |
| `vols` | `llmtext` | mount | models :ro |
| `vols` | `llmvoice` | mount | models :ro |
| `vols` | `image` | mount | comfy models+data |
| `vols` | `imageapi` | mount | comfy output |
| `vols` | `voiceapi` | mount | voice-api/data |
| `vols` | `orchestrator` | mount | orchestrator/data |
| `vols` | `annaagent` | mount | anna-data |
| `vols` | `annaapi` | mount | anna-data :ro |
| `net` | `orchestrator` | net | bridge (all join) |
| `net` | `frontend` | net | bridge |
