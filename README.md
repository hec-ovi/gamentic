# 🎲 Gamentic

A self-hosted AI dungeon role-playing game you play in the browser, running entirely on your own machine. An AI narrator and a cast of AI characters (each with their own persona and voice) drive a living, branching story. No cloud and no API keys: the text, images, and voice are all generated locally.

> Built and tuned for an AMD Strix Halo APU (Ryzen AI Max), on standard containers.

![status](https://img.shields.io/badge/status-work%20in%20progress-orange) ![local](https://img.shields.io/badge/runs-100%25%20local-success) ![model](https://img.shields.io/badge/LLM-Gemma%2012B%20(llama.cpp%2FVulkan)-blue) ![api](https://img.shields.io/badge/backend-FastAPI%20%2B%20SQLite-009688) ![license](https://img.shields.io/badge/license-MIT-green)

## ✨ What you do

- 🗺️ Explore scenes, find ways out, search for hidden things.
- 💬 Talk to characters, each its own AI with its own voice and agenda.
- ⚔️ Fight, give, take, trade: characters can act on each other and on you, not just talk.
- 🤫 Pull a character aside for a private word no one else hears.
- 👁️ Hit "See" to generate an image of the scene with everyone in it, exactly as the world stands right now.
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
- ⏳ **Time:** a fictional story clock. A few minutes pass with every action, the narrator jumps it for rests and journeys, and days and times of day derive from it.
- 📓 **Draft / pending layer:** when you leave a place, the world keeps a draft of how you left it (its items, who was there, the open threads). That snapshot is what makes the world persistent: return later and it is as you left it, and the narrator reasons about what plausibly changed while you were gone.

Everything is bounded by caps (max items, characters, exits, actions) on purpose. Bounded state is what keeps the story consistent and the model honest.

## 🗣️ Why the "Heretic" model

The text model is an uncensored ("heretic") finetune of Gemma (`igorls/gemma-4-12B-it-heretic`, GGUF Q4) on llama.cpp with Vulkan. It was chosen deliberately: a dungeon needs characters that can genuinely act (attack, betray, scheme, make morally grey choices) and a narrator that stays inside the fiction instead of refusing or moralizing. The uncensored variant buys that creative freedom and keeps characters in character.

## 🖼️ Image (optional)

**FLUX.2 [klein] 4B** (the distilled, few-step variant) running in ComfyUI behind a small REST adapter, generating scene and character art. The exact model set (Comfy-Org repacks, the official ComfyUI Klein template, around 16 GB total):

- diffusion model: `flux-2-klein-4b.safetensors`
- text encoder: `qwen_3_4b.safetensors` (FLUX.2 uses a Qwen3-4B encoder)
- VAE: `flux2-vae.safetensors`

Optional: the game is fully playable text-only, and art fills in as it is generated.

## 🔊 Voice (optional)

Kokoro-82M text-to-speech on CPU, giving the narrator and each character a distinct voice. Optional, synthesized on demand. (See the known issues below; the voice layer is still rough.)

## 🚀 Run it

Requires Docker (with GPU access for the model and the image service) and local model files on disk.

```bash
cd infra
# set your model paths and ports in infra/.env (the compose file lists the variables it reads)
docker compose up -d
```

| Service | URL | Tech stack |
|---|---|---|
| 🎮 Frontend | http://localhost:5173 | Vanilla HTML / CSS / JS, served by nginx |
| 🧠 Orchestrator (game API) | http://localhost:8000 | FastAPI, SQLite, httpx, Python 3.12 |
| 📝 Text model | http://localhost:8080 | llama.cpp (Vulkan), `gemma-4-12B-it-heretic` GGUF Q4 |
| 🖼️ Image | http://localhost:9001 | ComfyUI + FLUX.2 [klein] 4B (distilled), FastAPI REST adapter |
| 🔊 Voice | http://localhost:9002 | Kokoro-82M (ONNX) on CPU, FastAPI |

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

## 📜 Models and licenses

Gamentic is just the harness. It does NOT distribute, host, or bundle any model weights. You bring your own, downloaded from their official sources, and each model stays the property of its authors under its own license and terms, which you are responsible for following. Read them at the source:

- 📝 **Text, Gemma (Google).** The game runs a community uncensored finetune of Google's Gemma. Gemma and its derivatives are governed by Google's own terms, not by this repository:
  - Gemma Terms of Use: https://ai.google.dev/gemma/terms
  - Gemma Prohibited Use Policy: https://ai.google.dev/gemma/prohibited_use_policy
  - The specific finetune used: https://huggingface.co/igorls/gemma-4-12B-it-heretic-GGUF
- 🖼️ **Image, FLUX.2 [klein] 4B (Black Forest Labs),** under Apache-2.0:
  - Model: https://huggingface.co/black-forest-labs/FLUX.2-klein-4B
  - Black Forest Labs licensing: https://bfl.ai/licensing
- 🔊 **Voice, Kokoro-82M (hexgrad),** under Apache-2.0:
  - https://huggingface.co/hexgrad/Kokoro-82M
- ⚙️ **Runtimes** are used as-is under their own licenses: llama.cpp (MIT) and ComfyUI (GPL-3.0).

Nothing in this repository grants you any rights to those models. If you swap in a different model, follow that model's license. Gamentic simply orchestrates whatever local models you point it at.

Gamentic's own code is **MIT licensed** (see [LICENSE](LICENSE)). Changes are tracked in the [CHANGELOG](CHANGELOG.md).
</content>
