// Turn cues and surfaces: transition notices, one-shot flashes, help
// popovers and toasts.

import { icon } from "../icons.js";
import { HELP } from "../render.js";
import { buildNotices } from "../transitions.js";
import { cssAttr, cssId, root } from "./ctx.js";

// ---------------------------------------------------------------------------
// animation juice + helpers
// ---------------------------------------------------------------------------

// Apply the turn's transitions to the freshly-rendered DOM: transient notices for
// narrative changes, plus one-shot flashes on the cards/slots/HUD that changed.
export function applyTransitions(g) {
  const ch = g.changes;
  g.changes = null;
  if (!ch || ch.firstLoad) return;

  const notices = buildNotices(ch);
  if (notices.length) showNotices(notices);

  // scene establish: the identity wing of the deck announces the new place
  if (ch.sceneChanged) flash(".deck-scene", "scene-enter", 900);

  // HUD deltas
  if (ch.lifeDelta < 0) flash("[data-hud-life]", "shake", 600);
  if (ch.pointsDelta > 0) flash('[data-hud-num="points"]', "tick", 600);
  if (ch.goalChanged) flash(".hud-goal", "goal-flash", 1200);

  // scene items revealed; player inventory gained
  ch.itemsAdded.forEach((id) => flash(`.scene-items .slot[data-item-id="${cssId(id)}"]`, "slot-new", 1400));
  ch.invAdded.forEach((name) => flash(`.player-items .slot[data-item-name="${cssAttr(name)}"]`, "slot-new", 1400));

  // characters
  ch.charJoined.forEach((c) => flash(`.char-col[data-char-id="${cssId(c.id)}"]`, "card-arrive", 800));
  ch.charHurt.forEach((id) => flash(`.char-col[data-char-id="${cssId(id)}"] .hp-fill`, "hp-flash", 700));
  ch.charDisposition.forEach((c) => flash(`.char-col[data-char-id="${cssId(c.id)}"] .disp-badge`, "disp-flash", 900));
}

export function flash(selector, cls, ms) {
  const el = root.querySelector(selector);
  if (!el) return;
  el.classList.add(cls);
  setTimeout(() => el.classList.remove(cls), ms);
}

// Transient notice stack (top-center): animated chips that fade. Not part of the
// permanent story log - they communicate the TRANSITION, then get out of the way.
export function showNotices(notices) {
  let stack = document.querySelector(".notice-stack");
  if (!stack) {
    stack = document.createElement("div");
    stack.className = "notice-stack";
    document.body.appendChild(stack);
  }
  notices.slice(0, 6).forEach((n, i) => {
    const el = document.createElement("div");
    el.className = `notice tone-${n.tone}`;
    el.innerHTML = `${icon(n.icon)}<span></span>`;
    el.querySelector("span").textContent = n.text;
    stack.appendChild(el);
    setTimeout(() => el.classList.add("show"), 20 + i * 70);
    setTimeout(() => {
      el.classList.remove("show");
      setTimeout(() => el.remove(), 400);
    }, 3400 + i * 250);
  });
}

// tracked so repeated clicks on the same dot never stack document listeners
let helpDismiss = null;

// Where the popover's top edge goes: below the dot when it fits, else flipped
// above it (live: the composer's bottom-right dot pushed the pop past the
// viewport and grew the page into a scrollbar). Pure, so it is testable.
export function helpPopTop(rect, popHeight, viewportH, scrollY) {
  const below = rect.bottom + 6 + popHeight <= viewportH;
  const top = below ? rect.bottom + 6 : Math.max(8, rect.top - popHeight - 6);
  return top + scrollY;
}

export function showHelp(el) {
  document.querySelectorAll(".help-pop").forEach((p) => p.remove());
  if (helpDismiss) {
    document.removeEventListener("click", helpDismiss);
    helpDismiss = null;
  }
  const pop = document.createElement("div");
  pop.className = "help-pop";
  pop.textContent = HELP[el.dataset.help] || "Part of the game.";
  document.body.appendChild(pop);
  const r = el.getBoundingClientRect();
  pop.style.top = `${helpPopTop(r, pop.offsetHeight, window.innerHeight, window.scrollY)}px`;
  pop.style.left = `${Math.max(8, Math.min(window.innerWidth - 268, r.left + window.scrollX - 120))}px`;
  const close = (ev) => {
    if (ev.target !== el) {
      pop.remove();
      document.removeEventListener("click", close);
      if (helpDismiss === close) helpDismiss = null;
    }
  };
  helpDismiss = close;
  setTimeout(() => document.addEventListener("click", close), 0);
}

export function showToast(message) {
  const t = document.createElement("div");
  t.className = "toast";
  t.textContent = message;
  document.body.appendChild(t);
  setTimeout(() => t.classList.add("show"), 10);
  setTimeout(() => {
    t.classList.remove("show");
    setTimeout(() => t.remove(), 300);
  }, 3200);
}
