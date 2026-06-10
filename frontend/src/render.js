// Pure-ish rendering: turn the view model into HTML strings.
//
// The most important rule (the heart of the feel):
//   - NARRATION renders as flowing STORY PROSE. No bubble, no "Narrator:" label.
//     It is just the text of the game, set like a book.
//   - DIALOGUE renders as a distinct named bubble/card carrying the character's
//     identity (name + color, avatar when present).
//   - PLAYER actions render as a quiet inline marker, not a competing chat bubble.
//   - SYSTEM beats render as small animated badges (the "juice").
//
// All dynamic text is escaped. Help "?" buttons carry data-help="<key>".
//
// This file is the FACADE: one module per screen/concern lives in src/render/,
// and the public surface (what app.js and the tests import) is re-exported
// here so callers never need to know the file layout.

import { renderMenu, renderLibrary, renderCreator, renderSettings } from "./render/screens.js";
import { renderPlay } from "./render/play.js";

export { HELP, escapeHtml, stripWrappingQuotes, initials } from "./render/common.js";
export { playerSpeech } from "./render/story.js";
export { renderProfilePane } from "./render/profile.js";

// ---------------------------------------------------------------------------
// Top-level shell
// ---------------------------------------------------------------------------

export function renderApp(state) {
  if (state.view === "menu") return renderMenu(state);
  if (state.view === "library") return renderLibrary(state);
  if (state.view === "creator") return renderCreator(state);
  if (state.view === "settings") return renderSettings(state);
  return renderPlay(state);
}
