// The app context: the ONE in-memory state, the voice engine, the API client
// and the root element, shared by every controller module as live bindings.

import { createApi } from "../api.js";
import { Voice } from "../voice.js";

export const STORAGE_KEY = "gamentic.v2";

// `root` and `api` are reassigned through setters: imported bindings are
// read-only in ES modules, so every other module reads the live binding and
// only this module writes it.
export let root = null;
export function setRoot(el) {
  root = el;
}

export const state = {
  view: "menu", // menu | library | creator | play | settings
  games: [], // raw library entries from GET /games
  backendOnline: false,
  backendError: "",
  active: null, // { id, state(mapped), beats(mapped), generating, composer, profile, give, revealedArt }
  creator: { sessionId: "creator-" + rand(), messages: [], busy: false, error: "" },
  confirm: null, // { gameId, title } when a delete confirmation is open
  exportChoice: null, // { gameId, title } when a card's export choice (share/save) is open
  wipe: null, // { stage: 1|2, busy } when the wipe-all double confirm is open
  settings: loadSettings(),
};

export const voice = new Voice();
voice.applySettings(state.settings);

export let api = createApi(state.settings.backendUrl);
export function setApi(backendUrl) {
  api = createApi(backendUrl);
}

export function loadSettings() {
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

export function saveSettings() {
  try {
    // _return is navigation state (where settings was opened from), not a setting
    const { _return, ...persisted } = state.settings;
    void _return;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(persisted));
  } catch {
    /* ignore quota */
  }
}

export function storyNearBottom(el) {
  return el.scrollHeight - el.scrollTop - el.clientHeight < 140;
}

// CSS.escape fallbacks for ids / attribute values used in selectors
export function cssId(v) {
  const s = String(v ?? "");
  return typeof CSS !== "undefined" && CSS.escape ? CSS.escape(s) : s.replace(/["\\\]]/g, "\\$&");
}

export function cssAttr(v) {
  return String(v ?? "").replace(/["\\]/g, "\\$&");
}

export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function rand() {
  return Math.random().toString(36).slice(2, 10);
}
