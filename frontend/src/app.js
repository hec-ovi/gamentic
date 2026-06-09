// Gamentic frontend controller.
//
// One in-memory `state`, one render() that rebuilds the DOM, and event handlers
// that mutate state + re-render. No mock games, no streaming machinery: the
// real backend is sequential (one POST /action -> { beats, state }).

import { createApi } from "./api.js";
import { mapGameState, mapBeats, voiceForBeat } from "./adapters.js";
import { diffState, buildNotices } from "./transitions.js";
import { Voice } from "./voice.js";
import { renderApp, HELP, escapeHtml } from "./render.js";
import { icon } from "./icons.js";

const STORAGE_KEY = "gamentic.v2";
let root = null;

const state = {
  view: "menu", // menu | library | creator | play | settings
  games: [], // raw library entries from GET /games
  backendOnline: false,
  backendError: "",
  active: null, // { id, state(mapped), beats(mapped), quickActions, generating }
  creator: { sessionId: "creator-" + rand(), messages: [], busy: false, error: "" },
  confirm: null, // { gameId, title } when a delete confirmation is open
  settings: loadSettings(),
};

const voice = new Voice();
voice.applySettings(state.settings);
let api = createApi(state.settings.backendUrl);
let pollTimer = null;

// ---------------------------------------------------------------------------
// boot. Exported so tests can mount the app against a fresh DOM + mocked network
// (vi.resetModules() between tests gives each one its own module state).
// ---------------------------------------------------------------------------

export function init(opts = {}) {
  root = opts.root || document.querySelector("#app");
  if (!root) return null;
  resetCreator();
  render();
  refreshLibrary();
  return { state, voice };
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
  root.dataset.view = state.view;
  root.innerHTML = renderApp(state);
  bind();
  if (state.view === "play") scrollStory();
  if (state.view === "creator") scrollCreator();
}

function bind() {
  root.querySelectorAll("[data-act]").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation(); // keep nested data-act (e.g. modal buttons over a backdrop) from double-firing
      onAction(el.dataset.act, el);
    });
  });

  root.querySelector('[data-form="action"]')?.addEventListener("submit", (e) => {
    e.preventDefault();
    submitAction(new FormData(e.currentTarget).get("actionText"));
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
  switch (act) {
    case "new-game":
      resetCreator();
      state.view = "creator";
      render();
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
    case "quick":
      submitAction(el.dataset.text);
      break;
    case "speak-beat":
      speakBeat(el.dataset.beatId);
      break;
    // --- play: scene / character action buttons -> tagged segments ---
    case "scene-action":
      takeTurn([{ type: "do", text: el.dataset.label }]);
      break;
    case "exit":
      takeTurn([{ type: "do", text: "go to " + (el.dataset.label || "") }]);
      break;
    case "take-item":
      takeTurn([{ type: "do", text: "take the " + (el.dataset.itemName || "item") }]);
      break;
    case "examine-item":
      takeTurn([{ type: "do", text: "examine the " + (el.dataset.itemName || "item") }]);
      break;
    case "char-action":
      onCharAction(el);
      break;
    case "whisper":
      openChat(el.dataset.charId, el.dataset.charName, "private");
      break;
    case "end-chat":
      if (state.active) state.active.chat = null;
      render();
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
    case "trade": // trade view is not built yet; treat as a directed chat for now
      openChat(charId, charName, "directed");
      break;
    case "attack":
      takeTurn([{ type: "attack", target: charName }]);
      break;
    case "give":
      g.give = { charId, name: charName };
      g.chat = null;
      render();
      break;
    default:
      // offer / follow / observe / back-away / provoke: a freeform action aimed
      // at the character, so the narrator knows the target.
      takeTurn([{ type: "do", text: `${label} ${charName}`.trim() }]);
      break;
  }
}

function openChat(charId, name, mode) {
  const g = state.active;
  if (!g) return;
  g.chat = { charId, name, mode };
  g.give = null;
  render();
  const input = root.querySelector('[name="actionText"]');
  if (input) input.focus();
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
  state.active = { id: gameId, state: null, beats: [], quickActions: [], generating: true, chat: null, give: null };
  state.view = "play";
  render();
  try {
    const [rawState, rawBeats] = await Promise.all([api.getState(gameId), api.getBeats(gameId)]);
    state.active.state = mapGameState(rawState);
    state.active.beats = mapBeats((rawBeats && rawBeats.beats) || []).map((b) => withVoice(b));
    state.active.quickActions = buildQuickActions(state.active.state);
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

// Free-text / quick-chip submit. When a per-character chat is open, the typed
// line becomes a directed (or private) `say` segment aimed at that character.
function submitAction(raw) {
  const g = state.active;
  if (!g) return;
  const text = String(raw || "").trim();
  if (!text) return;
  if (g.chat) {
    // directed Talk -> public "say" aimed at the character; Whisper -> private 1:1.
    const seg =
      g.chat.mode === "private"
        ? { type: "whisper", text, target: g.chat.name }
        : { type: "say", text, target: g.chat.name };
    takeTurn([seg]);
  } else {
    takeTurn(text);
  }
}

// Take a turn. `input` is either a plain string (freeform) or an array of tagged
// segments (what the buttons compose). One POST -> { beats, state }.
async function takeTurn(input) {
  const g = state.active;
  if (!g || g.generating) return;
  const empty = Array.isArray(input) ? !input.length : !String(input || "").trim();
  if (empty) return;

  g.generating = true;
  render();

  try {
    const turn = await api.takeAction(g.id, input);
    const prevState = g.state;
    g.state = mapGameState(turn.state);
    g.changes = diffState(prevState, g.state); // what transitioned this turn
    const newBeats = mapBeats(turn.beats || []).map((b) => withVoice(b));
    g.beats = [...g.beats, ...newBeats];
    g.quickActions = buildQuickActions(g.state);
    state.backendOnline = true;

    render();
    applyTransitions(g); // notices + one-shot flashes from the diff

    if (state.settings.autoplayVoice) autoplay(newBeats);
  } catch (err) {
    state.backendError = err.message || "Turn failed";
    if (err.status === 0) state.backendOnline = false;
    showToast(err.message || "The backend did not accept that action.");
  } finally {
    g.generating = false;
    render();
    maybePollForArt();
  }
}

// ---------------------------------------------------------------------------
// creator
// ---------------------------------------------------------------------------

function resetCreator() {
  state.creator = {
    sessionId: "creator-" + rand(),
    busy: false,
    finalizing: false,
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

function autoplay(beats) {
  const beat = beats.find((b) => b.voiceId && (b.kind === "narration" || b.kind === "dialogue"));
  if (beat) voice.speak({ text: beat.text, voiceId: beat.voiceId, speakerId: beat.speaker });
}

// ---------------------------------------------------------------------------
// late-arriving art: media is optional + async (image gen lags). Poll /state
// until the scene image and character faces fill in, then slot them in. Slots
// already reserve space so swapping art in never relayouts.
// ---------------------------------------------------------------------------

function artMissing(s) {
  if (!s) return false;
  const sceneMissing = s.scene && !s.scene.imageUrl;
  const faceMissing = (s.characters || []).some((c) => c.alive && c.present && !c.faceUrl);
  return Boolean(sceneMissing || faceMissing);
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
      const gainedFace = mapped.characters.some(
        (c) => c.faceUrl && !(prev.characters.find((p) => p.id === c.id) || {}).faceUrl,
      );
      const gainedScene = mapped.scene && mapped.scene.imageUrl && !(prev.scene && prev.scene.imageUrl);
      state.active.state = mapped;
      if ((gainedFace || gainedScene) && state.view === "play") render();
      if (!artMissing(mapped)) stopPolling();
    } catch {
      /* keep trying */
    }
  }, 2500);
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

  // scene establish
  if (ch.sceneChanged) flash(".scene-band", "scene-enter", 900);

  // HUD deltas
  if (ch.lifeDelta < 0) flash("[data-hud-life]", "shake", 600);
  if (ch.pointsDelta > 0) flash('[data-hud-num="points"]', "tick", 600);
  if (ch.goalChanged) flash(".hud-goal", "goal-flash", 1200);

  // scene items revealed; player inventory gained
  ch.itemsAdded.forEach((id) => flash(`.scene-items .slot[data-item-id="${cssId(id)}"]`, "slot-new", 1400));
  ch.invAdded.forEach((name) => flash(`.player-items .slot[data-item-name="${cssAttr(name)}"]`, "slot-new", 1400));

  // characters
  ch.charJoined.forEach((c) => flash(`.char-card[data-char-id="${cssId(c.id)}"]`, "card-arrive", 800));
  ch.charHurt.forEach((id) => flash(`.char-card[data-char-id="${cssId(id)}"] .hp-fill`, "hp-flash", 700));
  ch.charDisposition.forEach((c) => flash(`.char-card[data-char-id="${cssId(c.id)}"] .disp-badge`, "disp-flash", 900));
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

// Frontend-only helper chips. Never presented as backend choices.
function buildQuickActions(s) {
  if (!s) return [];
  const out = [];
  const q = (s.quests || []).find((x) => x.status === "active");
  const obj = q && q.objectives.find((o) => !o.done);
  if (obj) out.push(obj.text);
  out.push("Look around carefully");
  const present = (s.characters || []).find((c) => c.present);
  if (present) out.push(`Talk to ${present.name}`);
  return out.slice(0, 3);
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
