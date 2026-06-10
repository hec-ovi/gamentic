// Game lifecycle: the library, opening a game, delete/wipe, export/import,
// and the late-art /state polling.

import { mapBeats, mapGameState } from "../adapters.js";
import { clearCreatorSession, resetCreator } from "./creatorctl.js";
import { api, root, state, voice } from "./ctx.js";
import { showToast } from "./cues.js";
import { announceImage } from "./reveal.js";
import { withVoice } from "./speech.js";
import { lastTurnIndexOf, stopLateWatch, watchLateBeats } from "./turns.js";
import { render } from "./ui.js";

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
    stopPolling();
    stopLateWatch();
    voice.stop();
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

// Export an adventure card: fetch the JSON, hand it to the browser as a download.
export async function exportGame(gameId, kind, title) {
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

export function downloadJson(data, filename) {
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

export let pollTimer = null; // late-art /state polling

// (turn autoplay is handled by the staged reveal: each speech beat's audio is
// prepared in a pipeline and played when that beat reveals)

// ---------------------------------------------------------------------------
// late-arriving art: media is optional + async (image gen lags). Poll /state
// until the scene image and character faces fill in, then slot them in. Slots
// already reserve space so swapping art in never relayouts.
// ---------------------------------------------------------------------------

export function artMissing(s) {
  if (!s) return false;
  // images_enabled is the rule: false means images are OFF - nothing is coming,
  // show static placeholders and never poll.
  if (!s.imagesEnabled) return false;
  const sceneMissing = s.scene && !s.scene.imageUrl;
  const portraitMissing = (s.characters || []).some((c) => c.alive && c.present && (!c.faceUrl || !c.bodyUrl));
  return Boolean(sceneMissing || portraitMissing);
}

export function maybePollForArt() {
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

export function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}
