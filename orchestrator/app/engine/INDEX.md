# engine/ index

The turn loop, one module per concern. Callers import the PACKAGE (`from . import engine`) and call `engine.<fn>`; `__init__.py` re-exports everything, so you never need to know the module to CALL a function, only to CHANGE one. `run_turn` takes the open connection from main.py (one turn = one commit); the folds open their own.

| Module | Owns | Key functions |
|---|---|---|
| `parsing.py` | text hygiene + character-output parsing: everything that turns raw model text into clean displayable beats | `trim_to_sentence`, `clean_prose`, `parse_character_output`, `EMOTIONS` (the word -> renderable-tone map), `_extract_emotion`, `_scrub_narration`, `_reclassify_do`, `_unquote`, `_clean_segment`, the leak-scrubbing regexes |
| `folds.py` | background memory folds (scheduled after turns by main.py) | `maybe_update_summary` (the rolling game recap), `maybe_update_character_summaries` (per-character witnessed recaps) |
| `turn.py` | `run_turn` and its direct helpers: segment composing, deterministic adjudication pre-check, the narrator call, the bounded character cascade, the private channel, the freeform interpreter | `run_turn`, `interpret_action`, `_compose`, `_why_impossible`, `_character_reply`, `_image_pacing_ok`, `CONTINUE_IMPULSE`, `_SEGMENT_TYPES`, `_DEDUP_EXEMPT` |
| `live.py` | the live turn feed (display-plane only): per-game stop flag, phase/live_beat/live_text events over the SSE bus, the on_delta adapters for narrator and character calls | `begin_turn`, `request_stop`, `stop_event`, `publish_beat`, `publish_done`, `LiveNarration`, `LiveCharacter` |
| `streamscrub.py` | streaming-safe view over parsing.py's batch hygiene: re-scrub accumulated raw text per fragment, release only the stable prefix (hold-back for open think-spans/tags/fences/undecided lines); finalize is byte-identical to the batch pipeline | `ProseStream`, `CharacterStream` |

Conventions:
- Intra-package imports are module-style (`from . import parsing` then `parsing.clean_prose(...)`), same as repo/.
- Anything shown to the player or stored as memory passes through `parsing` first (prose scrub, emotion lift, sentence trim); never emit raw model text.
- main.py calls through the facade namespace (`engine.run_turn`), resolved at call time; keep it that way so tests can monkeypatch `engine.<fn>`.
