# Gamentic guide — RESOLVER

Resolver-style map of the whole project for an agent. **Read this first, then load ONLY the file the task needs.** Each file under `guide/` is deliberately fat and self-contained: opening one fully answers a class of question. Never bulk-read the folder.

Each section below is the **agent-ready twin** of a view in the single-page docs site (the same data, written vs. drawn). Open the view to *see* the system; open the `index.md` to *load* it.


| Section | Load when the task involves | One-liner | View |
|---|---|---|---|
| [`agents/`](agents/index.md) | who writes/decides what, narrator vs character, skills, folds, cueing | every LLM agent + the agentic-tool bridges | [open](../index.html#agents) |
| [`engine/`](engine/index.md) | the turn pipeline, REST/SSE wiring, provider resolution | engine ↔ frontend ↔ backend services | [open](../index.html#engine) |
| [`state/`](state/index.md) | what is stored, lifecycle, what mutates a table | ingestion flow + persistent SQLite state | [open](../index.html#state) |
| [`state-json/`](state-json/index.md) | exact field names / JSON shapes | the full-state JSON reference | [open](../index.html#statejson) |
| [`context/`](context/index.md) | which LLM context reads what, speech ownership | every distinct LLM context + enhancer path | [open](../index.html#context) |
| [`folders/`](folders/index.md) | where a piece of code lives | the repo tree, one job per file | [open](../index.html#folders) |

**Load discipline.** A "who speaks" question needs `agents/` only. A wiring/timeout question needs `engine/` only. A "what column holds X" question needs `state/` (+`state-json/` for the exact shape). A deploy/port question needs `infra/` only. Never load all seven; that's the point of this layout.


<sub>Convention: a hand-written resolver dispatching to fat, self-contained, git-tracked markdown an agent reads on demand — the same idea as Garry Tan's gbrain ("agent brain in markdown"), expressed in this repo's house style.</sub>
