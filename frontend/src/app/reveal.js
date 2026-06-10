// Simulated streaming: the staged beat reveal. The backend computes a turn
// atomically, so the PACING is ours - typewriter prose, instant receipts,
// fading images, voice pipelined per beat.

import { icon } from "../icons.js";
import { stripWrappingQuotes } from "../render.js";
import { cssId, root, sleep, state, storyNearBottom, voice } from "./ctx.js";
import { render } from "./ui.js";

// ---------------------------------------------------------------------------
// Simulated streaming: the backend computes a turn atomically (real token
// streaming is impossible by design), so the PACING is ours. Per beat kind, in
// seq order: system beats + the player's own echo are INSTANT; narration /
// dialogue / private whispers get a fast typewriter (instant-finish on story
// click); image beats fade in when reached. With voice autoplay on, a speech
// beat reveals when ITS audio is ready and the typewriter paces with the
// audio's duration (the next beat's audio renders while this one plays).
// ---------------------------------------------------------------------------

export const REVEAL_CPS = 45; // default typewriter speed (chars/second)

export const REVEAL_TICK = 45; // ms per typewriter tick

export function reducedMotion() {
  try {
    return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

export async function startReveal(g) {
  if (!g || g.revealing || !g.revealQueue || !g.revealQueue.length) return;
  g.revealing = true;
  try {
    while (g.revealQueue && g.revealQueue.length && state.active === g && state.view === "play") {
      const beat = g.beats.find((b) => b.id === g.revealQueue[0]);
      await revealBeat(g, beat);
      g.revealQueue.shift();
    }
  } finally {
    if (g.revealQueue) g.revealQueue.length = 0;
    g.revealing = false;
    g.skipReveal = false;
  }
}

export async function revealBeat(g, beat) {
  if (!beat) return;
  // a beat can render in two places at once (the story AND the talk-modal
  // thread); reveal every copy
  const find = () => [...root.querySelectorAll(`[data-beat-id="${cssId(beat.id)}"]`)];
  const unveil = () => {
    const els = find();
    els.forEach((el) => el.closest(".veil-wrap")?.classList.remove("veiled"));
    return els[0] || null;
  };

  const instant = g.skipReveal || reducedMotion();
  if (beat.kind === "image") {
    const el = unveil();
    if (el) {
      el.classList.add("img-arrive");
      followStory();
      announceImage(el);
    }
    if (!instant) await sleep(350);
    return;
  }

  const fromPlayer = !beat.speaker || beat.speaker === "player";
  const typed = (beat.kind === "narration" || beat.kind === "dialogue") && !fromPlayer;
  if (!typed) {
    unveil();
    followStory();
    if (!instant) await sleep(90);
    return;
  }

  // voice pairing: render this beat's audio first (reveal when ready), then
  // queue the NEXT voiced beat behind it so it renders while this one plays.
  // Autoplay is split: narration follows `autoplayNarrator`, character lines
  // (public dialogue AND private whispers) follow `autoplayCharacters`.
  let prepared = null;
  if (autoplayFor(beat) && beat.voiceId && voice.enabled) {
    const current = voice.prepare({ text: beat.text, voiceId: beat.voiceId, emotion: beat.emotion });
    const next = nextVoicedBeat(g, beat.id);
    if (next) voice.prepare({ text: next.text, voiceId: next.voiceId, emotion: next.emotion });
    prepared = await current;
  }

  const el = unveil();
  if (!el) return;
  if (prepared) voice.playUrl(prepared.audioUrl, beat.speaker);
  if (instant) return;

  const chars = String(beat.text || "").length || 1;
  const cps = prepared && prepared.duration ? Math.min(80, Math.max(15, chars / prepared.duration)) : REVEAL_CPS;
  await typewrite(g, beat, cps);
}

export function autoplayFor(beat) {
  return beat.kind === "narration" ? Boolean(state.settings.autoplayNarrator) : Boolean(state.settings.autoplayCharacters);
}

export function nextVoicedBeat(g, afterId) {
  const queue = g.revealQueue || [];
  const from = queue.indexOf(afterId);
  for (let i = from + 1; i < queue.length; i++) {
    const b = g.beats.find((x) => x.id === queue[i]);
    if (b && b.voiceId && (b.kind === "narration" || b.kind === "dialogue") && autoplayFor(b)) return b;
  }
  return null;
}

// Where the typewriter writes, per card shape. Counts mirror the renderers.
export function typeTargets(el) {
  if (el.classList.contains("narration")) return [...el.querySelectorAll(":scope > p")];
  const bubble = el.querySelector(".bubble p");
  if (bubble) return [bubble];
  const pm = el.querySelector(".pm-text");
  if (pm) return [pm];
  return [];
}

// Texts come from the BEAT (same paragraph split as the renderer), not the
// DOM: a mid-reveal re-render rebuilds the nodes with full text, and we keep
// typing into the fresh ones from our own position.
export async function typewrite(g, beat, cps) {
  // dialogue types the same quote-stripped text the bubble renders
  const paras =
    beat.kind === "narration" ? String(beat.text || "").split(/\n{2,}/) : [stripWrappingQuotes(beat.text)];
  const step = Math.max(1, Math.round((cps * REVEAL_TICK) / 1000));
  const els = () => [...root.querySelectorAll(`[data-beat-id="${cssId(beat.id)}"]`)];

  const first = els();
  if (!first.length) return;
  first.forEach((el) => {
    typeTargets(el).forEach((t) => (t.textContent = ""));
    el.classList.add("typing");
  });

  for (let i = 0; i < paras.length; i++) {
    let pos = 0;
    while (pos < paras[i].length) {
      if (g.skipReveal || state.active !== g || state.view !== "play") {
        finishTyping(beat, paras);
        return;
      }
      pos = Math.min(paras[i].length, pos + step);
      const copies = els();
      if (!copies.length) return; // windowed out mid-type
      for (const el of copies) {
        el.closest(".veil-wrap")?.classList.remove("veiled"); // survive re-renders
        const targets = typeTargets(el);
        for (let j = 0; j < targets.length; j++) {
          targets[j].textContent = j < i ? paras[j] : j === i ? paras[i].slice(0, pos) : "";
        }
      }
      followStory();
      await sleep(REVEAL_TICK);
    }
  }
  finishTyping(beat, paras);
}

export function finishTyping(beat, paras) {
  root.querySelectorAll(`[data-beat-id="${cssId(beat.id)}"]`).forEach((el) => {
    el.closest(".veil-wrap")?.classList.remove("veiled");
    typeTargets(el).forEach((t, j) => (t.textContent = paras[j] ?? ""));
    el.classList.remove("typing");
  });
  followStory();
}

// Keep following the story while it grows, but only if the reader is at the
// bottom (scrolling up to read pauses the follow). The whisper thread in the
// profile follows the same rule, so private replies keep it pinned to the
// newest line as they type.
export function followStory() {
  const story = root.querySelector("#storyStream");
  if (story && storyNearBottom(story)) story.scrollTop = story.scrollHeight;
  const thread = root.querySelector("#pmThread");
  if (thread && storyNearBottom(thread)) thread.scrollTop = thread.scrollHeight;
}

// A new image landed in the flow: bring it into view when the reader is at the
// bottom; otherwise offer a small "new image below" affordance instead of
// yanking them away from what they are reading.
export function announceImage(el) {
  const story = root.querySelector("#storyStream");
  if (!story) return;
  if (storyNearBottom(story)) {
    if (typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    else followStory();
    return;
  }
  if (story.querySelector(".new-image-chip")) return;
  const chip = document.createElement("button");
  chip.type = "button";
  chip.className = "new-image-chip";
  chip.innerHTML = `${icon("eye")}<span>New image below</span>`;
  chip.addEventListener("click", (e) => {
    e.stopPropagation();
    if (typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "center", behavior: "smooth" });
    chip.remove();
  });
  story.appendChild(chip);
  setTimeout(() => chip.remove(), 15000);
}
