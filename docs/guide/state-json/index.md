# State JSON reference — agent-ready

The authoritative JSON shapes for the DB state, the API projection, the turn runtime and the frontend copy. Field names are grounded in `db.py`, `models.py`, `repo/state.py`, `repo/*`, `tools/*`, and `frontend/src/adapters.js`; values are illustrative.

> Paired with the interactive view: [`state-json` in the docs site](../index.html#statejson). For the lifecycle of each shape (who writes it, who reads it) see [`../state/`](../state/index.md).
> **Read this first, then load ONLY the file the task needs.** Each file under `guide/` is deliberately fat and self-contained: opening one fully answers a class of question. Never bulk-read the folder.

## Shapes

### `db` — SQLite (source of truth)

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

### `games` — games (1 row, always)

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

### `player` — player_state (1 row, always)

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

### `scenes` — scenes (0..N, lazy)

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

### `characters` — characters (seed + spawn)

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

### `quests` — quests + objectives (progression)

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

### `lore` — lore (matched facts)

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

### `beats` — beats (append-only log)

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

### `charctx` — Character context (witnessed POV)

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

### `cascade` — Character LLMs (bounded cascade)

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

### `folds` — Memory folds (old beats -> summaries)

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

### `media` — Media jobs (late image/voice)

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

### `api` — GameState API (projection)

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

### `ui` — Frontend state (presentation only)

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
