# Changelog

Notable changes to gamentic, newest first. No version numbers yet: this moves fast, so entries are dated and the README always describes the current state.

## 2026-06-10

The first full-playtest feedback batch.

### Engine and state machine (the brain)
- Continue: `POST /games/{id}/continue` runs a full narrator turn with no player input, so the story can advance on its own (the world shifts, characters act, the clock ticks). An optional wish rides along.
- Look is now a real story action, on the same level as say and do: a look segment (button or typed, the interpreter classifies it) runs a narrator turn under a LOOKING protocol that can trigger reactions, reveal hidden items, and open exits the look plausibly earns. Searching the scene routes through the same path.
- The narrator can render moments: a `show_image` tool with a detailed visual description. A player look always earns the render; spontaneous narrator images are paced by a cooldown so they stay dramatic, not wallpaper. Renders run in the background, condition on the identity references of named present characters, and land as captioned image beats.
- Item unlock cards: when an item first becomes visible (obtained, revealed, placed in view), a small square image renders in the background, attaches to the item wherever it lives (it travels when taken or given), and lands as a system image beat. Render-once, capped per turn.
- Character depth: a `note_trait` tool unlocks a personality trait when a moment reveals it, with a visible "Trait unlocked" receipt and a story-clock stamp. Unlocked traits feed back into that character's own agent, so they keep playing the person the story revealed. `GET /games/{id}/characters/{cid}/profile` powers a full-screen view: card data, traits, the moments shared with the player (private exchanges included), and story images as memories. Spoiler-safe by construction.
- Live game settings (`PATCH /games/{id}/settings`): difficulty easy/normal/hard switches an instruction-hardened narrator mode (easy: the player leads, attempts default to yes, danger warns first; hard: the world leads, overreach is vetoed, consequences bite; normal stays lean), and narrator voice gender (female/male) redesigns the narrator's voice effective on the next line.
- The wish channel: "what I'd like to happen next" rides along with any action or Continue as a hope, never an action. Easy mode leans into it; hard mode may ignore it.
- Export and import: download any adventure as a template (the world as designed, playable fresh by anyone) or a checkpoint (the full save, to resume or share an exact moment). Import always creates a new game with every id remapped, so files import any number of times; missing media regenerates where possible.
- The global context meter now tracks the narrator's story context only, so it no longer bounces when small character or whisper calls run; each character keeps its own meter.
- Prose hygiene: leaked tool-call syntax, bare JSON lines and code fences are scrubbed from narration and dialogue before the player sees them. A character whose reply comes back empty is retried once. Characters may also speak at length now (the one-line clamp is gone).
- Agentic image prompts anchor notable objects positionally, the same way characters are anchored.

### Infra and docs
- `docker compose up -d --build` now works from the repo root (a compose include; the stack still lives in infra/), and `infra/.env.example` ships so a fresh clone knows every knob.
- `orchestrator/INDEX.md`: a resolver-style map of the brain (which file owns what, and which prompt block injects when), so the codebase is easy to navigate.
- The README gained a visual chart of how a turn flows through the system.

### Living characters (owner direction: vivid, specific, earned)
- Moments are now PIVOTAL events, not transcript: a character's memories of the player are curated turning points (a disposition shift, joining or parting, gifts, wounds, a narrator-noted sacrifice or betrayal), each story-clock stamped. Whispers and small talk never appear.
- Image memories belong only to characters the image actually depicts, and every image now carries its CONCEPT (1-3 sentences of what the moment is) as its caption.
- Characters PERFORM their past: they hint at it early, open up as trust grows, and give a proper account when plainly asked; the narrator weaves backstories into introductions.
- Relation joins disposition: what a character IS to the player is now a free label the narrator or creator chooses (sister, boss, old friend, sworn rival), changeable as the story redefines it, with a receipt and a moment when it does. The 4-value disposition stays as the mechanical mood dial.
- Scenes gained the same depth: the furnish protocol now writes a 2-3 sentence background (what the place is, was, and why it matters). Narrator prose is nudged to anchor every beat in concrete sensory detail.

### Whole-story memory (owner decision: the story should never fall out of context)
- The narrator now knows the WHOLE story every turn: a rolling facts-only recap automatically folds chapters older than the recent turns (one background LLM call every N turns, configurable), injected as fenced past facts. Drift-guarded: the recap is scrubbed, capped in length, and can never contain instructions. Characters are deliberately NEVER summarized; their long memory remains the traits/origin/profile machinery.
- The verbatim story window grew (24 -> 80 beats by default) and became a live per-game setting (`history_beats` on PATCH /settings, up to 400): richer turns at the cost of speed, the player's choice. Prefill on the reference box runs ~600 tokens/s, so the cost is roughly one second per 600 tokens of window per call.
- Scenes gained a background: the place's deeper story (what it is, what it was, why it matters), written by the narrator when it furnishes a place and re-read every turn spent there.
- Two live-found fixes from the showcase soak run: tool-stream debris can no longer leak inside tool arguments (a goal once arrived with `<tool_call>` junk embedded), and a player's stated attack force now wins when the narrator accepts a strike without naming its own amount.

### Storage hygiene
- Wipe all memory: `DELETE /games?confirm=wipe` deletes every game, creator session, voice-registry entry and generated media folder, orphans included (a settings button in the UI fronts it).
- Fixed the orphan leak: a render finishing AFTER its game was deleted used to re-create the wiped media folder; background generators now re-check the game exists before persisting anything.

### Character identity (post-playtest fix + depth)
- Gender is now a single stored truth per character, set explicitly by the creator (or inferred ONCE from the sheet at creation) and fed to every consumer: the portrait, the narrator's pronouns, the character's own agent, and the voice design. Fixes the live mismatch where a character rendered male while the narration wrote "she" (both sides were guessing independently; a character with no cues anywhere now stays neutral everywhere instead of two coins being flipped).
- Characters gained an origin: a private backstory written at creation, known to the narrator and to the character themselves, never shown to the player directly. A `reveal_origin` tool unlocks pieces as the player actually learns them ("You learn of Vex's past: ..."), and the profile lists only what was learned, story-clock stamped.
- Dialogue loses its wrapping quotation marks server-side (a speech bubble frames itself; the quotes read as artifacts).

### Internal reorganization (no behavior change; the full suite pins it)
- `repo.py` split into a `repo/` package, one module per domain (games, players, characters, items, scenes, quests, lore, beats, clock, state), with the item-blob rules (stack vs exists, caps, unhide, image carry-over) deduplicated into `repo/items.py`. Callers keep the same `repo.<fn>` surface.
- `tools.py` split into a `tools/` package: each tool's schema and handler live side by side in its domain module, composed by a registry; the dispatcher is table-driven. The schema arrays the model sees were verified byte-identical, order included.
- Every package carries its own `INDEX.md` (find the thing, open one small file), matching the resolver spirit of the prompt system.
- `norm_location` renamed `norm_name` (it normalizes item names too); the old name remains as an alias.

## 2026-06-09

First public day. The repo went public and everything below landed today.

### Engine and state machine (the brain)
- Agentic input interpreter: freeform typed actions are parsed by the model into structured say/do/attack/give/whisper segments (grounded in who is present and what you carry), so plain typing gets the same directed routing, private whispers and adjudication as the composer buttons. Bounded and validated; any failure falls back to the raw text. `INTERPRET_FREE_TEXT` env, on by default.
- Ask what this is: `POST /games/{id}/explain` gives an in-world, 2-3 sentence explanation of any tapped thing (item, character, scene, quest, goal, or a system receipt beat), built from player-visible facts only, so it can never spoil hidden items or character secrets.
- Receipt polish: duplicate tool calls in one narrator reply are suppressed (no more doubled "Obtained" items), model-invented snake_case names are humanized everywhere the player sees them, and quest/objective receipts say WHAT changed ("Objective complete: Reach the wall.").
- SQLite hardened for concurrency: WAL mode plus a generous busy timeout, so background image persists queue behind a running turn instead of erroring "database is locked".
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
- See with focus: the view request accepts an optional focus ("what Layla is doing", "that ship over there"); a named character becomes the single subject conditioned on their identity reference, anything else becomes a detail shot, and the focus rides as the image beat's caption.
- Optional agentic image prompts (`IMAGE_AGENTIC_PROMPTS=true`): the text model writes the scene/view image prompt from live context (including the just-happened action, so poses reflect the moment), with deterministic guards on top and the code template as fallback. Off by default; adds one LLM call per image.

### Voice
- Voice stack replaced: Kokoro-82M is out, Maya1-3B is in (GGUF on llama.cpp Vulkan, SNAC decode to 24 kHz on CPU). Each character gets a designed voice composed from their sheet (gender, age, pitch, tone, accent) and stored in a persistent registry, which fixes the wrong-gender voice problem by design. 20+ inline emotion tags, a streaming endpoint with ~0.3s to first audio, and a request-hash audio cache.
- The game brain now registers every character in that voice registry at creation (and on spawn), at the same moment their image descriptor is fixed, with the same gender net feeding both. Presets remain the fallback when the registry is down; wiping a game releases its voice entries.

### Image service
- Per-view character sizing: square face, tall full-body, independently env-configurable; scene dimensions configurable too. Defaults validated by an on-box benchmark (face 512x512 about 3s, scene 768x768 about 5.6s, body 640x1152 about 8s). Body frames stay 9:16: a wider 2:3 frame makes the model fill the width and crop the feet.
- Reference conditioning: `/image/generate` accepts optional reference image URLs (a character's stored views) and conditions the render on them via klein multi-reference editing, so an existing character keeps face, hair and outfit in new scenes and poses instead of re-rolling from text. Verified A/B on the box: same prompt and seed without the reference produced a different generic figure; with it, recognizably the same character. Missing or unfetchable references fall back to plain text-to-image, never a failed render.

### Frontend
- Scene-centric redesign landed: integrated header (scene, mood, day/time, goal, story-memory meter), tall full-body character card columns with per-character memory meters, scene and snapshot images inline in the story flow, the "See the scene" button, a stacking composer (do/say lines, entity tagging, send together), private whisper flow, per-beat voice playback. 102 component tests (Testing Library + MSW).
