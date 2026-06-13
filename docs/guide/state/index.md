# State — agent-ready

The linear ingestion flow plus the persistent SQLite state it mutates. The model never owns state; SQLite does. One turn = one transaction, then a full state snapshot is projected to the API.

> Paired with the interactive chart: [`state-atlas.html`](../../state-atlas.html). This file mirrors it node-for-node; the chart is the same data drawn.
> **Read this first, then load ONLY the file the task needs.** Each file under `guide/` is deliberately fat and self-contained: opening one fully answers a class of question. Never bulk-read the folder.

**Lanes:** `linear ingestion` · `persistent state` · `history, folds, late media`

**Orientation.** Player input → interpreter → deterministic gates → narrator context → narrator LLM → tool dispatcher → SQLite (games, player_state, scenes, characters, quests, lore, beats). `player_state.location` selects the current scene; present cast is derived (alive + present + same location). Old beats fold into summaries; media jobs fill URLs later.

## Nodes

### Player input — `input`  ·  _ingest_

The player sends free text or composer-built segments. This is not state yet.

- **Lifecycle:** Ephemeral request payload.
- **Populated with:** ActionIn.action: freeform text; ActionIn.segments: say/do/look/attack/give/whisper; wish: hope channel, not an action
- **Modified by / where:** frontend/src/composer.js: buildSegment; frontend/src/app/turns.js: takeTurn; orchestrator/app/models.py: ActionIn
- **Read by:** Current UI state for chips, target names, inventory ids.
- **Key point:** Free text may be reinterpreted before the turn. Structured segments skip that LLM step.
- **IN:** _none_
- **OUT:** `interpret` (typed only); `gates` (segments)

<details><summary>JSON shape</summary>

```json
{
  "action": "string | null",
  "wish": "string | null",
  "segments": [
    {
      "type": "say | do | look | attack | give | whisper",
      "text": "string",
      "target": "character id/name | null",
      "item": "item id/name | null",
      "amount": "number | null",
      "mode": "say | do | look | null",
      "refs": [
        {
          "kind": "character | item",
          "id": "string",
          "name": "string"
        }
      ]
    }
  ]
}
```
</details>

### Interpreter — `interpret`  ·  _ingest_

A small one-call agent normalizes typed input into the same segment contract as the UI composer.

- **Lifecycle:** Optional and stateless.
- **Populated with:** submit_segments tool result; max 6 interpreted segments accepted by engine
- **Modified by / where:** orchestrator/app/engine/turn.py: interpret_action; orchestrator/app/prompts.py: build_interpret_messages
- **Read by:** player_state.inventory; present characters at player_state.location
- **Key point:** Failure falls back to raw text, so this does not block a turn.
- **IN:** `input` (typed only)
- **OUT:** `gates` (segments)

<details><summary>JSON shape</summary>

```json
{
  "tool": "submit_segments",
  "arguments": {
    "segments": [
      {
        "type": "say | do | attack | give | whisper | look",
        "text": "faithful short text",
        "target": "present character name when clear",
        "item": "inventory item when clear",
        "amount": "only if stated",
        "mode": "say | do"
      }
    ]
  }
}
```
</details>

### Deterministic gates — `gates`  ·  _ingest_

Plain code handles movement through known exits, impossible attempts, echo beats, and the automatic story-clock tick before narrator reasoning.

- **Lifecycle:** Runs every public turn.
- **Populated with:** player beat; system rejection beats; pending attack/give attempts; arrival_note on return
- **Modified by / where:** run_turn; _compose; _match_exit; _why_impossible; repo.advance_time
- **Read by:** player_state.location; scenes.exits; characters location/present/alive; player inventory
- **Key point:** This is where the engine prevents the model from narrating impossible handovers or attacks as successful.
- **IN:** `interpret` (segments); `input` (segments)
- **OUT:** `nctx` (public turn)

<details><summary>JSON shape</summary>

```json
{
  "turn_scratch": {
    "turn_index": "next beat turn",
    "action_text": "composed public action",
    "directed": [
      {
        "tool": "attack | give_item | _address",
        "args": {}
      }
    ],
    "pending_attempts": [
      {
        "family": "attack | give",
        "line": "for narrator",
        "handled": false,
        "rejected": false
      }
    ],
    "failures": [
      "friendly system beat text"
    ],
    "queue": [
      "character ids to react"
    ]
  }
}
```
</details>

### Narrator context — `nctx`  ·  _derived_

The narrator prompt is rebuilt from current state, recent beats, folded recap, lore, and situational protocol blocks.

- **Lifecycle:** Derived per narrator call; never stored.
- **Populated with:** GAME STATE block; STORY SO FAR; EARLIER CHAPTERS; tool error feedback; look/new-place/returning/attempt blocks
- **Modified by / where:** orchestrator/app/prompts.py: build_narrator_messages; _state_block; _situation_blocks
- **Read by:** games; player_state; characters; scenes; quests; lore; beats
- **Key point:** This is the main context-engineering seam.
- **IN:** `gates` (public turn); `beats` (recent + recap); `games` (global state); `scenes` (place state); `characters` (cast state); `quests` (progression); `lore` (matched facts)
- **OUT:** `narrator` (messages)

<details><summary>JSON shape</summary>

```json
{
  "messages": [
    {
      "role": "system",
      "content": "narrator.system + state + situational blocks + lore"
    },
    {
      "role": "user",
      "content": "summary + transcript + tool_errors + player action + attempts + wish"
    }
  ],
  "tools": [
    "NARRATOR_TOOLS",
    "reject_attempt when pending",
    "show_image when images on"
  ]
}
```
</details>

### Narrator LLM — `narrator`  ·  _boundary_

The narrator reasons about next state, writes prose, and proposes tool calls. It does not directly own state.

- **Lifecycle:** One call per public turn, plus a short resolve pass only if needed.
- **Populated with:** assistant content; OpenAI-style tool_calls; usage.prompt_tokens
- **Modified by / where:** orchestrator/app/llm.py: chat; orchestrator/prompts/narrator.system.md
- **Read by:** The prompt stack only.
- **Key point:** Tool calls are proposals until the dispatcher validates them.
- **IN:** `nctx` (messages)
- **OUT:** `tools` (tool_calls); `beats` (narration)

<details><summary>JSON shape</summary>

```json
{
  "content": "scrubbed into narration beat",
  "tool_calls": [
    {
      "name": "tool_name",
      "arguments": {}
    }
  ],
  "finish_reason": "stop | length | tool_calls",
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```
</details>

### Tool dispatcher — `tools`  ·  _ingest_

Every model mutation goes through a registered tool handler. Unknown or bad calls return invalid, not a crash.

- **Lifecycle:** Runs for narrator and character tool calls.
- **Populated with:** state receipts; cue targets; reactions queue; invalid reasons; image requests
- **Modified by / where:** orchestrator/app/tools/__init__.py: apply_tool; tools/* handlers
- **Read by:** Current DB rows for validation and normalization.
- **Key point:** This is the hard boundary between fiction and stored state.
- **IN:** `narrator` (tool_calls); `cascade` (character tools)
- **OUT:** `db` (validated writes); `beats` (receipts); `charctx` (cue_character)

<details><summary>JSON shape</summary>

```json
{
  "result": {
    "kind": "state | cue | memory | invalid | spawn | kill | reject | image",
    "text": "system receipt | image description | invalid reason | null",
    "cue": {
      "id": "character id",
      "name": "name",
      "reason": "why cued"
    },
    "reactions": [
      "character ids"
    ]
  }
}
```
</details>

### SQLite — `db`  ·  _persistent_

The model never owns state. SQLite does. One turn holds one transaction, then returns a full state snapshot.

- **Lifecycle:** Always present while the game exists.
- **Populated with:** games; player_state; characters; scenes; quests/objectives; lore; beats
- **Modified by / where:** orchestrator/app/db.py: get_conn; repo/*; tools/*
- **Read by:** all prompts; API state; background jobs; frontend via REST
- **Key point:** A turn can be slow because the transaction spans LLM calls.
- **IN:** `tools` (validated writes)
- **OUT:** `games` (table); `player` (table); `scenes` (table); `characters` (table); `quests` (table); `lore` (table); `beats` (table); `media` (state-grounded prompts); `api` (game_state())

<details><summary>JSON shape</summary>

```json
{
  "games": "global row",
  "player_state": "hero row",
  "characters": "cast rows",
  "scenes": "place rows",
  "quests": "quest rows + objective rows",
  "lore": "fact rows",
  "beats": "story log rows"
}
```
</details>

### games — `games`  ·  _persistent_

World identity, story FSM, clock, current goal, memory folds, settings, and context meter.

- **Lifecycle:** Created once by create_game; deleted with the adventure.
- **Populated with:** title/setting/tone/opening_scenario/art_style; status: active|won|lost; current_goal; time_minutes; story_summary; last_tool_errors; history/context/turn pacing dials
- **Modified by / where:** create_game; set_goal; set_game_status; advance_time; remember; maybe_update_summary; PATCH /settings; run_turn post checks
- **Read by:** narrator context; state API; image prompt style; clock labels
- **Key point:** Always there. It is not the world; it is the global control row.
- **IN:** `db` (table); `folds` (story_summary)
- **OUT:** `nctx` (global state)

<details><summary>JSON shape</summary>

```json
{
  "id": "gid",
  "title": "string",
  "setting": "string",
  "tone": "string",
  "narrator_persona": "string",
  "opening_scenario": "string",
  "art_style": "string",
  "status": "active | won | lost",
  "current_goal": "string",
  "time_minutes": 0,
  "arrival_note": "transient return note",
  "difficulty": "easy | normal | hard",
  "memory": "- durable fact",
  "story_summary": "folded older story",
  "summarized_through": 0,
  "context_used": 0,
  "last_tool_errors": [
    "fed back once"
  ],
  "history_beats": 0,
  "summary_every": 0,
  "context_tokens": 0,
  "turn_voices": 0,
  "turn_acts": 0
}
```
</details>

### player_state — `player`  ·  _persistent_

The hero row. Its location is the pointer that selects the current scene and present cast.

- **Lifecycle:** Created once by create_game.
- **Populated with:** life/max_life; points; location; inventory; flags
- **Modified by / where:** set_location; apply_damage/heal; award_points; add/remove/give/take_item; set_flag
- **Read by:** current_scene(); present_characters(); narrator state block; UI state
- **Key point:** Your intuition is correct: current stage is not a separate object. It is scenes[player_state.location].
- **IN:** `db` (table)
- **OUT:** `scenes` (location -> current scene); `characters` (location -> present cast)

<details><summary>JSON shape</summary>

```json
{
  "game_id": "gid",
  "life": 20,
  "max_life": 20,
  "points": 0,
  "location": "scene name key",
  "inventory": [
    {
      "id": "item id",
      "name": "item",
      "description": "string",
      "qty": 1,
      "image_url": "url | null"
    }
  ],
  "flags": {
    "flag_key": "value"
  }
}
```
</details>

### scenes — `scenes`  ·  _persistent_

All places that exist. Start scene is seeded; other scenes are created when movement first points to them.

- **Lifecycle:** Populated over play. Rows persist even after leaving.
- **Populated with:** name; description: empty means NEW PLACE; background; status; exits; items; left_at_minutes; draft; image_url
- **Modified by / where:** get_or_create_scene; move_location/set_location; describe_scene; set_scene_status; add_exit; place/reveal/take_item; note_scene; generate_scene_image
- **Read by:** narrator state block; movement router; image prompts; state API
- **Key point:** History feeds scenes through draft + left_at_minutes. Returning sets arrival_note so the narrator can make elapsed changes real.
- **IN:** `db` (table); `player` (location -> current scene); `media` (scene art)
- **OUT:** `nctx` (place state)

<details><summary>JSON shape</summary>

```json
{
  "id": "scene id",
  "game_id": "gid",
  "name": "location key",
  "description": "card text; empty means new place",
  "background": "deeper place context",
  "status": "calm | tense | dangerous",
  "exits": [
    {
      "id": "exit id",
      "label": "button label",
      "target": "scene name"
    }
  ],
  "items": [
    {
      "id": "item id",
      "name": "item",
      "description": "string",
      "hidden": false,
      "fixed": false,
      "image_url": "url | null"
    }
  ],
  "offers": [
    {
      "id": "offer id",
      "label": "action label"
    }
  ],
  "visited": 1,
  "left_at_minutes": "number | null",
  "draft": "open threads left here",
  "image_url": "url | null"
}
```
</details>

### characters — `characters`  ·  _persistent_

Each row is both a stateful character and the seed for a separate character agent context.

- **Lifecycle:** Created at world start or via spawn_character. Death sets alive=0; row remains.
- **Populated with:** persona/knowledge/origin; gender/appearance/voice/image identity; location/present/following/alive; life; disposition; relation; inventory; traits; moments; memory_summary; context_used
- **Modified by / where:** spawn_character; kill_character; set_following; set_disposition; set_relation; describe_character; note_trait; note_moment; reveal_origin; give_item; apply_damage/heal; character summary folds
- **Read by:** narrator state block; character prompts; present cast; profile endpoint; voice/image jobs
- **Key point:** Actual present characters are computed: alive + present + same location as player.
- **IN:** `db` (table); `player` (location -> present cast); `folds` (memory_summary); `media` (portraits/voice)
- **OUT:** `nctx` (cast state); `charctx` (persona + memory)

<details><summary>JSON shape</summary>

```json
{
  "id": "character id",
  "game_id": "gid",
  "name": "Mara",
  "persona": "agent system context",
  "knowledge": "private knowledge",
  "origin": "full private backstory",
  "origin_revealed": [
    {
      "id": "fact id",
      "text": "learned fact",
      "minutes": 0
    }
  ],
  "gender": "female | male | ''",
  "relation": "ally | rival | sister | ...",
  "disposition": "friendly | neutral | hostile | unknown",
  "location": "scene name",
  "present": 1,
  "following": 0,
  "alive": 1,
  "life": 10,
  "max_life": 10,
  "inventory": [
    {
      "id": "item id",
      "name": "item",
      "hidden": false
    }
  ],
  "traits": [
    {
      "id": "trait id",
      "text": "trait",
      "minutes": 0
    }
  ],
  "moments": [
    {
      "id": "moment id",
      "text": "pivotal event",
      "minutes": 0
    }
  ],
  "offers": [
    {
      "id": "offer id",
      "label": "button"
    }
  ],
  "memory_summary": "private folded witnessed memory",
  "summarized_through": 0,
  "context_used": 0,
  "voice_id": "provider voice id",
  "face_url": "url | null",
  "body_front_url": "url | null",
  "body_side_url": "url | null"
}
```
</details>

### quests + objectives — `quests`  ·  _persistent_

Active goals and objective checklists. The current goal also lives on games.current_goal.

- **Lifecycle:** Seeded at creation; can grow during play.
- **Populated with:** quest title/description/status; objective text/done/progress
- **Modified by / where:** start_quest; update_objective; complete_quest; fail_quest; set_goal
- **Read by:** narrator state block; state API; transition notices
- **Key point:** Quest state is explicit; prose alone does not complete objectives.
- **IN:** `db` (table)
- **OUT:** `nctx` (progression)

<details><summary>JSON shape</summary>

```json
{
  "quest": {
    "id": "quest id",
    "game_id": "gid",
    "title": "Quest",
    "description": "string",
    "status": "active | done | failed"
  },
  "objective": {
    "id": "objective id",
    "quest_id": "quest id",
    "text": "objective text",
    "done": 0,
    "progress": "string | null"
  }
}
```
</details>

### lore — `lore`  ·  _persistent_

World facts injected only when constant or keyword-matched against the current action/recent history.

- **Lifecycle:** Mostly creation-time static.
- **Populated with:** keys; content; constant; priority
- **Modified by / where:** create_game; transfer import
- **Read by:** match_lore -> narrator context
- **Key point:** Lore is context, not current world state. It informs the narrator but does not mutate by itself.
- **IN:** `db` (table)
- **OUT:** `nctx` (matched facts)

<details><summary>JSON shape</summary>

```json
{
  "id": "lore id",
  "game_id": "gid",
  "keys": [
    "keyword"
  ],
  "content": "world fact",
  "constant": 0,
  "priority": 0,
  "discovered": 0
}
```
</details>

### beats — `beats`  ·  _persistent_

The story log. It is also the source of narrator history, character witnessed memory, folds, private threads, and late image beats.

- **Lifecycle:** Append-only unless history is explicitly cleared.
- **Populated with:** turn_index/seq; speaker/kind/text; location; private_with; witnesses; emotion; image_url/audio_url
- **Modified by / where:** repo.add_beat from run_turn; creator opening beat; background image jobs
- **Read by:** recent_beats; witnessed_beats_for_character; summary folds; frontend story stream
- **Key point:** Privacy is stored here: private_with + witnesses decides who can remember what.
- **IN:** `db` (table); `tools` (receipts); `narrator` (narration); `cascade` (dialogue/action); `media` (image beats)
- **OUT:** `nctx` (recent + recap); `charctx` (witnessed window); `folds` (old history); `ui` (story stream)

<details><summary>JSON shape</summary>

```json
{
  "id": "beat id",
  "game_id": "gid",
  "turn_index": 1,
  "seq": 0,
  "speaker": "narrator | player | character_id | system",
  "speaker_name": "display name | null",
  "kind": "narration | dialogue | action | system | image",
  "text": "stored clean text or image caption",
  "location": "scene name",
  "private_with": "character id | null",
  "witnesses": [
    "character ids who perceived it"
  ],
  "emotion": "angry | whisper | ... | ''",
  "image_url": "url | null",
  "audio_url": "url | null"
}
```
</details>

### Character context — `charctx`  ·  _derived_

A character prompt is built from its persona, private knowledge, own memory summary, own moments/traits, and only beats it witnessed.

- **Lifecycle:** Derived per character call.
- **Populated with:** WHAT YOU REMEMBER; CURRENT SCENE transcript; YOUR STATE; present roster; trait anchor
- **Modified by / where:** build_character_messages; witnessed_beats_for_character
- **Read by:** characters; beats; player_state
- **Key point:** A late arrival cannot inherit earlier room talk because beats are witness-stamped.
- **IN:** `tools` (cue_character); `beats` (witnessed window); `characters` (persona + memory)
- **OUT:** `cascade` (messages)

<details><summary>JSON shape</summary>

```json
{
  "messages": [
    {
      "role": "system",
      "content": "character.system + persona + private knowledge + state"
    },
    {
      "role": "user",
      "content": "memory block + witnessed transcript + directed impulse"
    }
  ],
  "tools": [
    "attack",
    "give_item",
    "share_past",
    "mark_moment",
    "admit_trait"
  ]
}
```
</details>

### Character LLMs — `cascade`  ·  _boundary_

Cued characters speak/act with their own context. They can call attack, give_item, share_past, mark_moment, admit_trait.

- **Lifecycle:** Only when cued or privately addressed.
- **Populated with:** dialogue/action beats; character tool calls; private replies
- **Modified by / where:** _character_reply; parse_character_output_with_marks
- **Read by:** character context
- **Key point:** Whisper-only turns skip the narrator and go directly here.
- **IN:** `charctx` (messages)
- **OUT:** `tools` (character tools); `beats` (dialogue/action)

<details><summary>JSON shape</summary>

```json
{
  "raw_reply": "[say]...[/say][do]...[/do]",
  "parsed_segments": [
    {
      "kind": "say | do | whisper",
      "text": "clean display text",
      "emotion": "tone"
    }
  ],
  "tool_calls": [
    {
      "name": "attack | give_item | share_past | mark_moment | admit_trait",
      "arguments": {}
    }
  ],
  "emitted_beats": [
    "dialogue/action beats"
  ]
}
```
</details>

### Memory folds — `folds`  ·  _background_

Background summarizers compress older beats into games.story_summary and characters.memory_summary.

- **Lifecycle:** Async after turns, cadence-gated.
- **Populated with:** story_summary; character memory_summary; summarized_through cursors
- **Modified by / where:** maybe_update_summary; maybe_update_character_summaries
- **Read by:** beats; characters.alive
- **Key point:** This is the long-context solution: recent beats stay verbatim; older material becomes factual recap.
- **IN:** `beats` (old history)
- **OUT:** `games` (story_summary); `characters` (memory_summary)

<details><summary>JSON shape</summary>

```json
{
  "game_fold": {
    "source": "beats older than keep window",
    "writes": {
      "games": {
        "story_summary": "text",
        "summarized_through": 0
      }
    }
  },
  "character_fold": {
    "source": "witnessed beats only",
    "writes": {
      "characters": {
        "memory_summary": "text",
        "summarized_through": 0
      }
    }
  }
}
```
</details>

### Media jobs — `media`  ·  _background_

Slow image/voice work runs after the turn and fills URLs or appends image beats when ready.

- **Lifecycle:** Async and idempotent.
- **Populated with:** scene.image_url; character face/body URLs; item image_url; image beats
- **Modified by / where:** generate_scene_image; generate_view_snapshot; generate_directed_image; generate_item_image; assign_voices_for_game
- **Read by:** game style; current scene; present characters; recent beats
- **Key point:** Late results push SSE events; the frontend refetches state/beats.
- **IN:** `db` (state-grounded prompts)
- **OUT:** `scenes` (scene art); `characters` (portraits/voice); `beats` (image beats)

<details><summary>JSON shape</summary>

```json
{
  "event": {
    "kind": "scene | portrait | item | beat",
    "game_id": "gid"
  },
  "writes": {
    "scenes": {
      "image_url": "/media/gid/images/scene.png"
    },
    "characters": {
      "face_url": "/media/...",
      "body_front_url": "/media/..."
    },
    "beats": {
      "kind": "image",
      "image_url": "/media/...",
      "text": "caption"
    }
  }
}
```
</details>

### GameState API — `api`  ·  _derived_

Every response contains a full view model assembled from SQLite. It is not stored separately.

- **Lifecycle:** Derived on /state and turn responses.
- **Populated with:** current scene; visible items; present characters; available actions; meters; clock; quests
- **Modified by / where:** repo.game_state
- **Read by:** games; player_state; scenes; characters; quests
- **Key point:** Frontend truth is replaced from this after every turn.
- **IN:** `db` (game_state())
- **OUT:** `ui` (full replacement)

<details><summary>JSON shape</summary>

```json
{
  "turn_response": {
    "beats": [
      "Beat[] just created this turn"
    ],
    "state": "GameState"
  },
  "GameState": {
    "game_id": "gid",
    "title": "string",
    "status": "active | won | lost",
    "current_goal": "string",
    "scene": "SceneOut",
    "player": "PlayerStateOut",
    "characters": [
      "CharacterOut"
    ],
    "quests": [
      "QuestOut"
    ],
    "context": {
      "used": 0,
      "max": 131072
    },
    "settings": {
      "difficulty": "normal",
      "history_beats": 80,
      "context_tokens": 0
    },
    "time": {
      "minutes": 0,
      "day": 1,
      "hour": 8,
      "part": "morning",
      "label": "Day 1, morning"
    }
  }
}
```
</details>

### Frontend state — `ui`  ·  _ui_

The browser keeps active game view state: mapped backend state, beats, profile tab, reveal queue, pending media, local settings.

- **Lifecycle:** In-memory and reloadable from backend.
- **Populated with:** active.state; active.beats; generating; revealQueue; pendingView; profile; composer
- **Modified by / where:** frontend/src/app/turns.js: resolveTurn; mediastream.js; reveal.js
- **Read by:** GameState API; beats endpoint; SSE events
- **Key point:** It can animate and cache, but it does not decide game truth.
- **IN:** `api` (full replacement); `beats` (story stream)
- **OUT:** _none_

<details><summary>JSON shape</summary>

```json
{
  "active": {
    "id": "gid",
    "state": "mapped GameState",
    "beats": [
      "mapped Beat"
    ],
    "generating": false,
    "composer": {
      "mode": "do",
      "stack": []
    },
    "profile": {
      "charId": "id",
      "tab": "whisper",
      "data": "profile | null"
    },
    "revealQueue": [
      "beat ids"
    ],
    "pendingView": false,
    "lastTurnIndex": 0
  }
}
```
</details>

## Edges (IN → OUT)

| from | to | kind | label |
|---|---|---|---|
| `input` | `interpret` | flow | typed only |
| `interpret` | `gates` | flow | segments |
| `input` | `gates` | flow | segments |
| `gates` | `nctx` | flow | public turn |
| `nctx` | `narrator` | flow | messages |
| `narrator` | `tools` | flow | tool_calls |
| `tools` | `db` | write | validated writes |
| `db` | `games` | read | table |
| `db` | `player` | read | table |
| `db` | `scenes` | read | table |
| `db` | `characters` | read | table |
| `db` | `quests` | read | table |
| `db` | `lore` | read | table |
| `db` | `beats` | read | table |
| `player` | `scenes` | derive | location -> current scene |
| `player` | `characters` | derive | location -> present cast |
| `beats` | `nctx` | read | recent + recap |
| `games` | `nctx` | read | global state |
| `scenes` | `nctx` | read | place state |
| `characters` | `nctx` | read | cast state |
| `quests` | `nctx` | read | progression |
| `lore` | `nctx` | read | matched facts |
| `tools` | `beats` | write | receipts |
| `narrator` | `beats` | write | narration |
| `tools` | `charctx` | flow | cue_character |
| `beats` | `charctx` | read | witnessed window |
| `characters` | `charctx` | read | persona + memory |
| `charctx` | `cascade` | flow | messages |
| `cascade` | `tools` | flow | character tools |
| `cascade` | `beats` | write | dialogue/action |
| `beats` | `folds` | read | old history |
| `folds` | `games` | write | story_summary |
| `folds` | `characters` | write | memory_summary |
| `db` | `media` | read | state-grounded prompts |
| `media` | `scenes` | write | scene art |
| `media` | `characters` | write | portraits/voice |
| `media` | `beats` | write | image beats |
| `db` | `api` | derive | game_state() |
| `api` | `ui` | flow | full replacement |
| `beats` | `ui` | flow | story stream |
