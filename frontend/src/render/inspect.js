// Tap-to-inspect: the detail modal over items, the goal, quests, receipts.

import { icon } from "../icons.js";
import { escapeHtml } from "./common.js";

// ---------------------------------------------------------------------------
// Tap-to-inspect: every small thing on screen (items, characters, the goal,
// quests, system receipts) expands into a detail modal with the facts already
// in /state plus an "ask what this is" narrator aside (POST /explain,
// spoiler-safe by construction). Its image click opens the lightbox.
// ---------------------------------------------------------------------------
export function renderInspectModal(s, g) {
  const ins = g.inspect; // { kind, key, beatId, asking, answer }
  const locked = Boolean(g.generating);
  const view = inspectView(s, g, ins);
  const ask = `
    <div class="ins-ask">
      ${
        ins.asking
          ? `<div class="narrating"><span class="dot"></span><span class="dot"></span><span class="dot"></span><em>the narrator considers...</em></div>`
          : ins.answer != null
            ? `<p class="ins-answer">${escapeHtml(ins.answer)}</p>`
            : ""
      }
      <button type="button" class="holo-btn" data-act="inspect-ask" ${ins.asking ? "disabled" : ""}>
        ${icon("sparkles")}<span>${ins.answer != null ? "Ask again" : "Ask what this is"}</span>
      </button>
    </div>`;

  return `
    <div class="modal-overlay" data-act="close-inspect">
      <div class="holo-modal inspect-modal" data-act="noop" role="dialog" aria-modal="true" aria-label="${escapeHtml(view.title)}">
        <span class="card-corner tr"></span><span class="card-corner bl"></span>
        <header class="ins-head">
          <h3 class="ins-title">${escapeHtml(view.title)}</h3>
          <button type="button" class="holo-icon" data-act="close-inspect" aria-label="Close" title="Close">${icon("x")}</button>
        </header>
        ${view.body}
        ${view.actions ? `<div class="ins-actions">${view.actions}</div>` : ""}
        ${ask}
      </div>
    </div>`;
}

export function inspectView(s, g, ins) {
  if (ins.kind === "item") return inspectItem(s, ins, g);
  if (ins.kind === "goal") return inspectGoal(s);
  if (ins.kind === "quest") return inspectQuest(s, ins);
  if (ins.kind === "beat") return inspectBeat(g, ins);
  return { title: "Unknown", body: `<p class="modal-body">Nothing to see.</p>`, actions: "" };
}

export function findInspectItem(s, key) {
  const pools = [
    ...(((s.scene && s.scene.items) || []).map((it) => ({ ...it, where: "here in the scene", inScene: true }))),
    ...((s.player.inventory || []).map((it) => ({ ...it, where: "in your pack" }))),
    ...((s.characters || []).flatMap((c) => (c.inventory || []).map((it) => ({ ...it, where: `carried by ${c.name}` })))),
  ];
  return pools.find((it) => (it.id && it.id === key) || it.name === key) || null;
}

export function inspectImage(url, alt) {
  // not wrapped in a button: the global lightbox listener picks the click up
  return url
    ? `<div class="ins-figure"><img data-art="${escapeHtml(url)}" src="${escapeHtml(url)}" alt="${escapeHtml(alt)}" loading="lazy" /></div>`
    : "";
}

export function inspectItem(s, ins, g) {
  const it = findInspectItem(s, ins.key);
  if (!it) return { title: "Gone", body: `<p class="modal-body">It is no longer here.</p>`, actions: "" };
  const locked = Boolean(g.generating);
  const tags = [
    it.where,
    it.qty > 1 ? `x${it.qty}` : "",
    it.inScene ? (it.fixed ? "part of the scene" : "can be taken") : "",
  ].filter(Boolean);
  const actions = it.inScene
    ? it.fixed
      ? `<button type="button" class="holo-btn" data-act="examine-item" data-item-name="${escapeHtml(it.name)}" ${locked ? "disabled" : ""}>${icon("eye")}<span>Examine ${escapeHtml(it.name)}</span></button>`
      : `<button type="button" class="holo-btn primary" data-act="take-item" data-item-name="${escapeHtml(it.name)}" ${locked ? "disabled" : ""}>${icon("plus")}<span>Take ${escapeHtml(it.name)}</span></button>`
    : "";
  return {
    title: it.name,
    body: `
      ${inspectImage(it.imageUrl, it.name)}
      <p class="ins-tags">${tags.map((t) => `<span class="ins-tag">${escapeHtml(t)}</span>`).join("")}</p>
      ${it.description ? `<p class="modal-body">${escapeHtml(it.description)}</p>` : ""}`,
    actions,
  };
}

// (characters no longer use the inspect modal: tapping one opens the
// full-screen profile, which is richer and carries the whisper channel)

export function inspectGoal(s) {
  const quests = (s.quests || []).filter((q) => q.status === "active");
  const questRows = quests
    .map(
      (q) => `
        <button type="button" class="ins-quest" data-act="inspect-quest" data-quest-id="${escapeHtml(q.id)}">
          ${icon("scroll")}<span class="ins-quest-name">${escapeHtml(q.title)}</span>
          <span class="ins-quest-progress">${q.objectives.filter((o) => o.done).length}/${q.objectives.length}</span>
        </button>`,
    )
    .join("");
  return {
    title: "Current goal",
    body: `
      <p class="modal-body goal-line">${icon("compass")}<span>${escapeHtml(s.currentGoal || "No goal right now.")}</span></p>
      ${quests.length ? `<p class="ins-tags"><span class="ins-tag">quest log</span></p>${questRows}` : ""}`,
    actions: "",
  };
}

export function inspectQuest(s, ins) {
  const q = (s.quests || []).find((x) => x.id === ins.key);
  if (!q) return { title: "Quest", body: `<p class="modal-body">That thread of the story is gone.</p>`, actions: "" };
  const objectives = q.objectives
    .map(
      (o) => `
        <li class="${o.done ? "done" : ""}">
          <span class="check">${o.done ? icon("check") : ""}</span><span>${escapeHtml(o.text)}</span>
        </li>`,
    )
    .join("");
  return {
    title: q.title,
    body: `
      ${q.description ? `<p class="modal-body">${escapeHtml(q.description)}</p>` : ""}
      <ul class="ins-objectives quest">${objectives}</ul>`,
    actions: "",
  };
}

export function inspectBeat(g, ins) {
  const beat = g.beats.find((b) => b.id === ins.beatId);
  return {
    title: "What just happened",
    body: `<p class="modal-body">${escapeHtml((beat && beat.text) || "")}</p>`,
    actions: "",
  };
}
