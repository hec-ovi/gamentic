// Gamentic frontend controller.
//
// One in-memory `state`, one render() that rebuilds the DOM, and event handlers
// that mutate state + re-render. No mock games, no streaming machinery: the
// real backend is sequential (one POST /action -> { beats, state }).

import { createApi } from "./api.js";
import { mapGameState, mapBeats, mapProfile, voiceForBeat, presentCharacters } from "./adapters.js";
import { diffState, buildNotices } from "./transitions.js";
import { Voice } from "./voice.js";
import { renderApp, HELP, escapeHtml, stripWrappingQuotes } from "./render.js";
import { serializeComposer, insertChip, clearComposer, buildSegment } from "./composer.js";
import { icon } from "./icons.js";

const STORAGE_KEY = "gamentic.v2";
let root = null;

const state = {
  view: "menu", // menu | library | creator | play | settings
  games: [], // raw library entries from GET /games
  backendOnline: false,
  backendError: "",
  active: null, // { id, state(mapped), beats(mapped), generating, composer, profile, give, revealedArt }
  creator: { sessionId: "creator-" + rand(), messages: [], busy: false, error: "" },
  confirm: null, // { gameId, title } when a delete confirmation is open
  exportChoice: null, // { gameId, title } when a card's export choice (share/save) is open
  settings: loadSettings(),
};

const voice = new Voice();
voice.applySettings(state.settings);
let api = createApi(state.settings.backendUrl);
let pollTimer = null; // late-art /state polling
let lateTimer = null; // post-turn late-image-beat polling (look images, item cards)
// document-level dismiss listener for the tagger popover (tracked so a stale
// one can never close the next popover)
let taggerDismiss = null;
// the per-beat speak button state: { beatId, phase: "loading" | "playing" }
let speaking = null;

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
    // autoplay is SPLIT: the owner wants character voices without narration
    // sometimes. Both are FE-local settings.
    autoplayNarrator: false,
    autoplayCharacters: false,
    masterVolume: 0.7,
    speakerVolumes: {},
  };
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null") || {};
    // migrate the old single `autoplayVoice` toggle into the split pair
    if ("autoplayVoice" in saved) {
      if (!("autoplayNarrator" in saved)) saved.autoplayNarrator = Boolean(saved.autoplayVoice);
      if (!("autoplayCharacters" in saved)) saved.autoplayCharacters = Boolean(saved.autoplayVoice);
      delete saved.autoplayVoice;
    }
    // backendUrl is always the automatic value, never a stale persisted one.
    return { ...defaults, ...saved, backendUrl: defaults.backendUrl };
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
    // the whisper thread pins itself to the newest line
    if (state.active && state.active.profile) scrollToBottom("#pmThread");
    markArtReveals(state.active);
    applySpeakStates(); // the rebuild wiped the speak-button states
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

  // per-adventure settings (difficulty / narrator voice) -> PATCH /settings
  root.querySelectorAll("[data-game-setting]").forEach((el) => {
    el.addEventListener("change", () => patchGameSettings(el.dataset.gameSetting, el.value));
  });

  // the wish line survives re-renders via state (it is not a form of its own)
  root.querySelector("#wishInput")?.addEventListener("input", (e) => {
    if (state.active) state.active.wish = e.target.value;
  });

  // library import: file picker -> POST /games/import
  root.querySelector("#importFile")?.addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";
    importGameFile(file);
  });

  root.querySelectorAll("[data-help]").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      showHelp(el);
    });
  });
}

// PARTIAL busy-lock: while a turn is in flight, only state-MUTATING acts are
// blocked (their buttons also render disabled - this guard covers anything left
// clickable). Read-only interactions (inspect, /explain, lightbox, profiles,
// settings, scrolling) stay live.
const MUTATING_ACTS = new Set([
  "scene-action",
  "exit",
  "take-item",
  "examine-item",
  "char-action",
  "pick-give",
  "continue-story",
  "cmp-stack",
  "pm-stack",
  "cmp-unstack",
  "pm-unstack",
  "open-tagger",
  "go-library",
  "go-menu",
]);

function onAction(act, el) {
  const gameId = el.dataset.gameId;
  if (state.active && state.active.generating && MUTATING_ACTS.has(act)) return;
  switch (act) {
    case "new-game":
      enterCreator();
      break;
    case "go-menu":
      stopPolling();
      stopLateWatch();
      state.view = "menu";
      render();
      refreshLibrary();
      break;
    case "go-library":
      stopPolling();
      stopLateWatch();
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
    case "creator-restart":
      clearCreatorSession();
      resetCreator();
      render();
      break;
    // --- play: scene / character action buttons -> tagged segments ---
    case "scene-action":
      takeSceneAction(el.dataset.type, el.dataset.label);
      break;
    case "continue-story":
      continueStory();
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
    case "open-profile":
      openProfile(el.dataset.charId, el.dataset.charName);
      break;
    case "profile-tab":
      if (state.active && state.active.profile) {
        state.active.profile.tab = el.dataset.tab;
        render();
        if (el.dataset.tab === "whisper") focusComposer("#pmInput");
      }
      break;
    case "close-profile":
      if (state.active) state.active.profile = null;
      render();
      break;
    case "ask-export":
      state.exportChoice = { gameId, title: el.dataset.gameTitle || "adventure" };
      render();
      break;
    case "cancel-export":
      state.exportChoice = null;
      render();
      break;
    case "export-game":
      state.exportChoice = null;
      exportGame(gameId, el.dataset.kind, el.dataset.gameTitle);
      break;
    case "import-game":
      root.querySelector("#importFile")?.click();
      break;
    case "cmp-mode":
      setComposerMode(state.active && state.active.composer, "cmp", el.dataset.mode);
      break;
    case "pm-mode":
      setComposerMode(state.active && state.active.profile, "pm", el.dataset.mode);
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
      unstackSegment(state.active && state.active.profile, el.dataset.index);
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

// The scene's base actions are real story actions. Look around / Search map to
// the `look` segment (they can reveal the scene's hidden items and exits);
// anything else stays a freeform do with the button's label.
function takeSceneAction(type, label) {
  if (type === "look") return takeTurn([{ type: "look", text: "" }]);
  if (type === "search") return takeTurn([{ type: "look", text: "for anything hidden or useful here" }]);
  takeTurn([{ type: "do", text: label }]);
}

// Map a character action button (its `type`) to the right segment / panel.
// (Talk is GONE as an affordance: whisper is the private channel and it lives
// in the character profile screen.)
function onCharAction(el) {
  const g = state.active;
  if (!g) return;
  const { type, charId, charName, label } = el.dataset;
  switch (type) {
    case "attack":
      takeTurn([{ type: "attack", target: charId || charName }]);
      break;
    case "give":
      g.give = { charId, name: charName };
      render();
      break;
    default:
      // talk/trade/offer/follow/observe/back-away/provoke: a freeform action
      // aimed at the character, so the narrator knows the target.
      takeTurn([{ type: "do", text: `${label} ${charName}`.trim() }]);
      break;
  }
}

// ---------------------------------------------------------------------------
// the full-screen character profile (+ the private whisper channel inside it)
// ---------------------------------------------------------------------------

// Open the profile screen. Read-only, so it works mid-turn too. The whisper
// composer state (mode/stack) lives on it; the data refetches on open and
// after each turn while it stays open.
function openProfile(charId, name) {
  const g = state.active;
  if (!g || !g.state) return;
  g.profile = { charId, name, tab: "profile", mode: "say", stack: [], loading: true, data: null, error: "" };
  g.give = null;
  render();
  refreshProfile(g);
}

async function refreshProfile(g) {
  const pf = g.profile;
  if (!pf) return;
  try {
    const raw = await api.characterProfile(g.id, pf.charId);
    if (g.profile !== pf) return; // closed / switched while fetching
    pf.data = mapProfile(raw);
    pf.error = "";
  } catch (err) {
    if (g.profile !== pf) return;
    if (!pf.data) pf.error = err.status === 404 ? "No trace of them remains." : "Their story is out of reach right now.";
  } finally {
    if (g.profile === pf) {
      pf.loading = false;
      if (state.active === g) render();
    }
  }
}

// Toggle Do/Say/Look in place (no re-render: a render would wipe the typed line).
const MODE_PLACEHOLDERS = {
  cmp: {
    do: "Do or say anything... (Enter sends)",
    say: "What do you say?",
    look: "Look at what? (empty = study the whole scene)",
  },
};
function setComposerMode(holder, scope, mode) {
  if (!holder || (mode !== "say" && mode !== "do" && mode !== "look")) return;
  if (scope === "pm" && mode === "look") return; // the private channel has no look
  holder.mode = mode;
  root.querySelectorAll(`[data-act="${scope}-mode"]`).forEach((b) => {
    const on = b.dataset.mode === mode;
    b.classList.toggle("active", on);
    b.setAttribute("aria-pressed", String(on));
  });
  const input = root.querySelector(`#${scope}Input`);
  if (input) {
    const pf = state.active && state.active.profile;
    const name = pf ? pf.name : "";
    input.dataset.placeholder =
      scope === "pm"
        ? mode === "say"
          ? `Whisper to ${name}...`
          : `A discreet act only ${name} notices...`
        : MODE_PLACEHOLDERS.cmp[mode];
    input.setAttribute(
      "aria-label",
      mode === "say" ? "What you say" : mode === "look" ? "What you look at" : "What you do",
    );
    input.focus();
  }
}

// Pull the current line out of a composer as a wire segment, or null if empty.
// (A look line may be empty on SEND - "study the whole scene" - but an empty
// line is never worth stacking, so empty stays null here.)
function currentSegment(scope) {
  const g = state.active;
  if (!g) return null;
  const input = root.querySelector(`#${scope}Input`);
  const { text, refs } = serializeComposer(input);
  if (!text) return null;
  const pm = scope === "pm" ? g.profile : null;
  const channel = pm ? { kind: "whisper", target: pm.name } : null;
  const mode = (pm || g.composer || {}).mode || "do";
  clearComposer(input);
  return buildSegment({ mode, text, refs, channel });
}

// "+": stack the current line to execute together with the rest of the turn.
function stackSegment(scope) {
  const g = state.active;
  if (!g) return;
  const holder = scope === "pm" ? g.profile : g.composer;
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
// An empty LOOK line is a real turn: "study the whole scene".
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
  } else if (cmp.mode === "look" && !segments.length) {
    segments.push({ type: "look", text: "" });
  }
  if (!segments.length) return;
  cmp.stack = [];
  takeTurn(segments);
}

// Execute the whisper channel's turn (from the profile screen): all stacked
// lines land at the SAME character, then they reply once. The profile stays
// open to show the reply.
function executePrivate() {
  const g = state.active;
  if (!g || !g.profile || g.generating) return;
  const pf = g.profile;
  const segments = [...pf.stack];
  const seg = currentSegment("pm");
  if (seg) segments.push(seg);
  if (!segments.length) return;
  pf.stack = [];
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
  stopLateWatch();
  state.active = {
    id: gameId,
    state: null,
    beats: [],
    generating: true,
    profile: null, // { charId, name, mode, stack, loading, data, error } - the full-screen character view
    give: null,
    inspect: null, // { kind, key|beatId, asking, answer } - the tap-to-inspect modal
    composer: { mode: "do", stack: [] },
    wish: "", // the optional "what do you wish to happen next?" line
    lastTurnIndex: 0, // high-water mark for GET /beats?since= polling
    pendingView: false, // a look turn's image may still be rendering
    revealedArt: new Set(), // art urls already card-revealed (the effect plays once)
  };
  state.view = "play";
  render();
  try {
    const [rawState, rawBeats] = await Promise.all([api.getState(gameId), api.getBeats(gameId)]);
    state.active.state = mapGameState(rawState);
    state.active.beats = mapBeats((rawBeats && rawBeats.beats) || []).map((b) => withVoice(b));
    state.active.lastTurnIndex = lastTurnIndexOf(state.active.beats);
    state.backendOnline = true;
  } catch (err) {
    state.backendOnline = false;
    state.backendError = err.message || "unreachable";
  } finally {
    if (state.active) state.active.generating = false;
    render();
    maybePollForArt();
    watchLateBeats(state.active); // a just-left turn's image may still land
  }
}

// ---------------------------------------------------------------------------
// take a turn
// ---------------------------------------------------------------------------

// Take a turn. `input` is either a plain string (freeform) or an array of tagged
// segments (what the composers build). One POST -> { beats, state }; only the
// state-mutating surfaces lock until the response lands (the partial busy-lock).
async function takeTurn(input) {
  const g = state.active;
  if (!g || g.generating) return;
  const empty = Array.isArray(input) ? !input.length : !String(input || "").trim();
  if (empty) return;
  const wish = captureWish(g);
  const look = Array.isArray(input) && input.some((s) => s.type === "look");
  await resolveTurn(g, () => api.takeAction(g.id, input, wish), { look, echo: echoBeats(g, input) });
}

// Optimistic echo: the player's own line shows the moment they send it (the
// backend's canonical echo replaces it when the turn resolves). The texts
// mirror the wire's echo phrasing so speech renders as speech immediately.
let pendingSeq = 0;
function echoBeats(g, input) {
  const mk = (text, privateWith = null) => ({
    id: `pending-${++pendingSeq}`,
    turnIndex: null,
    seq: 0,
    kind: "action",
    speaker: "player",
    speakerName: null,
    text,
    location: null,
    imageUrl: null,
    audioUrl: null,
    privateWith,
    voiceId: null,
    pending: true,
  });
  if (!Array.isArray(input)) return [mk(String(input))];
  const beats = [];
  for (const seg of input) {
    if (seg.type === "say") {
      beats.push(mk(`you say "${seg.text}"${seg.target ? ` to ${seg.target}` : ""}`));
    } else if (seg.type === "whisper") {
      // route into the open profile's private thread
      const pf = g.profile;
      const cid = pf && (pf.name === seg.target || pf.charId === seg.target) ? pf.charId : seg.target;
      beats.push(
        mk(
          seg.mode === "do" ? `you discreetly: ${seg.text}` : `you whisper to ${seg.target}: "${seg.text}"`,
          cid,
        ),
      );
    } else if (seg.type === "look") {
      beats.push(mk(seg.text ? `you look at ${seg.text}` : "you study the scene"));
    } else if (seg.type === "attack") {
      beats.push(mk(`you attack ${seg.target}`));
    } else if (seg.type === "give") {
      beats.push(mk(`you offer ${seg.item} to ${seg.target}`));
    } else if (seg.text) {
      beats.push(mk(seg.text));
    }
  }
  return beats;
}

// "Continue": the narrator advances the story with no player input. Same
// locking and reveal as /action; no player beat comes back.
async function continueStory() {
  const g = state.active;
  if (!g || g.generating) return;
  const wish = captureWish(g);
  await resolveTurn(g, () => api.continueStory(g.id, wish));
}

// The wish is a hope whispered to the storyteller, never an action: it rides
// along on the next send (action or continue) and clears after each send.
function captureWish(g) {
  const el = root.querySelector("#wishInput");
  const wish = String((el && el.value) || g.wish || "").trim();
  g.wish = "";
  if (el) el.value = "";
  return wish || null;
}

// Shared turn resolver (action / continue): one POST -> { beats, state },
// then the diff cues, the staged reveal, and the post-turn image watch. The
// optimistic `echo` beats render instantly and are swapped for the backend's
// canonical player echoes when the response lands (or dropped on failure).
async function resolveTurn(g, send, { look = false, echo = null } = {}) {
  g.generating = true;
  g.skipReveal = true; // fast-forward any reveal still running from last turn
  stopLateWatch(); // the new turn supersedes the previous watch window
  if (echo && echo.length) g.beats = [...g.beats, ...echo];
  render();

  try {
    const turn = await send();
    g.beats = g.beats.filter((b) => !b.pending); // the canonical echoes replace ours
    const prevState = g.state;
    g.state = mapGameState(turn.state);
    g.changes = diffState(prevState, g.state); // what transitioned this turn
    const seen = new Set(g.beats.map((b) => b.id));
    const newBeats = mapBeats(turn.beats || [])
      .filter((b) => !seen.has(b.id))
      .map((b) => withVoice(b));
    g.beats = [...g.beats, ...newBeats];
    g.lastTurnIndex = lastTurnIndexOf(g.beats, g.lastTurnIndex);
    g.revealQueue = newBeats.map((b) => b.id); // staged reveal, in seq order
    g.skipReveal = false;
    // a look turn may earn an image; it renders in the background and lands as
    // a late image beat (the watcher below catches it)
    g.pendingView = Boolean(look && g.state.imagesEnabled);
    state.backendOnline = true;
  } catch (err) {
    g.beats = g.beats.filter((b) => !b.pending); // the turn never happened
    state.backendError = err.message || "Turn failed";
    if (err.status === 0) state.backendOnline = false;
    showToast(err.message || "The backend did not accept that action.");
  } finally {
    g.generating = false;
    render();
    applyTransitions(g); // notices + one-shot flashes from the diff
    startReveal(g);
    maybePollForArt();
    watchLateBeats(g); // narrator images + item unlock cards land seconds later
    if (g.profile) refreshProfile(g); // the open profile reflects the new turn
  }
}

function lastTurnIndexOf(beats, fallback = 0) {
  let max = Number.isInteger(fallback) ? fallback : 0;
  for (const b of beats) if (Number.isInteger(b.turnIndex) && b.turnIndex > max) max = b.turnIndex;
  return max;
}

// ---------------------------------------------------------------------------
// Post-turn image watch: narrator-granted images (look turns, dramatic moments)
// and item unlock cards render in the BACKGROUND and land as new image beats a
// few seconds after the turn. Poll GET /beats?since=<last turn_index> every ~3s
// for ~45s and append what arrives through the usual staged reveal.
// ---------------------------------------------------------------------------

const LATE_BEAT_INTERVAL = 3000;
const LATE_BEAT_TICKS = 15; // ~45s window

function watchLateBeats(g) {
  stopLateWatch();
  if (!g || !Number.isInteger(g.lastTurnIndex)) return;
  let ticks = 0;
  lateTimer = setInterval(async () => {
    ticks += 1;
    if (state.active !== g || state.view !== "play" || ticks > LATE_BEAT_TICKS) {
      stopLateWatch();
      // the window expired without an image: that is normal (the narrator may
      // decide no image); just drop the hint
      if (g.pendingView) {
        g.pendingView = false;
        if (state.active === g && state.view === "play") render();
      }
      return;
    }
    try {
      const res = await api.getBeats(g.id, g.lastTurnIndex);
      const seen = new Set(g.beats.map((b) => b.id));
      const fresh = mapBeats((res && res.beats) || [])
        .filter((b) => !seen.has(b.id))
        .map((b) => withVoice(b));
      if (!fresh.length) return;
      g.beats = [...g.beats, ...fresh];
      g.lastTurnIndex = lastTurnIndexOf(g.beats, g.lastTurnIndex);
      if (fresh.some((b) => b.kind === "image" && b.speaker !== "system")) g.pendingView = false;
      g.revealQueue = [...(g.revealQueue || []), ...fresh.map((b) => b.id)];
      render();
      startReveal(g);
    } catch {
      /* keep watching */
    }
  }, LATE_BEAT_INTERVAL);
}

function stopLateWatch() {
  if (lateTimer) clearInterval(lateTimer);
  lateTimer = null;
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
  // Autoplay is split: narration follows `autoplayNarrator`, character lines
  // (public dialogue AND private whispers) follow `autoplayCharacters`.
  let prepared = null;
  if (autoplayFor(beat) && beat.voiceId && voice.enabled) {
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

function autoplayFor(beat) {
  return beat.kind === "narration" ? Boolean(state.settings.autoplayNarrator) : Boolean(state.settings.autoplayCharacters);
}

function nextVoicedBeat(g, afterId) {
  const queue = g.revealQueue || [];
  const from = queue.indexOf(afterId);
  for (let i = from + 1; i < queue.length; i++) {
    const b = g.beats.find((x) => x.id === queue[i]);
    if (b && b.voiceId && (b.kind === "narration" || b.kind === "dialogue") && autoplayFor(b)) return b;
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
  // dialogue types the same quote-stripped text the bubble renders
  const paras =
    beat.kind === "narration" ? String(beat.text || "").split(/\n{2,}/) : [stripWrappingQuotes(beat.text)];
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
// bottom (scrolling up to read pauses the follow). The whisper thread in the
// profile follows the same rule, so private replies keep it pinned to the
// newest line as they type.
function followStory() {
  const story = root.querySelector("#storyStream");
  if (story && storyNearBottom(story)) story.scrollTop = story.scrollHeight;
  const thread = root.querySelector("#pmThread");
  if (thread && storyNearBottom(thread)) thread.scrollTop = thread.scrollHeight;
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

// (the old synchronous "See" eye-flow is gone: LOOK is a first-class action
// segment now, and its image arrives async as a late image beat)

// ---------------------------------------------------------------------------
// game settings (PATCH /games/{id}/settings) + export / import
// ---------------------------------------------------------------------------

async function patchGameSettings(key, value) {
  const g = state.active;
  if (!g || !g.state || g.settingsSaving) return;
  g.settingsSaving = true;
  render();
  try {
    const res = await api.patchSettings(g.id, { [key]: value });
    if (res && res.settings) {
      g.state.settings = {
        difficulty: res.settings.difficulty || "normal",
        narratorGender: res.settings.narrator_gender || "",
      };
    }
    // a narrator_gender change redesigns the narrator voice from the next line
    if (res && "narrator_voice_id" in res) g.state.narratorVoiceId = res.narrator_voice_id || null;
    state.backendOnline = true;
  } catch (err) {
    showToast(err.message || "Could not change that setting.");
  } finally {
    g.settingsSaving = false;
    render();
  }
}

// Export an adventure card: fetch the JSON, hand it to the browser as a download.
async function exportGame(gameId, kind, title) {
  if (!gameId) return;
  try {
    const data = await api.exportGame(gameId, kind);
    render(); // the choice modal is gone; reflect it
    const slug =
      String(title || "adventure")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "") || "adventure";
    downloadJson(data, `${slug}-${kind}.json`);
    showToast(kind === "template" ? "Adventure exported - share the file." : "This moment is saved.");
  } catch (err) {
    render();
    showToast(err.message || "Could not export this adventure.");
  }
}

function downloadJson(data, filename) {
  if (typeof URL === "undefined" || typeof URL.createObjectURL !== "function") return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

// Import a previously exported adventure (template or checkpoint): always a
// NEW game; navigate straight into it.
async function importGameFile(file) {
  if (!file || state.importing) return;
  let payload;
  try {
    payload = JSON.parse(await readFileText(file));
  } catch {
    showToast("That file is not a gamentic export.");
    return;
  }
  state.importing = true;
  render();
  try {
    const res = await api.importGame(payload);
    state.importing = false;
    openGame(res.game_id);
  } catch (err) {
    state.importing = false;
    showToast(err.message || "That file is not a gamentic export.");
    render();
  }
}

// Blob.text() with a FileReader fallback (older engines / jsdom variants).
function readFileText(file) {
  if (typeof file.text === "function") return file.text();
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(r.error);
    r.readAsText(file);
  });
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

// The per-beat speak button is a little state machine: click -> LOADING while
// the line synthesizes, PLAYING while the audio runs (click again to stop),
// then back to the plain speaker when it finishes.
async function speakBeat(beatId) {
  const g = state.active;
  const beat = g && g.beats.find((b) => b.id === beatId);
  if (!beat) return;
  if (speaking && speaking.beatId === beatId) {
    // clicking the busy beat again stops it
    voice.stop();
    setSpeaking(null);
    return;
  }
  setSpeaking({ beatId, phase: "loading" });
  const prepared = await voice.prepare({ text: beat.text, voiceId: beat.voiceId });
  if (!speaking || speaking.beatId !== beatId) return; // stopped or superseded meanwhile
  if (!prepared) return setSpeaking(null); // synth failed; the text is on screen
  const el = voice.playUrl(prepared.audioUrl, beat.speaker);
  if (!el) return setSpeaking(null);
  setSpeaking({ beatId, phase: "playing" });
  const done = () => {
    if (speaking && speaking.beatId === beatId) setSpeaking(null);
  };
  el.addEventListener("ended", done);
  el.addEventListener("pause", done); // stop() pauses
  el.addEventListener("error", done);
}

function setSpeaking(next) {
  speaking = next;
  applySpeakStates();
}

// Patch the speak buttons in place (no full render: never disturb reading or a
// running typewriter). render() re-applies it after every rebuild.
function applySpeakStates() {
  root.querySelectorAll('[data-act="speak-beat"]').forEach((btn) => {
    const mine = speaking && btn.dataset.beatId === speaking.beatId;
    const loading = Boolean(mine && speaking.phase === "loading");
    const playing = Boolean(mine && speaking.phase === "playing");
    btn.classList.toggle("speak-loading", loading);
    btn.classList.toggle("speak-playing", playing);
    const label = loading ? "Preparing voice..." : playing ? "Stop voice" : "Play voice";
    btn.setAttribute("aria-label", label);
    btn.setAttribute("title", label);
  });
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
