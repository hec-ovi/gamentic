// The composer controllers: Do/Say/Look modes, the current line as a wire
// segment, stacking, and the public/private execute paths.

import { buildSegment, clearComposer, serializeComposer } from "../composer.js";
import { root, state } from "./ctx.js";
import { takeTurn } from "./turns.js";
import { focusComposer, render } from "./ui.js";

// Toggle Do/Say/Look in place (no re-render: a render would wipe the typed line).
export const MODE_PLACEHOLDERS = {
  cmp: {
    do: "Do or say anything... (Enter sends)",
    say: "What do you say?",
    look: "Look at what? (empty = study the whole scene)",
  },
};

export function setComposerMode(holder, scope, mode) {
  if (!holder || (mode !== "say" && mode !== "do" && mode !== "look")) return;
  holder.mode = mode;
  root.querySelectorAll(`[data-act="${scope}-mode"]`).forEach((b) => {
    const on = b.dataset.mode === mode;
    b.classList.toggle("active", on);
    b.setAttribute("aria-pressed", String(on));
  });
  const input = root.querySelector(`#${scope}Input`);
  if (input) {
    const pf = state.active && state.active.profile;
    const name = pf ? pf.name : "";
    input.dataset.placeholder =
      scope === "pm"
        ? mode === "say"
          ? `Whisper to ${name}...`
          : mode === "look"
            ? `Look at what? (${name}, a detail, the room...)`
            : `A discreet act only ${name} notices...`
        : MODE_PLACEHOLDERS.cmp[mode];
    input.setAttribute(
      "aria-label",
      mode === "say" ? "What you say" : mode === "look" ? "What you look at" : "What you do",
    );
    input.focus();
  }
}

// Pull the current line out of a composer as a wire segment, or null if empty.
// (A look line may be empty on SEND - "study the whole scene" - but an empty
// line is never worth stacking, so empty stays null here.)
export function currentSegment(scope) {
  const g = state.active;
  if (!g) return null;
  const input = root.querySelector(`#${scope}Input`);
  const { text, refs } = serializeComposer(input);
  if (!text) return null;
  const pm = scope === "pm" ? g.profile : null;
  const channel = pm ? { kind: "whisper", target: pm.name } : null;
  const mode = (pm || g.composer || {}).mode || "do";
  clearComposer(input);
  return buildSegment({ mode, text, refs, channel });
}

// "+": stack the current line to execute together with the rest of the turn.
export function stackSegment(scope) {
  const g = state.active;
  if (!g) return;
  const holder = scope === "pm" ? g.profile : g.composer;
  const seg = currentSegment(scope);
  if (!holder || !seg) return;
  holder.stack.push(seg);
  render();
  focusComposer(`#${scope}Input`);
}

export function unstackSegment(holder, index) {
  if (!holder) return;
  holder.stack.splice(Number(index), 1);
  render();
}

// Send from the main composer: stacked segments + the current line, one POST.
// A single plain "do" line with no tags stays a freeform { action } (the
// narrator likes raw words); anything tagged/stacked/spoken goes as segments.
// An empty LOOK line is a real turn: "study the whole scene".
export function executeComposer() {
  const g = state.active;
  if (!g || g.generating) return;
  const cmp = g.composer || (g.composer = { mode: "do", stack: [] });
  const input = root.querySelector("#cmpInput");
  const { text, refs } = serializeComposer(input);
  clearComposer(input);

  const segments = [...cmp.stack];
  if (text) {
    if (!segments.length && !refs.length && cmp.mode === "do") {
      cmp.stack = [];
      takeTurn(text);
      return;
    }
    segments.push(buildSegment({ mode: cmp.mode, text, refs, channel: null }));
  } else if (cmp.mode === "look" && !segments.length) {
    segments.push({ type: "look", text: "" });
  }
  if (!segments.length) return;
  cmp.stack = [];
  takeTurn(segments);
}

// Execute the whisper channel's turn (from the profile screen): all stacked
// lines land at the SAME character, then they reply once. The profile stays
// open to show the reply.
export function executePrivate() {
  const g = state.active;
  if (!g || !g.profile || g.generating) return;
  // you cannot whisper to someone who is not here (the composer does not
  // render for the absent/dead; this guard covers anything that slips through)
  const pc = (g.state.characters || []).find((x) => x.id === g.profile.charId);
  const here = g.state.player && g.state.player.location;
  if (!pc || !pc.alive || !pc.present || (here && pc.location !== here)) return;
  const pf = g.profile;
  const segments = [...pf.stack];
  const seg = currentSegment("pm");
  if (seg) segments.push(seg);
  else if (pf.mode === "look" && !segments.length) segments.push({ type: "look", text: "" });
  if (!segments.length) return;
  pf.stack = [];
  takeTurn(segments, pf.charId); // results mirror into this character's panel
}
