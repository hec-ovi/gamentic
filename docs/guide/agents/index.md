# Agents — agent-ready

Every distinct LLM call in Gamentic, plus the agentic tools that bridge to another agent. An *agent* = a purpose-built context one local model runs; `cue_character`/`spawn_character` are the bridges.

> Paired with the interactive chart: [`agents-atlas.html`](../../agents-atlas.html). This file mirrors it node-for-node; the chart is the same data drawn.
> **Read this first, then load ONLY the file the task needs.** Each file under `guide/` is deliberately fat and self-contained: opening one fully answers a class of question. Never bulk-read the folder.

**Lanes:** `turn agents` · `skill agents` · `creation agents` · `background folds` · `backend`

**Orientation.** One player turn: the **interpreter** structures free text → the **narrator** writes prose and proposes tools → `cue_character` runs each **character agent** (own witnessed context) → if tools changed state but no prose, **narrator-resolve** voices it. **Skills** (image-prompt, explain) load for one call. **Creation** agents build the world; **folds** compress memory in the background. With ANNA=true every one of these runs on the **Anna backend**.

## Nodes

### Narrator — `narrator`  ·  _turn_

The main per-turn agent: reads full world state + recap + lore + the player's composed action, writes second-person present-tense prose and drives all world-state change through the narrator toolset, cuing characters to speak rather than voicing them.

- **Reads / inputs:** prompts.build_narrator_messages (prompts.py:202): narrator.system.md + narrator.user.md; _state_block (prompts.py:59): scene, mood, present/elsewhere cast, inventory, exits, quests, goal, time, SECRETS (other chars' knowledge+origin), remembered facts; _situation_blocks (prompts.py:167): narrator.easy/hard/newplace/returning.md dispatched by state; narrator.looking.md when looking; _lore_block (prompts.py:157): repo.match_lore budgeted; _fit_token_budget (prompts.py:186): verbatim beat window trimmed to ~60% of effective_context_tokens; g['story_summary'] (EARLIER CHAPTERS recap), g['last_tool_errors'] (failed calls fed back once), narrator.attempts.md (numbered attack/give attempts), wish_block (fenced player wish)
- **Generates / outputs:** prose narration beat (emit narrator/Narrator/narration); tool calls from tools.narrator_tools(adjudicating, images); cues (queued character reactions), spawns, image_request, reject_attempt vetoes
- **Writes / mutates:** beats (narration); all game/scene/character/quest/item state via apply_tool; g.last_tool_errors (still-invalid calls), g.context_used (global meter), scene.description seed if unfurnished
- **Owned by (code):** engine/turn.py: run_turn (llm.chat at turn.py:477); prompts.py: build_narrator_messages; tools/__init__.py: narrator_tools, apply_tool
- **Key point:** Never voices a character: it must cue_character and stop. tool_choice='auto', NARRATOR_TEMPERATURE, scaffold + cast-name stop sequences, optional thinking.
- **IN:** `interpreter` (segments -> composed action); `annaBackend` (is the text provider for every agent)
- **OUT:** `characterPublic` (cue_character (agentic tool bridge)); `characterPublic` (spawn_character -> reaction enqueue); `narratorResolve` (dead-air -> resolve pass); `imagePromptWriter` (show_image / LOOK -> image prompt); `characterPrivate` (landed give -> forced private reply); `characterPrivate` (player whisper -> private exchange); `gameSummaryFold` (after turn -> fold old chapters)

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_narrator_messages(conn, gid, action, history_limit, lore_budget, attempts, looking, wish)",
  "messages": [
    {
      "role": "system",
      "content": "narrator.system.md rendered (persona, setting, tone, situation, world_rules, state, lore)"
    },
    {
      "role": "user",
      "content": "narrator.user.md (transcript, action, attempts_block, wish_block, summary_block, tool_errors_block)"
    }
  ],
  "tools": "NARRATOR_TOOLS [+reject_attempt if adjudicating] [+show_image if images]",
  "output": {
    "content": "prose",
    "tool_calls": [
      {
        "name": "cue_character|apply_damage|move_location|...",
        "arguments": {}
      }
    ],
    "finish_reason": "stop|length",
    "usage": {
      "prompt_tokens": 0
    }
  }
}
```
</details>

### Narrator-Resolve (dead-air killer) — `narratorResolve`  ·  _turn_

A short second narrator call fired ONLY when the first pass changed state via tools but wrote no prose (and nobody else will speak); it voices the mechanical outcome in one or two sentences so no turn is dead air.

- **Reads / inputs:** prompts.build_narrator_resolve_messages (prompts.py:276): narrator.resolve.md + narrator.resolve.user.md; _state_block (current state); narrator_action (the action) + state_notes list ('CHANGES': move/furnish/pickup receipts)
- **Generates / outputs:** one short narration beat only (no tools, no dialogue)
- **Writes / mutates:** beats (narration); g.context_used (max with main pass)
- **Owned by (code):** engine/turn.py: run_turn (llm.chat at turn.py:610, the else-branch when prose empty); prompts.py: build_narrator_resolve_messages
- **Key point:** Same voice and same stop sequences as the main pass; no tools list passed. Fires when (state_notes or not will_speak) and main prose was empty.
- **IN:** `narrator` (dead-air -> resolve pass)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_narrator_resolve_messages(conn, gid, action, changes)",
  "messages": [
    {
      "role": "system",
      "content": "narrator.resolve.md (persona, setting, tone, state)"
    },
    {
      "role": "user",
      "content": "narrator.resolve.user.md (action, changes)"
    }
  ],
  "tools": "none",
  "output": {
    "content": "1-2 sentence prose",
    "finish_reason": "stop|length"
  }
}
```
</details>

### Character Agent (public) — `characterPublic`  ·  _character_

Each present character runs as its own agent with its own context: only its persona, private knowledge, past, traits, felt-HP and the beats IT witnessed; it replies in [say]/[do]/[whisper] tags and can act on others via its own tools.

- **Reads / inputs:** prompts.build_character_messages (prompts.py:303): character.system.md + character.user.md; witnessed_beats_for_character (per-character verbatim window, not the room log); persona, knowledge_block, origin_block (its past), traits_block, felt_hp (words not numbers), present_block (who is here), memory_block (its own folded recap + pivotal moments); impulse line when directed (forced gift reply)
- **Generates / outputs:** [say]->dialogue bubble, [do]->action, [whisper]->private-to-player dialogue (parsed by parsing.parse_character_output_with_marks); reaction targets to enqueue; tool calls / inline memory marks
- **Writes / mutates:** beats (dialogue/action/system); character.context (per-character meter, set_character_context); own memory via share_past/mark_moment/admit_trait; attack/give_item on others
- **Owned by (code):** engine/turn.py: _character_reply (llm.chat at turn.py:187); prompts.py: build_character_messages; tools/__init__.py: CHARACTER_TOOLS, apply_tool(actor=ch)
- **Key point:** Voiced separately from the narrator; cued via cue_character. One retry if it returns nothing usable. CHARACTER_TEMPERATURE, CHAR_HISTORY_BEATS.
- **IN:** `narrator` (cue_character (agentic tool bridge)); `narrator` (spawn_character -> reaction enqueue); `characterPublic` (attack/give cascade reaction)
- **OUT:** `characterPublic` (attack/give cascade reaction); `charSummaryFold` (after turn -> fold witnessed beats)

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_character_messages(conn, gid, character, history_limit, impulse)",
  "messages": [
    {
      "role": "system",
      "content": "character.system.md (name, persona, gender_line, knowledge/origin/traits/state/present/example blocks)"
    },
    {
      "role": "user",
      "content": "character.user.md (location, scene transcript, memory_block, anchor, impulse_block)"
    }
  ],
  "tools": "CHARACTER_TOOLS [attack, give_item, share_past, mark_moment, admit_trait]",
  "output": {
    "content": "[say][whisper]...[/say][do]...[/do]",
    "tool_calls": [
      {
        "name": "attack|give_item|share_past|...",
        "arguments": {}
      }
    ]
  }
}
```
</details>

### Character Agent (private / whisper) — `characterPrivate`  ·  _character_

The same character agent run with private_with set, so its ENTIRE reply lands in a 1:1 thread no one else witnesses: the whisper channel and the forced gift reply. Built by the same builder; lifecycle and routing differ.

- **Reads / inputs:** prompts.build_character_messages (same builder) with private exchange beats marked (privately) in the witnessed window; impulse for the forced gift reply: 'The player just gave you <item>. React to the gift, just to them.'
- **Generates / outputs:** private dialogue/action beats bound to private_with (a stated-emotion-less private say is voiced as a whisper)
- **Writes / mutates:** beats (private_with=character id); character.context; own memory via share_past/mark_moment/admit_trait (whispers run NO narrator, so these self-tools are the only way confessions get recorded)
- **Owned by (code):** engine/turn.py: _character_reply(private_with=...) called at turn.py:657 (gift) and turn.py:717 (whisper exchange); engine/turn.py: run_turn private channel block (lines 661-717)
- **Key point:** Same agent, different lifecycle: triggered by player whisper segments or a landed give. Consecutive whispers to the same char form ONE exchange, char replies once.
- **IN:** `narrator` (landed give -> forced private reply); `narrator` (player whisper -> private exchange)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_character_messages(...) called with private_with at the engine, impulse for gifts",
  "messages": "same shape as characterPublic; user transcript includes (privately)-marked beats",
  "tools": "CHARACTER_TOOLS",
  "output": "[say]/[do]/[whisper] all routed private_with=cid"
}
```
</details>

### Input Interpreter — `interpreter`  ·  _skill_

One small tool-constrained call loaded only for this skill: parses a freeform typed action into ordered structured segments (say/do/attack/give/whisper/look) so typing freely gets the same directed routing and adjudication as the composer buttons.

- **Reads / inputs:** prompts.build_interpret_messages (prompts.py:579): interpret.system.md + interpret.user.md; present character names + player inventory (so names/items resolve)
- **Generates / outputs:** a submit_segments tool call -> validated list[dict] of segments (or None on any failure -> caller falls back to raw text)
- **Writes / mutates:** no DB state; its output drives _compose/run_turn
- **Owned by (code):** engine/turn.py: interpret_action (llm.chat at turn.py:248); prompts.py: build_interpret_messages, INTERPRET_TOOL
- **Key point:** Gated by settings.INTERPRET_FREE_TEXT. temperature 0.2, bounded to 6 segments, single forced submit_segments tool.
- **IN:** _none_
- **OUT:** `narrator` (segments -> composed action)

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_interpret_messages(conn, gid, message)",
  "messages": [
    {
      "role": "system",
      "content": "interpret.system.md"
    },
    {
      "role": "user",
      "content": "interpret.user.md (characters, inventory, message)"
    }
  ],
  "tools": "INTERPRET_TOOL [submit_segments]",
  "output": {
    "tool_calls": [
      {
        "name": "submit_segments",
        "arguments": {
          "segments": [
            {
              "type": "give",
              "item": "brass key",
              "target": "Mara"
            },
            {
              "type": "say",
              "text": "...",
              "target": "Mara"
            }
          ]
        }
      }
    ]
  }
}
```
</details>

### Image-Prompt Writer — `imagePromptWriter`  ·  _skill_

Optional agentic image-prompt writer: one LLM call that turns live scene context into a single FLUX.2-klein prompt (poses, the just-happened moment), then CODE hardens it (strips quoted lettering, clips length, appends no-text guard); any failure falls back to the deterministic template prompt.

- **Reads / inputs:** prompts.build_image_prompt_messages (prompts.py:595): imageprompt.system.md + imageprompt.user.md; _image_context (image_prompts.py:172): PLACE, time/mood, focus, present characters' gendered base, JUST HAPPENED recent public beats, STYLE
- **Generates / outputs:** one prose FLUX prompt (<80 words, subjects-first recipe), hardened by _harden_image_prompt
- **Writes / mutates:** no DB; returns the prompt string consumed by the media render job
- **Owned by (code):** integrate/image_prompts.py: _agentic_prompt (llm.chat at image_prompts.py:198); integrate/jobs.py: generate_view_snapshot (jobs.py:25; _agentic_prompt at jobs.py:56), generate_scene_image (jobs.py:255); prompts.py: build_image_prompt_messages
- **Key point:** Gated by settings.IMAGE_AGENTIC_PROMPTS. Fires for look/show_image renders and current-scene art; temperature 0.4, max_tokens 140. Triggered downstream of the narrator's show_image tool or a player LOOK.
- **IN:** `narrator` (show_image / LOOK -> image prompt); `artDirector` (direction overrides templates)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_image_prompt_messages(context)",
  "messages": [
    {
      "role": "system",
      "content": "imageprompt.system.md (FLUX recipe + worked example)"
    },
    {
      "role": "user",
      "content": "imageprompt.user.md (context)"
    }
  ],
  "tools": "none",
  "output": {
    "content": "Wide full-body shot of N people in ... plain unmarked surfaces, no signage."
  }
}
```
</details>

### Explain (tap-to-ask) — `explain`  ·  _skill_

Answers a player's tap on a thing (item/character/scene/quest/goal/beat) with a short spoiler-safe in-world explanation built ONLY from player-visible facts; returns None (no call) when nothing visible matches the tapped key.

- **Reads / inputs:** prompts.build_explain_messages (prompts.py:541): explain.system.md + explain.user.md; _explain_facts (prompts.py:472): only revealed items, public bios, known scene/quest/goal/beat state; never persona/knowledge/hidden items
- **Generates / outputs:** 2-3 sentence in-world explanation prose (returned to the FE, not stored as a beat)
- **Writes / mutates:** no DB state
- **Owned by (code):** main.py: explain endpoint (main.py:398, builds messages at :405); prompts.py: build_explain_messages, _explain_facts
- **Key point:** Spoiler-safe by construction: the facts builder is the gate; if facts is None the messages are None and no LLM call happens.
- **IN:** _none_
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_explain_messages(conn, gid, kind, key, beat_id) -> messages | None",
  "messages": [
    {
      "role": "system",
      "content": "explain.system.md"
    },
    {
      "role": "user",
      "content": "explain.user.md (kind, facts)"
    }
  ],
  "tools": "none",
  "output": {
    "content": "short in-world explanation"
  }
}
```
</details>

### Creator Chat — `creatorChat`  ·  _creation_

A warm story-architect agent that interviews the user across a persisted conversation to design the world, asking 1-2 questions per turn and emitting a [ready] marker (or prose equivalent) when the world is complete enough to forge.

- **Reads / inputs:** prompts.build_creator_messages (prompts.py:606): creator.system.md + full persisted history + new user message
- **Generates / outputs:** conversational reply (sanitized of think/tool debris), readiness signal; history is appended and persisted to creator_sessions
- **Writes / mutates:** creator_sessions.history (SQLite), with [ready] marker re-appended to the stored copy
- **Owned by (code):** creator.py: message (llm.chat at creator.py:77); prompts.py: build_creator_messages; creator.py: is_ready/strip_ready
- **Key point:** Free-form chat, no tools. temperature 0.8. Readiness parsed from RAW reply ([ready] mark or prose fallback) before clean_prose strips it.
- **IN:** _none_
- **OUT:** `finalizeExtractor` ([ready] -> finalize)

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_creator_messages(history, message)",
  "messages": [
    {
      "role": "system",
      "content": "creator.system.md"
    },
    "...history...",
    {
      "role": "user",
      "content": "<user message>"
    }
  ],
  "tools": "none",
  "output": {
    "content": "conversational reply (may end with [ready])"
  }
}
```
</details>

### Finalize Extractor — `finalizeExtractor`  ·  _creation_

Converts the whole creator conversation into one structured WorldSheet via a single forced save_world tool call (title, setting, cast with sex/origin/appearance, quests, lore, opening fiction), which repo.create_game persists to start the game.

- **Reads / inputs:** prompts.build_finalize_messages (prompts.py:613): finalize.system.md + finalize.user.md (full conversation flattened)
- **Generates / outputs:** one save_world tool call -> WorldSheet -> a new game id
- **Writes / mutates:** games + player_state + characters + scenes + quests + objectives + lore via repo.create_game; seeds player_items and start time via _seed_sheet_extras; deletes the creator session
- **Owned by (code):** creator.py: finalize (llm.chat at creator.py:122); prompts.py: build_finalize_messages, FINALIZE_TOOL; creator.py: _seed_sheet_extras
- **Key point:** tool_choice='auto', temperature 0.4, max_tokens 1200. No save_world call => ValueError, keep chatting.
- **IN:** `creatorChat` ([ready] -> finalize)
- **OUT:** `originEnrich` (creation -> enrich thin origins); `artDirector` (creation -> art direction)

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_finalize_messages(history)",
  "messages": [
    {
      "role": "system",
      "content": "finalize.system.md"
    },
    {
      "role": "user",
      "content": "finalize.user.md (convo flattened)"
    }
  ],
  "tools": "FINALIZE_TOOL [save_world]",
  "output": {
    "tool_calls": [
      {
        "name": "save_world",
        "arguments": {
          "title": "",
          "opening_scenario": "",
          "characters": [
            {
              "name": "",
              "persona": "",
              "sex": "female",
              "origin": "",
              "appearance": "",
              "disposition": "neutral"
            }
          ],
          "quests": [],
          "lore": []
        }
      }
    ]
  }
}
```
</details>

### Art Director — `artDirector`  ·  _creation_

ONE creation-time call that reads the whole world bible and writes the first-sight image prompts: each character's reference descriptor plus the main opening image, emitted as strict JSON so portraits and the opening render never depend on a thin per-render template.

- **Reads / inputs:** prompts.build_artdirector_messages (prompts.py:443): artdirector.system.md + artdirector.user.md; title, setting, tone, art_style, opening_scenario, start_location, time_of_day, full cast (name/gender/description/appearance)
- **Generates / outputs:** strict JSON {characters:[{name, descriptor}], main_image} -> hardened/clipped into a direction dict
- **Writes / mutates:** no DB directly; the returned direction feeds generate_images_for_game (character descriptors) and generate_scene_image (main-image override)
- **Owned by (code):** integrate/jobs.py: art_direction (llm.chat at jobs.py:169); prompts.py: build_artdirector_messages; integrate/jobs.py: generate_creation_art orchestrates the order
- **Key point:** Creation-only; temperature 0.4, max_tokens 700, no tools (parses fenced JSON). Any failure returns None and templates carry the renders.
- **IN:** `finalizeExtractor` (creation -> art direction)
- **OUT:** `imagePromptWriter` (direction overrides templates)

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_artdirector_messages(g, chars, time_of_day, start_location)",
  "messages": [
    {
      "role": "system",
      "content": "artdirector.system.md"
    },
    {
      "role": "user",
      "content": "artdirector.user.md (title, setting, tone, art_style, opening_scenario, start_location, time_of_day, cast)"
    }
  ],
  "tools": "none",
  "output": {
    "content": "{\"characters\": [{\"name\": \"...\", \"descriptor\": \"...\"}], \"main_image\": \"...\"}"
  }
}
```
</details>

### Origin Enrichment — `originEnrich`  ·  _creation_

Background per-character call (one LLM call each) that gives any character with a thin origin a real 5-8 sentence private biography; the finalize pass under-delivers on backstories, so a focused single-character pass is what the small model does well.

- **Reads / inputs:** prompts.build_origin_messages (prompts.py:420): origin.system.md + origin.user.md; setting, tone, character name/gender/persona/description/relation/knowledge/existing origin
- **Generates / outputs:** a 5-8 sentence third-person past-tense biography (cleaned, trimmed to a sentence on length cut)
- **Writes / mutates:** characters.origin via repo.set_character_origin (only ever upgrades, never downgrades)
- **Owned by (code):** creator.py: enrich_origins (llm.chat at creator.py:49); prompts.py: build_origin_messages; main.py: scheduled at every creation path (main.py:55, :115, :477)
- **Key point:** Runs only for chars whose origin is under ORIGIN_MIN_CHARS (220). temperature 0.7, max_tokens 400. Never blocks/fails creation.
- **IN:** `finalizeExtractor` (creation -> enrich thin origins)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_origin_messages(g, c)",
  "messages": [
    {
      "role": "system",
      "content": "origin.system.md"
    },
    {
      "role": "user",
      "content": "origin.user.md (setting, tone, name, gender, persona, description, relation, knowledge, origin)"
    }
  ],
  "tools": "none",
  "output": {
    "content": "5-8 sentence biography prose"
  }
}
```
</details>

### Game-Summary Fold — `gameSummaryFold`  ·  _fold_

Background fold: compresses story OLDER than the newest kept turns into a facts-only rolling recap (<400 words) so the narrator knows the whole story at bounded token cost; one LLM call per fold, stale-guarded.

- **Reads / inputs:** prompts.build_summary_messages (prompts.py:265): summary.system.md + summary.user.md; previous recap + the transcript of beats between summarized_through and target turn
- **Generates / outputs:** one updated facts-only recap (scrubbed of think/scaffold by scrub_model_text)
- **Writes / mutates:** games.story_summary + games.summarized_through via repo.set_story_summary (only if cursor hasn't moved)
- **Owned by (code):** engine/folds.py: maybe_update_summary (llm.chat at folds.py:31); prompts.py: build_summary_messages; main.py: scheduled after turns (main.py:293)
- **Key point:** Gated by SUMMARY_ENABLED; cadence effective_summary_every; KEEP_TURNS never folded. temperature 0.3. Output is re-fed to the narrator every turn, so leaks compound (full scrub).
- **IN:** `narrator` (after turn -> fold old chapters)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_summary_messages(prev_summary, transcript)",
  "messages": [
    {
      "role": "system",
      "content": "summary.system.md"
    },
    {
      "role": "user",
      "content": "summary.user.md (summary, transcript)"
    }
  ],
  "tools": "none",
  "output": {
    "content": "- fact\\n- fact (<400 words)"
  }
}
```
</details>

### Character-Summary Fold — `charSummaryFold`  ·  _fold_

Background fold (beside the game recap): folds what each ALIVE character WITNESSED into their private second-person recap (<150 words), built only from witnessed beats so another character's whispers can never enter; one LLM call per qualifying character.

- **Reads / inputs:** prompts.build_character_summary_messages (prompts.py:409): charsummary.system.md + charsummary.user.md; character name + prev memory_summary + witnessed_beats_between (their POV only)
- **Generates / outputs:** one updated second-person facts-only memory per folded character (scrubbed)
- **Writes / mutates:** characters.memory_summary + characters.summarized_through via repo.set_character_summary (stale-guarded)
- **Owned by (code):** engine/folds.py: maybe_update_character_summaries (llm.chat at folds.py:80); prompts.py: build_character_summary_messages; main.py: scheduled after turns (main.py:295)
- **Key point:** Gated by CHAR_SUMMARY_ENABLED; folds only when a character crossed CHAR_SUMMARY_EVERY witnessed beats (in practice story-central chars only). temperature 0.3.
- **IN:** `characterPublic` (after turn -> fold witnessed beats)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "builder": "build_character_summary_messages(name, prev_summary, transcript)",
  "messages": [
    {
      "role": "system",
      "content": "charsummary.system.md (name)"
    },
    {
      "role": "user",
      "content": "charsummary.user.md (name, summary, transcript)"
    }
  ],
  "tools": "none",
  "output": {
    "content": "- You remember ... (<150 words, second person to the character)"
  }
}
```
</details>

### ANNA Backend Agent — `annaBackend`  ·  _backend_

When ANNA=true the text backend itself IS an agent: the vendor Anna copilot CLI runs in its own container, and anna-api flattens every orchestrator chat stack into ONE copilot ask, wraps tools in a JSON contract, parses tool_calls back out, and applies stops/usage client-side, so every Gamentic agent above runs ON the Anna agent.

- **Reads / inputs:** anna-api main.py: POST /v1/chat/completions (messages + tools); wire.build_prompt: flatten_messages (labeled transcript) + tools_instruction (loose-args JSON contract from docs/anna/05-sampling-llm.md); agent.py AgentClient.ask -> POST {agent}/api/copilot/ask SSE; session minted from the Web-UI refresh token on the shared anna-data volume
- **Generates / outputs:** OpenAI chat.completion: {message:{content, tool_calls}, finish_reason, usage} via wire.parse_reply + wire.chat_response; 501 on /v1/images/* by default (game degrades text-only)
- **Writes / mutates:** no game DB; it is the text inference provider. Replaces llm.chat's endpoint via providers.resolve('text') -> ANNA_BASE_URL
- **Owned by (code):** infra/anna-api/app/main.py: chat_completions (:66); infra/anna-api/app/wire.py: build_prompt/parse_reply/apply_stops; infra/anna-api/app/agent.py: AgentClient.ask/_ask_once; docker-compose.yml: anna-agent + anna-api services (ANNA=true profile)
- **Key point:** Stateless ask per call (conversation_id=None); a reply that fails the {prose, tool_calls} contract degrades to prose-only, which the engine tolerates. orchestrator code is unchanged: resolve('text') just points at anna-api.
- **IN:** _none_
- **OUT:** `narrator` (is the text provider for every agent)

<details><summary>JSON shape</summary>

```json
{
  "in": {
    "messages": [],
    "tools": [],
    "stop": [],
    "model": "anna-copilot"
  },
  "copilotAsk": {
    "message": "<flattened transcript + [RESPONSE FORMAT] tools contract + [ASSISTANT]>",
    "conversation_id": null,
    "stream": true
  },
  "out": {
    "id": "chatcmpl-anna",
    "choices": [
      {
        "message": {
          "role": "assistant",
          "content": "prose",
          "tool_calls": [
            {
              "id": "call_0",
              "type": "function",
              "function": {
                "name": "",
                "arguments": "{}"
              }
            }
          ]
        },
        "finish_reason": "tool_calls|stop"
      }
    ],
    "usage": {
      "prompt_tokens": 0,
      "completion_tokens": 0,
      "total_tokens": 0
    }
  }
}
```
</details>

## Edges (IN → OUT)

| from | to | kind | label |
|---|---|---|---|
| `interpreter` | `narrator` | feed | segments -> composed action |
| `narrator` | `characterPublic` | cue | cue_character (agentic tool bridge) |
| `narrator` | `characterPublic` | trigger | spawn_character -> reaction enqueue |
| `characterPublic` | `characterPublic` | trigger | attack/give cascade reaction |
| `narrator` | `narratorResolve` | trigger | dead-air -> resolve pass |
| `narrator` | `imagePromptWriter` | trigger | show_image / LOOK -> image prompt |
| `narrator` | `characterPrivate` | trigger | landed give -> forced private reply |
| `narrator` | `characterPrivate` | cue | player whisper -> private exchange |
| `creatorChat` | `finalizeExtractor` | feed | [ready] -> finalize |
| `finalizeExtractor` | `originEnrich` | trigger | creation -> enrich thin origins |
| `finalizeExtractor` | `artDirector` | trigger | creation -> art direction |
| `artDirector` | `imagePromptWriter` | feed | direction overrides templates |
| `narrator` | `gameSummaryFold` | fold | after turn -> fold old chapters |
| `characterPublic` | `charSummaryFold` | fold | after turn -> fold witnessed beats |
| `annaBackend` | `narrator` | feed | is the text provider for every agent |
