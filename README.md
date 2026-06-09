# 🎲 Gamentic

A self-hosted AI dungeon role-playing game you play in the browser, running entirely on your own machine. An AI narrator and a cast of AI characters (each with their own persona and voice) drive a living, branching story. No cloud and no API keys: the text, images, and voice are all generated locally.

> Built and tuned for an AMD Strix Halo APU (Ryzen AI Max), on standard containers.

![status](https://img.shields.io/badge/status-work%20in%20progress-orange) ![local](https://img.shields.io/badge/runs-100%25%20local-success) ![model](https://img.shields.io/badge/LLM-Gemma%2012B%20(llama.cpp%2FVulkan)-blue) ![api](https://img.shields.io/badge/backend-FastAPI%20%2B%20SQLite-009688)

## ✨ What you do

- 🗺️ Explore scenes, find ways out, search for hidden things.
- 💬 Talk to characters, each its own AI with its own voice and agenda.
- ⚔️ Fight, give, take, trade: characters can act on each other and on you, not just talk.
- 🤫 Pull a character aside for a private word no one else hears.
- 🎯 Chase quests and a goal the story keeps up to date as you play.

## 🧠 The brain

FastAPI + SQLite. One local LLM plays the narrator and every character through separate contexts. It writes prose and proposes changes only by calling validated tools; the database is the source of truth, so the model never owns game state (LLMs hallucinate state, a database does not). Plain REST, sequential: one request returns one fully resolved turn.

## 🧩 The state machine (the heart of it)

Gamentic treats the world as an explicit state machine, and the narrator is the engine that advances it. Every turn it reasons (silently, in its prompt) about the transition: what is the state now, what actions and dialogue just happened, what did the player actually do, and therefore what changes, what is kept, and what transitions.

What the state tracks:

- 🏚️ **Scenes as real places:** description, mood (calm / tense / dangerous), exits (with an automatic way back so you are never stranded), and their own inventory that persists when you leave and return.
- 👤 **Characters:** disposition toward you (friendly / neutral / hostile / unknown), whether they follow you between scenes, HP, and what they carry.
- 🎒 **Items:** loose loot you can pocket vs fixed scenery you cannot, plus hidden items you only find by searching.
- 🎯 **Progression:** quests, objectives, points, life, and a current goal.
- ⏳ **Time** (in progress): the world advances, and a place you left is reasoned about when you come back to it.

Everything is bounded by caps (max items, characters, exits, actions) on purpose. Bounded state is what keeps the story consistent and the model honest.

## 🗣️ Why the "Heretic" model

The text model is an uncensored ("heretic") finetune of Gemma (`igorls/gemma-4-12B-it-heretic`, GGUF Q4) on llama.cpp with Vulkan. It was chosen deliberately: a dungeon needs characters that can genuinely act (attack, betray, scheme, make morally grey choices) and a narrator that stays inside the fiction instead of refusing or moralizing. The uncensored variant buys that creative freedom and keeps characters in character.

## 🖼️ Images and 🔊 voice (optional)

- 🖼️ **Image:** ComfyUI (FLUX) behind a small REST adapter, for scene and character art.
- 🔊 **Voice:** Kokoro-82M text-to-speech on CPU, a distinct voice per character.

Both are optional. The game is fully playable text-only, and art and voice fill in as they generate.

## 🚀 Run it

Requires Docker (with GPU access for the model and the image service) and local model files on disk.

```bash
cd infra
# set your model paths and ports in infra/.env (the compose file lists the variables it reads)
docker compose up -d
```

| Service | URL |
|---|---|
| 🎮 Frontend | http://localhost:5173 |
| 🧠 Orchestrator (game API) | http://localhost:8000 |
| 📝 Text model (llama.cpp) | http://localhost:8080 |
| 🖼️ Image / 🔊 Voice | http://localhost:9001 / http://localhost:9002 |

Open the frontend, create a world by chatting with the story creator, and play.

## 🗂️ Layout

```
gamentic/
  orchestrator/   game brain (FastAPI + SQLite, narrator + character agents, tools)
  frontend/       vanilla HTML / CSS / JS client
  infra/          docker-compose stack + image service
  voice-api/      Kokoro TTS service
```

## 🧪 Status

Active personal project, in progress and under heavy iteration. The brain and the services run and are covered by an automated test suite (deterministic tests plus live tests against the real model). The frontend is being redesigned right now. Expect rough edges.

## ⚠️ Known issues and limitations

Being honest about where it stands today:

- 🔊 **TTS is rough.** Kokoro sometimes gives a character the wrong-sounding voice (a male can read female, a female can read male) and drifts in consistency across lines. It works, but it is slated for a rework.
- 🖼️ **Images can be small or plain,** and scene art is still being wired into the UI cleanly.
- 🧠 **Some limits are model-based.** A 12B Q4 model on local hardware will occasionally miss a tool call, repeat itself, or under-furnish a scene. The brain adds structure to fight this: a no-dead-air narration pass, bounded state, and explicit transition reasoning.
- 🛠️ We are actively optimizing all of this, to make it as good as the local model and hardware allow.
</content>
