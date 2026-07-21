# Roadmap: art direction and character evolution

Two workstreams, built on the `evolve` branch in small milestones. Each milestone is one commit pushed to `origin/evolve`, playable on its own, with the full local test suites green. Hector tests each one; when a milestone feels right we merge to `main` and ship.

**Workstream A, art direction.** The image prompts are capped hard today (90-word clips, small token caps on the prompt-writing LLM calls) and the art director's user prompt had a template bug that stripped all world context from it. The FLUX.2 klein encoder actually accepts 512 tokens (roughly 350 words); the "degrades past 100 words" comment in the code is not supported by any primary source. So: fix the bug, remove the caps, teach the art director to write dense detailed prompts (poses, gesture, composition, lighting, materials), and give the player a per-game art-direction field that rides every render.

**Workstream B, character evolution.** A character's persona is a single sentence written once at creation and never touched again; there is no tool that can change it. The plan: make persona mutable and structured (persona + behavior directives + an evolution log), add narrator tools that write it, and put an Evolve tab on the character profile where you tell the narrator how the character should change ("more assertive", "speaks at length", "acts on her own"). Characters already write their own memories (share_past, mark_moment, admit_trait); the last milestone extends that autonomy to self-images and stronger initiative.

Invariants that hold at every commit: the game stays fully playable text-only; every render path falls back to the deterministic template prompts on any failure; all state changes go through validated tools; beats land only under the write lock; wire schemas keep validating; docs/guide contract pages are updated in the same commit that changes a shape.

## Milestones

### M0. Groundwork repairs
Fixes in the blast radius of the two workstreams, each with tests.
- Fix `artdirector.user.md` placeholders (single braces where the renderer substitutes only double braces): the art director currently receives zero world data. This alone should visibly improve first-sight art.
- Remove the LLM output caps in this path: creator finalize (1200 tokens, truncates rich worlds into invalid JSON and fails creation), art director (700), agentic image prompts (140), explain (160), origin enrichment (400). Parse failures still fall back to template prompts.
- Give background image persists a busy timeout that survives a long turn, so rendered art stops being lost to "database is locked".
- Tool guards: `remove_item` rejects non-positive quantities; `heal` refuses dead targets.
- Transfer: template export carries gender, origin, relation, player_items and start_time_of_day; checkpoint import validates the incoming game id before touching the filesystem, with hostile-import tests.

### M1. Rich art prompts, uncapped
- Replace the 90-word clips with one boundary guard sized to the encoder's real 512-token window.
- Rewrite `artdirector.system.md` and `imageprompt.system.md` to teach dense structured prompts: subject first, one positionally anchored sentence per character (left/center/right plus foreground/background) so traits do not bleed, pose and gesture, clothing materials, lighting always, camera framing, style named once, exclusions phrased positively. No word-count instructions anywhere.
- Raise the small clips on view and directed shots (18/20/25 words today) to the same boundary.
- Keep the parts that are correctness rather than length: quote stripping, the no-text guard, the 3-person ceiling, template fallback.
- Imported worlds get the art-director pass too (skipped entirely today).
- The opening main image gets the fresh character portraits as identity references (it sends none today).

### M2. Per-game art direction
- New `games.art_direction` column: standing instructions for how this adventure should look (poses, framing, detail level, palette). One style helper replaces the scattered per-site style lookups so the direction rides every render: portraits, scenes, views, item cards and the creation art director.
- Editable in game settings while playing, same PATCH chain as difficulty; carried by template export.
- The narrator's `show_image` tool schema teaches pose and composition detail.

### M3. Structured evolvable persona (backend only)
- `characters` gains behavior directives (how active, how verbose, how much initiative) and an evolution log, as additive migrations; persona gets its first setter.
- New narrator tools `evolve_persona` and `set_directives`, validated like every other tool.
- `character.system.md` gains a directives block; the hardcoded "keep it brief" line becomes data-driven; the public one-line bio re-derives when persona changes so it never contradicts the evolved character. Evolve text is scrubbed like character output before it is stored.
- The dead `talkativeness` column goes away (nothing ever read it).
- No visible change yet; tests prove an evolved persona reaches the character's next prompt.

### M4. The Evolve screen
- New tab on the character profile: a conversation with the narrator about this character. The narrator answers in prose and applies changes through the new tools; the tab shows current persona, directives and the evolution history.
- Runs as a gated turn (same busy lock as the composer) so it cannot race an in-flight turn; the pane rewrites from the server echo so the post-turn refetch never clobbers an edit.
- This tab deliberately shows the persona you are now editing; a character's private knowledge and unrevealed past stay hidden.
- Frontend component tests for the tab, the gating and the echo.

### M5. Character autonomy
- A `self_image` character tool: a character can show you something (itself, a memory, its handiwork), on a per-character cooldown mirroring the narrator's, rendered with that character's portrait as identity reference and attributed to their gallery.
- High-initiative directives let characters reach for their tools more; the cascade bounds still cap total acts per turn.
- Appearance evolution triggers portrait regeneration through the existing self-heal.
- SSE stays within the existing event vocabulary on both ends; an open profile refreshes when its character's art changes.

### M6. Ship
- docs/guide pages, INDEX files, README and CHANGELOG brought up to reality; repo description and topics re-checked; `evolve` merges into `main`.
