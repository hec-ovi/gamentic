# providers/ index

The inference-providers layer (docs/shared/inference-providers.md): one interface per
modality, dialect classes for pure JSON shaping (httpx only, no SDKs), and the config
spine. Config resolves AT CALL TIME (admin DB override -> env -> default), so the
/admin panel hot-swaps providers with no restart. Defaults reproduce the local stack
byte-for-byte.

| Module | Owns | Key pieces |
|---|---|---|
| `base.py` | the config spine + capabilities + the shared fal queue transport | `resolve`, `ProviderConfig`, `DIALECTS`, `capability_notes`, `fal_queue_run` |
| `image.py` | image dialects: `comfy` (the tested local default), `openai` (generations/edits), `gemini` (generateContent parts), `fal` (queue + per-model maps) | `get_provider`, `ImageProvider.generate/character_set` |
| `audio.py` | audio dialects: `local` (Maya1 voice-api), `openai` (instructions), `elevenlabs` ([tag]), `fal` (maya/batch, \<tag\>) | `get_provider`, `AudioProvider.speak`, `default_voice` |

Text has no dialect class: `llm.chat` IS the text interface (the OpenAI wire dialect
covers llama.cpp and every cloud endpoint); it reads `resolve("text")` per call for
base_url/model/Bearer plus the max_stops and thinking capabilities.

Conventions:
- The engine NEVER imports a dialect class directly: game code goes through the
  media.py facade (image), llm.chat (text), or the /audio/speak route (audio), each of
  which resolves the active provider per call.
- Capability degradation is deterministic and silent: no references -> plain t2i, no
  seed -> unused, emotion none -> tone dropped. Never an error.
- Providers returning raw image data hand back a `data:` URL; media.fetch_image_bytes
  decodes it on persist, so the storage path is provider-agnostic.
- Cloud dialects are pinned by contract tests over mocked HTTP against their PUBLISHED
  schemas; live verification is the admin TEST button. comfy + local are live-tested.
