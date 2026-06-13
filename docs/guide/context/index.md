# Context — agent-ready

Every distinct LLM context and enhancer path. Character speech is owned by character-agent calls; narrator content is narration. Image and voice are enhancers, not story authorities.

> Paired with the interactive view: [`context` in the docs site](../index.html#context) (Graphs / Text). This file mirrors it node-for-node; the page is the same data drawn.
> **Read this first, then load ONLY the file the task needs.** Each file under `guide/` is deliberately fat and self-contained: opening one fully answers a class of question. Never bulk-read the folder.

**Lanes:** `turn contexts` · `shared state, media, voice` · `background/creation contexts`

**Orientation.** Turn input → interpreter/gates → narrator (omniscient) → tool dispatcher → state/beats; character agents read only their witnessed window; folds compress old beats; image/voice jobs read state and produce media/ids without deciding story truth.

## Nodes

### Turn input — `input`  ·  _shared_

The player payload for one turn.

- **Reads / shared input:** browser composer; action buttons; profile whisper panel
- **Generates:** ActionIn.action or ActionIn.segments; optional wish
- **Writes / mutates:** none
- **Key point:** The player payload for one turn.
- **IN:** _none_
- **OUT:** `interpreter` (free text only); `gates` (segments/direct)

<details><summary>JSON shape</summary>

```json
{
  "action": "string | null",
  "segments": [
    "Segment[] | null"
  ],
  "wish": "string | null"
}
```
</details>

### SQLite state — `state`  ·  _persist_

Games, player_state, scenes, characters, quests, lore, beats.

- **Reads / shared input:** all prompt builders; repo.game_state; media jobs; voice resolver
- **Generates:** current scene; present cast; prompt state blocks; API projection
- **Writes / mutates:** tools; turn engine; background media; folds; settings API
- **Key point:** Games, player_state, scenes, characters, quests, lore, beats.
- **IN:** `dispatcher` (validated writes); `summaryGame` (story_summary); `summaryChar` (memory_summary); `creator` (create rows); `origin` (characters.origin); `imageJobs` (media URLs); `voice` (voice ids)
- **OUT:** `gates` (current scene + inventory); `narrator` (state block); `charMara` (own row); `charSentinel` (own row); `artdir` (world bible); `imagePrompt` (visual context); `voice` (identity fields); `explain` (visible facts only); `apiui` (GameState)

<details><summary>JSON shape</summary>

```json
{
  "games": "row",
  "player_state": "row",
  "scenes": "rows",
  "characters": "rows",
  "beats": "rows",
  "lore": "rows"
}
```
</details>

### Beats windows — `beats`  ·  _shared_

The transcript source. Public/private beats are filtered per context.

- **Reads / shared input:** narrator; character agents; fold agents; image context; frontend
- **Generates:** narrator transcript; character witnessed window; story log stream
- **Writes / mutates:** turn engine emits beats; media image beats
- **Key point:** The transcript source. Public/private beats are filtered per context.
- **IN:** `dispatcher` (receipts); `narrator` (narration beat); `resolve` (short narration); `charMara` (dialogue/action); `charSentinel` (dialogue/action); `privateChar` (private_with)
- **OUT:** `narrator` (recent + recap); `charMara` (witnessed beats); `charSentinel` (witnessed beats); `summaryGame` (old beats); `summaryChar` (witnessed old beats); `imagePrompt` (recent public action); `apiui` (story stream)

<details><summary>JSON shape</summary>

```json
{
  "recent_beats": "global verbatim window",
  "witnessed_beats_for_character": "per-character memory window",
  "private_with": "character id | null"
}
```
</details>

### Tool schemas — `toolschemas`  ·  _tool_

The function schemas visible to narrator/character agents.

- **Reads / shared input:** tools/__init__.py; settings flags
- **Generates:** narrator_tools(); CHARACTER_TOOLS
- **Writes / mutates:** none; schemas only
- **Key point:** The function schemas visible to narrator/character agents.
- **IN:** _none_
- **OUT:** `narrator` (narrator tools); `charMara` (character tools)

<details><summary>JSON shape</summary>

```json
{
  "narrator_tools": [
    "state tools",
    "cue_character",
    "spawn/kill",
    "reject_attempt conditional",
    "show_image conditional"
  ],
  "character_tools": [
    "attack",
    "give_item",
    "share_past",
    "mark_moment",
    "admit_trait"
  ]
}
```
</details>

### Interpreter agent — `interpreter`  ·  _agent_

Small LLM call only when typed text arrives without structured segments.

- **Reads / shared input:** present character names; player inventory; raw typed text
- **Generates:** submit_segments tool call
- **Writes / mutates:** none; output is runtime segments
- **Key point:** Small LLM call only when typed text arrives without structured segments.
- **IN:** `input` (free text only)
- **OUT:** `gates` (segments)

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_interpret_messages",
  "tools": [
    "submit_segments"
  ],
  "output": {
    "segments": "Segment[]"
  }
}
```
</details>

### Deterministic gates — `gates`  ·  _tool_

Moves through known exits, validates attack/give, splits public/private.

- **Reads / shared input:** segments; current scene exits; inventory; present cast
- **Generates:** public action text; pending attempts; private exchanges; reaction queue
- **Writes / mutates:** move_location can apply before narrator; system failure beats
- **Key point:** Moves through known exits, validates attack/give, splits public/private.
- **IN:** `interpreter` (segments); `input` (segments/direct); `state` (current scene + inventory)
- **OUT:** `narrator` (public action + attempts); `privateChar` (whisper exchange); `imageJobs` (look/private look)

<details><summary>JSON shape</summary>

```json
{
  "pending_attempts": [
    "attack/give"
  ],
  "public": [
    "non-whisper segments"
  ],
  "private": [
    "whisper segments"
  ]
}
```
</details>

### Narrator agent — `narrator`  ·  _agent_

Omniscient story agent: narration, tool proposals, cues, image requests.

- **Reads / shared input:** state block; recent beats; story_summary; lore matches; attempts; wish; tool schemas
- **Generates:** narration beat text; tool_calls; cue_character; show_image request
- **Writes / mutates:** indirectly through tools only; narrator beat through engine
- **Key point:** Omniscient story agent: narration, tool proposals, cues, image requests.
- **IN:** `gates` (public action + attempts); `state` (state block); `beats` (recent + recap); `toolschemas` (narrator tools)
- **OUT:** `dispatcher` (tool_calls); `beats` (narration beat); `resolve` (state changed no prose); `imageJobs` (show_image request); `speechAnswer` (narration only)

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_narrator_messages",
  "role": "public scene narrator",
  "output": {
    "content": "narration",
    "tool_calls": "NARRATOR_TOOLS[]"
  }
}
```
</details>

### Narrator resolve — `resolve`  ·  _agent_

Second narrator call when tools changed state but no prose landed.

- **Reads / shared input:** current state; player action; state_notes
- **Generates:** short narration only
- **Writes / mutates:** narration beat through engine
- **Key point:** Second narrator call when tools changed state but no prose landed.
- **IN:** `narrator` (state changed no prose)
- **OUT:** `beats` (short narration)

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_narrator_resolve_messages",
  "tools": "none",
  "output": "short narration"
}
```
</details>

### Tool dispatcher — `dispatcher`  ·  _tool_

The only path from LLM proposals into authoritative state.

- **Reads / shared input:** tool name; arguments; actor character or narrator; SQLite state
- **Generates:** state receipt; invalid reason; cue; reactions; image_request
- **Writes / mutates:** SQLite through repo functions
- **Key point:** The only path from LLM proposals into authoritative state.
- **IN:** `narrator` (tool_calls); `charMara` (character tool_calls)
- **OUT:** `state` (validated writes); `beats` (receipts); `charMara` (cue/reaction); `charSentinel` (reaction); `privateChar` (gift reply impulse)

<details><summary>JSON shape</summary>

```json
{
  "apply_tool": {
    "name": "string",
    "arguments": {},
    "actor": "null | character row"
  },
  "result": {
    "kind": "state | cue | invalid | image | spawn | kill | reject"
  }
}
```
</details>

### Character agent A — `charMara`  ·  _agent_

One LLM call for one queued character. Example: Mara.

- **Reads / shared input:** own persona; own knowledge; own origin; own memory_summary; own witnessed beats; present roster; CHARACTER_TOOLS
- **Generates:** [say]/[do]/[whisper] tags; character tool calls; memory marks
- **Writes / mutates:** dialogue/action beats through engine; state through character tools
- **Key point:** One LLM call for one queued character. Example: Mara.
- **IN:** `dispatcher` (cue/reaction); `state` (own row); `beats` (witnessed beats); `toolschemas` (character tools)
- **OUT:** `beats` (dialogue/action); `dispatcher` (character tool_calls); `speechAnswer` (character speech)

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_character_messages",
  "instance": "character_id=char_mara",
  "output": {
    "say": "dialogue beat",
    "do": "action beat",
    "whisper": "private dialogue beat"
  }
}
```
</details>

### Character agent B — `charSentinel`  ·  _agent_

Same template, separate context and memory. Example: Vault Sentinel.

- **Reads / shared input:** its own row only; its own witnessed beats; same scene roster
- **Generates:** its own dialogue/action/tool calls
- **Writes / mutates:** beats as that character; state through character tools
- **Key point:** Same template, separate context and memory. Example: Vault Sentinel.
- **IN:** `dispatcher` (reaction); `state` (own row); `beats` (witnessed beats)
- **OUT:** `beats` (dialogue/action); `speechAnswer` (character speech)

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_character_messages",
  "instance": "character_id=char_sentinel",
  "isolated_from": "Mara private knowledge and memory"
}
```
</details>

### Private character agent — `privateChar`  ·  _agent_

Same character agent, but every emitted beat is forced into one private thread.

- **Reads / shared input:** target character context; private player whisper or gift impulse
- **Generates:** private dialogue/action beats; optional private tool effects
- **Writes / mutates:** beats.private_with = character id
- **Key point:** Same character agent, but every emitted beat is forced into one private thread.
- **IN:** `gates` (whisper exchange); `dispatcher` (gift reply impulse)
- **OUT:** `beats` (private_with)

<details><summary>JSON shape</summary>

```json
{
  "private_with": "character id",
  "impulse": "optional gift line",
  "output": "private thread beats"
}
```
</details>

### Game summary fold — `summaryGame`  ·  _agent_

Background LLM call compressing older beats into game-level recap.

- **Reads / shared input:** beats older than keep window; previous story_summary
- **Generates:** facts-only story summary
- **Writes / mutates:** games.story_summary; games.summarized_through
- **Key point:** Background LLM call compressing older beats into game-level recap.
- **IN:** `beats` (old beats)
- **OUT:** `state` (story_summary)

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_summary_messages",
  "output": {
    "story_summary": "text",
    "summarized_through": "turn_index"
  }
}
```
</details>

### Character summary fold — `summaryChar`  ·  _agent_

Background LLM call per character that crossed the witnessed-beat threshold.

- **Reads / shared input:** that character witnessed beats only; previous memory_summary
- **Generates:** private character memory recap
- **Writes / mutates:** characters.memory_summary; characters.summarized_through
- **Key point:** Background LLM call per character that crossed the witnessed-beat threshold.
- **IN:** `beats` (witnessed old beats)
- **OUT:** `state` (memory_summary)

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_character_summary_messages",
  "one_per": "alive character when threshold reached",
  "privacy": "witnessed beats only"
}
```
</details>

### Origin enrichment — `origin`  ·  _agent_

Focused LLM pass that fills thin character origins after finalize/import.

- **Reads / shared input:** game setting/tone; character persona; description; knowledge; relation
- **Generates:** private origin text
- **Writes / mutates:** characters.origin
- **Key point:** Focused LLM pass that fills thin character origins after finalize/import.
- **IN:** `creator` (thin origins)
- **OUT:** `state` (characters.origin)

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_origin_messages",
  "output": {
    "origin": "private backstory"
  }
}
```
</details>

### Creator chat/finalize — `creator`  ·  _agent_

Creation contexts that interview and then emit the initial WorldSheet.

- **Reads / shared input:** creator_sessions.history; user design answers
- **Generates:** WorldSheet JSON; characters; quests; lore; start state
- **Writes / mutates:** games; player_state; characters; quests; lore; opening beat
- **Key point:** Creation contexts that interview and then emit the initial WorldSheet.
- **IN:** _none_
- **OUT:** `state` (create rows); `origin` (thin origins)

<details><summary>JSON shape</summary>

```json
{
  "builders": [
    "build_creator_messages",
    "build_finalize_messages"
  ],
  "output": "WorldSheet"
}
```
</details>

### Art director agent — `artdir`  ·  _agent_

One optional LLM call at creation for first-sight art prompts.

- **Reads / shared input:** world bible; cast descriptors; start location; time of day
- **Generates:** main opening image prompt; character reference descriptors
- **Writes / mutates:** no state directly; prompts feed image jobs
- **Key point:** One optional LLM call at creation for first-sight art prompts.
- **IN:** `state` (world bible)
- **OUT:** `imageJobs` (opening prompts)

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_artdirector_messages",
  "output": {
    "main_image": "prompt",
    "characters": [
      {
        "name": "",
        "descriptor": ""
      }
    ]
  }
}
```
</details>

### Image prompt agent — `imagePrompt`  ·  _agent_

Optional LLM call that rewrites state-grounded image context into a FLUX prompt.

- **Reads / shared input:** place/time/mood; present characters; recent public beats; focus
- **Generates:** hardened image prompt
- **Writes / mutates:** no state directly
- **Key point:** Optional LLM call that rewrites state-grounded image context into a FLUX prompt.
- **IN:** `state` (visual context); `beats` (recent public action)
- **OUT:** `imageJobs` (prompt string)

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_image_prompt_messages",
  "output": "single image prompt string"
}
```
</details>

### Image jobs — `imageJobs`  ·  _enhancer_

Non-story media layer. Renders prompts, persists files, then updates rows/beats.

- **Reads / shared input:** state-grounded prompts; character reference images; media provider
- **Generates:** scene art; portraits; item cards; look/show_image beats
- **Writes / mutates:** scenes.image_url; characters.*_url; item.image_url; beats.kind=image; SSE events
- **Key point:** Non-story media layer. Renders prompts, persists files, then updates rows/beats.
- **IN:** `artdir` (opening prompts); `narrator` (show_image request); `gates` (look/private look); `imagePrompt` (prompt string)
- **OUT:** `state` (media URLs); `apiui` (SSE/refetch)

<details><summary>JSON shape</summary>

```json
{
  "jobs": [
    "generate_scene_image",
    "generate_images_for_game",
    "generate_item_image",
    "generate_view_snapshot",
    "generate_directed_image"
  ]
}
```
</details>

### Voice resolver/synth — `voice`  ·  _enhancer_

No story agent. It assigns/resolves stable narrator and character voices.

- **Reads / shared input:** characters.gender/description/persona; voice_design; narrator_gender; audio provider
- **Generates:** voice_design; voice_id; speech audio on demand
- **Writes / mutates:** games.narrator_voice_id; characters.voice_design; characters.voice_id; characters.voice_provider
- **Key point:** No story agent. It assigns/resolves stable narrator and character voices.
- **IN:** `state` (identity fields); `apiui` (speak button)
- **OUT:** `state` (voice ids)

<details><summary>JSON shape</summary>

```json
{
  "identity": "assign_voices_for_game",
  "playback": "frontend speakBeat -> /audio/speak",
  "story_authority": "none"
}
```
</details>

### Explain agent — `explain`  ·  _agent_

Spoiler-safe explanation call for tapped visible things.

- **Reads / shared input:** player-visible facts only; visible items; public character card; scene/quest/beat facts
- **Generates:** short in-world explanation
- **Writes / mutates:** none
- **Key point:** Spoiler-safe explanation call for tapped visible things.
- **IN:** `state` (visible facts only)
- **OUT:** `apiui` (aside text)

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_explain_messages",
  "output": "text only",
  "state_mutation": false
}
```
</details>

### API + frontend mirror — `apiui`  ·  _ui_

Receives GameState and beats, maps them, animates reveal, fetches late media.

- **Reads / shared input:** repo.game_state; /beats; SSE events; voice ids on beats
- **Generates:** mapped UI state; reveal queue; speak requests
- **Writes / mutates:** frontend memory only; localStorage PM seen markers
- **Key point:** Receives GameState and beats, maps them, animates reveal, fetches late media.
- **IN:** `imageJobs` (SSE/refetch); `explain` (aside text); `beats` (story stream); `state` (GameState)
- **OUT:** `voice` (speak button)

<details><summary>JSON shape</summary>

```json
{
  "active": {
    "state": "mapped GameState",
    "beats": "mapped Beat[]",
    "revealQueue": "beat ids",
    "profile": "profile view"
  }
}
```
</details>

### Speech ownership rule — `speechAnswer`  ·  _shared_

Character dialogue beats come from character-agent calls. Narrator content is narration.

- **Reads / shared input:** narrator content; character [say]/[whisper] tags; stop sequences
- **Generates:** ownership boundary
- **Writes / mutates:** none
- **Key point:** Character dialogue beats come from character-agent calls. Narrator content is narration.
- **IN:** `narrator` (narration only); `charMara` (character speech); `charSentinel` (character speech)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "character_speaks": "_character_reply -> [say]/[whisper] -> dialogue beat",
  "narrator_speaks": "narrator content -> narration beat",
  "guard": "stop at present character name-colon"
}
```
</details>

## Edges (IN → OUT)

| from | to | kind | label |
|---|---|---|---|
| `input` | `interpreter` | agent | free text only |
| `interpreter` | `gates` | shared | segments |
| `input` | `gates` | shared | segments/direct |
| `state` | `gates` | persist | current scene + inventory |
| `gates` | `narrator` | agent | public action + attempts |
| `state` | `narrator` | persist | state block |
| `beats` | `narrator` | shared | recent + recap |
| `toolschemas` | `narrator` | tool | narrator tools |
| `narrator` | `dispatcher` | tool | tool_calls |
| `dispatcher` | `state` | persist | validated writes |
| `dispatcher` | `beats` | persist | receipts |
| `narrator` | `beats` | agent | narration beat |
| `narrator` | `resolve` | agent | state changed no prose |
| `resolve` | `beats` | agent | short narration |
| `dispatcher` | `charMara` | agent | cue/reaction |
| `dispatcher` | `charSentinel` | agent | reaction |
| `state` | `charMara` | persist | own row |
| `state` | `charSentinel` | persist | own row |
| `beats` | `charMara` | shared | witnessed beats |
| `beats` | `charSentinel` | shared | witnessed beats |
| `toolschemas` | `charMara` | tool | character tools |
| `charMara` | `beats` | agent | dialogue/action |
| `charSentinel` | `beats` | agent | dialogue/action |
| `charMara` | `dispatcher` | tool | character tool_calls |
| `gates` | `privateChar` | agent | whisper exchange |
| `dispatcher` | `privateChar` | agent | gift reply impulse |
| `privateChar` | `beats` | agent | private_with |
| `beats` | `summaryGame` | shared | old beats |
| `summaryGame` | `state` | persist | story_summary |
| `beats` | `summaryChar` | shared | witnessed old beats |
| `summaryChar` | `state` | persist | memory_summary |
| `creator` | `state` | persist | create rows |
| `creator` | `origin` | agent | thin origins |
| `origin` | `state` | persist | characters.origin |
| `state` | `artdir` | persist | world bible |
| `artdir` | `imageJobs` | enhancer | opening prompts |
| `state` | `imagePrompt` | persist | visual context |
| `beats` | `imagePrompt` | shared | recent public action |
| `narrator` | `imageJobs` | enhancer | show_image request |
| `gates` | `imageJobs` | enhancer | look/private look |
| `imagePrompt` | `imageJobs` | enhancer | prompt string |
| `imageJobs` | `state` | persist | media URLs |
| `imageJobs` | `apiui` | ui | SSE/refetch |
| `state` | `voice` | persist | identity fields |
| `voice` | `state` | persist | voice ids |
| `apiui` | `voice` | enhancer | speak button |
| `state` | `explain` | persist | visible facts only |
| `explain` | `apiui` | ui | aside text |
| `beats` | `apiui` | ui | story stream |
| `state` | `apiui` | ui | GameState |
| `narrator` | `speechAnswer` | shared | narration only |
| `charMara` | `speechAnswer` | shared | character speech |
| `charSentinel` | `speechAnswer` | shared | character speech |
