# Changelog

Notable changes to gamentic, newest first. No version numbers yet: this moves fast, so entries are dated and the README always describes the current state.

## 2026-06-11

### The scaffold regression, killed at the root (live find by the owner)
- At deep context the model regressed into printing its turn as the worked example's shape - a "(think: ...)" block, a "tools: { ... }" object written as text, a "Prose:" label, even screenplay lines from characters that were never spawned - and called no real tools at all, so the prose moved while the world froze.
- Three causes, all fixed: "reason silently" was physically impossible with hybrid thinking disabled, so narrator reasoning now runs in the model's real thinking channel (on by default, separated from prose by llama.cpp); the worked example itself was a printable template, so it was rewritten to contain no printable format; and scaffold stop sequences now halt a regressing generation at its first marker, letting the resolve pass voice the turn cleanly.
- The display nets were generalized too (reasoning spans strip wherever they start, balanced across lines and nested parentheses; written-out tool blocks die whole), with regression tests pinning the exact raw bytes from the live database. Existing stories were retro-scrubbed clean.

### Inference goes pluggable (owner direction: the engine is ours, the inference is nobody's)
- Each modality now sits behind a provider interface resolved at call time: text (any OpenAI-compatible endpoint), audio (local Maya1, OpenAI TTS, ElevenLabs, fal), image (local ComfyUI templates, OpenAI gpt-image, Google nano banana, fal). Dialects are tiny JSON translators, no SDKs; capability flags (references, seed, emotion mode) make the engine degrade deterministically instead of breaking.
- Character voice identity moved into the engine: the designed voice is composed from the sheet and stored with the character, then resolved per provider deterministically. Switching audio providers re-resolves every voice exactly once; a character never speaks in two voices. The voice service's registry is no longer used and holds no game state.
- A one-file admin panel at /admin (optional ADMIN_TOKEN gate): pick providers, paste keys (masked, write-only, server-side), press TEST per modality, save; the next call uses it, no restart. POST /audio/speak is the key-safe passthrough for cloud audio.
- Honest testing line: local paths are the live-tested defaults; cloud dialects are pinned by contract tests against published schemas and await live verification by anyone holding a key. The README explains the whole abstraction.

### The model swap: Gemma 4 26B-A4B mixture-of-experts
- The text model is now the heretic finetune of Gemma 4 26B-A4B (Q4_K_M, ~16.8 GB): 26B of knowledge, ~4B active per token. Measured on the box: ~900-1000 tok/s prefill and ~55 tok/s decode, against the 12B's ~600 and ~24. A full scripted adventure ran 49 turns with zero timeouts where the 12B lost three; deep-context turns dropped from 60-300s to 20-60s.
- Side-by-side scripted runs (same arc, same code) showed the 26B holds what the 12B could not: no cast impersonation inside narration, state staying in sync with the prose across scene moves, dialogue from the whole cast with richer emotion coverage.

### What the live runs taught the brain (fixes from real play, both models)
- The hybrid model likes to print its reasoning line: a leading "(think: ...)" span is now stripped from narration, never shown. A NARRATOR_THINKING knob can instead route that reasoning into the model's real thinking channel (later made the default; see the scaffold entry above).
- The narrator generation now carries stop sequences for every present character's name, so screenplay-style impersonation ("Vane: ...") halts mid-generation instead of reaching the screen. A line that is nothing but a code-shaped call is scrubbed whatever its name (a hallucinated tool once leaked as prose).
- Failed tool calls get a second chance and a voice: a call that failed only because of ordering inside the same reply (a disposition set before its own spawn) is retried once and lands; whatever stays invalid is reported to the narrator next turn ("fix the call, not the story") instead of vanishing silently.
- A turn is a beat, not a chapter: at most two characters speak per turn and each acts once, so quest unlocks, scene changes and new voices land as moments instead of pile-ups. Both dials are player-facing per-game settings now (voices per turn, acts per voice), next to the story-memory ones.
- Thin character backstories get a real biography at creation: one focused call per character writes 5-8 concrete sentences (the whole-world finalize call consistently under-delivered), guided by a worked example. Trait wording is steered to vivid behavior words (cynical, impulsive, fiercely loyal), and the trait-fragment bug turned out to be the prompt's own worked example teaching a dangling word - fixed at the source.
- Snapshot images get unique filenames (two background renders could overwrite each other and leave two captions pointing at one image); a closing emotion tag can no longer leak into dialogue as text; a length-cut fragment with no finished sentence is dropped instead of displayed; the transport timeout honors the slow-turns decision (300s).

### Frontend (round 3.3: work order closed, deep audit, widgets, theme isolation)
- The round-3.1 work order is fully shipped. The turn-pacing dials joined the adventure settings (voices per turn 1-4, acts per voice 1-3, Default hands the reins back), and the profile's Look became truly private: whisper mode "look" on the wire, its echo and image live in the whisper thread and never leak into the public story (the old build sent a public look and the tests had enshrined it).
- A look's "rendering the view..." hint never expires anymore. The image is guaranteed, so the poll now outlives the 45s window, backs off to ~9s after the first minute, and waits for the swap-in instead of showing the user a lie when a render queues behind other GPU work.
- A deep multi-agent audit of the layer (every finding adversarially verified against the code) drove a hardening batch: a failed game open returns to the library with a toast instead of stranding on a dead loading screen; background renders (late images, art polls, profile refetches) no longer erase a half-typed line; a stale in-flight state poll can no longer clobber fresh post-turn state; every request times out (20s reads, 330s LLM calls) so a hung backend releases the busy-lock; FastAPI 422 details toast as their human message, not [object Object]; voice stops and its synth queue flushes on game switch; peeking at settings pauses the pollers instead of killing them; a network blip during creator restore no longer discards the saved session.
- The render layer's repeated patterns became 13 shared widgets (modal scaffold, hp bars, the badge pair, thinking dots, lightbox images, the reveal veil, avatar fallbacks, and more), with accessibility riding along: every thinking indicator is a live status region, every dialog has an accessible name, every icon button is type=button.
- The visual system split into theme tokens and structure: themes/hightech.css holds every design decision (colors, fonts, a single chamfer factor for the sci-fi corner cuts, eases) and styles.css consumes tokens only, lint-enforced down to the JS layer (character fallback colors ride tokens too). Verified pixel-identical in a real browser against the pre-refactor build; a future medieval theme is now a one-file job. No new theme yet, by design.
- 178 tests across 10 files, was 163: pacing round-trips, the never-expiring hint on a fake clock, failure restores, the theme contract.

### Frontend (round 3.4: the render becomes a morph)
- render() no longer rebuilds the DOM with innerHTML: it morphs the real DOM against the fresh HTML (vendored idiomorph, one 0BSD-licensed file, still no build step). Unchanged nodes keep their identity, so focus, caret, scroll positions and mid-flight animations survive background re-renders structurally; the hand-rolled scroll bookkeeping is gone and the typed-input snapshot demoted to a belt-and-braces for plain inputs.
- Events went with it: per-element re-binding after every render is replaced by five delegated listeners on the root, attached once. An in-place pane patch needs no re-wire, and preserved nodes can never double-fire.
- Verified live against the running stack, not just in jsdom: typed text and composer focus survive profile open/close renders in a real browser, a full narrator turn (echo, reveal, prose, art) plays correctly under morphing, zero console errors. 179 tests.

## 2026-06-10

### Characters with their own memory (late batch; owner direction: whole context per character)
- Every beat now records WHO witnessed it. A character's verbatim window is what THEY lived through, not the room's log: a follower keeps the scenes it traveled through, a late arrival can never "remember" talk from before it entered, and a whisper belongs to its addressee alone. Legacy beats keep working through a location fallback; checkpoint import remaps the stamps so imported casts keep their memory.
- Each character can fold their older witnessed beats into a private second-person recap ("You remember...") in the background, facts-only and capped, only when enough unfolded memory piles up, so only story-central characters ever trigger a call. On by default, env-tunable (`CHAR_HISTORY_BEATS`, `CHAR_SUMMARY_*`).
- Characters now feel their state when they speak: disposition toward the player, wounds in words ("badly wounded", never numbers), and what they carry. They remember their newest pivotal moments with story-clock labels, and their top traits are restated as the last thing they read plus one worked example, the two levers with actual evidence against persona drift.
- The narrator's state block now carries each present character's revealed traits, so it stages personality, not just mood and relation.
- Pivotal moments evict the oldest at the cap instead of rejecting the newest (a long story no longer freezes a character's memories in act one).

### Hardening pass (deep-read audit of the whole brain)
- One retry on dropped connections to the model server: a redeploy no longer kills the in-flight turn. Timeouts are deliberately never retried.
- Falling to zero life turns the story lost, with a system beat and the narrator told to stage the aftermath; a heal from zero brings it back. Turns stay allowed either way (aftermath play is a feature).
- Emotion tags are now mapped to what the voice can actually render ([tired] becomes a sigh instead of silently losing its tone), angle-bracket tags the model emits from habit are understood and scrubbed, and narrator prose can never show a tag on screen; a leading tag becomes the narration beat's spoken tone.
- A partial character portrait set (a crashed render that saved one of three views) now counts as missing and re-renders complete instead of passing as done.
- A stale background recap fold skips its write instead of clobbering a fresher one; a stray authoring artifact was removed from three live prompt templates; the last raw-SQL bypass of the repo layer is gone; three dead config knobs removed.

### Public face
- README rewritten: compact, current state only, the architecture rule stated once, no decoration. The GitHub description and topics finally stopped claiming Kokoro (Maya1 shipped two days ago).

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

### Late-night soak-run findings (a scripted 4-adventure, ~120-turn live playthrough)
- Every look now earns an image: when the narrator describes a look without rendering it, the deterministic state-grounded snapshot fires with the look's focus.
- Speech to an absent character bounces deterministically ("Garron Pike is not here.") instead of failing silently, which had let the narrator write absent people into scenes.
- Story-memory settings: fold cadence (`summary_every`) and a hard context budget (`context_tokens`, the verbatim window auto-shrinks to fit) join `history_beats` as live per-game settings; the recap ceiling grew to 400 words.
- Player attack force wins when the narrator accepts a strike without naming its own amount; tool-stream debris can no longer leak inside tool arguments; portraits are per-character resilient, relink from disk, and self-heal on later turns.
- Item unlock cards self-heal the same way: a card missed by the per-turn cap or a failed render gets picked up on later turns, so no item stays imageless.
- Trait, origin and moment texts are tidied on write AND read (snake_case collapsed, markdown debris stripped), cleaning rows recorded before the fix existed.

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
