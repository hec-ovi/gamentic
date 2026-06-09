# Gamentic

A self-hosted AI dungeon role-playing game you play in the browser, running entirely on your own machine. An AI narrator and a cast of AI characters, each with their own persona and voice, drive a living story: you explore scenes, talk, fight, pick up items, and chase quests, and the world changes as you play. No cloud and no API keys; the text, images, and voice are all generated locally.

Built and tuned for an AMD Strix Halo APU (Ryzen AI Max), but the pieces are standard containers.

## What's inside

- **Orchestrator (the game brain):** FastAPI + SQLite. One local LLM plays the narrator and every character through separate contexts. The model proposes changes only through validated tools, and the database is the source of truth, so the model never owns game state. Plain REST: one request returns one fully resolved turn.
- **Frontend:** a vanilla HTML / CSS / JS app, no framework.
- **Image service (optional):** ComfyUI behind a small REST adapter, for scene and character art.
- **Voice service (optional):** Kokoro-82M text-to-speech on CPU, a distinct voice per character.
- One **docker-compose** stack ties them together.

The text model is a Gemma GGUF on llama.cpp with Vulkan. Images and voice are optional; the game is fully playable text-only.

## How it works

The browser sends the player's action over REST. The orchestrator loads the current state from the database, builds a lean prompt for the narrator (state summary + recent story + relevant lore), and calls the local model. The model writes prose and proposes state changes by calling tools (damage, items, points, quests, move, spawn or remove characters, reveal items, and so on). The orchestrator validates each call and writes it to the database, then hands the scene to any character who should react (each character is its own separate model call). The whole turn, new story beats plus the fresh state, comes back in one response.

## Run it

Requires Docker with GPU access for the model (and the image service), plus local model files on disk.

```bash
cd infra
# set your model paths and ports in infra/.env (the compose file lists the variables it reads)
docker compose up -d
```

Main services:

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Orchestrator (game API) | http://localhost:8000 |
| Text model (llama.cpp) | http://localhost:8080 |
| Image / Voice services | http://localhost:9001 / http://localhost:9002 |

Open the frontend, create a world by chatting with the story creator, and play.

## Layout

```
gamentic/
  orchestrator/   game brain (FastAPI + SQLite, narrator + character agents, tools)
  frontend/       vanilla HTML / CSS / JS client
  infra/          docker-compose stack + image service
  voice-api/      Kokoro TTS service
```

## Status

Active personal project, work in progress. The brain and the services run and are tested; the frontend is being redesigned.
</content>
