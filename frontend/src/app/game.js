// Game lifecycle: the library, opening a game, delete/wipe, export/import,
// and the late-art /state polling.

import { mapBeats, mapGameState } from "../adapters.js";
import { clearCreatorSession, resetCreator } from "./creatorctl.js";
import { api, root, state, voice } from "./ctx.js";
import { showToast } from "./cues.js";
import { withVoice } from "./speech.js";
import { lastTurnIndexOf } from "./turns.js";
import { stopMediaWatch, watchMedia } from "./mediastream.js";
import { focusComposer, render } from "./ui.js";

// ---------------------------------------------------------------------------
// library
// ---------------------------------------------------------------------------

export async function refreshLibrary() {
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

// Wipe ALL memory: every game, creator session, voice entry and media folder
// (server-side), then drop every cached game/session trace on this end too.
export async function wipeEverything() {
  state.wipe.busy = true;
  render();
  try {
    await api.wipeAll();
    stopMediaWatch();
    voice.stop();
    voice.flush();
    state.active = null;
    state.confirm = null;
    state.exportChoice = null;
    clearCreatorSession();
    resetCreator();
    state.wipe = null;
    state.view = "library";
    render();
    showToast("Everything is gone. A clean slate.");
    refreshLibrary();
  } catch (err) {
    state.wipe = null;
    render();
    showToast(err.message || "The wipe did not go through.");
  }
}

export async function removeGame(id) {
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

export async function openGame(gameId) {
  stopMediaWatch();
  state.active = {
    id: gameId,
    state: null,
    beats: [],
    generating: true,
    profile: null, // { charId, name, mode, stack, loading, data, error } - the full-screen character view
    give: null,
    inspect: null, // { kind, key|beatId, asking, answer } - the tap-to-inspect modal
    composer: { mode: "say", stack: [] },
    wish: "", // the optional "what do you wish to happen next?" line
    lastTurnIndex: 0, // high-water mark for GET /beats?since= polling
    pendingView: false, // a look turn's image may still be rendering
    revealedArt: new Set(), // art urls already card-revealed (the effect plays once)
  };
  state.view = "play";
  voice.stop(); // the previous game must not keep talking over this one
  voice.flush();
  render();
  try {
    const [rawState, rawBeats] = await Promise.all([api.getState(gameId), api.getBeats(gameId)]);
    state.active.state = mapGameState(rawState);
    state.active.beats = mapBeats((rawBeats && rawBeats.beats) || []).map((b) => withVoice(b));
    state.active.lastTurnIndex = lastTurnIndexOf(state.active.beats);
    state.backendOnline = true;
  } catch (err) {
    // never strand the player on the dead loading screen (it has no controls):
    // back to the library with the reason, retry from there
    if (err.status === 0) {
      state.backendOnline = false;
      state.backendError = err.message || "unreachable";
    }
    state.active = null;
    state.view = "library";
    showToast(err.message || "Could not open that adventure.");
    refreshLibrary();
  } finally {
    if (state.active) state.active.generating = false;
    render();
    watchMedia(state.active); // media-ready push + the slow fallback sweep
    // joining a game seats you at the keyboard, same as a finished turn does
    // (live: activeElement was <body> on entry and the first action needed a click)
    if (state.active && state.view === "play") focusComposer("#cmpInput");
  }
}

// Export an adventure card: fetch the JSON, hand it to the browser as a download.
export async function exportGame(gameId, kind, title) {
  if (!gameId || state.exporting) return; // one export at a time
  state.exporting = true;
  try {
    const data = await api.exportGame(gameId, kind);
    const slug =
      String(title || "adventure")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "") || "adventure";
    downloadJson(data, `${slug}-${kind}.json`);
    showToast(kind === "template" ? "Adventure exported - share the file." : "This moment is saved.");
  } catch (err) {
    showToast(err.message || "Could not export this adventure.");
  } finally {
    state.exporting = false;
  }
}

export function downloadJson(data, filename) {
  if (typeof URL === "undefined" || typeof URL.createObjectURL !== "function") return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // optional-chained: the delayed revoke may outlive a DOM that never had it (jsdom)
  setTimeout(() => URL.revokeObjectURL?.(url), 5000);
}

// Import a previously exported adventure (template or checkpoint): always a
// NEW game; navigate straight into it.
export async function importGameFile(file) {
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
export function readFileText(file) {
  if (typeof file.text === "function") return file.text();
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(r.error);
    r.readAsText(file);
  });
}

// Card-reveal: any [data-art] image not yet seen this session gets the
// collection-card reveal animation, exactly once per url (re-renders rebuild
// the DOM every turn; without the seen-set the effect would replay each time).
export function markArtReveals(g) {
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

