// The render/bind cycle and the action dispatcher: state in, DOM out, events
// wired on [data-act] markup.

import { renderApp } from "../render.js";
import { executeComposer, executePrivate, setComposerMode, stackSegment, unstackSegment } from "./composerctl.js";
import { beginAdventure, clearCreatorSession, enterCreator, resetCreator, sendCreatorMessage } from "./creatorctl.js";
import { root, state, storyNearBottom, voice } from "./ctx.js";
import { showHelp } from "./cues.js";
import { exportGame, importGameFile, markArtReveals, openGame, refreshLibrary, removeGame, stopPolling, wipeEverything } from "./game.js";
import { closeTagger, doExplain, doGive, onCharAction, openInspect, openTagger, takeSceneAction } from "./playctl.js";
import { openProfile, switchProfileTab } from "./profilectl.js";
import { patchGameSettings, updateSetting } from "./settingsctl.js";
import { applySpeakStates, speakBeat } from "./speech.js";
import { continueStory, stopLateWatch, takeTurn } from "./turns.js";

// ---------------------------------------------------------------------------
// render + event binding
// ---------------------------------------------------------------------------

// Inner scroll surfaces (besides the story, which has its own pin-to-bottom
// rule) whose position must SURVIVE a full rebuild - a re-render must never
// read as a "refresh".
const KEEP_SCROLL = [".char-column", ".set-main", ".profile-main"];

export function render() {
  closeTagger();
  // chat scroll rule: keep the reader's place across rebuilds; pin to the
  // bottom only when they were already reading at the bottom.
  const story = root.querySelector("#storyStream");
  const stick = !story || storyNearBottom(story);
  const prevTop = story ? story.scrollTop : 0;
  const kept = KEEP_SCROLL.map((sel) => {
    const el = root.querySelector(sel);
    return el && el.scrollTop ? [sel, el.scrollTop] : null;
  }).filter(Boolean);
  root.dataset.view = state.view;
  root.innerHTML = renderApp(state);
  bind();
  kept.forEach(([sel, top]) => {
    const el = root.querySelector(sel);
    if (el) el.scrollTop = top;
  });
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

// Wire events on freshly-built markup. `scope` defaults to the whole app (a
// full render); an in-place patch (e.g. a profile tab switch) passes just the
// replaced subtree so existing elements never collect duplicate listeners.
export function bind(scope = root) {
  scope.querySelectorAll("[data-act]").forEach((el) => {
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

  scope.querySelector('[data-form="action"]')?.addEventListener("submit", (e) => {
    e.preventDefault();
    executeComposer();
  });
  scope.querySelector('[data-form="private"]')?.addEventListener("submit", (e) => {
    e.preventDefault();
    executePrivate();
  });
  // Enter in a composer line = submit its form (the contenteditable line is
  // single-line; newlines have no meaning in a segment)
  scope.querySelectorAll(".composer-input").forEach((el) => {
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
  scope.querySelector("#storyStream")?.addEventListener("click", () => {
    const g = state.active;
    if (g && g.revealing) g.skipReveal = true;
  });
  scope.querySelector('[data-form="creator"]')?.addEventListener("submit", (e) => {
    e.preventDefault();
    const input = e.currentTarget.querySelector('[name="creatorText"]');
    sendCreatorMessage(input.value);
    input.value = "";
  });

  scope.querySelectorAll("[data-setting]").forEach((el) => {
    const evt = el.type === "range" ? "input" : "change";
    el.addEventListener(evt, () => updateSetting(el));
  });

  // per-adventure settings (difficulty / narrator voice) -> PATCH /settings
  scope.querySelectorAll("[data-game-setting]").forEach((el) => {
    el.addEventListener("change", () => patchGameSettings(el.dataset.gameSetting, el.value));
  });

  // the wish line survives re-renders via state (it is not a form of its own)
  scope.querySelector("#wishInput")?.addEventListener("input", (e) => {
    if (state.active) state.active.wish = e.target.value;
  });

  // library import: file picker -> POST /games/import
  scope.querySelector("#importFile")?.addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";
    importGameFile(file);
  });

  scope.querySelectorAll("[data-help]").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      showHelp(el);
    });
  });
}

export function onAction(act, el) {
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
