// Shared widgets: the context meter, fixed-slot grids, the composer + stack.

import { describeSegment } from "../composer.js";
import { icon } from "../icons.js";
import { cardCorners, escapeHtml, initials } from "./common.js";

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

// ---------------------------------------------------------------------------
// Shared chrome bits: the thinking dots, the modal shell, the icon button, the
// little stat pill, the staged-reveal veil. One copy each, used everywhere.
// ---------------------------------------------------------------------------

// The "...thinking" indicator: three pulsing dots and a label. Always a live
// region (role=status / aria-live=polite) so a screen reader announces the
// wait. `cls` carries the per-site flavor class (profile-loading, pm-thinking).
export function narratingDots(label, cls = "") {
  return `<div class="narrating${cls ? ` ${cls}` : ""}" role="status" aria-live="polite">
            <span class="dot"></span><span class="dot"></span><span class="dot"></span>
            <em>${escapeHtml(label)}</em>
          </div>`;
}

// The modal scaffold: a click-to-dismiss overlay wrapping a holo card that
// swallows its own clicks (data-act="noop"), with the corner accents and a
// labeled dialog box. Every dialog carries an aria-label. The header defaults
// to an icon + title h3; pass `header` to supply a custom one (the inspect
// modal puts a close button up there).
export function modalShell({ overlayAct, title, titleIcon, header, body, actions, actionsCls = "", cls = "", ariaLabel }) {
  const head =
    header != null
      ? header
      : `<h3 class="modal-title">${titleIcon ? icon(titleIcon) : ""}<span>${escapeHtml(title)}</span></h3>`;
  const label = ariaLabel != null ? ariaLabel : title;
  return `
    <div class="modal-overlay" data-act="${overlayAct}">
      <div class="holo-modal${cls ? ` ${cls}` : ""}" data-act="noop" role="dialog" aria-modal="true" aria-label="${escapeHtml(label)}">
        ${cardCorners()}
        ${head}
        ${body}
        ${actions ? `<div class="modal-actions${actionsCls ? ` ${actionsCls}` : ""}">${actions}</div>` : ""}
      </div>
    </div>`;
}

// A clamped life/hp bar. `variant` picks the class family: "player" -> the deck
// vitals (life-track/life-fill), "char" -> a character bar (hp-track/hp-fill).
// `cls` is an optional wrapper class (e.g. "char-hp"); markup is identical to
// the hand-built versions it replaces.
export function hpBar(life, maxLife, { variant = "char", cls = "", title = "" } = {}) {
  const pct = maxLife ? Math.max(0, Math.min(100, (life / maxLife) * 100)) : 0;
  const track = variant === "player" ? "life-track" : "hp-track";
  const fill = variant === "player" ? "life-fill" : "hp-fill";
  const open = cls ? `<div class="${cls}"${title ? ` title="${escapeHtml(title)}"` : ""}>` : "";
  const close = cls ? "</div>" : "";
  return `${open}<div class="${track}"><div class="${fill}" style="width:${pct}%"></div></div>${close}`;
}

// The relation + disposition badge pair worn on a character (the column badges,
// the profile status sheet). Relation is optional; disposition always shows.
export function relationBadge(text) {
  return text ? `<span class="relation-badge">${escapeHtml(text)}</span>` : "";
}

export function dispBadge(disposition) {
  return `<span class="disp-badge disp-${escapeHtml(disposition)}">${escapeHtml(disposition)}</span>`;
}

export function dispositionBadges(c) {
  return `${relationBadge(c.relation)}
          ${dispBadge(c.disposition)}`;
}

// A lightbox-trigger image: data-art arms the global lightbox listener and the
// card-reveal, data-caption is what shows when it expands, loading=lazy keeps
// the strip cheap. Every art image goes through here so none of those drift.
export function artImg({ url, alt = "", caption, cls = "" }) {
  const clsAttr = cls ? ` class="${cls}"` : "";
  const cap = caption ? ` data-caption="${escapeHtml(caption)}"` : "";
  return `<img${clsAttr} data-art="${escapeHtml(url)}" src="${escapeHtml(url)}" alt="${escapeHtml(alt)}"${cap} loading="lazy" />`;
}

// The staged-reveal wrapper: a beat queued for the typewriter reveal renders
// veiled until its turn. reveal.js keys off this exact structure.
export function veilWrap(html, veiled) {
  return veiled ? `<div class="veil-wrap veiled">${html}</div>` : html;
}

// img-or-initials: the small portrait used in the cast roster and dialogue
// bubbles. A real face when we have one, else the initials on a color plate.
// (col-art / profile-art are a different shape and stay hand-built.)
export function avatarOrInitials({ url, name, color, imgCls = "", fallbackCls }) {
  return url
    ? `<img${imgCls ? ` class="${imgCls}"` : ""} src="${escapeHtml(url)}" alt="${escapeHtml(name)}" loading="lazy" />`
    : `<span class="${fallbackCls}" style="background:${escapeHtml(color)}">${escapeHtml(initials(name))}</span>`;
}

// The scan-line "art is being painted" skeleton (the developing-photo look).
// `cls` is the wrapper's extra class (col-body, prose-art ...), `hint` the
// caption word, `ariaLabel` what a screen reader hears for the role=img box.
// `tag` is the wrapper element - a div for a character column, a figure for the
// scene card (which lives among other prose-art figures).
export function artLoading(cls, hint, ariaLabel, tag = "div") {
  return `<${tag} class="${cls} art-loading" role="img" aria-label="${escapeHtml(ariaLabel)}">
            <span class="art-scan" aria-hidden="true"></span><span class="art-hint">${escapeHtml(hint)}</span>
          </${tag}>`;
}

// A small section heading: an icon and a label span. Covers both families -
// the profile's h4.profile-sec-head and the screens' h3.panel-head - via the
// tag + class params. (col-head and rail-label are a different shape.)
export function secHead(tag, cls, iconName, label) {
  return `<${tag} class="${cls}">${icon(iconName)}<span>${escapeHtml(label)}</span></${tag}>`;
}

// An icon-only holo-icon button: the aria-label + title pair name it for both
// assistive tech and a hover tooltip, and type=button keeps it from submitting
// any form it sits inside. `title` defaults to the label but can differ (a
// short screen-reader name, a longer tooltip). `data` is a map of extra data-*.
export function iconBtn({ act, icon: iconName, label, title, cls = "", data = {}, disabled = false }) {
  const dataAttrs = Object.entries(data)
    .map(([k, v]) => ` data-${k}="${escapeHtml(v)}"`)
    .join("");
  const tip = title != null ? title : label;
  return `<button type="button" class="holo-icon${cls ? ` ${cls}` : ""}" data-act="${act}"${dataAttrs} aria-label="${escapeHtml(label)}" title="${escapeHtml(tip)}" ${disabled ? "disabled" : ""}>${icon(iconName)}</button>`;
}

// The backend-link pill: SYSTEM ONLINE when the server answers, LINK LOST when
// it does not. Lives in the menu header and the library header.
export function hudStat(online) {
  return `<span class="hud-stat ${online ? "ok" : "down"}">
          <span class="stat-dot"></span>${online ? "SYSTEM ONLINE" : "LINK LOST"}
        </span>`;
}

// One trait / origin list item: the text, then a "stamp" (unlocked: / learned:)
// noting when it was revealed. `cls` adds the "origin" flavor for past entries.
export function traitLi(text, stampWord, when, cls = "") {
  return `<li class="trait${cls ? ` ${cls}` : ""}"><span class="trait-text">${escapeHtml(text)}</span>${when ? `<span class="trait-stamp">${stampWord} ${escapeHtml(when)}</span>` : ""}</li>`;
}
