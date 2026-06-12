// The render cycle and the action dispatcher: state in, DOM morphed, events
// DELEGATED on [data-act] markup (five listeners on the root, attached once;
// re-renders never re-wire anything).

import { Idiomorph } from "../../vendor/idiomorph.esm.js";
import { markPmSeen } from "../adapters.js";
import { renderApp } from "../render.js";
import { executeComposer, executePrivate, setComposerMode, stackSegment, unstackSegment } from "./composerctl.js";
import { beginAdventure, clearCreatorSession, enterCreator, resetCreator, sendCreatorMessage } from "./creatorctl.js";
import { root, state, storyNearBottom, torn, voice } from "./ctx.js";
import { showHelp } from "./cues.js";
import { exportGame, importGameFile, markArtReveals, openGame, refreshLibrary, removeGame, wipeEverything } from "./game.js";
import { stopMediaWatch } from "./mediastream.js";
import { closeTagger, doExplain, doGive, onCharAction, openInspect, openTagger, takeSceneAction } from "./playctl.js";
import { openProfile, switchProfileTab } from "./profilectl.js";
import { applyMemorySetting, patchGameSettings, updateSetting } from "./settingsctl.js";
import { applySpeakStates, speakBeat } from "./speech.js";
import { continueStory, takeTurn } from "./turns.js";

// ---------------------------------------------------------------------------
// render + event binding
// ---------------------------------------------------------------------------

// In-progress typed input must SURVIVE a full rebuild: background renders (a
// late image beat landing, the art poll, a profile refetch) fire exactly in
// the post-turn typing window. The morph preserves the composer nodes and a
// callback shields their children; this snapshot is the belt-and-braces for
// the plain-value inputs (the creator line) the morph can still clear.
const KEEP_INPUT = ["#cmpInput", "#pmInput"];

function snapshotInputs() {
  const focused = typeof document !== "undefined" ? document.activeElement : null;
  const kept = [];
  for (const sel of KEEP_INPUT) {
    const el = root.querySelector(sel);
    // chips are markup, so preserve innerHTML, not textContent
    if (el && el.innerHTML) kept.push({ sel, html: el.innerHTML, focus: el === focused });
  }
  const creator = root.querySelector('[name="creatorText"]');
  if (creator && creator.value) kept.push({ sel: '[name="creatorText"]', value: creator.value, focus: creator === focused });
  return kept;
}

function restoreInputs(kept) {
  for (const s of kept) {
    const el = root.querySelector(s.sel);
    if (!el) continue;
    if (s.value != null) {
      if (!el.value) el.value = s.value;
    } else if (!el.innerHTML) {
      el.innerHTML = s.html;
    }
    if (s.focus) {
      el.focus();
      placeCaretAtEnd(el);
    }
  }
}

// Typing continues from the end of the restored line (chip-aware caret
// offsets are not worth their complexity; the end is where typing happens).
function placeCaretAtEnd(el) {
  if (el.isContentEditable === false && el.setSelectionRange) {
    try {
      el.setSelectionRange(el.value.length, el.value.length);
    } catch {
      /* non-text input */
    }
    return;
  }
  if (typeof window === "undefined" || !window.getSelection || !el.isContentEditable) return;
  const range = document.createRange();
  range.selectNodeContents(el);
  range.collapse(false);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
}

export function render() {
  if (torn || !root) return; // a torn-down instance must not touch the DOM/globals
  delegate();
  closeTagger();
  // chat scroll rule: pin to the bottom only when the reader was already
  // there (the morph keeps every preserved node's scroll position itself).
  const story = root.querySelector("#storyStream");
  const stick = !story || storyNearBottom(story);
  const keptInputs = snapshotInputs();
  root.dataset.view = state.view;
  // While a character's Whisper tab is the open pane, every private beat in
  // hand counts as SEEN. Mark BEFORE building the HTML so the cast-card dot and
  // the tab badge (which both read the seen marker) render already-cleared this
  // same pass - no separate timer, no one-render lag.
  if (state.view === "play" && state.active && state.active.profile) {
    const pf = state.active.profile;
    if (pf.tab === "whisper") markPmSeen(state.active, pf.charId);
  }
  // MORPH, don't rebuild: idiomorph diffs the real DOM against the fresh
  // HTML and patches in place, so unchanged nodes keep their identity -
  // focus, caret, scroll positions and mid-flight animations all survive a
  // background render structurally instead of via hand-rolled restores.
  Idiomorph.morph(root, renderApp(state), {
    morphStyle: "innerHTML",
    // NO ignoreActiveValue: state is the single source of truth for control
    // values (the wish line syncs per keystroke, radios re-check from the
    // PATCH echo); skipping the active element would let a mid-save render's
    // native radio-group unchecking stick. Free-typed surfaces are protected
    // separately (the composer callback below + the input snapshot).
    callbacks: {
      // the composer contenteditables always RENDER empty; their live
      // children ARE the draft - a morph must never remove them
      beforeNodeRemoved: (node) => {
        const parent = node.parentNode;
        return !(parent && parent.nodeType === 1 && parent.closest && parent.closest(".composer-input"));
      },
    },
  });
  restoreInputs(keptInputs);
  if (state.view === "play") {
    if (stick) scrollStory();
    // the whisper thread pins itself to the newest line
    if (state.active && state.active.profile) scrollToBottom("#pmThread");
    markArtReveals(state.active);
    applySpeakStates(); // the morph syncs class attributes, wiping the states
  }
  if (state.view === "creator") scrollCreator();
}

// A scroll pinned before an <img> finishes loading lands above it: the image
// grows the container AFTER the pin (live: a whisper look's picture stayed
// below the fold). Every scrollToBottom arms one-shot load repins on the
// images still loading inside that container.
function repinWhenImagesLoad(selector) {
  const el = root.querySelector(selector);
  if (!el) return;
  el.querySelectorAll("img").forEach((im) => {
    if (im.complete || im.dataset.repin) return;
    im.dataset.repin = "1";
    im.addEventListener("load", () => scrollToBottom(selector), { once: true });
  });
}

// ---------------------------------------------------------------------------
// event DELEGATION: five listeners on the root, attached once per root. The
// morph preserves nodes across renders, so per-element listeners would both
// leak and double-fire; delegation makes wiring independent of rendering
// (an in-place pane patch needs no re-bind either).
// ---------------------------------------------------------------------------

let delegatedRoot = null;

export function delegate() {
  if (!root || delegatedRoot === root) return;
  delegatedRoot = root;
  root.addEventListener("click", onRootClick);
  root.addEventListener("submit", onRootSubmit);
  root.addEventListener("keydown", onRootKeydown);
  root.addEventListener("change", onRootChange);
  root.addEventListener("input", onRootInput);
}

function onRootClick(e) {
  const help = e.target.closest && e.target.closest("[data-help]");
  if (help) {
    e.stopPropagation(); // the popover's own document-level dismiss must not see this click
    showHelp(help);
    return;
  }
  const el = e.target.closest && e.target.closest("[data-act]");
  // a click on the story PROSE instant-finishes the staged reveal (a click on
  // a control inside the story - speak button, receipt - keeps its meaning)
  if (!el && e.target.closest && e.target.closest("#storyStream")) {
    const g = state.active;
    if (g && g.revealing) g.skipReveal = true;
    return;
  }
  if (!el) return;
  // "noop" wrappers (modal bodies over a clickable backdrop): the innermost
  // match wins, so stopping here shields the overlay's act. No preventDefault:
  // form submits from buttons inside the modal must still work.
  if (el.dataset.act === "noop") return;
  e.preventDefault();
  onAction(el.dataset.act, el);
}

function onRootSubmit(e) {
  const form = e.target.closest && e.target.closest("[data-form]");
  if (!form) return;
  e.preventDefault();
  const kind = form.dataset.form;
  if (kind === "action") executeComposer();
  else if (kind === "private") executePrivate();
  else if (kind === "creator") {
    const input = form.querySelector('[name="creatorText"]');
    sendCreatorMessage(input.value);
    input.value = "";
  }
}

// Enter in a composer line = submit its form (the contenteditable line is
// single-line; newlines have no meaning in a segment)
function onRootKeydown(e) {
  if (e.key !== "Enter") return;
  const input = e.target.closest && e.target.closest(".composer-input");
  if (!input) return;
  e.preventDefault();
  const form = input.closest("form");
  if (!form) return;
  if (typeof form.requestSubmit === "function") form.requestSubmit();
  else form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
}

function onRootChange(e) {
  const t = e.target;
  if (!t || !t.matches) return;
  if (t.matches("[data-setting]")) {
    if (t.type !== "range") updateSetting(t); // ranges live-update on input
    return;
  }
  // per-adventure settings (difficulty / voice / pacing) -> PATCH /settings
  if (t.matches("[data-game-setting]")) return patchGameSettings(t.dataset.gameSetting, t.value);
  // the story-memory numeric controls validate their range client-side
  if (t.matches("[data-mem-setting]")) return applyMemorySetting(t);
  // library import: file picker -> POST /games/import
  if (t.id === "importFile") {
    const file = t.files && t.files[0];
    t.value = "";
    importGameFile(file);
  }
}

function onRootInput(e) {
  const t = e.target;
  if (!t || !t.matches) return;
  if (t.matches('[data-setting][type="range"]')) return updateSetting(t);
  // the wish line survives re-renders via state (it is not a form of its own)
  if (t.id === "wishInput" && state.active) state.active.wish = t.value;
}

export function onAction(act, el) {
  const gameId = el.dataset.gameId;
  if (state.active && state.active.generating && MUTATING_ACTS.has(act)) return;
  switch (act) {
    case "new-game":
      enterCreator();
      break;
    case "go-menu":
      stopMediaWatch();
      voice.stop(); // the story must not keep talking over the menu
      voice.flush();
      state.view = "menu";
      render();
      refreshLibrary();
      break;
    case "go-library":
      stopMediaWatch();
      voice.stop();
      voice.flush();
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
    case "inspect-scene":
      openInspect({ kind: "scene", key: (state.active && state.active.state.scene && state.active.state.scene.name) || "scene" });
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
      switchProfileTab(el.dataset.tab);
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
      render(); // close the choice modal NOW, not when the fetch resolves
      exportGame(gameId, el.dataset.kind, el.dataset.gameTitle);
      break;
    case "ask-wipe":
      state.wipe = { stage: 1, busy: false };
      render();
      break;
    case "cancel-wipe":
      if (state.wipe && state.wipe.busy) break;
      state.wipe = null;
      render();
      break;
    case "confirm-wipe":
      if (!state.wipe || state.wipe.busy) break;
      if (state.wipe.stage < 2) {
        state.wipe.stage = 2; // ARMED: one more deliberate click erases
        render();
      } else {
        wipeEverything();
      }
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

// PARTIAL busy-lock: while a turn is in flight, only state-MUTATING acts are
// blocked (their buttons also render disabled - this guard covers anything left
// clickable). Read-only interactions (inspect, /explain, lightbox, profiles,
// settings, scrolling) stay live.
export const MUTATING_ACTS = new Set([
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

// Pin a scroll container to the bottom. Runs on the next frame so it measures
// AFTER the new content has been laid out (a sync scroll right after innerHTML
// can read a stale scrollHeight and miss the latest message).
export function scrollToBottom(selector) {
  const el = root.querySelector(selector);
  if (!el) return;
  el.scrollTop = el.scrollHeight; // immediate best-effort
  const raf = typeof requestAnimationFrame === "function" ? requestAnimationFrame : (fn) => setTimeout(fn, 16);
  raf(() => {
    const e = root.querySelector(selector);
    if (e) e.scrollTop = e.scrollHeight;
  });
  repinWhenImagesLoad(selector);
}

export function scrollStory() {
  scrollToBottom("#storyStream");
}

export function scrollCreator() {
  scrollToBottom("#creatorThread");
}

export function focusComposer(selector) {
  const el = root.querySelector(selector);
  if (el) el.focus();
}
