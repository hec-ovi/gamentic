// The play screen: the deck, character columns, the action bar, give modal.

import { presentCharacters } from "../adapters.js";
import { icon } from "../icons.js";
import { escapeHtml, help, holoFx, initials, titleCase } from "./common.js";
import { renderInspectModal } from "./inspect.js";
import { renderProfile } from "./profile.js";
import { renderStory } from "./story.js";
import { contextMeter, renderComposer, renderStack, sceneItemSlot, slotGrid } from "./widgets.js";

// ---------------------------------------------------------------------------
// Play
// ---------------------------------------------------------------------------

// Command-deck layout (v0.2 scene-centric, integrated-header redesign):
//   ONE integrated header (scene identity + scene affordances + vitals, no
//   repeated affordances) | story (scene art mixed into the prose) + character
//   columns | player inventory + the say/do composer.
export function renderPlay(state) {
  const g = state.active;
  if (!g || !g.state) {
    return `<main class="play-loading"><div class="empty-icon">${icon("sparkles")}</div><p>Loading the adventure...</p></main>`;
  }
  const s = g.state;
  // PARTIAL busy-lock: while a turn is in flight, only state-MUTATING surfaces
  // lock (composer/send, action buttons, exits, Continue, Look, the private
  // composer). Everything read-only stays interactive: lightbox, inspect,
  // /explain, scrolling, profiles, settings. No full-screen veil.
  const locked = Boolean(g.generating);

  return `
    <div class="holo-stage play-stage${locked ? " generating" : ""}" data-stage>
      ${holoFx()}
      ${renderPlayDeck(s, locked, g)}

      <div class="play-body">
        <main class="story" id="storyStream" data-help-anchor role="log" aria-live="polite" aria-relevant="additions" aria-label="Story">
          <div class="story-help-row">${help("story")}</div>
          ${renderStory(g)}
          ${g.pendingView ? renderViewPending() : ""}
          ${locked ? renderNarrating() : ""}
        </main>

        <aside class="char-column">
          <div class="col-head">${icon("mask")}<span>In the scene</span>${help("party")}</div>
          ${renderCharacters(s, locked, g)}
        </aside>
      </div>

      ${renderActionBar(g, s, locked)}
      ${g.give ? renderGiveModal(s, g.give, locked) : ""}
      ${g.inspect ? renderInspectModal(s, g) : ""}
      ${g.profile ? renderProfile(s, g) : ""}
    </div>`;
}

// A look turn's image (when the narrator grants one) renders in the background
// and lands seconds later; this subtle hint marks the wait. It disappears when
// the beat arrives or the polling window expires (no image is normal too).
export function renderViewPending() {
  return `<div class="render-hint" role="status"><span class="art-scan" aria-hidden="true"></span><em>rendering the view...</em></div>`;
}

// Give-picker: choose an item from the player's inventory to hand to a character.
export function renderGiveModal(s, give, locked) {
  const dis = locked ? "disabled" : "";
  const items = s.player.inventory || [];
  const body = items.length
    ? `<div class="give-grid">${items
        .map(
          (it) =>
            `<button type="button" class="holo-btn give-pick" data-act="pick-give" data-item="${escapeHtml(it.id || it.name)}" data-target="${escapeHtml(give.name)}" ${dis}>${escapeHtml(it.name)}</button>`,
        )
        .join("")}</div>`
    : `<p class="modal-body">You have nothing to give.</p>`;
  return `
    <div class="modal-overlay" data-act="cancel-give">
      <div class="holo-modal give-modal" data-act="noop" role="dialog" aria-modal="true">
        <span class="card-corner tr"></span><span class="card-corner bl"></span>
        <h3 class="modal-title give"><span class="ic">${icon("gem")}</span><span>Give to ${escapeHtml(give.name)}</span></h3>
        ${items.length ? `<p class="modal-body">Choose an item to hand over.</p>` : ""}
        ${body}
        <div class="modal-actions"><button class="holo-btn" data-act="cancel-give" ${dis}>Cancel</button></div>
      </div>
    </div>`;
}

// ---------------------------------------------------------------------------
// The integrated header ("the deck"). ONE structure, three shape levels:
//   nav | scene identity wing (tall, protrudes) | affordance board | vitals wing
// Every affordance renders from exactly ONE state field, in exactly ONE place:
// goal chip (current_goal), mood badge (scene.status, on the scene name),
// scene items/actions/exits, context meter, story clock.
// ---------------------------------------------------------------------------
export function renderPlayDeck(s, locked, g = {}) {
  const dis = locked ? "disabled" : "";
  const p = s.player;
  const scene = s.scene;
  const name = (scene && scene.name) || titleCase(p.location || "Unknown");
  const desc = (scene && scene.description) || "";
  const mood = (scene && scene.status) || s.sceneStatus || null;
  const items = (scene && scene.items) || [];
  const actions = (scene && scene.actions) || [];
  const exits = (scene && scene.exits) || [];
  const pct = p.maxLife ? Math.max(0, Math.min(100, (p.life / p.maxLife) * 100)) : 0;
  void g;

  return `
    <header class="play-deck">
      <div class="deck-nav">
        <button class="holo-icon" data-act="go-library" aria-label="Library" title="Library" ${dis}>${icon("chevronLeft")}</button>
      </div>

      <div class="deck-scene">
        <span class="card-corner tr"></span><span class="card-corner bl"></span>
        <div class="scene-id">
          ${mood ? `<span class="mood-badge mood-${escapeHtml(mood)}">${escapeHtml(mood)}</span>` : ""}
          ${s.time ? `<span class="time-chip" title="Story time, not yours">${icon("clock")}<span>${escapeHtml(s.time.label)}</span></span>` : ""}
        </div>
        <h2 class="scene-name">${escapeHtml(name)}${help("scene")}</h2>
        ${desc ? `<p class="scene-desc">${escapeHtml(desc)}</p>` : ""}
      </div>

      <div class="deck-board">
        <div class="board-cell">
          <span class="rail-label">${icon("gem")}<span>Scene items</span></span>
          ${slotGrid(items, 6, "scene-items", (it) => sceneItemSlot(it))}
        </div>
        <i class="board-sep" aria-hidden="true"></i>
        <div class="board-cell">
          <span class="rail-label">${icon("zap")}<span>Actions</span></span>
          <div class="act-row">
            ${actions.map((a) => sceneActionBtn(a, locked)).join("")}
            ${!actions.length ? `<span class="muted small">Nothing obvious to do.</span>` : ""}
          </div>
        </div>
        <i class="board-sep" aria-hidden="true"></i>
        <div class="board-cell">
          <span class="rail-label">${icon("compass")}<span>Ways out</span></span>
          <div class="act-row">
            ${exits.map((e) => exitBtn(e, locked)).join("")}
            ${!exits.length ? `<span class="dead-end">${icon("x")}<span>Dead end: no way out revealed</span></span>` : ""}
          </div>
        </div>
      </div>

      <div class="deck-vitals" data-hud>
        <div class="vital-row">
          <div class="hud-life" data-hud-life>
            ${icon("heart")}
            <div class="life-track"><div class="life-fill" style="width:${pct}%"></div></div>
            <span class="hud-num" data-hud-num="life">${p.life}/${p.maxLife}</span>
          </div>
          <div class="hud-points">${icon("star")}<span class="hud-num" data-hud-num="points">${p.points}</span></div>
          ${help("hud")}
        </div>
        ${contextMeter(s.context)}
        ${s.currentGoal ? `<button type="button" class="hud-goal" data-act="inspect-goal" title="Current goal - tap for the quest log">${icon("compass")}<span>${escapeHtml(s.currentGoal)}</span></button>` : ""}
      </div>

      <div class="deck-nav">
        <button class="holo-icon" data-act="open-settings" aria-label="Menu" title="Menu / settings">${icon("settings")}</button>
      </div>
    </header>`;
}

export function renderCharacters(s, locked, g = {}) {
  const present = presentCharacters(s);
  const presentIds = new Set(present.map((c) => c.id));
  // everyone known but not standing here: followers lagging, those left behind, the fallen.
  const elsewhere = (s.characters || []).filter((c) => c.name && !presentIds.has(c.id));

  const here = present.length
    ? `<div class="char-deck cols-${present.length}">${present.map((c) => renderCharColumn(c, s, locked, g)).join("")}</div>`
    : `<p class="muted small char-empty">No one else is here right now.</p>`;

  const roster = elsewhere.length
    ? `<div class="cast-roster">
         <div class="col-head sub">${icon("eye")}<span>Elsewhere</span></div>
         ${elsewhere.map(castRow).join("")}
       </div>`
    : "";

  return here + roster;
}

// A character is a tall vertical card column: the full-body reference art fills
// the column, identity reads off a plate at its foot, and only the Carrying
// row + one "Actions" button hang below (the description lives in the
// profile, not on the card). "Actions" expands the offer buttons (Give,
// Provoke, ...); tapping the card opens the FULL-SCREEN profile.
export function renderCharColumn(c, s, locked, g = {}) {
  const hp =
    c.life != null && c.maxLife
      ? `<div class="char-hp" title="${c.life}/${c.maxLife}">
           <div class="hp-track"><div class="hp-fill" style="width:${Math.max(0, Math.min(100, (c.life / c.maxLife) * 100))}%"></div></div>
         </div>`
      : "";
  const actions = c.actions.filter((a) => a.type !== "talk");
  const open = g.actionsFor === c.id;
  const actionsBlock = actions.length
    ? `<div class="char-actions">
         <button type="button" class="chip-btn actions-toggle${open ? " open" : ""}" data-act="toggle-char-actions"
                 data-char-id="${escapeHtml(c.id)}" aria-expanded="${open}" title="What you can do to ${escapeHtml(c.name)}">
           ${icon("zap")}<span>Actions</span>
         </button>
         ${open ? actions.map((a) => charActionBtn(a, c, locked)).join("") : ""}
       </div>`
    : "";
  return `
    <article class="char-col${c.alive ? "" : " dead"}" data-char-id="${escapeHtml(c.id)}" style="--speaker:${escapeHtml(c.color)}">
      <button type="button" class="col-art" data-act="open-profile" data-char-id="${escapeHtml(c.id)}" data-char-name="${escapeHtml(c.name)}" title="Open ${escapeHtml(c.name)}'s profile" aria-label="Open ${escapeHtml(c.name)}'s profile">
        ${bodyArt(c, s)}
        <div class="col-grad" aria-hidden="true"></div>
        <span class="disp-badge disp-${escapeHtml(c.disposition)}">${escapeHtml(c.disposition)}</span>
        <div class="col-plate">
          <span class="char-name">${escapeHtml(c.name)}${c.following ? ` <span class="follow-tag" title="Following you">${icon("compass")}</span>` : ""}</span>
          ${hp}
        </div>
      </button>
      ${contextMeter(c.context, { mini: true, label: `${c.name}'s memory` })}
      <div class="char-inv">
        <span class="inv-mini-label">Carrying</span>
        ${slotGrid(c.inventory, 3, "char-items")}
      </div>
      ${actionsBlock}
    </article>`;
}

// Full-body art for a character column, honoring the loading rule:
// url -> the image; null + images_enabled -> a loader (art is generating);
// null + images off -> a static color+initial figure, no loader.
export function bodyArt(c, s) {
  if (c.bodyUrl) {
    return `<img class="col-body" data-art="${escapeHtml(c.bodyUrl)}" src="${escapeHtml(c.bodyUrl)}" alt="${escapeHtml(c.name)}" loading="lazy" />`;
  }
  if (s.imagesEnabled) {
    return `<div class="col-body art-loading" role="img" aria-label="${escapeHtml(c.name)} (art is being painted)">
              <span class="art-scan" aria-hidden="true"></span><span class="art-hint">manifesting</span>
            </div>`;
  }
  return `<div class="col-body art-off" role="img" aria-label="${escapeHtml(c.name)}">
            <span class="col-initial">${escapeHtml(initials(c.name))}</span>
          </div>`;
}

export function castRow(c) {
  const avatar = c.faceUrl
    ? `<img src="${escapeHtml(c.faceUrl)}" alt="${escapeHtml(c.name)}" loading="lazy" />`
    : `<span class="cast-fallback" style="background:${escapeHtml(c.color)}">${escapeHtml(initials(c.name))}</span>`;
  let where;
  if (!c.alive) where = "fallen";
  else if (c.following) where = "with you";
  else if (c.present === false) where = "gone";
  else if (c.location) where = `at ${titleCase(c.location)}`;
  else where = "elsewhere";
  return `<button type="button" class="cast-row${c.alive ? "" : " dead"}" data-act="open-profile" data-char-id="${escapeHtml(c.id)}" data-char-name="${escapeHtml(c.name)}" style="--speaker:${escapeHtml(c.color)}" title="${escapeHtml(c.name)} - ${escapeHtml(where)}">
            <span class="cast-portrait">${avatar}</span>
            <span class="cast-id"><span class="cast-name">${escapeHtml(c.name)}</span><span class="cast-where">${escapeHtml(where)}</span></span>
          </button>`;
}

// --- action buttons (button -> segment mapping is resolved in app.js) ---
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

export function renderActionBar(g, s, locked) {
  const cmp = g.composer || { mode: "do", stack: [] };
  const dis = locked ? "disabled" : "";
  return `
    <footer class="play-actionbar">
      <div class="player-inv">
        <span class="rail-label">${icon("gem")}<span>You</span>${help("inventory")}</span>
        ${slotGrid(s.player.inventory, 6, "player-items")}
        <span class="action-help">${help("action")}</span>
      </div>
      ${renderStack(cmp.stack, "cmp")}
      <form class="action-form" data-form="action">
        ${renderComposer({
          id: "cmp",
          mode: cmp.mode,
          locked,
          modes: ["do", "say", "look"],
          placeholders: {
            do: "Do or say anything... (Enter sends)",
            say: "What do you say?",
            look: "Look at what? (empty = study the whole scene)",
          },
          submitLabel: "Send",
        })}
      </form>
      <div class="turn-aux">
        <input type="text" id="wishInput" class="holo-input wish-input" autocomplete="off" maxlength="200"
               placeholder="What do you wish to happen next? (optional)" aria-label="What do you wish to happen next?"
               title="A hope whispered to the storyteller, not an action. Easy stories lean into wishes; hard ones may ignore them."
               value="${escapeHtml(g.wish || "")}" ${dis} />
        <button type="button" class="holo-btn continue-btn" data-act="continue-story"
                title="Let the story advance on its own, no input needed" ${dis}>
          ${icon("play")}<span>Continue</span>
        </button>
      </div>
    </footer>`;
}

export function renderNarrating() {
  return `<div class="narrating" role="status" aria-live="polite">
            <span class="dot"></span><span class="dot"></span><span class="dot"></span>
            <em>the narrator is thinking...</em>
          </div>`;
}
