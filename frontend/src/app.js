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
import { stopMediaWatch } from "./app/mediastream.js";
import { resetCreator } from "./app/creatorctl.js";
import { maybeOpenLightbox, retryFailedImage } from "./app/media.js";
import { followStory } from "./app/reveal.js";

// Late-loading images shift the layout AFTER the join-scroll has already
// happened; keep the reader pinned to the newest content when that's where
// they were (owner: never land mid-history because a picture finished last).
function followOnAssetLoad(e) {
  const t = e.target;
  if (t && t.tagName === "IMG" && t.closest && (t.closest("#storyStream") || t.closest("#pmThread"))) followStory();
}

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
  // load events don't bubble either -> capture
  root.addEventListener("load", followOnAssetLoad, true);
  // Lightbox: any game image opens full size (stored files are larger than
  // their slots). Capture phase so it also works inside modal wrappers; images
  // inside action buttons (item slots) keep their own click meaning.
  root.addEventListener("click", maybeOpenLightbox, true);
  // Grant audio playback on the first user gesture: speakBeat awaits synthesis
  // before playing, so without this the play() runs outside the click's task and
  // the browser can silently block it. Capture + once, cheap and idempotent.
  root.addEventListener("pointerdown", () => voice.unlock(), { capture: true, once: true });
  resetCreator();
  render();
  refreshLibrary();
  return {
    state,
    voice,
    // tear an instance fully down (tests mount many per file; without this a
    // finished test's pollers keep firing into the next one's network)
    destroy() {
      stopMediaWatch();
      voice.stop();
      voice.flush();
    },
  };
}

if (typeof document !== "undefined" && document.querySelector("#app")) {
  init();
}

// expose minimal hooks for debugging
window.__gamentic = { state, voice, render };
