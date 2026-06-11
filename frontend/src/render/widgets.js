// Shared widgets: the context meter, fixed-slot grids, the composer + stack.

import { describeSegment } from "../composer.js";
import { icon } from "../icons.js";
import { escapeHtml, initials } from "./common.js";

// Prompt-token usage as a colored meter: green -> amber -> red as it fills.
// A PERMANENT HUD element ("12k/128k"), not a debug toggle: it renders whenever
// the backend sends context, including used=0 before the first turn. The same
// builder draws the small per-character meters (each character is its own
// agent context).
export function contextMeter(ctx, { mini = false, label = "Story memory" } = {}) {
  if (!ctx || !ctx.max) return "";
  const pct = Math.round(ctx.ratio * 100);
  const tone = ctx.ratio > 0.85 ? "red" : ctx.ratio > 0.6 ? "amber" : "green";
  // "4.2k / 128k": one decimal below 10k, integers above (raw count below 1k)
  const fmt = (n) => {
    const k = n / 1024;
    if (k >= 10) return `${Math.round(k)}k`;
    if (k >= 1) return `${Math.round(k * 10) / 10}k`;
    return String(n);
  };
  const text = `${fmt(ctx.used)} / ${fmt(ctx.max)}`;
  return `
    <div class="ctx-meter${mini ? " mini" : ""} tone-${tone}" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"
         aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}: ${text} tokens (${pct}%)">
      ${icon("gauge")}
      <div class="ctx-track"><div class="ctx-fill" style="width:${pct}%"></div></div>
      <span class="ctx-num">${text}</span>
    </div>`;
}

// A look turn's image is GUARANTEED but renders in the background and lands
// seconds (sometimes minutes) later; this hint marks the wait until the image
// beat swaps in. It never expires on a timer (the poll backs off instead).
// Renders in the public story for a composer look, inside the whisper thread
// for a private study (whisper mode:"look").
export function renderViewPending() {
  return `<div class="render-hint" role="status"><span class="art-scan" aria-hidden="true"></span><em>rendering the view...</em></div>`;
}

// --- fixed-slot grids (caps are maximums; empty slots show capacity) ---
export function slotGrid(items, total, cls, cellFn = filledSlot) {
  let cells = "";
  for (let i = 0; i < total; i++) {
    const it = items[i];
    cells += it ? cellFn(it) : `<span class="slot empty"></span>`;
  }
  return `<div class="slot-grid ${cls}">${cells}</div>`;
}

export function slotInner(it) {
  return it.imageUrl
    ? `<img src="${escapeHtml(it.imageUrl)}" alt="${escapeHtml(it.name)}" loading="lazy" />`
    : `<span class="slot-abbr">${escapeHtml(initials(it.name))}</span>`;
}

export function slotTip(it) {
  return it.description ? `${it.name}: ${it.description}` : it.name;
}

// inventory display slot (player / character): tappable -> the inspect modal
export function filledSlot(it) {
  return `<button type="button" class="slot filled" data-act="inspect-item" data-item-id="${escapeHtml(it.id || "")}" data-item-name="${escapeHtml(it.name)}" title="${escapeHtml(slotTip(it))}" aria-label="Inspect ${escapeHtml(it.name)}">${slotInner(it)}</button>`;
}

// scene-item slot: tappable -> the inspect modal (which offers Take for loose
// loot, Examine for fixed scenery, and "ask what this is" for both). Inspecting
// is read-only, so it stays interactive even while a turn resolves.
export function sceneItemSlot(it) {
  const kind = it.fixed ? "scenery" : "loot";
  const tag = it.fixed
    ? `<span class="slot-tag fixed" aria-hidden="true">${icon("landmark")}</span>`
    : `<span class="slot-tag loot" aria-hidden="true">${icon("plus")}</span>`;
  return `<button type="button" class="slot filled item-${kind}" data-act="inspect-item" data-item-id="${escapeHtml(it.id || "")}" data-item-name="${escapeHtml(it.name)}" title="${escapeHtml(slotTip(it))}" aria-label="Inspect ${escapeHtml(it.name)}">${slotInner(it)}${tag}</button>`;
}

// ---------------------------------------------------------------------------
// The composer: Do/Say(/Look) modes, entity chips (@), segment stacking (+),
// Send. The contenteditable line hosts non-editable chips; app.js serializes it
// into tagged segments with refs on submit. Look is a first-class action: an
// optional "look at what?" line (empty = study the whole scene).
// ---------------------------------------------------------------------------
export const MODE_LABELS = { do: "Do", say: "Say", look: "Look" };

export const MODE_ARIA = { do: "What you do", say: "What you say", look: "What you look at" };

export function renderComposer({ id, mode, locked, modes = ["do", "say"], placeholders, submitLabel }) {
  const dis = locked ? "disabled" : "";
  const ph = placeholders[mode] || placeholders.do;
  return `
    <div class="composer">
      <div class="composer-modes" role="group" aria-label="Line kind">
        ${modes
          .map(
            (m) =>
              `<button type="button" class="mode-btn${mode === m ? " active" : ""}" data-act="${id}-mode" data-mode="${m}" aria-pressed="${mode === m}" ${dis}>${MODE_LABELS[m]}</button>`,
          )
          .join("")}
      </div>
      <div class="composer-input holo-input" id="${id}Input" contenteditable="${locked ? "false" : "true"}"
           role="textbox" aria-multiline="false" aria-label="${MODE_ARIA[mode] || MODE_ARIA.do}"
           data-placeholder="${escapeHtml(locked ? "The narrator is thinking..." : ph)}"></div>
      <button type="button" class="holo-icon tag-btn" data-act="open-tagger" data-scope="${id}"
              title="Tag a character or item" aria-label="Tag a character or item" ${dis}>${icon("at")}</button>
      <button type="button" class="holo-icon stack-btn" data-act="${id}-stack"
              title="Stack this line to send several at once" aria-label="Stack this line" ${dis}>${icon("plus")}</button>
      <button class="holo-btn" type="submit" ${dis}>${icon("send")}<span>${submitLabel}</span></button>
    </div>`;
}

// The stacked-segment queue above a composer: each row is one tagged segment
// waiting to execute, removable until sent.
export function renderStack(stack, scope) {
  if (!stack || !stack.length) return "";
  return `<div class="seg-stack" aria-label="Stacked lines">
    ${stack
      .map(
        (seg, i) =>
          `<span class="seg-row seg-${escapeHtml(seg.type)}">${escapeHtml(describeSegment(seg))}
             <button type="button" class="seg-del" data-act="${scope}-unstack" data-index="${i}" aria-label="Remove stacked line">${icon("x")}</button>
           </span>`,
      )
      .join("")}
  </div>`;
}

// A character offer button (Give..., Provoke, narrator offers). Lives with
// the widgets: the profile renders these now (cards just hint at the panel).
export function sceneActionBtn(a, locked) {
  return `<button type="button" class="chip-btn" data-act="scene-action" data-type="${escapeHtml(a.type)}" data-label="${escapeHtml(a.label)}" ${locked ? "disabled" : ""}>${escapeHtml(a.label)}</button>`;
}

export function exitBtn(e, locked) {
  const ic = e.isBack ? "chevronLeft" : "compass";
  return `<button type="button" class="chip-btn exit${e.isBack ? " back" : ""}" data-act="exit" data-label="${escapeHtml(e.label)}" data-target="${escapeHtml(e.target || "")}" ${locked ? "disabled" : ""}>${icon(ic)}<span>${escapeHtml(e.label)}</span></button>`;
}

export function charActionBtn(a, c, locked) {
  return `<button type="button" class="chip-btn" data-act="char-action" data-type="${escapeHtml(a.type)}" data-label="${escapeHtml(a.label)}" data-char-id="${escapeHtml(c.id)}" data-char-name="${escapeHtml(c.name)}" ${locked ? "disabled" : ""}>${escapeHtml(a.label)}</button>`;
}
