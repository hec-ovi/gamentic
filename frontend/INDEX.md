# Frontend index

Resolver-style map of the UI layer: find the thing you want to change, go straight to the file that owns it. Vanilla ES modules, no build step; one in-memory state, one `render()` that rebuilds the DOM, event handlers that mutate state and re-render.

## The flow of one turn

Composer submit (`app.js`) -> `api.takeAction` (or `api.continueStory`) -> `adapters.mapGameState`/`mapBeats` -> `render.js` rebuilds the screen with new beats veiled -> `diffState` notices + flashes -> the staged reveal types them out (voice pipelined per beat) -> `watchLateBeats` polls `GET /beats?since=` for background images (look shots, item cards) for ~45s.

## Files

| Where | What lives there |
|---|---|
| `index.html` | Document shell, favicon, the CSS/JS entrypoints. Nothing else. |
| `styles.css` | The whole visual system: prose narration, dialogue bubbles, the deck, character columns, the profile screen, animations, scrollbars. |
| `src/app.js` | The controller: state, view routing, event wiring, the turn loop (action/continue/wish), the partial busy-lock, the staged reveal engine, art + late-beat polling, the character profile fetch, game settings PATCH, export/import, lightbox, toasts. Exports `init()` for tests. |
| `src/api.js` | `createApi(backendUrl)`: the thin orchestrator REST client. Every endpoint the UI calls, in one place. |
| `src/adapters.js` | Raw wire JSON -> the view model: `mapGameState`, `mapBeats`, `mapProfile`, `voiceForBeat`, `presentCharacters`. Media URLs stay relative. |
| `src/composer.js` | The tagged-segment composer helpers: entity chips, `buildSegment` (say/do/look x public/whisper), `serializeComposer`, `describeSegment`. |
| `src/transitions.js` | `diffState(prev, next)` + `buildNotices()`: the pure state-diff engine that makes every turn's changes legible. |
| `src/voice.js` | `Voice`: Maya1 TTS via `POST /voice/speak` only (never /voice/stream into an `<audio>`). `prepare()`/`playUrl()` split + a strict FIFO synth queue power the reveal pipeline. |
| `src/render.js` | Pure-ish HTML builders for every screen + the `HELP` copy map. |
| `src/icons.js` | The inline SVG icon set. |

## Feature resolver

| Feature | Lives in | Tested in |
|---|---|---|
| Library / delete / export choice / import | `render.js` (renderLibrary, renderGameCard, renderExportChoice), `app.js` (refreshLibrary, exportGame, importGameFile) | `test/play.component.test.js`, `test/render.test.js` |
| Story creator + session restore | `render.js` (renderCreator), `app.js` (creator fns, localStorage session) | `test/creator.component.test.js` |
| The integrated deck (scene, items, exits, vitals, goal, clock, meter) | `render.js` (renderPlayDeck, contextMeter) | `test/render.test.js` |
| Context meter format ("4.2k / 128k", tones) | `render.js` (contextMeter) | `test/render.test.js` |
| Character columns + light action row | `render.js` (renderCharColumn, castRow) | `test/render.test.js` |
| Full-screen character profile (tabs: status/traits/memory/whisper) | `render.js` (renderProfile, profileBody, the pane builders), `app.js` (openProfile, refreshProfile, profile-tab), `adapters.js` (mapProfile) | `test/render.test.js`, `test/play.component.test.js` |
| Whisper channel (in the profile; scroll pin; voice on replies) | `render.js` (renderWhisperChannel, renderPmBeat), `app.js` (executePrivate, followStory) | `test/play.component.test.js` |
| Composer: Do/Say/Look modes, chips, stacking | `render.js` (renderComposer), `composer.js`, `app.js` (executeComposer, setComposerMode) | `test/composer.test.js`, `test/interaction.test.js`, `test/play.component.test.js` |
| Look action (button, empty = whole scene, scene Look/Search rewire) | `app.js` (takeSceneAction, executeComposer), `composer.js` (buildSegment) | `test/play.component.test.js` |
| Continue + the wish line | `render.js` (renderActionBar), `app.js` (continueStory, captureWish) | `test/play.component.test.js` |
| Partial busy-lock (read-only stays live) | `app.js` (MUTATING_ACTS), `render.js` (per-control `disabled`) | `test/play.component.test.js`, `test/interaction.test.js` |
| Staged reveal (typewriter, veils, click to skip, voice pacing) | `app.js` (startReveal, revealBeat, typewrite) | `test/play.component.test.js` |
| Optimistic player echo (instant lines, swap on resolve) | `app.js` (echoBeats, resolveTurn) | `test/play.component.test.js` |
| Quote stripping on speech | `render.js` (stripWrappingQuotes) | `test/render.test.js` |
| Speak button states (loading/playing/idle) | `app.js` (speakBeat, applySpeakStates) | `test/play.component.test.js` |
| Scene-art anchoring (establishing narration, never "latest") | `render.js` (renderStory, sceneArtCard) | `test/render.test.js`, `test/play.component.test.js` |
| Late image beats (look shots, item unlock cards) | `app.js` (watchLateBeats), `render.js` (renderImageBeat, renderViewPending) | `test/play.component.test.js`, `test/render.test.js` |
| Item thumbnails + tap-to-inspect + /explain | `render.js` (slot builders, renderInspectModal), `app.js` (openInspect, doExplain) | `test/play.component.test.js` |
| Trait receipts (celebration tone) | `render.js` (systemTone "trait") | `test/render.test.js` |
| Transition notices + HUD flashes | `transitions.js`, `app.js` (applyTransitions) | `test/transitions.test.js` |
| Voice playback (speak-not-stream, FIFO, autoplay split) | `voice.js`, `app.js` (autoplayFor, reveal pipeline) | `test/voice.test.js`, `test/play.component.test.js` |
| Settings (audio split; per-game difficulty/voice) | `render.js` (renderSettings, renderGameSettings), `app.js` (updateSetting, patchGameSettings) | `test/render.test.js`, `test/play.component.test.js` |
| Lightbox + image retry | `app.js` (maybeOpenLightbox, retryFailedImage) | `test/play.component.test.js` |
| Backend wire calls | `api.js` | `test/api.test.js` |

## Tests

`npm test` (vitest, jsdom). Component tests mount the real `app.js` via `init()`, drive it with `@testing-library/user-event`, and intercept the orchestrator with MSW at the network layer (`test/setup.js` holds the default handlers, `test/fixtures.js` the wire-shaped builders).
