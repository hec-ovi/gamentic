# Changelog

Notable changes to gamentic, newest first. No version numbers yet: this moves fast, so entries are dated and the README always describes the current state.

## 2026-06-09

First public day. The repo went public and everything below landed today.

### Engine and state machine (the brain)
- Narrator reasons about every state transition internally (state now, what happened, next state) and changes the world only through validated tools; the database is the single source of truth.
- Resolver-style prompt dispatch: a lean narrator core, plus situational protocol blocks (furnish a new place, return after an absence) injected only on the turns that trigger them, each carrying a few-shot example. Few-shots also added for adjudication, character tool use, and image description fields.
- Player attempt adjudication: impossible attempts are rejected deterministically with friendly in-world reasons; valid attack/give attempts go to the narrator to accept, adjust, or veto with a reason; anything left untouched happens as attempted, so no action is ever silently dropped. The veto tool is only offered while attempts are pending.
- Fictional story clock (hybrid): a few minutes pass automatically per action, the narrator jumps it for rests and journeys, and day/part-of-day derive from it.
- Draft persistency layer: leaving a scene stamps when, the narrator can note open threads, and returning surfaces the elapsed time plus the note so the place plausibly lived while you were gone.
- Entity chips: characters and items tagged in the composer resolve by real id, so names never drift.
- Private 1:1 channel: whisper say/do exchanges that other characters never see, composed as one exchange with one reply.
- Canonical scene keys (fixes a live bug where location-name drift duplicated scenes) and output hygiene scrubbing for small-model artifacts.
- Context meters: a global one (the biggest agent prompt of the turn) and one per character agent, since each character runs in its own context.

### Images
- Character reference sets (square face plus tall full-body views) and scene art generated in the background via FLUX.2 Klein 4B on ComfyUI, persisted per game, fully optional (the game is playable text-only).
- Image prompts hardened: every character descriptor leads with explicit sex and age (with a deterministic gender net when the model forgets), quoted sign text is stripped from scene prompts, and exclusions are phrased positively because FLUX has no negative prompts.
- "See" button: `POST /games/{id}/view` renders the current scene with the characters present in it, grounded in live state (looks, time of day, mood, art style), and lands in the story log as an image beat.
- Optional agentic image prompts (`IMAGE_AGENTIC_PROMPTS=true`): the text model writes the scene/view image prompt from live context (including the just-happened action, so poses reflect the moment), with deterministic guards on top and the code template as fallback. Off by default; adds one LLM call per image.

### Voice
- Voice stack replaced: Kokoro-82M is out, Maya1-3B is in (GGUF on llama.cpp Vulkan, SNAC decode to 24 kHz on CPU). Each character gets a designed voice composed from their sheet (gender, age, pitch, tone, accent) and stored in a persistent registry, which fixes the wrong-gender voice problem by design. 20+ inline emotion tags, a streaming endpoint with ~0.3s to first audio, and a request-hash audio cache.
- The game brain now registers every character in that voice registry at creation (and on spawn), at the same moment their image descriptor is fixed, with the same gender net feeding both. Presets remain the fallback when the registry is down; wiping a game releases its voice entries.

### Image service
- Per-view character sizing: square face, tall full-body, independently env-configurable; scene dimensions configurable too. Defaults validated by an on-box benchmark (face 512x512 about 3s, scene 768x768 about 5.6s, body 640x1152 about 8s). Body frames stay 9:16: a wider 2:3 frame makes the model fill the width and crop the feet.
- Reference conditioning: `/image/generate` accepts optional reference image URLs (a character's stored views) and conditions the render on them via klein multi-reference editing, so an existing character keeps face, hair and outfit in new scenes and poses instead of re-rolling from text. Verified A/B on the box: same prompt and seed without the reference produced a different generic figure; with it, recognizably the same character. Missing or unfetchable references fall back to plain text-to-image, never a failed render.

### Frontend
- Frontend redesign in progress (scene-centric layout, tagged composer with entity chips, character cards).
