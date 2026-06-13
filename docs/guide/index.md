# Gamentic guide — RESOLVER

Resolver-style map of the whole project for an agent. **Read this first, then load ONLY the file the task needs.** Each file under `guide/` is deliberately fat and self-contained: opening one fully answers a class of question. Never bulk-read the folder.

Each section below is the **agent-ready twin** of a view in the single-page docs site (the same data, written vs. drawn). Open the view to *see* the system; open the `index.md` to *load* it.

**The whole project in one line.** A self-hosted AI dungeon RPG: one local LLM plays every role through purpose-built contexts (agents); whatever it wants to change the world must pass a validated tool into SQLite (the single source of truth); a FastAPI brain resolves one turn per request and pushes late media over SSE; the frontend is a no-build vanilla SPA; image and voice are optional local services; one `ANNA` boolean swaps the whole text backend to a cloud agent.

| Section | Load when the task involves | One-liner | View |
|---|---|---|---|
| [`agents/`](agents/index.md) | who writes/decides what, narrator vs character, skills, folds, cueing | every LLM agent + the agentic-tool bridges | [open](../index.html#agents) |
| [`engine/`](engine/index.md) | the turn pipeline, REST/SSE wiring, provider resolution | engine ↔ frontend ↔ backend services | [open](../index.html#engine) |
| [`state/`](state/index.md) | what is stored, lifecycle, what mutates a table | ingestion flow + persistent SQLite state | [open](../index.html#state) |
| [`state-json/`](state-json/index.md) | exact field names / JSON shapes | the full-state JSON reference | [open](../index.html#statejson) |
| [`context/`](context/index.md) | which LLM context reads what, speech ownership | every distinct LLM context + enhancer path | [open](../index.html#context) |
| [`infra/`](infra/index.md) | docker, ports, volumes, profiles, ANNA mode | the 9-service compose stack | [open](../index.html#infra) |
| [`folders/`](folders/index.md) | where a piece of code lives | the repo tree, one job per file | [open](../index.html#folders) |

**Load discipline.** A "who speaks" question needs `agents/` only. A wiring/timeout question needs `engine/` only. A "what column holds X" question needs `state/` (+`state-json/` for the exact shape). A deploy/port question needs `infra/` only. Never load all seven; that's the point of this layout.

**In-repo authority.** These twins summarize the live code maps: `orchestrator/INDEX.md` (+ `app/{engine,tools,repo,integrate,providers}/INDEX.md`), `frontend/INDEX.md`, and `docs/anna/RESOLVER.md`. When code and a twin disagree, the code (and those INDEX maps) win.

<sub>Convention: a hand-written resolver dispatching to fat, self-contained, git-tracked markdown an agent reads on demand — the same idea as Garry Tan's gbrain ("agent brain in markdown"), expressed in this repo's house style.</sub>
