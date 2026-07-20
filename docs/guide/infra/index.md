# Infra — agent-ready

The Docker stack: nine services on one bridge network.

> Paired with the interactive view: [`infra` in the docs site](../index.html#infra) (Graphs / Text). This file mirrors it node-for-node; the page is the same data drawn.
> **Read this first, then load ONLY the file the task needs.** Each file under `guide/` is deliberately fat and self-contained: opening one fully answers a class of question. Never bulk-read the folder.



## Nodes

### .env — `env`  ·  _host_

The only config layer. The setup faces (gamentic-setup / setup.html) write it; compose reads it on the next up.

- **Lifecycle / profile:** Read at every compose up; never baked into an image.
- **Defined in:** infra/setup/schema.js -> cli.py + setup.html; .env.example is generated from the schema
- **IN:** _none_

<details><summary>JSON shape</summary>

```json
{
  "MODELS_DIR": "/home/.../gguf",
  "ORCHESTRATOR_PORT": 8000,
  "FRONTEND_PORT": 5173
}
```
</details>

### up.sh — `upsh`  ·  _host_


- **Lifecycle / profile:** Run by the operator: ./up.sh  (./up.sh down to stop).
- **Defined in:** up.sh
- **Key point:** Compose alone cannot clean up the OTHER mode's containers on a flip; up.sh does that one extra thing.
- **OUT:** `profiles` (selects world)

<details><summary>JSON shape</summary>

```json
{
  "run": "./up.sh",
  "down": "./up.sh down",
}
```
</details>

### COMPOSE_PROFILES — `profiles`  ·  _host_


- **Lifecycle / profile:** Evaluated by compose at up using .env.
- **Defined in:** docker-compose.yml profiles: on each service; .env COMPOSE_PROFILES
- **IN:** `upsh` (selects world)
- **OUT:** `llmtext` (local profile); `image` (local profile); `imageapi` (local profile); `llmvoice` (local profile); `voiceapi` (local profile)

<details><summary>JSON shape</summary>

```json
{
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

Host-mounted state so nothing important lives inside a container.

- **Lifecycle / profile:** Persist across rebuilds; data dirs gitignored.
- **Defined in:** docker-compose.yml volumes: + per-service mounts
- **Talks to / mounts:** the services that mount them
- **IN:** _none_
- **OUT:** `llmtext` (models :ro); `llmvoice` (models :ro); `image` (comfy models+data); `imageapi` (comfy output); `voiceapi` (voice-api/data); `orchestrator` (orchestrator/data)

<details><summary>JSON shape</summary>

```json
{
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
- **Defined in:** docker-compose.yml service orchestrator; ./orchestrator (build); app/config.py defaults
- **Key point:** depends_on uses required:false so each mode only waits for the backend it actually uses.
`frontend` (API + SSE (CORS)); `vols` (orchestrator/data); `net` (bridge (all join))
- **OUT:** `llmtext` (LLM_BASE_URL :8080/v1); `imageapi` (IMAGE_API_URL :9001); `voiceapi` (VOICE_API_URL :8080)

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
  }
}
```
</details>

### llm-text — `llmtext`  ·  _inference_

The text model: Gemma 4 26B-A4B Heretic (Q4) on llama.cpp server, Vulkan backend (AMD Strix Halo).

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

## Edges (IN → OUT)

| from | to | kind | label |
|---|---|---|---|
| `upsh` | `profiles` | config | selects world |
| `profiles` | `llmtext` | profile | local profile |
| `profiles` | `image` | profile | local profile |
| `profiles` | `imageapi` | profile | local profile |
| `profiles` | `llmvoice` | profile | local profile |
| `profiles` | `voiceapi` | profile | local profile |
| `frontend` | `orchestrator` | talks | API + SSE (CORS) |
| `frontend` | `imageapi` | talks | nginx /image |
| `frontend` | `voiceapi` | talks | nginx /voice,/audio |
| `orchestrator` | `llmtext` | talks | LLM_BASE_URL :8080/v1 |
| `orchestrator` | `imageapi` | talks | IMAGE_API_URL :9001 |
| `orchestrator` | `voiceapi` | talks | VOICE_API_URL :8080 |
| `imageapi` | `image` | talks | COMFY_URL :8188 |
| `voiceapi` | `llmvoice` | talks | MAYA1_URL :8080 |
| `vols` | `llmtext` | mount | models :ro |
| `vols` | `llmvoice` | mount | models :ro |
| `vols` | `image` | mount | comfy models+data |
| `vols` | `imageapi` | mount | comfy output |
| `vols` | `voiceapi` | mount | voice-api/data |
| `vols` | `orchestrator` | mount | orchestrator/data |
| `net` | `orchestrator` | net | bridge (all join) |
| `net` | `frontend` | net | bridge |
