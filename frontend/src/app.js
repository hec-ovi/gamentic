// Gamentic frontend controller.
//
// One in-memory `state`, one render() that rebuilds the DOM, and event handlers
// that mutate state + re-render. No mock games, no streaming machinery: the
// real backend is sequential (one POST /action -> { beats, state }).
//
// This file is the BOOT facade: the controller lives in src/app/ (one module
// per concern - see frontend/INDEX.md), and only `init()` is public.

import { state, voice, root, setRoot } from "./app/ctx.js";
import { render } from "./app/ui.js";
import { refreshLibrary } from "./app/game.js";
import { resetCreator } from "./app/creatorctl.js";
import { maybeOpenLightbox, retryFailedImage } from "./app/media.js";

// ---------------------------------------------------------------------------
// boot. Exported so tests can mount the app against a fresh DOM + mocked network
// (vi.resetModules() between tests gives each one its own module state).
// ---------------------------------------------------------------------------

export function init(opts = {}) {
  setRoot(opts.root || document.querySelector("#app"));
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

if (typeof document !== "undefined" && document.querySelector("#app")) {
  init();
}

// expose minimal hooks for debugging
window.__gamentic = { state, voice, render };
