// The full-screen character profile: open, refetch after turns, and in-place
// tab switching (no full re-render, no flicker).

import { mapProfile } from "../adapters.js";
import { renderProfilePane } from "../render.js";
import { api, root, state } from "./ctx.js";
import { bind, focusComposer, render, scrollToBottom } from "./ui.js";

// ---------------------------------------------------------------------------
// the full-screen character profile (+ the private whisper channel inside it)
// ---------------------------------------------------------------------------

// Open the profile screen. Read-only, so it works mid-turn too. The whisper
// composer state (mode/stack) lives on it; the data refetches on open and
// after each turn while it stays open.
export function openProfile(charId, name) {
  const g = state.active;
  if (!g || !g.state) return;
  g.profile = { charId, name, tab: "profile", mode: "say", stack: [], loading: true, data: null, error: "", arrive: true };
  g.give = null;
  render();
  g.profile.arrive = false; // the entrance fade plays once; refetches re-render without it
  refreshProfile(g);
}

// Switch the profile tab by patching the PANE in place: no full re-render, so
// the screen and its big art never flicker - the swap is instant.
export function switchProfileTab(tab) {
  const g = state.active;
  if (!g || !g.profile || g.profile.tab === tab) return;
  g.profile.tab = tab;
  const pane = root.querySelector(".profile-pane");
  if (!pane) return render(); // pane not on screen (still loading): full render
  pane.innerHTML = renderProfilePane(g.state, g);
  bind(pane); // only the fresh subtree: nothing else double-binds
  root.querySelectorAll(".profile-tab").forEach((t) => {
    const on = t.dataset.tab === tab;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", String(on));
  });
  if (tab === "whisper") {
    scrollToBottom("#pmThread");
    focusComposer("#pmInput");
  }
}

export async function refreshProfile(g) {
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
