// The story creator: persisted chat sessions, restore-on-entry, finalize.

import { api, rand, root, state } from "./ctx.js";
import { openGame } from "./game.js";
import { render } from "./ui.js";

// ---------------------------------------------------------------------------
// creator
// ---------------------------------------------------------------------------

// Creator sessions persist server-side and survive restarts; we keep the
// session id in localStorage so a page refresh restores the chat in progress.
export const CREATOR_SESSION_KEY = "gamentic.creator.session";

export function savedCreatorSession() {
  try {
    return localStorage.getItem(CREATOR_SESSION_KEY) || null;
  } catch {
    return null;
  }
}

export function storeCreatorSession(id) {
  try {
    localStorage.setItem(CREATOR_SESSION_KEY, id);
  } catch {
    /* ignore quota */
  }
}

export function clearCreatorSession() {
  try {
    localStorage.removeItem(CREATOR_SESSION_KEY);
  } catch {
    /* ignore */
  }
}

// Entering the creator: restore an in-progress session when one is stored,
// otherwise start fresh. A 404 means the backend no longer knows it.
export async function enterCreator() {
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
  } catch (err) {
    // only a backend that genuinely no longer knows the session clears it; a
    // network blip / 5xx keeps the pointer so the next entry retries
    if (err.status === 404 || err.status === 410) clearCreatorSession();
  } finally {
    c.busy = false;
    if (state.view === "creator") render();
  }
}

export function resetCreator() {
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

export async function sendCreatorMessage(raw) {
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
    // the reply landed: hand the keyboard back to the chat box (owner: never
    // make the player click the box again after every reply)
    root.querySelector('[name="creatorText"]')?.focus();
  }
}

export async function beginAdventure() {
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
    root.querySelector('[name="creatorText"]')?.focus();
  }
}
