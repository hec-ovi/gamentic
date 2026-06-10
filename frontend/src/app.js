// Gamentic frontend controller.
//
// One in-memory `state`, one render() that rebuilds the DOM, and event handlers
// that mutate state + re-render. No mock games, no streaming machinery: the
// real backend is sequential (one POST /action -> { beats, state }).

import { createApi } from "./api.js";
import { mapGameState, mapBeats, voiceForBeat, presentCharacters } from "./adapters.js";
import { diffState, buildNotices } from "./transitions.js";
import { Voice } from "./voice.js";
import { renderApp, HELP, escapeHtml } from "./render.js";
import { serializeComposer, insertChip, clearComposer, buildSegment } from "./composer.js";
import { icon } from "./icons.js";

const STORAGE_KEY = "gamentic.v2";
let root = null;

const state = {
  view: "menu", // menu | library | creator | play | settings
  games: [], // raw library entries from GET /games
  backendOnline: false,
  backendError: "",
  active: null, // { id, state(mapped), beats(mapped), generating, composer, privateChat, give, revealedArt }
  creator: { sessionId: "creator-" + rand(), messages: [], busy: false, error: "" },
  confirm: null, // { gameId, title } when a delete confirmation is open
  settings: loadSettings(),
};

const voice = new Voice();
voice.applySettings(state.settings);
let api = createApi(state.settings.backendUrl);
let pollTimer = null;
// document-level dismiss listeners for the transient popovers (tracked so a
// stale one can never close the next popover)
let seeDismiss = null;
let taggerDismiss = null;

// ---------------------------------------------------------------------------
// boot. Exported so tests can mount the app against a fresh DOM + mocked network
// (vi.resetModules() between tests gives each one its own module state).
// ---------------------------------------------------------------------------

export function init(opts = {}) {
  root = opts.root || document.querySelector("#app");
  if (!root) return null;
  // Generated media can 404/truncate for a beat right after generation (the
  // file is still being persisted). Retry failed game images a few times with
  // backoff instead of leaving a dead slot. error events don't bubble -> capture.
  root.addEventListener("error", retryFailedImage, true);
  // Lightbox: any game image opens full size (stored files are larger than
  // their slots). Capture phase so it also works inside modal wrappers; images
  // inside action buttons (item slots) keep their own click meaning.
  root.addEventListener("click", maybeOpenLightbox, true);
  resetCreator();
  render();
  refreshLibrary();
  return { state, voice };
}

// ---------------------------------------------------------------------------
// image lightbox: click any game image -> full-size viewer overlay
// ---------------------------------------------------------------------------

function maybeOpenLightbox(e) {
  const img = e.target;
  if (!img || img.tagName !== "IMG") return;
  if (img.closest("button")) return; // item-slot buttons keep their own click
  const src = img.getAttribute("src") || "";
  if (!src.startsWith("/")) return; // only our same-origin game media
  e.preventDefault();
  e.stopPropagation();
  openLightbox(src, img.getAttribute("alt") || "");
}

function openLightbox(src, alt) {
  closeLightbox();
  const ov = document.createElement("div");
  ov.className = "lightbox-overlay";
  ov.setAttribute("role", "dialog");
  ov.setAttribute("aria-modal", "true");
  ov.setAttribute("aria-label", alt || "Image viewer");
  const img = document.createElement("img");
  img.src = src;
  img.alt = alt;
  ov.appendChild(img);
  ov.addEventListener("click", closeLightbox); // click anywhere closes
  document.body.appendChild(ov);
  document.addEventListener("keydown", lightboxKey);
}

function lightboxKey(e) {
  if (e.key === "Escape") closeLightbox();
}

function closeLightbox() {
  document.querySelectorAll(".lightbox-overlay").forEach((o) => o.remove());
  document.removeEventListener("keydown", lightboxKey);
}

function retryFailedImage(e) {
  const img = e.target;
  if (!img || img.tagName !== "IMG") return;
  const src = img.getAttribute("src") || "";
  if (!src.startsWith("/")) return; // only our same-origin game media
  const tries = Number(img.dataset.retry || 0);
  if (tries >= 3) return;
  img.dataset.retry = String(tries + 1);
  const base = src.replace(/[?&]r=\d+$/, "");
  setTimeout(() => {
    if (!img.isConnected) return;
    img.src = `${base}${base.includes("?") ? "&" : "?"}r=${tries + 1}`;
  }, 700 * (tries + 1));
}

if (typeof document !== "undefined" && document.querySelector("#app")) {
  init();
}

function loadSettings() {
  const defaults = {
    // Backend origin is automatic: same host as the page, orchestrator port 8000.
    // Works for local dev and the Docker deployment (orchestrator mapped to host :8000).
    // Not user-editable; no longer surfaced in Settings. A hidden ?api= query
    // override exists for dev/testing (e.g. pointing at a mock backend).
    backendUrl:
      new URLSearchParams(location.search).get("api") ||
      `${location.protocol}//${location.hostname || "localhost"}:8000`,
    voiceEnabled: true,
    autoplayVoice: false,
    masterVolume: 0.7,
    speakerVolumes: {},
  };
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    // backendUrl is always the automatic value, never a stale persisted one.
    return { ...defaults, ...(saved || {}), backendUrl: defaults.backendUrl };
  } catch {
    return defaults;
  }
}

function saveSettings() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.settings));
  } catch {
    /* ignore quota */
  }
}

// ---------------------------------------------------------------------------
// render + event binding
// ---------------------------------------------------------------------------

function render() {
  closeTagger();
  closeSeePopover();
  // chat scroll rule: keep the reader's place across rebuilds; pin to the
  // bottom only when they were already reading at the bottom.
  const story = root.querySelector("#storyStream");
  const stick = !story || storyNearBottom(story);
  const prevTop = story ? story.scrollTop : 0;
  root.dataset.view = state.view;
  root.innerHTML = renderApp(state);
  bind();
  if (state.view === "play") {
    const fresh = root.querySelector("#storyStream");
    if (fresh) {
      if (stick) scrollStory();
      else fresh.scrollTop = prevTop;
    }
    if (state.active && state.active.privateChat) scrollToBottom("#pmThread");
    markArtReveals(state.active);
  }
  if (state.view === "creator") scrollCreator();
}

function storyNearBottom(el) {
  return el.scrollHeight - el.scrollTop - el.clientHeight < 140;
}

function bind() {
  root.querySelectorAll("[data-act]").forEach((el) => {
    el.addEventListener("click", (e) => {
      // "noop" wrappers (modal bodies over a clickable backdrop) must only stop
      // the bubble - preventDefault here would cancel form submits bubbling up
      // from buttons inside the modal.
      if (el.dataset.act === "noop") {
        e.stopPropagation();
        return;
      }
      e.preventDefault();
      e.stopPropagation(); // keep nested data-act (e.g. modal buttons over a backdrop) from double-firing
      onAction(el.dataset.act, el);
    });
  });

  root.querySelector('[data-form="action"]')?.addEventListener("submit", (e) => {
    e.preventDefault();
    executeComposer();
  });
  root.querySelector('[data-form="private"]')?.addEventListener("submit", (e) => {
    e.preventDefault();
    executePrivate();
  });
  // Enter in a composer line = submit its form (the contenteditable line is
  // single-line; newlines have no meaning in a segment)
  root.querySelectorAll(".composer-input").forEach((el) => {
    el.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      const form = el.closest("form");
      if (!form) return;
      if (typeof form.requestSubmit === "function") form.requestSubmit();
      else form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
  });
  // a click on the story instant-finishes the staged reveal
  root.querySelector("#storyStream")?.addEventListener("click", () => {
    const g = state.active;
    if (g && g.revealing) g.skipReveal = true;
  });
  root.querySelector('[data-form="creator"]')?.addEventListener("submit", (e) => {
    e.preventDefault();
    const input = e.currentTarget.querySelector('[name="creatorText"]');
    sendCreatorMessage(input.value);
    input.value = "";
  });

  root.querySelectorAll("[data-setting]").forEach((el) => {
    const evt = el.type === "range" ? "input" : "change";
    el.addEventListener(evt, () => updateSetting(el));
  });

  root.querySelectorAll("[data-help]").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      showHelp(el);
    });
  });
}

function onAction(act, el) {
  const gameId = el.dataset.gameId;
  // busy-lock: one POST = one fully resolved turn; while it is in flight, block
  // EVERY interaction (buttons are also rendered disabled - this guard covers
  // anything left clickable, e.g. modal backdrops).
  if (state.active && state.active.generating && state.view === "play" && act !== "noop") return;
  switch (act) {
    case "new-game":
      enterCreator();
      break;
    case "go-menu":
      stopPolling();
      state.view = "menu";
      render();
      refreshLibrary();
      break;
    case "go-library":
      stopPolling();
      state.view = "library";
      render();
      refreshLibrary();
      break;
    case "retry-library":
      refreshLibrary();
      break;
    case "continue-game":
      openGame(gameId);
      break;
    case "ask-delete":
      state.confirm = { gameId, title: el.dataset.gameTitle || "this adventure" };
      render();
      break;
    case "cancel-delete":
      state.confirm = null;
      render();
      break;
    case "confirm-delete":
      removeGame(gameId);
      break;
    case "noop":
      break;
    case "open-settings":
      state.settings._return = state.view;
      state.view = "settings";
      render();
      break;
    case "close-settings":
    case "go-back":
      state.view = state.settings._return || "library";
      render();
      break;
    case "begin-adventure":
      beginAdventure();
      break;
    case "speak-beat":
      speakBeat(el.dataset.beatId);
      break;
    case "see-scene":
      openSeePopover(el);
      break;
    case "creator-restart":
      clearCreatorSession();
      resetCreator();
      render();
      break;
    // --- play: scene / character action buttons -> tagged segments ---
    case "scene-action":
      takeTurn([{ type: "do", text: el.dataset.label }]);
      break;
    case "exit":
      takeTurn([{ type: "do", text: "go to " + (el.dataset.label || "") }]);
      break;
    case "take-item":
      if (state.active) state.active.inspect = null; // acting closes the modal
      takeTurn([{ type: "do", text: "take the " + (el.dataset.itemName || "item") }]);
      break;
    case "examine-item":
      if (state.active) state.active.inspect = null;
      takeTurn([{ type: "do", text: "examine the " + (el.dataset.itemName || "item") }]);
      break;
    // --- tap-to-inspect: the detail modal + "ask what this is" ---
    case "inspect-item":
      openInspect({ kind: "item", key: el.dataset.itemId || el.dataset.itemName });
      break;
    case "inspect-char":
      openInspect({ kind: "character", key: el.dataset.charId });
      break;
    case "inspect-goal":
      openInspect({ kind: "goal", key: (state.active && state.active.state.currentGoal) || "goal" });
      break;
    case "inspect-quest":
      openInspect({ kind: "quest", key: el.dataset.questId });
      break;
    case "inspect-beat":
      openInspect({ kind: "beat", beatId: el.dataset.beatId });
      break;
    case "close-inspect":
      if (state.active) state.active.inspect = null;
      render();
      break;
    case "inspect-ask":
      doExplain();
      break;
    case "char-action":
      onCharAction(el);
      break;
    case "open-private":
      openPrivate(el.dataset.charId, el.dataset.charName, el.dataset.channel || "whisper");
      break;
    case "close-private":
      if (state.active) state.active.privateChat = null;
      render();
      break;
    case "pm-channel":
      switchPmChannel(el.dataset.channel);
      break;
    case "cmp-mode":
      setComposerMode(state.active && state.active.composer, "cmp", el.dataset.mode);
      break;
    case "pm-mode":
      setComposerMode(state.active && state.active.privateChat, "pm", el.dataset.mode);
      break;
    case "cmp-stack":
      stackSegment("cmp");
      break;
    case "pm-stack":
      stackSegment("pm");
      break;
    case "cmp-unstack":
      unstackSegment(state.active && state.active.composer, el.dataset.index);
      break;
    case "pm-unstack":
      unstackSegment(state.active && state.active.privateChat, el.dataset.index);
      break;
    case "open-tagger":
      openTagger(el);
      break;
    case "pick-give":
      doGive(el.dataset.item, el.dataset.target);
      break;
    case "cancel-give":
      if (state.active) state.active.give = null;
      render();
      break;
    default:
      break;
  }
}

// Map a character action button (its `type`) to the right segment / panel.
function onCharAction(el) {
  const g = state.active;
  if (!g) return;
  const { type, charId, charName, label } = el.dataset;
  switch (type) {
    case "talk":
    case "trade": // trade view is not built yet; treat as the talk modal for now
      openPrivate(charId, charName, "talk");
      break;
    case "attack":
      takeTurn([{ type: "attack", target: charId || charName }]);
      break;
    case "give":
      g.give = { charId, name: charName };
      render();
      break;
    default:
      // offer / follow / observe / back-away / provoke: a freeform action aimed
      // at the character, so the narrator knows the target.
      takeTurn([{ type: "do", text: `${label} ${charName}`.trim() }]);
      break;
  }
}

// ---------------------------------------------------------------------------
// the private modal (Talk / Whisper) + the composers
// ---------------------------------------------------------------------------

function openPrivate(charId, name, channel) {
  const g = state.active;
  if (!g) return;
  g.privateChat = { charId, name, channel, mode: "say", stack: [] };
  g.give = null;
  render();
  focusComposer("#pmInput");
}

// Switching Talk <-> Whisper re-renders the thread; preserve whatever the
// player already typed (chips included) across the rebuild.
function switchPmChannel(channel) {
  const g = state.active;
  if (!g || !g.privateChat || g.privateChat.channel === channel) return;
  const draft = root.querySelector("#pmInput");
  const html = draft ? draft.innerHTML : "";
  g.privateChat.channel = channel;
  render();
  const restored = root.querySelector("#pmInput");
  if (restored && html) restored.innerHTML = html;
  focusComposer("#pmInput");
}

// Toggle Do/Say in place (no re-render: a render would wipe the typed line).
function setComposerMode(holder, scope, mode) {
  if (!holder || (mode !== "say" && mode !== "do")) return;
  holder.mode = mode;
  root.querySelectorAll(`[data-act="${scope}-mode"]`).forEach((b) => {
    const on = b.dataset.mode === mode;
    b.classList.toggle("active", on);
    b.setAttribute("aria-pressed", String(on));
  });
  const input = root.querySelector(`#${scope}Input`);
  if (input) {
    const pm = state.active && state.active.privateChat;
    const whisper = scope === "pm" && pm && pm.channel === "whisper";
    const name = pm ? pm.name : "";
    input.dataset.placeholder =
      mode === "say"
        ? scope === "pm"
          ? `${whisper ? "Whisper" : "Say"} to ${name}...`
          : "What do you say?"
        : scope === "pm"
          ? whisper
            ? `A discreet act only ${name} notices...`
            : "Do something..."
          : "Do or say anything... (Enter sends)";
    input.setAttribute("aria-label", mode === "say" ? "What you say" : "What you do");
    input.focus();
  }
}

// Pull the current line out of a composer as a wire segment, or null if empty.
function currentSegment(scope) {
  const g = state.active;
  if (!g) return null;
  const input = root.querySelector(`#${scope}Input`);
  const { text, refs } = serializeComposer(input);
  if (!text) return null;
  const pm = scope === "pm" ? g.privateChat : null;
  const channel = pm ? { kind: pm.channel, target: pm.name } : null;
  const mode = (pm || g.composer || {}).mode || "do";
  clearComposer(input);
  return buildSegment({ mode, text, refs, channel });
}

// "+": stack the current line to execute together with the rest of the turn.
function stackSegment(scope) {
  const g = state.active;
  if (!g) return;
  const holder = scope === "pm" ? g.privateChat : g.composer;
  const seg = currentSegment(scope);
  if (!holder || !seg) return;
  holder.stack.push(seg);
  render();
  focusComposer(`#${scope}Input`);
}

function unstackSegment(holder, index) {
  if (!holder) return;
  holder.stack.splice(Number(index), 1);
  render();
}

// Send from the main composer: stacked segments + the current line, one POST.
// A single plain "do" line with no tags stays a freeform { action } (the
// narrator likes raw words); anything tagged/stacked/spoken goes as segments.
function executeComposer() {
  const g = state.active;
  if (!g || g.generating) return;
  const cmp = g.composer || (g.composer = { mode: "do", stack: [] });
  const input = root.querySelector("#cmpInput");
  const { text, refs } = serializeComposer(input);
  clearComposer(input);

  const segments = [...cmp.stack];
  if (text) {
    if (!segments.length && !refs.length && cmp.mode === "do") {
      cmp.stack = [];
      takeTurn(text);
      return;
    }
    segments.push(buildSegment({ mode: cmp.mode, text, refs, channel: null }));
  }
  if (!segments.length) return;
  cmp.stack = [];
  takeTurn(segments);
}

// Execute the private modal's turn: all stacked lines land at the SAME target,
// then the character replies once. The modal stays open to show the reply.
function executePrivate() {
  const g = state.active;
  if (!g || !g.privateChat || g.generating) return;
  const pm = g.privateChat;
  const segments = [...pm.stack];
  const seg = currentSegment("pm");
  if (seg) segments.push(seg);
  if (!segments.length) return;
  pm.stack = [];
  takeTurn(segments);
}

function focusComposer(selector) {
  const el = root.querySelector(selector);
  if (el) el.focus();
}

// ---------------------------------------------------------------------------
// the entity tagger ("@"): pick a character or item to chip into the line
// ---------------------------------------------------------------------------

function closeTagger() {
  document.querySelectorAll(".tagger-pop").forEach((p) => p.remove());
  if (taggerDismiss) {
    document.removeEventListener("click", taggerDismiss);
    taggerDismiss = null;
  }
}

function openTagger(btn) {
  const g = state.active;
  if (!g || !g.state) return;
  closeTagger();
  const scope = btn.dataset.scope || "cmp";
  const s = g.state;

  const entities = [
    ...presentCharacters(s).map((c) => ({ kind: "character", id: c.id, name: c.name })),
    ...((s.scene && s.scene.items) || []).map((it) => ({ kind: "item", id: it.id, name: it.name })),
    ...(s.player.inventory || []).map((it) => ({ kind: "item", id: it.id, name: it.name })),
  ].filter((e) => e.name);

  const pop = document.createElement("div");
  pop.className = "tagger-pop";
  pop.setAttribute("role", "listbox");
  pop.setAttribute("aria-label", "Tag a character or item");
  pop.innerHTML = entities.length
    ? entities
        .map(
          (e, i) =>
            `<button type="button" role="option" class="tag-opt kind-${e.kind}" data-index="${i}">
               ${icon(e.kind === "character" ? "mask" : "gem")}<span></span>
             </button>`,
        )
        .join("")
    : `<p class="tag-empty">Nothing here to tag yet.</p>`;
  pop.querySelectorAll(".tag-opt span").forEach((span, i) => {
    span.textContent = entities[i].name;
  });
  pop.querySelectorAll(".tag-opt").forEach((opt) => {
    opt.addEventListener("click", (e) => {
      e.stopPropagation();
      const ref = entities[Number(opt.dataset.index)];
      const editor = root.querySelector(`#${scope}Input`);
      if (editor && ref) insertChip(editor, ref);
      closeTagger();
      if (editor) editor.focus();
    });
  });
  document.body.appendChild(pop);
  const r = btn.getBoundingClientRect();
  pop.style.left = `${Math.max(8, Math.min(window.innerWidth - 248, r.left + window.scrollX - 110))}px`;
  pop.style.top = `${Math.max(8, r.top + window.scrollY - pop.offsetHeight - 8)}px`;
  taggerDismiss = (ev) => {
    if (!pop.contains(ev.target) && ev.target !== btn) closeTagger();
  };
  setTimeout(() => {
    if (taggerDismiss) document.addEventListener("click", taggerDismiss);
  }, 0);
}

// ---------------------------------------------------------------------------
// tap-to-inspect: the detail modal + the /explain narrator aside
// ---------------------------------------------------------------------------

function openInspect(spec) {
  const g = state.active;
  if (!g || !g.state) return;
  g.inspect = { ...spec, asking: false, answer: null };
  render();
}

async function doExplain() {
  const g = state.active;
  const ins = g && g.inspect;
  if (!ins || ins.asking) return;
  ins.asking = true;
  ins.answer = null;
  render();
  try {
    const payload = ins.kind === "beat" ? { kind: "beat", beat_id: ins.beatId } : { kind: ins.kind, key: ins.key };
    const res = await api.explain(g.id, payload);
    ins.answer = (res && res.text) || "";
  } catch (err) {
    ins.answer = err.status === 404 ? "Nothing more can be seen." : "The narrator is silent right now.";
  } finally {
    if (g.inspect === ins) {
      ins.asking = false;
      render();
    }
  }
}

function doGive(item, target) {
  const g = state.active;
  if (!g) return;
  g.give = null;
  takeTurn([{ type: "give", item, target }]);
}

function updateSetting(el) {
  const key = el.dataset.setting;
  let value = el.value;
  if (el.type === "checkbox") value = el.checked;
  if (el.type === "range") value = Number(el.value);
  state.settings[key] = value;
  if (key === "backendUrl") api = createApi(value);
  if (key === "voiceEnabled" && !value) voice.stop();
  voice.applySettings(state.settings);
  saveSettings();
  if (el.type !== "range") render();
}

// ---------------------------------------------------------------------------
// library
// ---------------------------------------------------------------------------

async function refreshLibrary() {
  try {
    const res = await api.listGames();
    state.backendOnline = true;
    state.backendError = "";
    state.games = (res && res.games) || [];
  } catch (err) {
    state.backendOnline = false;
    state.backendError = err.message || "unreachable";
    state.games = [];
  }
  if (state.view === "library" || state.view === "menu") render();
}

async function removeGame(id) {
  state.confirm = null;
  render();
  try {
    await api.deleteGame(id);
  } catch (err) {
    showToast(err.message || "Could not delete that adventure.");
  }
  refreshLibrary();
}

// ---------------------------------------------------------------------------
// open / load a game
// ---------------------------------------------------------------------------

async function openGame(gameId) {
  stopPolling();
  state.active = {
    id: gameId,
    state: null,
    beats: [],
    generating: true,
    privateChat: null, // { charId, name, channel: talk|whisper, mode: say|do, stack }
    give: null,
    inspect: null, // { kind, key|beatId, asking, answer } - the tap-to-inspect modal
    composer: { mode: "do", stack: [] },
    revealedArt: new Set(), // art urls already card-revealed (the effect plays once)
  };
  state.view = "play";
  render();
  try {
    const [rawState, rawBeats] = await Promise.all([api.getState(gameId), api.getBeats(gameId)]);
    state.active.state = mapGameState(rawState);
    state.active.beats = mapBeats((rawBeats && rawBeats.beats) || []).map((b) => withVoice(b));
    state.backendOnline = true;
  } catch (err) {
    state.backendOnline = false;
    state.backendError = err.message || "unreachable";
  } finally {
    if (state.active) state.active.generating = false;
    render();
    maybePollForArt();
  }
}

// ---------------------------------------------------------------------------
// take a turn
// ---------------------------------------------------------------------------

// Take a turn. `input` is either a plain string (freeform) or an array of tagged
// segments (what the composers build). One POST -> { beats, state }; everything
// is blocked until the response lands (the busy-lock).
async function takeTurn(input) {
  const g = state.active;
  if (!g || g.generating) return;
  const empty = Array.isArray(input) ? !input.length : !String(input || "").trim();
  if (empty) return;

  g.generating = true;
  g.skipReveal = true; // fast-forward any reveal still running from last turn
  render();

  try {
    const turn = await api.takeAction(g.id, input);
    const prevState = g.state;
    g.state = mapGameState(turn.state);
    g.changes = diffState(prevState, g.state); // what transitioned this turn
    const newBeats = mapBeats(turn.beats || []).map((b) => withVoice(b));
    g.beats = [...g.beats, ...newBeats];
    g.revealQueue = newBeats.map((b) => b.id); // staged reveal, in seq order
    g.skipReveal = false;
    state.backendOnline = true;
  } catch (err) {
    state.backendError = err.message || "Turn failed";
    if (err.status === 0) state.backendOnline = false;
    showToast(err.message || "The backend did not accept that action.");
  } finally {
    g.generating = false;
    render();
    applyTransitions(g); // notices + one-shot flashes from the diff
    startReveal(g);
    maybePollForArt();
  }
}

// ---------------------------------------------------------------------------
// Simulated streaming: the backend computes a turn atomically (real token
// streaming is impossible by design), so the PACING is ours. Per beat kind, in
// seq order: system beats + the player's own echo are INSTANT; narration /
// dialogue / private whispers get a fast typewriter (instant-finish on story
// click); image beats fade in when reached. With voice autoplay on, a speech
// beat reveals when ITS audio is ready and the typewriter paces with the
// audio's duration (the next beat's audio renders while this one plays).
// ---------------------------------------------------------------------------

const REVEAL_CPS = 45; // default typewriter speed (chars/second)
const REVEAL_TICK = 45; // ms per typewriter tick

function reducedMotion() {
  try {
    return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

async function startReveal(g) {
  if (!g || g.revealing || !g.revealQueue || !g.revealQueue.length) return;
  g.revealing = true;
  try {
    while (g.revealQueue && g.revealQueue.length && state.active === g && state.view === "play") {
      const beat = g.beats.find((b) => b.id === g.revealQueue[0]);
      await revealBeat(g, beat);
      g.revealQueue.shift();
    }
  } finally {
    if (g.revealQueue) g.revealQueue.length = 0;
    g.revealing = false;
    g.skipReveal = false;
  }
}

async function revealBeat(g, beat) {
  if (!beat) return;
  // a beat can render in two places at once (the story AND the talk-modal
  // thread); reveal every copy
  const find = () => [...root.querySelectorAll(`[data-beat-id="${cssId(beat.id)}"]`)];
  const unveil = () => {
    const els = find();
    els.forEach((el) => el.closest(".veil-wrap")?.classList.remove("veiled"));
    return els[0] || null;
  };

  const instant = g.skipReveal || reducedMotion();
  if (beat.kind === "image") {
    const el = unveil();
    if (el) {
      el.classList.add("img-arrive");
      followStory();
      announceImage(el);
    }
    if (!instant) await sleep(350);
    return;
  }

  const fromPlayer = !beat.speaker || beat.speaker === "player";
  const typed = (beat.kind === "narration" || beat.kind === "dialogue") && !fromPlayer;
  if (!typed) {
    unveil();
    followStory();
    if (!instant) await sleep(90);
    return;
  }

  // voice pairing: render this beat's audio first (reveal when ready), then
  // queue the NEXT voiced beat behind it so it renders while this one plays.
  let prepared = null;
  if (state.settings.autoplayVoice && beat.voiceId && voice.enabled) {
    const current = voice.prepare({ text: beat.text, voiceId: beat.voiceId });
    const next = nextVoicedBeat(g, beat.id);
    if (next) voice.prepare({ text: next.text, voiceId: next.voiceId });
    prepared = await current;
  }

  const el = unveil();
  if (!el) return;
  if (prepared) voice.playUrl(prepared.audioUrl, beat.speaker);
  if (instant) return;

  const chars = String(beat.text || "").length || 1;
  const cps = prepared && prepared.duration ? Math.min(80, Math.max(15, chars / prepared.duration)) : REVEAL_CPS;
  await typewrite(g, beat, cps);
}

function nextVoicedBeat(g, afterId) {
  const queue = g.revealQueue || [];
  const from = queue.indexOf(afterId);
  for (let i = from + 1; i < queue.length; i++) {
    const b = g.beats.find((x) => x.id === queue[i]);
    if (b && b.voiceId && (b.kind === "narration" || b.kind === "dialogue")) return b;
  }
  return null;
}

// Where the typewriter writes, per card shape. Counts mirror the renderers.
function typeTargets(el) {
  if (el.classList.contains("narration")) return [...el.querySelectorAll(":scope > p")];
  const bubble = el.querySelector(".bubble p");
  if (bubble) return [bubble];
  const pm = el.querySelector(".pm-text");
  if (pm) return [pm];
  return [];
}

// Texts come from the BEAT (same paragraph split as the renderer), not the
// DOM: a mid-reveal re-render rebuilds the nodes with full text, and we keep
// typing into the fresh ones from our own position.
async function typewrite(g, beat, cps) {
  const paras = beat.kind === "narration" ? String(beat.text || "").split(/\n{2,}/) : [String(beat.text || "")];
  const step = Math.max(1, Math.round((cps * REVEAL_TICK) / 1000));
  const els = () => [...root.querySelectorAll(`[data-beat-id="${cssId(beat.id)}"]`)];

  const first = els();
  if (!first.length) return;
  first.forEach((el) => {
    typeTargets(el).forEach((t) => (t.textContent = ""));
    el.classList.add("typing");
  });

  for (let i = 0; i < paras.length; i++) {
    let pos = 0;
    while (pos < paras[i].length) {
      if (g.skipReveal || state.active !== g || state.view !== "play") {
        finishTyping(beat, paras);
        return;
      }
      pos = Math.min(paras[i].length, pos + step);
      const copies = els();
      if (!copies.length) return; // windowed out mid-type
      for (const el of copies) {
        el.closest(".veil-wrap")?.classList.remove("veiled"); // survive re-renders
        const targets = typeTargets(el);
        for (let j = 0; j < targets.length; j++) {
          targets[j].textContent = j < i ? paras[j] : j === i ? paras[i].slice(0, pos) : "";
        }
      }
      followStory();
      await sleep(REVEAL_TICK);
    }
  }
  finishTyping(beat, paras);
}

function finishTyping(beat, paras) {
  root.querySelectorAll(`[data-beat-id="${cssId(beat.id)}"]`).forEach((el) => {
    el.closest(".veil-wrap")?.classList.remove("veiled");
    typeTargets(el).forEach((t, j) => (t.textContent = paras[j] ?? ""));
    el.classList.remove("typing");
  });
  followStory();
}

// Keep following the story while it grows, but only if the reader is at the
// bottom (scrolling up to read pauses the follow).
function followStory() {
  const story = root.querySelector("#storyStream");
  if (story && storyNearBottom(story)) story.scrollTop = story.scrollHeight;
}

// A new image landed in the flow: bring it into view when the reader is at the
// bottom; otherwise offer a small "new image below" affordance instead of
// yanking them away from what they are reading.
function announceImage(el) {
  const story = root.querySelector("#storyStream");
  if (!story) return;
  if (storyNearBottom(story)) {
    if (typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    else followStory();
    return;
  }
  if (story.querySelector(".new-image-chip")) return;
  const chip = document.createElement("button");
  chip.type = "button";
  chip.className = "new-image-chip";
  chip.innerHTML = `${icon("eye")}<span>New image below</span>`;
  chip.addEventListener("click", (e) => {
    e.stopPropagation();
    if (typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "center", behavior: "smooth" });
    chip.remove();
  });
  story.appendChild(chip);
  setTimeout(() => chip.remove(), 15000);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ---------------------------------------------------------------------------
// "See" the scene: a synchronous image of the current scene WITH the present
// characters (5-10s). Loader + lock on the button only; the result arrives as
// a persisted `kind: "image"` beat rendered inline in the story.
// ---------------------------------------------------------------------------

// The eye opens a small "look at what?" popover first: empty = the whole
// scene, a focus ("what Layla is doing") frames the shot on it.
function openSeePopover(btn) {
  const g = state.active;
  if (!g || !g.state || !g.state.imagesEnabled || g.seeing || g.generating) return;
  closeSeePopover();
  const pop = document.createElement("form");
  pop.className = "see-pop";
  pop.innerHTML = `
    <input name="seeFocus" class="holo-input" autocomplete="off"
           placeholder="Look at what? (empty = whole scene)" aria-label="Look at what?" />
    <button class="holo-btn" type="submit">${icon("eye")}<span>See</span></button>`;
  pop.addEventListener("submit", (e) => {
    e.preventDefault();
    const focus = String(new FormData(pop).get("seeFocus") || "").trim();
    closeSeePopover();
    seeScene(focus);
  });
  document.body.appendChild(pop);
  const r = btn.getBoundingClientRect();
  pop.style.top = `${r.bottom + window.scrollY + 8}px`;
  pop.style.left = `${Math.max(8, Math.min(window.innerWidth - 330, r.left + window.scrollX - 40))}px`;
  pop.querySelector("input").focus();
  seeDismiss = (ev) => {
    if (!pop.contains(ev.target) && ev.target !== btn) closeSeePopover();
  };
  setTimeout(() => {
    if (seeDismiss) document.addEventListener("click", seeDismiss);
  }, 0);
}

function closeSeePopover() {
  document.querySelectorAll(".see-pop").forEach((p) => p.remove());
  if (seeDismiss) {
    document.removeEventListener("click", seeDismiss);
    seeDismiss = null;
  }
}

async function seeScene(focus) {
  const g = state.active;
  if (!g || !g.state || !g.state.imagesEnabled || g.seeing || g.generating) return;
  g.seeing = true;
  render();
  try {
    const res = await api.viewScene(g.id, focus);
    if (res && res.beat) {
      const beats = mapBeats([res.beat]);
      g.beats = [...g.beats, ...beats];
      g.revealQueue = [...(g.revealQueue || []), ...beats.map((b) => b.id)];
    }
  } catch (err) {
    if (err.status === 409) {
      // images are disabled server-side: hide the button by trusting the flag
      g.state.imagesEnabled = false;
      showToast("Images are disabled for this world.");
    } else {
      showToast("The vision fades... (image service unavailable)");
    }
  } finally {
    if (state.active === g) {
      g.seeing = false;
      render();
      startReveal(g);
    }
  }
}

// ---------------------------------------------------------------------------
// creator
// ---------------------------------------------------------------------------

// Creator sessions persist server-side and survive restarts; we keep the
// session id in localStorage so a page refresh restores the chat in progress.
const CREATOR_SESSION_KEY = "gamentic.creator.session";

function savedCreatorSession() {
  try {
    return localStorage.getItem(CREATOR_SESSION_KEY) || null;
  } catch {
    return null;
  }
}

function storeCreatorSession(id) {
  try {
    localStorage.setItem(CREATOR_SESSION_KEY, id);
  } catch {
    /* ignore quota */
  }
}

function clearCreatorSession() {
  try {
    localStorage.removeItem(CREATOR_SESSION_KEY);
  } catch {
    /* ignore */
  }
}

// Entering the creator: restore an in-progress session when one is stored,
// otherwise start fresh. A 404 means the backend no longer knows it.
async function enterCreator() {
  resetCreator();
  state.view = "creator";
  const saved = savedCreatorSession();
  if (!saved) {
    render();
    return;
  }
  const c = state.creator;
  c.busy = true;
  render();
  try {
    const res = await api.creatorSession(saved);
    c.sessionId = res.session_id || saved;
    const history = (res.history || []).map((m) => ({
      role: m.role === "user" ? "user" : "builder",
      text: m.content || "",
    }));
    if (history.length) c.messages = [...c.messages, ...history];
    c.restored = history.length > 0;
  } catch {
    clearCreatorSession(); // unknown/expired session: start clean
  } finally {
    c.busy = false;
    if (state.view === "creator") render();
  }
}

function resetCreator() {
  state.creator = {
    sessionId: "creator-" + rand(),
    busy: false,
    finalizing: false,
    restored: false,
    error: "",
    messages: [
      {
        role: "builder",
        text: "Tell me about the world you want to play. A place, a mood, a danger, a companion. I will shape it into a real adventure.",
      },
    ],
  };
}

async function sendCreatorMessage(raw) {
  const text = String(raw || "").trim();
  const c = state.creator;
  if (!text || c.busy) return;
  c.messages.push({ role: "user", text });
  c.busy = true;
  c.error = "";
  render();
  try {
    const res = await api.creatorMessage(c.sessionId, text);
    c.messages.push({ role: "builder", text: (res && res.reply) || "..." });
    storeCreatorSession(c.sessionId); // the session now exists server-side
    state.backendOnline = true;
  } catch (err) {
    c.error = "Could not reach the world-builder: " + (err.message || "offline");
    state.backendOnline = false;
  } finally {
    c.busy = false;
    render();
  }
}

async function beginAdventure() {
  const c = state.creator;
  if (c.busy) return;
  c.busy = true;
  c.finalizing = true; // full-screen "forging your world" takeover (blocks the chat)
  c.error = "";
  render();
  try {
    const res = await api.creatorFinalize(c.sessionId);
    c.busy = false;
    clearCreatorSession(); // the chat became a real game; next New starts fresh
    // leave finalizing on until openGame swaps the view, so the animation never flickers off first
    openGame(res.game_id);
  } catch (err) {
    c.busy = false;
    c.finalizing = false;
    if (err.status === 409) {
      c.messages.push({ role: "builder", text: err.message || "I need a little more before we can begin. Keep going." });
    } else {
      c.error = "Could not start the game: " + (err.message || "offline");
      state.backendOnline = false;
    }
    render();
  }
}

// ---------------------------------------------------------------------------
// voice
// ---------------------------------------------------------------------------

function withVoice(beat) {
  return { ...beat, voiceId: voiceForBeat(beat, state.active && state.active.state) };
}

function speakBeat(beatId) {
  const g = state.active;
  const beat = g && g.beats.find((b) => b.id === beatId);
  if (!beat) return;
  voice.speak({ text: beat.text, voiceId: beat.voiceId, speakerId: beat.speaker });
}

// (turn autoplay is handled by the staged reveal: each speech beat's audio is
// prepared in a pipeline and played when that beat reveals)

// ---------------------------------------------------------------------------
// late-arriving art: media is optional + async (image gen lags). Poll /state
// until the scene image and character faces fill in, then slot them in. Slots
// already reserve space so swapping art in never relayouts.
// ---------------------------------------------------------------------------

function artMissing(s) {
  if (!s) return false;
  // images_enabled is the rule: false means images are OFF - nothing is coming,
  // show static placeholders and never poll.
  if (!s.imagesEnabled) return false;
  const sceneMissing = s.scene && !s.scene.imageUrl;
  const portraitMissing = (s.characters || []).some((c) => c.alive && c.present && (!c.faceUrl || !c.bodyUrl));
  return Boolean(sceneMissing || portraitMissing);
}

function maybePollForArt() {
  stopPolling();
  const g = state.active;
  if (!g || !g.state || !artMissing(g.state)) return;

  let tries = 0;
  pollTimer = setInterval(async () => {
    tries += 1;
    if (!state.active || state.view !== "play" || tries > 16) return stopPolling();
    try {
      const mapped = mapGameState(await api.getState(state.active.id));
      const prev = state.active.state;
      const gainedPortrait = mapped.characters.some((c) => {
        const p = prev.characters.find((x) => x.id === c.id) || {};
        return (c.faceUrl && !p.faceUrl) || (c.bodyUrl && !p.bodyUrl);
      });
      const gainedScene = mapped.scene && mapped.scene.imageUrl && !(prev.scene && prev.scene.imageUrl);
      state.active.state = mapped;
      // don't yank the DOM out from under a running typewriter; the art shows
      // on the next natural render
      if ((gainedPortrait || gainedScene) && state.view === "play" && !state.active.revealing) {
        render();
        if (gainedScene) {
          const art = root.querySelector("#storyStream .prose-art img");
          if (art) announceImage(art.closest(".prose-art") || art);
        }
      }
      if (!artMissing(mapped)) stopPolling();
    } catch {
      /* keep trying */
    }
  }, 2500);
}

// Card-reveal: any [data-art] image not yet seen this session gets the
// collection-card reveal animation, exactly once per url (re-renders rebuild
// the DOM every turn; without the seen-set the effect would replay each time).
function markArtReveals(g) {
  if (!g || !g.revealedArt) return;
  root.querySelectorAll("[data-art]").forEach((img) => {
    const url = img.dataset.art;
    if (g.revealedArt.has(url)) return;
    g.revealedArt.add(url);
    const card = img.closest(".prose-art, .col-art, .pm-face") || img;
    card.classList.add("art-reveal");
    setTimeout(() => card.classList.remove("art-reveal"), 1400);
  });
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

// ---------------------------------------------------------------------------
// animation juice + helpers
// ---------------------------------------------------------------------------

// Apply the turn's transitions to the freshly-rendered DOM: transient notices for
// narrative changes, plus one-shot flashes on the cards/slots/HUD that changed.
function applyTransitions(g) {
  const ch = g.changes;
  g.changes = null;
  if (!ch || ch.firstLoad) return;

  const notices = buildNotices(ch);
  if (notices.length) showNotices(notices);

  // scene establish: the identity wing of the deck announces the new place
  if (ch.sceneChanged) flash(".deck-scene", "scene-enter", 900);

  // HUD deltas
  if (ch.lifeDelta < 0) flash("[data-hud-life]", "shake", 600);
  if (ch.pointsDelta > 0) flash('[data-hud-num="points"]', "tick", 600);
  if (ch.goalChanged) flash(".hud-goal", "goal-flash", 1200);

  // scene items revealed; player inventory gained
  ch.itemsAdded.forEach((id) => flash(`.scene-items .slot[data-item-id="${cssId(id)}"]`, "slot-new", 1400));
  ch.invAdded.forEach((name) => flash(`.player-items .slot[data-item-name="${cssAttr(name)}"]`, "slot-new", 1400));

  // characters
  ch.charJoined.forEach((c) => flash(`.char-col[data-char-id="${cssId(c.id)}"]`, "card-arrive", 800));
  ch.charHurt.forEach((id) => flash(`.char-col[data-char-id="${cssId(id)}"] .hp-fill`, "hp-flash", 700));
  ch.charDisposition.forEach((c) => flash(`.char-col[data-char-id="${cssId(c.id)}"] .disp-badge`, "disp-flash", 900));
}

function flash(selector, cls, ms) {
  const el = root.querySelector(selector);
  if (!el) return;
  el.classList.add(cls);
  setTimeout(() => el.classList.remove(cls), ms);
}

// CSS.escape fallbacks for ids / attribute values used in selectors
function cssId(v) {
  const s = String(v ?? "");
  return typeof CSS !== "undefined" && CSS.escape ? CSS.escape(s) : s.replace(/["\\\]]/g, "\\$&");
}
function cssAttr(v) {
  return String(v ?? "").replace(/["\\]/g, "\\$&");
}

// Transient notice stack (top-center): animated chips that fade. Not part of the
// permanent story log - they communicate the TRANSITION, then get out of the way.
function showNotices(notices) {
  let stack = document.querySelector(".notice-stack");
  if (!stack) {
    stack = document.createElement("div");
    stack.className = "notice-stack";
    document.body.appendChild(stack);
  }
  notices.slice(0, 6).forEach((n, i) => {
    const el = document.createElement("div");
    el.className = `notice tone-${n.tone}`;
    el.innerHTML = `${icon(n.icon)}<span></span>`;
    el.querySelector("span").textContent = n.text;
    stack.appendChild(el);
    setTimeout(() => el.classList.add("show"), 20 + i * 70);
    setTimeout(() => {
      el.classList.remove("show");
      setTimeout(() => el.remove(), 400);
    }, 3400 + i * 250);
  });
}

function showHelp(el) {
  document.querySelectorAll(".help-pop").forEach((p) => p.remove());
  const pop = document.createElement("div");
  pop.className = "help-pop";
  pop.textContent = HELP[el.dataset.help] || "Part of the game.";
  document.body.appendChild(pop);
  const r = el.getBoundingClientRect();
  pop.style.top = `${r.bottom + window.scrollY + 6}px`;
  pop.style.left = `${Math.max(8, Math.min(window.innerWidth - 268, r.left + window.scrollX - 120))}px`;
  const close = (ev) => {
    if (ev.target !== el) {
      pop.remove();
      document.removeEventListener("click", close);
    }
  };
  setTimeout(() => document.addEventListener("click", close), 0);
}

function showToast(message) {
  const t = document.createElement("div");
  t.className = "toast";
  t.textContent = message;
  document.body.appendChild(t);
  setTimeout(() => t.classList.add("show"), 10);
  setTimeout(() => {
    t.classList.remove("show");
    setTimeout(() => t.remove(), 300);
  }, 3200);
}

// Pin a scroll container to the bottom. Runs on the next frame so it measures
// AFTER the new content has been laid out (a sync scroll right after innerHTML
// can read a stale scrollHeight and miss the latest message).
function scrollToBottom(selector) {
  const el = root.querySelector(selector);
  if (!el) return;
  el.scrollTop = el.scrollHeight; // immediate best-effort
  const raf = typeof requestAnimationFrame === "function" ? requestAnimationFrame : (fn) => setTimeout(fn, 16);
  raf(() => {
    const e = root.querySelector(selector);
    if (e) e.scrollTop = e.scrollHeight;
  });
}

function scrollStory() {
  scrollToBottom("#storyStream");
}
function scrollCreator() {
  scrollToBottom("#creatorThread");
}

function rand() {
  return Math.random().toString(36).slice(2, 10);
}

// expose minimal hooks for debugging
window.__gamentic = { state, voice, render };
void escapeHtml;
