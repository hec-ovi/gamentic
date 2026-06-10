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

import { icon } from "./icons.js";
import { presentCharacters } from "./adapters.js";
import { describeSegment } from "./composer.js";

export const HELP = {
  menu: "The main deck. Play drops you into your saved worlds, New forges a fresh adventure, and Settings tunes sound and the backend. Everything else is just light.",
  hud: "Your vitals. The heart bar is your life; if it empties the story turns against you. Points are story score earned by clever and brave actions. Memory shows how much of the tale the narrator can still hold in mind: green is fine, red means it is nearly full.",
  quests: "Your current goals. Each quest has a checklist of objectives. The narrator ticks them off as you make progress, and may add new ones as the story unfolds.",
  party: "Characters standing here with you, full figure. Each card shows their mood toward you, health, and what they carry. Their buttons are what you can do to them right now; Talk and Whisper open a private exchange over the scene.",
  scene: "Where you are right now. Its mood (calm, tense, dangerous) shifts with the story, and the clock is story time, not yours. Alongside are the objects revealed here, the things you can try, and the ways out. A dead end means no way out has been revealed yet.",
  inventory: "What you are carrying. Empty slots show how much more you can hold. Use a character's Give button to hand something over.",
  story: "The story itself. Plain flowing text is the narrator telling the tale, just read it. Coloured cards with a name are characters speaking to you. Small badges are things that just happened (damage, items, points). Scene art develops here like a photograph as it is painted.",
  action: "Just type what you do or say in your own words and press Enter - the game understands speech, deeds, attacks, gifts and even whispers from plain text. The Do/Say buttons, the @ tag (so it knows exactly who or what you mean) and the + stack (several lines as one turn) are there when you want precise control.",
  creator: "Describe the world you want in plain language and chat with the world-builder. When it has enough, press Begin the Adventure and it spins up a real game.",
  settings: "Sound options, out of the way. Turn voice on or off, autoplay each new line as it arrives, or set the master volume. The game server connects automatically.",
  library: "Your saved adventures. Continue one, or start a brand new world. These are real games stored on the backend.",
};

function help(key) {
  return `<button type="button" class="help-dot" data-help="${key}" aria-label="What is this?" title="What is this?">?</button>`;
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

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

// ---------------------------------------------------------------------------
// Main menu / title (the holographic landing deck)
// ---------------------------------------------------------------------------
//
// Phase 1 of the UI redesign: an ice-cyan sci-fi HUD landing screen. Three
// chamfered "nodes" (New / Play / Settings) with rotating dial rings, corner
// brackets and bloom. Pure CSS motion; no canvas, no framework. The nodes route
// straight into the existing views (Play -> library, New -> creator, etc.).

// Shared holographic background FX. Scanlines only (the nebula spheres, bloom
// halo and perspective grid were removed at the owner's request - too busy).
function holoFx() {
  return `<div class="menu-fx" aria-hidden="true">
            <span class="fx-scan"></span>
          </div>`;
}

function holoFrame() {
  // Four crisp corner brackets that hug a chamfered frame.
  return `<span class="holo-frame" aria-hidden="true">
            <i class="corner tl"></i><i class="corner tr"></i>
            <i class="corner bl"></i><i class="corner br"></i>
          </span>`;
}

function menuNode({ act, icon: ic, label, sub, kind }) {
  return `
    <button type="button" class="holo-node node-${kind}" data-act="${act}">
      ${holoFrame()}
      <span class="node-dial">
        <span class="dial-ring"></span>
        <span class="dial-ring ring-2"></span>
        <span class="dial-core">${icon(ic)}</span>
      </span>
      <span class="node-label">${label}</span>
      <span class="node-sub">${sub}</span>
    </button>`;
}

function renderMenu(state) {
  const online = state.backendOnline;
  const nodes = [
    { kind: "new", act: "new-game", icon: "plus", label: "New", sub: "Forge a world" },
    { kind: "play", act: "go-library", icon: "play", label: "Play", sub: "Enter your saved worlds" },
    { kind: "settings", act: "open-settings", icon: "settings", label: "Settings", sub: "Sound & backend" },
  ];
  return `
    <div class="menu-stage holo-stage" data-stage>
      ${holoFx()}

      <header class="menu-top">
        <span class="hud-tag">// MENU</span>
        ${help("menu")}
        <span class="hud-stat ${online ? "ok" : "down"}">
          <span class="stat-dot"></span>${online ? "SYSTEM ONLINE" : "LINK LOST"}
        </span>
      </header>

      <div class="menu-title">
        <h1 class="title-glyph" data-text="GAMENTIC">GAMENTIC</h1>
        <p class="title-sub">A self-hosted AI dungeon // neon decay protocol</p>
      </div>

      <nav class="menu-deck">
        ${nodes.map(menuNode).join("")}
      </nav>

      <footer class="menu-foot">
        <span class="foot-chip">v1.0</span>
        <span class="foot-line"></span>
        <span class="foot-chip dim">vanilla // no build // local model</span>
      </footer>
    </div>`;
}

// ---------------------------------------------------------------------------
// Library
// ---------------------------------------------------------------------------

function renderLibrary(state) {
  const { games, backendOnline, backendError } = state;
  let body;
  if (!backendOnline) {
    body = `
      <div class="empty-state offline">
        <div class="empty-icon">${icon("radio")}</div>
        <h2>Backend offline</h2>
        <p>Could not reach the game server${backendError ? ` (${escapeHtml(backendError)})` : ""}.
           Start the stack and retry. No fake games are shown.</p>
        <button class="holo-btn" data-act="retry-library">${icon("rotate")}<span>Retry link</span></button>
      </div>`;
  } else if (!games.length) {
    body = `
      <div class="empty-state">
        <div class="empty-icon">${icon("sparkles")}</div>
        <h2>No adventures yet</h2>
        <p>Your archive is empty. Forge your first real world to begin.</p>
        <button class="holo-btn primary" data-act="new-game">${icon("plus")}<span>New adventure</span></button>
      </div>`;
  } else {
    body = `<div class="holo-grid">
      ${games.map(renderGameCard).join("")}
      <button class="holo-card new-card" data-act="new-game">
        <span class="mini-dial">${icon("plus")}</span>
        <span class="card-title">New world</span>
        <span class="card-meta">Forge a fresh adventure</span>
      </button>
    </div>`;
  }

  return `
    <div class="holo-stage lib-stage" data-stage>
      ${holoFx()}
      <header class="holo-bar">
        <button class="holo-icon" data-act="go-menu" aria-label="Main menu" title="Main menu">${icon("chevronLeft")}</button>
        <span class="hud-tag">// ARCHIVE</span>
        ${help("library")}
        <span class="hud-stat ${backendOnline ? "ok" : "down"}">
          <span class="stat-dot"></span>${backendOnline ? "SYSTEM ONLINE" : "LINK LOST"}
        </span>
        <button class="holo-icon" data-act="open-settings" aria-label="Settings" title="Settings">${icon("settings")}</button>
      </header>
      <main class="lib-main">${body}</main>
      ${state.confirm ? renderConfirm(state.confirm) : ""}
    </div>`;
}

function renderGameCard(game) {
  return `
    <article class="holo-card" data-game-id="${escapeHtml(game.id)}">
      <span class="card-corner tr"></span><span class="card-corner bl"></span>
      <span class="card-status">${escapeHtml(game.status || "active")}</span>
      <h3 class="card-title">${escapeHtml(game.title)}</h3>
      <p class="card-meta">${escapeHtml(game.created_at || "")}</p>
      <div class="card-actions">
        <button class="holo-btn" data-act="continue-game" data-game-id="${escapeHtml(game.id)}">
          ${icon("play")}<span>Enter</span>
        </button>
        <button class="holo-icon danger" data-act="ask-delete" data-game-id="${escapeHtml(game.id)}"
                data-game-title="${escapeHtml(game.title)}" aria-label="Delete adventure" title="Delete">
          ${icon("trash")}
        </button>
      </div>
    </article>`;
}

function renderConfirm(c) {
  return `
    <div class="modal-overlay" data-act="cancel-delete">
      <div class="holo-modal" data-act="noop" role="dialog" aria-modal="true">
        <span class="card-corner tr"></span><span class="card-corner bl"></span>
        <h3 class="modal-title">${icon("trash")}<span>Delete adventure?</span></h3>
        <p class="modal-body">"${escapeHtml(c.title)}" will be wiped: characters, scenes, quests, and history. This cannot be undone.</p>
        <div class="modal-actions">
          <button class="holo-btn" data-act="cancel-delete">Cancel</button>
          <button class="holo-btn danger" data-act="confirm-delete" data-game-id="${escapeHtml(c.gameId)}">${icon("trash")}<span>Delete</span></button>
        </div>
      </div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Creator
// ---------------------------------------------------------------------------

function renderCreator(state) {
  const c = state.creator;
  const messages = c.messages
    .map(
      (m) =>
        `<div class="forge-msg ${m.role === "user" ? "from-user" : "from-builder"}">
           <span class="forge-who">${m.role === "user" ? "You" : "World-builder"}</span>
           <p>${escapeHtml(m.text)}</p>
         </div>`,
    )
    .join("");
  const thinking = c.busy
    ? `<div class="forge-msg from-builder thinking"><span class="forge-who">World-builder</span>
         <div class="narrating"><span class="dot"></span><span class="dot"></span><span class="dot"></span><em>shaping the world...</em></div>
       </div>`
    : "";
  const restored = c.restored
    ? `<div class="forge-restored">${icon("rotate")}<span>Picked up where you left off. This conversation survived.</span></div>`
    : "";

  return `
    <div class="holo-stage forge-stage" data-stage>
      ${holoFx()}
      <header class="holo-bar">
        <button class="holo-icon" data-act="go-library" aria-label="Back" title="Back to archive">${icon("chevronLeft")}</button>
        <span class="hud-tag">// FORGE</span>
        ${help("creator")}
        <button class="holo-btn forge-restart" data-act="creator-restart" title="Discard this conversation and start a new world" ${c.busy ? "disabled" : ""}>
          ${icon("rotate")}<span>Start over</span>
        </button>
      </header>

      <main class="forge-main">
        <div class="forge-thread" id="creatorThread">${restored}${messages}${thinking}</div>
      </main>

      <footer class="forge-bar">
        ${c.error ? `<p class="forge-error">${escapeHtml(c.error)}</p>` : ""}
        <form class="forge-form" data-form="creator">
          <input name="creatorText" class="holo-input" autocomplete="off"
                 placeholder="Describe your world: a haunted lighthouse, a flooded crypt, a neon city in decay..."
                 ${c.busy ? "disabled" : ""} />
          <button class="holo-btn" type="submit" ${c.busy ? "disabled" : ""}>${icon("send")}<span>Send</span></button>
        </form>
        <button class="holo-btn primary forge-begin" data-act="begin-adventure" ${c.busy ? "disabled" : ""}>
          ${icon("flame")}<span>${c.busy ? "Summoning..." : "Begin the Adventure"}</span>
        </button>
      </footer>
      ${c.finalizing ? renderCrafting() : ""}
    </div>`;
}

// Full-screen takeover while the backend forges the world (finalize can take a
// while: it builds scenes, characters, portraits, voices). Blocks the chat.
function renderCrafting() {
  const lines = [
    "Seeding the opening scene",
    "Summoning characters",
    "Painting the world",
    "Binding voices",
    "Lighting the neon",
  ];
  return `
    <div class="craft-overlay" role="status" aria-live="polite">
      <div class="craft-core">
        <span class="craft-ring r1"></span>
        <span class="craft-ring r2"></span>
        <span class="craft-ring r3"></span>
        <span class="craft-orbit"><span class="craft-spark"></span></span>
        <span class="craft-orbit slow"><span class="craft-spark alt"></span></span>
        <span class="craft-glyph">${icon("sigil")}</span>
      </div>
      <h2 class="craft-title">Forging your world</h2>
      <div class="craft-status">
        ${lines.map((t, i) => `<span style="--i:${i}">${escapeHtml(t)}</span>`).join("")}
      </div>
      <div class="craft-bar"><span></span></div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Play
// ---------------------------------------------------------------------------

// Command-deck layout (v0.2 scene-centric, integrated-header redesign):
//   ONE integrated header (scene identity + scene affordances + vitals, no
//   repeated affordances) | story (scene art mixed into the prose) + character
//   columns | player inventory + the say/do composer.
function renderPlay(state) {
  const g = state.active;
  if (!g || !g.state) {
    return `<main class="play-loading"><div class="empty-icon">${icon("sparkles")}</div><p>Loading the adventure...</p></main>`;
  }
  const s = g.state;
  const locked = Boolean(g.generating); // busy-lock: one POST = one resolved turn

  return `
    <div class="holo-stage play-stage${locked ? " generating" : ""}" data-stage>
      ${holoFx()}
      ${renderPlayDeck(s, locked, g)}

      <div class="play-body">
        <main class="story" id="storyStream" data-help-anchor role="log" aria-live="polite" aria-relevant="additions" aria-label="Story">
          <div class="story-help-row">${help("story")}</div>
          ${renderStory(g)}
          ${locked ? renderNarrating() : ""}
        </main>

        <aside class="char-column">
          <div class="col-head">${icon("mask")}<span>In the scene</span>${help("party")}</div>
          ${renderCharacters(s, locked)}
        </aside>
      </div>

      ${g.privateChat ? "" : renderActionBar(g, s, locked)}
      ${g.privateChat ? renderPrivateModal(s, g) : ""}
      ${g.give ? renderGiveModal(s, g.give, locked) : ""}
      ${g.inspect ? renderInspectModal(s, g) : ""}
      ${locked ? `<div class="busy-veil" aria-hidden="true"><span class="busy-bar"></span></div>` : ""}
    </div>`;
}

// Give-picker: choose an item from the player's inventory to hand to a character.
function renderGiveModal(s, give, locked) {
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
function renderPlayDeck(s, locked, g = {}) {
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

  // "See": generate an image of the scene WITH the present characters (sync
  // 5-10s -> loader + lock on the button). Hidden entirely when images are off.
  const seeing = Boolean(g.seeing);
  const seeBtn = s.imagesEnabled
    ? `<button type="button" class="holo-icon see-btn${seeing ? " seeing" : ""}" data-act="see-scene"
               title="See the scene as it is right now" aria-label="See the scene"
               ${seeing || locked ? "disabled" : ""}>${icon("eye")}</button>`
    : "";

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
          ${seeBtn}
        </div>
        <h2 class="scene-name">${escapeHtml(name)}${help("scene")}</h2>
        ${desc ? `<p class="scene-desc">${escapeHtml(desc)}</p>` : ""}
      </div>

      <div class="deck-board">
        <div class="board-cell">
          <span class="rail-label">${icon("gem")}<span>Scene items</span></span>
          ${slotGrid(items, 6, "scene-items", (it) => sceneItemSlot(it, locked))}
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
        ${s.currentGoal ? `<button type="button" class="hud-goal" data-act="inspect-goal" title="Current goal - tap for the quest log" ${dis}>${icon("compass")}<span>${escapeHtml(s.currentGoal)}</span></button>` : ""}
      </div>

      <div class="deck-nav">
        <button class="holo-icon" data-act="open-settings" aria-label="Menu" title="Menu / settings" ${dis}>${icon("settings")}</button>
      </div>
    </header>`;
}

// Prompt-token usage as a colored meter: green -> amber -> red as it fills.
// A PERMANENT HUD element ("12k/128k"), not a debug toggle: it renders whenever
// the backend sends context, including used=0 before the first turn. The same
// builder draws the small per-character meters (each character is its own
// agent context).
function contextMeter(ctx, { mini = false, label = "Story memory" } = {}) {
  if (!ctx || !ctx.max) return "";
  const pct = Math.round(ctx.ratio * 100);
  const tone = ctx.ratio > 0.85 ? "red" : ctx.ratio > 0.6 ? "amber" : "green";
  const fmt = (n) => (n >= 1024 ? `${Math.round(n / 1024)}k` : String(n));
  const text = `${fmt(ctx.used)}/${fmt(ctx.max)}`;
  return `
    <div class="ctx-meter${mini ? " mini" : ""} tone-${tone}" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"
         aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}: ${text} tokens (${pct}%)">
      ${icon("gauge")}
      <div class="ctx-track"><div class="ctx-fill" style="width:${pct}%"></div></div>
      <span class="ctx-num">${text}</span>
    </div>`;
}

function renderCharacters(s, locked) {
  const present = presentCharacters(s);
  const presentIds = new Set(present.map((c) => c.id));
  // everyone known but not standing here: followers lagging, those left behind, the fallen.
  const elsewhere = (s.characters || []).filter((c) => c.name && !presentIds.has(c.id));

  const here = present.length
    ? `<div class="char-deck cols-${present.length}">${present.map((c) => renderCharColumn(c, s, locked)).join("")}</div>`
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
// the column, identity reads off a plate at its foot, and the inventory +
// action buttons hang below. Art is tall-portrait by contract (frontend-api 5b).
function renderCharColumn(c, s, locked) {
  const dis = locked ? "disabled" : "";
  const hp =
    c.life != null && c.maxLife
      ? `<div class="char-hp" title="${c.life}/${c.maxLife}">
           <div class="hp-track"><div class="hp-fill" style="width:${Math.max(0, Math.min(100, (c.life / c.maxLife) * 100))}%"></div></div>
         </div>`
      : "";
  return `
    <article class="char-col${c.alive ? "" : " dead"}" data-char-id="${escapeHtml(c.id)}" style="--speaker:${escapeHtml(c.color)}">
      <button type="button" class="col-art" data-act="inspect-char" data-char-id="${escapeHtml(c.id)}" title="Inspect ${escapeHtml(c.name)}" aria-label="Inspect ${escapeHtml(c.name)}" ${locked ? "disabled" : ""}>
        ${bodyArt(c, s)}
        <div class="col-grad" aria-hidden="true"></div>
        <span class="disp-badge disp-${escapeHtml(c.disposition)}">${escapeHtml(c.disposition)}</span>
        <div class="col-plate">
          <span class="char-name">${escapeHtml(c.name)}${c.following ? ` <span class="follow-tag" title="Following you">${icon("compass")}</span>` : ""}</span>
          ${hp}
        </div>
      </button>
      ${c.description ? `<p class="char-desc">${escapeHtml(c.description)}</p>` : ""}
      ${contextMeter(c.context, { mini: true, label: `${c.name}'s memory` })}
      <div class="char-inv">
        <span class="inv-mini-label">Carrying</span>
        ${slotGrid(c.inventory, 3, "char-items")}
      </div>
      <div class="char-actions">
        ${c.actions.map((a) => charActionBtn(a, c, locked)).join("")}
        <button type="button" class="chip-btn whisper" data-act="open-private" data-channel="whisper" data-char-id="${escapeHtml(c.id)}" data-char-name="${escapeHtml(c.name)}" title="Whisper privately to ${escapeHtml(c.name)}" ${dis}>${icon("mic")}<span>Whisper</span></button>
      </div>
    </article>`;
}

// Full-body art for a character column, honoring the loading rule:
// url -> the image; null + images_enabled -> a loader (art is generating);
// null + images off -> a static color+initial figure, no loader.
function bodyArt(c, s) {
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

// Face avatar with the same loading rule (used by the private modal header).
function faceArt(c, s, cls) {
  if (c.faceUrl) {
    return `<img class="${cls}" data-art="${escapeHtml(c.faceUrl)}" src="${escapeHtml(c.faceUrl)}" alt="${escapeHtml(c.name)}" loading="lazy" />`;
  }
  if (s.imagesEnabled) {
    return `<span class="${cls} art-loading" role="img" aria-label="${escapeHtml(c.name)}"><span class="art-scan" aria-hidden="true"></span></span>`;
  }
  return `<span class="${cls} fallback" style="background:${escapeHtml(c.color)}">${escapeHtml(initials(c.name))}</span>`;
}

function castRow(c) {
  const avatar = c.faceUrl
    ? `<img src="${escapeHtml(c.faceUrl)}" alt="${escapeHtml(c.name)}" loading="lazy" />`
    : `<span class="cast-fallback" style="background:${escapeHtml(c.color)}">${escapeHtml(initials(c.name))}</span>`;
  let where;
  if (!c.alive) where = "fallen";
  else if (c.following) where = "with you";
  else if (c.present === false) where = "gone";
  else if (c.location) where = `at ${titleCase(c.location)}`;
  else where = "elsewhere";
  return `<button type="button" class="cast-row${c.alive ? "" : " dead"}" data-act="inspect-char" data-char-id="${escapeHtml(c.id)}" style="--speaker:${escapeHtml(c.color)}" title="${escapeHtml(c.name)} - ${escapeHtml(where)}">
            <span class="cast-portrait">${avatar}</span>
            <span class="cast-id"><span class="cast-name">${escapeHtml(c.name)}</span><span class="cast-where">${escapeHtml(where)}</span></span>
          </button>`;
}

// --- action buttons (button -> segment mapping is resolved in app.js) ---
function sceneActionBtn(a, locked) {
  return `<button type="button" class="chip-btn" data-act="scene-action" data-type="${escapeHtml(a.type)}" data-label="${escapeHtml(a.label)}" ${locked ? "disabled" : ""}>${escapeHtml(a.label)}</button>`;
}
function exitBtn(e, locked) {
  const ic = e.isBack ? "chevronLeft" : "compass";
  return `<button type="button" class="chip-btn exit${e.isBack ? " back" : ""}" data-act="exit" data-label="${escapeHtml(e.label)}" data-target="${escapeHtml(e.target || "")}" ${locked ? "disabled" : ""}>${icon(ic)}<span>${escapeHtml(e.label)}</span></button>`;
}
function charActionBtn(a, c, locked) {
  return `<button type="button" class="chip-btn" data-act="char-action" data-type="${escapeHtml(a.type)}" data-label="${escapeHtml(a.label)}" data-char-id="${escapeHtml(c.id)}" data-char-name="${escapeHtml(c.name)}" ${locked ? "disabled" : ""}>${escapeHtml(a.label)}</button>`;
}

// --- fixed-slot grids (caps are maximums; empty slots show capacity) ---
function slotGrid(items, total, cls, cellFn = filledSlot) {
  let cells = "";
  for (let i = 0; i < total; i++) {
    const it = items[i];
    cells += it ? cellFn(it) : `<span class="slot empty"></span>`;
  }
  return `<div class="slot-grid ${cls}">${cells}</div>`;
}

function slotInner(it) {
  return it.imageUrl
    ? `<img src="${escapeHtml(it.imageUrl)}" alt="${escapeHtml(it.name)}" loading="lazy" />`
    : `<span class="slot-abbr">${escapeHtml(initials(it.name))}</span>`;
}
function slotTip(it) {
  return it.description ? `${it.name}: ${it.description}` : it.name;
}

// inventory display slot (player / character): tappable -> the inspect modal
function filledSlot(it) {
  return `<button type="button" class="slot filled" data-act="inspect-item" data-item-id="${escapeHtml(it.id || "")}" data-item-name="${escapeHtml(it.name)}" title="${escapeHtml(slotTip(it))}" aria-label="Inspect ${escapeHtml(it.name)}">${slotInner(it)}</button>`;
}

// scene-item slot: tappable -> the inspect modal (which offers Take for loose
// loot, Examine for fixed scenery, and "ask what this is" for both).
function sceneItemSlot(it, locked) {
  const kind = it.fixed ? "scenery" : "loot";
  const tag = it.fixed
    ? `<span class="slot-tag fixed" aria-hidden="true">${icon("landmark")}</span>`
    : `<span class="slot-tag loot" aria-hidden="true">${icon("plus")}</span>`;
  return `<button type="button" class="slot filled item-${kind}" data-act="inspect-item" data-item-id="${escapeHtml(it.id || "")}" data-item-name="${escapeHtml(it.name)}" title="${escapeHtml(slotTip(it))}" aria-label="Inspect ${escapeHtml(it.name)}" ${locked ? "disabled" : ""}>${slotInner(it)}${tag}</button>`;
}

// ---------------------------------------------------------------------------
// The composer: Do/Say modes, entity chips (@), segment stacking (+), Send.
// The contenteditable line hosts non-editable chips; app.js serializes it into
// tagged segments with refs on submit.
// ---------------------------------------------------------------------------
function renderComposer({ id, mode, locked, placeholderSay, placeholderDo, submitLabel }) {
  const dis = locked ? "disabled" : "";
  const ph = mode === "say" ? placeholderSay : placeholderDo;
  return `
    <div class="composer">
      <div class="composer-modes" role="group" aria-label="Line kind">
        <button type="button" class="mode-btn${mode === "do" ? " active" : ""}" data-act="${id}-mode" data-mode="do" aria-pressed="${mode === "do"}" ${dis}>Do</button>
        <button type="button" class="mode-btn${mode === "say" ? " active" : ""}" data-act="${id}-mode" data-mode="say" aria-pressed="${mode === "say"}" ${dis}>Say</button>
      </div>
      <div class="composer-input holo-input" id="${id}Input" contenteditable="${locked ? "false" : "true"}"
           role="textbox" aria-multiline="false" aria-label="${mode === "say" ? "What you say" : "What you do"}"
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
function renderStack(stack, scope) {
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

function renderActionBar(g, s, locked) {
  const cmp = g.composer || { mode: "do", stack: [] };
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
          placeholderSay: "What do you say?",
          placeholderDo: "Do or say anything... (Enter sends)",
          submitLabel: "Send",
        })}
      </form>
    </footer>`;
}

// ---------------------------------------------------------------------------
// The private modal (Talk / Whisper): a 1:1 exchange OVER the scene, scoped to
// one character, with its own say/do composer and segment stack. Talk is spoken
// aloud (directed, others hear); Whisper is the private channel (private_with
// beats render here and never in the public story).
// ---------------------------------------------------------------------------
function renderPrivateModal(s, g) {
  const pm = g.privateChat; // { charId, name, channel, mode, stack }
  const c = (s.characters || []).find((x) => x.id === pm.charId) || { id: pm.charId, name: pm.name, color: "#2fe6ff", disposition: "unknown", faceUrl: null };
  const locked = Boolean(g.generating);
  const dis = locked ? "disabled" : "";
  const whisper = pm.channel === "whisper";
  const name = c.name || pm.name;

  const beats = whisper
    ? g.beats.filter((b) => b.privateWith === pm.charId)
    : g.beats.filter((b) => !b.privateWith && b.speaker === pm.charId);
  const veiled = g.revealQueue && g.revealQueue.length ? new Set(g.revealQueue) : null;
  const thread = beats.length
    ? beats
        .slice(-40)
        .map((b) => {
          const html = renderPmBeat(b);
          return veiled && veiled.has(b.id) ? `<div class="veil-wrap veiled">${html}</div>` : html;
        })
        .join("")
    : `<p class="pm-empty muted">${
        whisper ? `Say something only ${escapeHtml(name)} will hear.` : `Speak, and ${escapeHtml(name)} will answer aloud.`
      }</p>`;

  return `
    <div class="modal-overlay private-overlay" data-act="close-private">
      <div class="holo-modal private-modal${whisper ? " is-whisper" : ""}" data-act="noop" role="dialog" aria-modal="true"
           aria-label="${whisper ? "Whisper to" : "Talk to"} ${escapeHtml(name)}" style="--speaker:${escapeHtml(c.color)}">
        <span class="card-corner tr"></span><span class="card-corner bl"></span>
        <header class="pm-head">
          ${faceArt(c, s, "pm-face")}
          <div class="pm-id">
            <span class="pm-name">${escapeHtml(name)}</span>
            <span class="disp-badge disp-${escapeHtml(c.disposition)}">${escapeHtml(c.disposition)}</span>
            ${contextMeter(c.context, { mini: true, label: `${name}'s memory` })}
          </div>
          <button type="button" class="holo-icon pm-close" data-act="close-private" aria-label="Close" title="Close" ${dis}>${icon("x")}</button>
        </header>

        <div class="pm-channel" role="tablist" aria-label="Channel">
          <button type="button" role="tab" aria-selected="${!whisper}" class="pm-tab${!whisper ? " active" : ""}"
                  data-act="pm-channel" data-channel="talk" ${dis}>${icon("mask")}<span>Talk aloud</span></button>
          <button type="button" role="tab" aria-selected="${whisper}" class="pm-tab${whisper ? " active" : ""}"
                  data-act="pm-channel" data-channel="whisper" ${dis}>${icon("mic")}<span>Whisper</span></button>
        </div>
        <p class="pm-hint">${
          whisper
            ? `Only ${escapeHtml(name)} (and the narrator) will ever know this. The others see nothing.`
            : `Spoken aloud to ${escapeHtml(name)}. Anyone in the scene can hear it.`
        }</p>

        <div class="pm-thread" id="pmThread">${thread}</div>
        ${renderStack(pm.stack, "pm")}
        <form class="pm-form" data-form="private">
          ${renderComposer({
            id: "pm",
            mode: pm.mode,
            locked,
            placeholderSay: whisper ? `Whisper to ${name}...` : `Say to ${name}...`,
            placeholderDo: whisper ? `A discreet act only ${name} notices...` : `Do something...`,
            submitLabel: locked ? "Resolving..." : "Execute",
          })}
        </form>
      </div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Tap-to-inspect: every small thing on screen (items, characters, the goal,
// quests, system receipts) expands into a detail modal with the facts already
// in /state plus an "ask what this is" narrator aside (POST /explain,
// spoiler-safe by construction). Its image click opens the lightbox.
// ---------------------------------------------------------------------------
function renderInspectModal(s, g) {
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
      <button type="button" class="holo-btn" data-act="inspect-ask" ${ins.asking || locked ? "disabled" : ""}>
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

function inspectView(s, g, ins) {
  if (ins.kind === "item") return inspectItem(s, ins, g);
  if (ins.kind === "character") return inspectCharacter(s, ins);
  if (ins.kind === "goal") return inspectGoal(s);
  if (ins.kind === "quest") return inspectQuest(s, ins);
  if (ins.kind === "beat") return inspectBeat(g, ins);
  return { title: "Unknown", body: `<p class="modal-body">Nothing to see.</p>`, actions: "" };
}

function findInspectItem(s, key) {
  const pools = [
    ...(((s.scene && s.scene.items) || []).map((it) => ({ ...it, where: "here in the scene", inScene: true }))),
    ...((s.player.inventory || []).map((it) => ({ ...it, where: "in your pack" }))),
    ...((s.characters || []).flatMap((c) => (c.inventory || []).map((it) => ({ ...it, where: `carried by ${c.name}` })))),
  ];
  return pools.find((it) => (it.id && it.id === key) || it.name === key) || null;
}

function inspectImage(url, alt) {
  // not wrapped in a button: the global lightbox listener picks the click up
  return url
    ? `<div class="ins-figure"><img data-art="${escapeHtml(url)}" src="${escapeHtml(url)}" alt="${escapeHtml(alt)}" loading="lazy" /></div>`
    : "";
}

function inspectItem(s, ins, g) {
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

function inspectCharacter(s, ins) {
  const c = (s.characters || []).find((x) => x.id === ins.key || x.name === ins.key);
  if (!c) return { title: "Gone", body: `<p class="modal-body">No trace of them remains.</p>`, actions: "" };
  const hp =
    c.life != null && c.maxLife
      ? `<div class="char-hp" title="${c.life}/${c.maxLife}"><div class="hp-track"><div class="hp-fill" style="width:${Math.max(0, Math.min(100, (c.life / c.maxLife) * 100))}%"></div></div></div>`
      : "";
  return {
    title: c.name,
    body: `
      ${inspectImage(c.bodyUrl || c.faceUrl, c.name)}
      <p class="ins-tags">
        <span class="disp-badge disp-${escapeHtml(c.disposition)}">${escapeHtml(c.disposition)}</span>
        ${c.following ? `<span class="ins-tag">following you</span>` : ""}
        ${!c.alive ? `<span class="ins-tag">fallen</span>` : ""}
      </p>
      ${hp}
      ${c.description ? `<p class="modal-body">${escapeHtml(c.description)}</p>` : ""}
      ${contextMeter(c.context, { mini: true, label: `${c.name}'s memory` })}
      ${
        (c.inventory || []).length
          ? `<p class="ins-tags">${c.inventory.map((it) => `<span class="ins-tag">${escapeHtml(it.name)}</span>`).join("")}</p>`
          : ""
      }`,
    actions: "",
  };
}

function inspectGoal(s) {
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

function inspectQuest(s, ins) {
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

function inspectBeat(g, ins) {
  const beat = g.beats.find((b) => b.id === ins.beatId);
  return {
    title: "What just happened",
    body: `<p class="modal-body">${escapeHtml((beat && beat.text) || "")}</p>`,
    actions: "",
  };
}

// Compact beat rendering inside the private modal thread. data-beat-id + the
// .pm-text span let the staged reveal typewrite private replies too.
function renderPmBeat(beat) {
  if (beat.kind === "system") {
    return `<div class="pm-line pm-system" data-beat-id="${escapeHtml(beat.id)}">${escapeHtml(beat.text)}</div>`;
  }
  const mine = !beat.speaker || beat.speaker === "player";
  const deed = beat.kind === "action";
  return `<div class="pm-line ${mine ? "pm-you" : "pm-them"}${deed ? " pm-deed" : ""}" data-beat-id="${escapeHtml(beat.id)}">
            ${!mine && beat.speakerName ? `<b>${escapeHtml(beat.speakerName)}</b> ` : ""}<span class="pm-text">${escapeHtml(beat.text)}</span>
          </div>`;
}

// The story log. Only public beats (private_with == null) ever render here;
// private exchanges live in the private modal. The current scene's art is mixed
// INTO the prose, anchored at the ESTABLISHING beat of the current scene visit.
function renderStory(g) {
  const beats = g.beats.filter((b) => !b.privateWith);
  const artCard = sceneArtCard(g.state);

  if (!beats.length) {
    return artCard + `<p class="story-prose muted">The story has not begun yet.</p>`;
  }

  // window very long logs so the DOM does not grow unbounded (perf requirement)
  const MAX = 120;
  let shown = beats;
  let trimmed = 0;
  if (beats.length > MAX) {
    trimmed = beats.length - MAX;
    shown = beats.slice(-MAX);
  }
  const trim = trimmed ? `<p class="story-trim muted small">${trimmed} earlier moments are behind you.</p>` : "";

  // ANCHORING RULE (round-2 fix): the scene-art card pins to the FIRST
  // narration of the CURRENT scene visit - its establishing beat - never the
  // latest one (anchoring to "latest" relocated the image on every new
  // narration). The current visit is the trailing run of beats whose location
  // matches where the player is now (location-less beats don't break the run).
  // If the visit has no narration in the window, the card stands alone at the
  // top of this visit's beats.
  const here = g.state && (g.state.player.location || (g.state.scene && g.state.scene.name)) || null;
  let visitStart = 0;
  for (let i = shown.length - 1; i >= 0; i--) {
    if (here && shown[i].location && !sameLocation(shown[i].location, here)) {
      visitStart = i + 1;
      break;
    }
  }
  let anchorIdx = -1;
  for (let i = visitStart; i < shown.length; i++) {
    if (shown[i].kind === "narration") {
      anchorIdx = i;
      break;
    }
  }

  // beats queued for the staged reveal render veiled until their turn
  const veiled = g.revealQueue && g.revealQueue.length ? new Set(g.revealQueue) : null;
  const parts = shown.map((b, i) => {
    const html = renderBeat(b, g, i === anchorIdx ? artCard : "");
    return veiled && veiled.has(b.id) ? `<div class="veil-wrap veiled">${html}</div>` : html;
  });
  if (anchorIdx === -1 && artCard) parts.splice(visitStart, 0, artCard);
  return trim + parts.join("");
}

// Mirror of the backend's norm_location (underscore/space collapse).
function sameLocation(a, b) {
  const norm = (v) => String(v || "").toLowerCase().replace(/[_\s]+/g, " ").trim();
  return norm(a) === norm(b);
}

// The scene image as a collectible card living inside the prose. Loader rule:
// null + images_enabled -> a developing-photo skeleton; images off -> nothing
// (pure text must read like a book, not a grid of dead boxes).
function sceneArtCard(s) {
  const scene = s && s.scene;
  if (!scene) return "";
  const name = scene.name || "";
  if (scene.imageUrl) {
    return `<figure class="prose-art">
              <span class="card-corner tr"></span><span class="card-corner bl"></span>
              <img data-art="${escapeHtml(scene.imageUrl)}" src="${escapeHtml(scene.imageUrl)}" alt="${escapeHtml(name)}" loading="lazy" />
              ${name ? `<figcaption>${escapeHtml(name)}</figcaption>` : ""}
            </figure>`;
  }
  if (s.imagesEnabled) {
    return `<figure class="prose-art art-loading" role="img" aria-label="Scene art is being painted">
              <span class="art-scan" aria-hidden="true"></span>
              <span class="art-hint">visual manifesting...</span>
            </figure>`;
  }
  return "";
}

function renderBeat(beat, g, embed = "") {
  switch (beat.kind) {
    case "narration":
      return renderNarration(beat, embed);
    case "dialogue":
      return renderDialogue(beat, g);
    case "action":
      return renderActionBeat(beat, g);
    case "system":
      return renderSystem(beat);
    case "image":
      return renderImageBeat(beat);
    default:
      return renderNarration(beat, embed);
  }
}

// IMAGE beat (the "See" result): just an inline picture in the story flow.
// No bubble; the beat's text (the See focus, when one was given) is a small
// caption under the image. Persists in the log and re-renders on reload.
function renderImageBeat(beat) {
  if (!beat.imageUrl) return "";
  return `<figure class="beat-image" data-beat-id="${escapeHtml(beat.id)}">
            <span class="card-corner tr"></span><span class="card-corner bl"></span>
            <img data-art="${escapeHtml(beat.imageUrl)}" src="${escapeHtml(beat.imageUrl)}" alt="${escapeHtml(beat.text || "The scene as it is right now")}" loading="lazy" />
            ${beat.text ? `<figcaption>${escapeHtml(beat.text)}</figcaption>` : ""}
          </figure>`;
}

// action beats are either the player's own echoed action or a CHARACTER's deed
// (e.g. "Vergonica draws her blade."). Render each distinctly; a player echo
// that is SPEECH (say/whisper) becomes a mirrored dialogue bubble.
function renderActionBeat(beat, g) {
  if (!beat.speaker || beat.speaker === "player" || beat.speaker === "narrator") {
    const sp = playerSpeech(beat);
    if (sp) return renderPlayerSpeech(beat, sp);
    return renderPlayerAction(beat);
  }
  const ch = (g.state.characters || []).find((c) => c.id === beat.speaker);
  const color = (ch && ch.color) || "#a79fb3";
  const name = beat.speakerName || (ch && ch.name) || "";
  return `<p class="char-deed" data-beat-id="${escapeHtml(beat.id)}" style="--speaker:${escapeHtml(color)}">
            ${name ? `<b>${escapeHtml(name)}</b> ` : ""}${escapeHtml(beat.text)}
          </p>`;
}

const PLAYER_COLOR = "#2fe6ff";

// Detect a player SPEECH echo. The wire gives player echoes as kind "action"
// with texts like `you say "..." to Vex` or `you whisper to Mara: "..."`;
// the quoted span is what was said.
export function playerSpeech(beat) {
  if (beat.kind !== "action" || (beat.speaker && beat.speaker !== "player")) return null;
  const t = String(beat.text || "");
  const m = t.match(/^you\s+(say|whisper|tell|ask|shout|reply|respond|call)\b/i);
  if (!m) return null;
  const q = t.match(/[“]([\s\S]+?)[”]|"([\s\S]+?)"/);
  if (!q) return null;
  const quote = q[1] != null ? q[1] : q[2];
  const tm = t.match(/\bto\s+([^:."“]+?)\s*(?::|\.|$)/i);
  return { quote, verb: m[1].toLowerCase(), target: tm ? tm[1].trim() : null };
}

// Player speech = a dialogue bubble MIRRORED: right-aligned, avatar on the
// right, the player's color. Speech should look like speech (owner playtest).
function renderPlayerSpeech(beat, sp) {
  const whisper = sp.verb === "whisper";
  const meta = sp.target ? `${whisper ? "whispered to" : "to"} ${sp.target}` : whisper ? "whispered" : "";
  return `
    <article class="dialogue from-player${whisper ? " whispered" : ""}" data-beat-id="${escapeHtml(beat.id)}" style="--speaker:${PLAYER_COLOR}">
      <span class="bubble-avatar fallback you" style="background:${PLAYER_COLOR}">YOU</span>
      <div class="bubble">
        <span class="bubble-name">You${meta ? ` <i class="bubble-meta">${escapeHtml(meta)}</i>` : ""}</span>
        <p>${escapeHtml(sp.quote)}</p>
      </div>
    </article>`;
}

// NARRATION = prose. No bubble, no speaker label. Just the story text, set like
// a book. `embed` is the scene-art card floated into this passage so the image
// reads as part of the text, and a beat may carry its own moment art too.
function renderNarration(beat, embed = "") {
  const paras = String(beat.text)
    .split(/\n{2,}/)
    .map((p) => `<p>${escapeHtml(p).replace(/\n/g, "<br />")}</p>`)
    .join("");
  const beatArt = beat.imageUrl
    ? `<figure class="prose-art beat-art">
         <span class="card-corner tr"></span><span class="card-corner bl"></span>
         <img data-art="${escapeHtml(beat.imageUrl)}" src="${escapeHtml(beat.imageUrl)}" alt="" loading="lazy" />
       </figure>`
    : "";
  const playable = beat.voiceId ? speakBtn(beat) : "";
  return `<section class="narration" data-beat-id="${escapeHtml(beat.id)}">
            ${embed}${beatArt}${paras}${playable}
          </section>`;
}

// DIALOGUE = a distinct named bubble with the character's identity.
function renderDialogue(beat, g) {
  const ch = (g.state.characters || []).find((c) => c.id === beat.speaker);
  const color = (ch && ch.color) || "#f2b84b";
  const name = beat.speakerName || (ch && ch.name) || "Someone";
  const avatar = ch && ch.faceUrl
    ? `<img class="bubble-avatar" src="${escapeHtml(ch.faceUrl)}" alt="${escapeHtml(name)}" loading="lazy" />`
    : `<span class="bubble-avatar fallback" style="background:${escapeHtml(color)}">${escapeHtml(initials(name))}</span>`;
  return `
    <article class="dialogue" data-beat-id="${escapeHtml(beat.id)}" style="--speaker:${escapeHtml(color)}">
      ${avatar}
      <div class="bubble">
        <span class="bubble-name">${escapeHtml(name)}</span>
        <p>${escapeHtml(beat.text)}</p>
        ${beat.voiceId ? speakBtn(beat) : ""}
      </div>
    </article>`;
}

// PLAYER action = quiet inline marker, right-aligned, not a big bubble.
function renderPlayerAction(beat) {
  return `<p class="player-action" data-beat-id="${escapeHtml(beat.id)}">
            ${icon("compass")}<span>${escapeHtml(beat.text)}</span>
          </p>`;
}

// SYSTEM = small animated badge (the juice). Tappable: a receipt like
// "Obtained: brass key" opens the inspect modal to ask what it was about.
function renderSystem(beat) {
  const tone = systemTone(beat.text);
  return `<button type="button" class="system-badge ${tone}" data-beat-id="${escapeHtml(beat.id)}" data-act="inspect-beat" role="status" title="Tap to inspect">
            ${icon(systemIcon(tone))}<span>${escapeHtml(beat.text)}</span>
          </button>`;
}

function speakBtn(beat) {
  return `<button type="button" class="speak-btn" data-act="speak-beat" data-beat-id="${escapeHtml(beat.id)}" aria-label="Play voice" title="Play voice">${icon("volume2")}</button>`;
}

function renderNarrating() {
  return `<div class="narrating" role="status" aria-live="polite">
            <span class="dot"></span><span class="dot"></span><span class="dot"></span>
            <em>the narrator is thinking...</em>
          </div>`;
}

// (Quick-action chips were removed on purpose: each affordance comes from ONE
// state field and renders in ONE place - synthesized suggestion chips restated
// the goal / scene actions / character actions and read as noise.)

// ---------------------------------------------------------------------------
// Settings (tucked away; NOT shown during play)
// ---------------------------------------------------------------------------

function holoSwitch(key, on) {
  return `<span class="holo-switch">
            <input type="checkbox" data-setting="${key}" ${on ? "checked" : ""} />
            <span class="switch-track"></span>
          </span>`;
}

function renderSettings(state) {
  const st = state.settings;
  const pct = Math.round((Number(st.masterVolume) || 0) * 100);
  return `
    <div class="holo-stage set-stage" data-stage>
      ${holoFx()}
      <header class="holo-bar">
        <button class="holo-icon" data-act="close-settings" aria-label="Back" title="Back">${icon("chevronLeft")}</button>
        <span class="hud-tag">// SYSTEM</span>
        ${help("settings")}
      </header>
      <main class="set-main">
        <section class="holo-panel">
          <span class="card-corner tr"></span><span class="card-corner bl"></span>
          <h3 class="panel-head">${icon("mic")}<span>Audio</span></h3>

          <label class="set-row">
            <span class="set-label">Voice<small>Narration & character speech</small></span>
            ${holoSwitch("voiceEnabled", st.voiceEnabled)}
          </label>

          <label class="set-row">
            <span class="set-label">Auto voice<small>Speak each new line as it arrives</small></span>
            ${holoSwitch("autoplayVoice", st.autoplayVoice)}
          </label>

          <label class="set-row">
            <span class="set-label">Master volume<small>Overall loudness</small></span>
            <span class="holo-range">
              <input type="range" min="0" max="1" step="0.05" data-setting="masterVolume" value="${st.masterVolume}" />
              <span class="range-val">${pct}%</span>
            </span>
          </label>
        </section>

        <p class="set-foot">${icon("radio")}<span>Game server linked automatically // media via same-origin proxy</span></p>
      </main>
    </div>`;
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function systemTone(text) {
  const t = String(text).toLowerCase();
  // adjudication: a rejected attempt ("You don't have X.", "Mara is not here.")
  // or a narrator veto ("Mara steps back, refusing the coin.")
  if (/(don't have|do not have|not here|refus|cannot|can't)/.test(t)) return "veto";
  if (/(damage|hurt|hit|lose|wound|life)/.test(t)) return "danger";
  if (/(point|score)/.test(t)) return "points";
  if (/(item|found|gain|acquire|unlock|inventory)/.test(t)) return "item";
  if (/(quest|objective)/.test(t)) return "quest";
  return "neutral";
}

function systemIcon(tone) {
  return { veto: "x", danger: "flame", points: "star", item: "gem", quest: "scroll", neutral: "zap" }[tone] || "zap";
}

function formatProgress(p) {
  if (p && typeof p === "object" && "current" in p) return `${p.current}/${p.total}`;
  return String(p);
}

export function initials(name) {
  return String(name || "?")
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0] || "")
    .join("")
    .toUpperCase();
}

function titleCase(value) {
  return String(value || "")
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (l) => l.toUpperCase());
}
