# Orchestrator index

Resolver-style map of the game brain: find what you want to change, go straight to where it lives. Each file has one job.

## The flow of one turn

`POST /games/{id}/action` (main.py) -> interpreter structures free text (engine.interpret_action) -> `engine.run_turn` does everything -> background art is scheduled (main.py) -> one resolved turn returns.

## Files

| Where | What lives there |
|---|---|
| `app/main.py` | The REST surface. Every route, request gating, background-task scheduling. Nothing else. |
| `app/engine.py` | The turn loop: player beats, deterministic adjudication of attempts, the narrator call, the character cascade (bounded), whispers, the context meter, prose scrubbing, the new-item diff. |
| `app/tools.py` | The model's ONLY way to change state: tool schemas (narrator + character sets) and the validated dispatcher `apply_tool`. A tool the schema does not describe does not exist. |
| `app/prompts.py` | Message assembly for every agent (narrator, characters, interpreter, explainer, image-prompt writer, creator). Computes the state block and decides WHICH protocol blocks inject this turn. |
| `prompts/*.md` | The actual prose of every prompt, editable without touching code (reloaded per call). See the dispatch table below. |
| `app/repo.py` | All SQL. State reads/writes, scenes, items, traits, beats, the assembled `game_state`, the character profile. |
| `app/db.py` | Schema, migrations, WAL connection settings. |
| `app/models.py` | Pydantic request/response shapes (the wire contract). |
| `app/integrate.py` | Glue to the media services: image prompt composition (gender net, no-text guard, identity references), voice assignment, all background generation jobs. |
| `app/media.py` | Thin HTTP clients for image-api and voice-api. |
| `app/transfer.py` | Export/import: adventure templates and checkpoint saves, id remapping, media scrubbing. |
| `app/creator.py` | The story-creator chat sessions (persisted in SQLite) and world finalization. |
| `app/llm.py` | The one llama.cpp client function, `chat()`. |
| `app/config.py` | Every knob, env-overridable, with defaults. |
| `app/constants.py` | The finite vocabularies (dispositions, moods, difficulties) the tools enforce. |
| `tests/` | Deterministic suite (FakeLLM at the `llm.chat` boundary, real routes + real SQLite). One file per feature area. |

## Prompt dispatch (the resolver)

The narrator core stays lean; protocol blocks inject ONLY when state triggers them:

| Block | Injected when |
|---|---|
| `narrator.system.md` | always (the lean core + worked example) |
| `narrator.easy.md` / `narrator.hard.md` | game difficulty is easy / hard (normal injects nothing) |
| `narrator.newplace.md` | the current scene has no description yet (furnish protocol) |
| `narrator.returning.md` | the player just returned somewhere they left (draft + elapsed time) |
| `narrator.looking.md` | the turn contains a look action (describe, discover, show_image) |
| `narrator.attempts.md` | mechanical attempts (attack/give) await adjudication |
| `narrator.resolve.md` | second pass when tools fired but no prose came back (no dead air) |
| `character.system.md` | every character agent call (persona + unlocked traits + private knowledge) |
| `interpret.system.md` | the one-call skill that structures freeform typed actions |
| `imageprompt.system.md` | the one-call skill that writes agentic image prompts |
| `explain.system.md` | the one-call skill behind tap-to-explain |
| `creator.system.md` / `finalize.system.md` | world-builder chat / world sheet extraction |

Skills (interpreter, image prompt, explain) load only for their single call and never persist in any story context.
