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

export const HELP = {
  menu: "The main deck. Play drops you into your saved worlds, New forges a fresh adventure, and Settings tunes sound and the backend. Everything else is just light.",
  hud: "Your vitals. The heart bar is your life; if it empties the story turns against you. Points are story score earned by clever and brave actions. The label shows where you are right now.",
  quests: "Your current goals. Each quest has a checklist of objectives. The narrator ticks them off as you make progress, and may add new ones as the story unfolds.",
  party: "Characters here in the scene with you. Each shows their mood toward you, health, and what they carry. Use their buttons to talk, give, or act on them, or Whisper for a private aside only they hear.",
  scene: "Where you are right now. The picture sets the place; its mood (calm, tense, dangerous) shifts with the story. Below are objects you have found here and the things you can do, including ways out.",
  inventory: "What you are carrying. Empty slots show how much more you can hold. Use a character's Give button to hand something over.",
  story: "The story itself. Plain flowing text is the narrator telling the tale, just read it. Coloured cards with a name are characters speaking to you. Small badges are things that just happened (damage, items, points).",
  action: "Type whatever you want to do in your own words and press Send. This is a freeform adventure, not a menu. The quick suggestions below are just shortcuts you can ignore.",
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

  return `
    <div class="holo-stage forge-stage" data-stage>
      ${holoFx()}
      <header class="holo-bar">
        <button class="holo-icon" data-act="go-library" aria-label="Back" title="Back to archive">${icon("chevronLeft")}</button>
        <span class="hud-tag">// FORGE</span>
        ${help("creator")}
      </header>

      <main class="forge-main">
        <div class="forge-thread" id="creatorThread">${messages}${thinking}</div>
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

// Command-deck layout (v0.2 scene-centric):
//   HUD bar | scene band (image + items + actions) | story (left) + characters
//   (right) | player inventory + action input.
function renderPlay(state) {
  const g = state.active;
  if (!g || !g.state) {
    return `<main class="play-loading"><div class="empty-icon">${icon("sparkles")}</div><p>Loading the adventure...</p></main>`;
  }
  const s = g.state;
  const chat = g.chat || null; // { mode: "directed"|"private", charId, name }

  return `
    <div class="holo-stage play-stage" data-stage>
      ${holoFx()}
      ${renderPlayHud(s)}
      ${renderSceneBand(s)}

      <div class="play-body">
        <main class="story" id="storyStream" data-help-anchor role="log" aria-live="polite" aria-relevant="additions" aria-label="Story">
          <div class="story-help-row">${help("story")}</div>
          ${renderStory(g)}
          ${g.generating ? renderNarrating() : ""}
        </main>

        <aside class="char-column">
          <div class="col-head">${icon("mask")}<span>In the scene</span>${help("party")}</div>
          ${renderCharacters(s)}
        </aside>
      </div>

      ${renderActionBar(g, s, chat)}
      ${g.give ? renderGiveModal(s, g.give) : ""}
    </div>`;
}

// Give-picker: choose an item from the player's inventory to hand to a character.
function renderGiveModal(s, give) {
  const items = s.player.inventory || [];
  const body = items.length
    ? `<div class="give-grid">${items
        .map(
          (it) =>
            `<button type="button" class="holo-btn give-pick" data-act="pick-give" data-item="${escapeHtml(it.name)}" data-target="${escapeHtml(give.name)}">${escapeHtml(it.name)}</button>`,
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
        <div class="modal-actions"><button class="holo-btn" data-act="cancel-give">Cancel</button></div>
      </div>
    </div>`;
}

function renderPlayHud(s) {
  const p = s.player;
  const pct = p.maxLife ? Math.max(0, Math.min(100, (p.life / p.maxLife) * 100)) : 0;
  const mood = s.sceneStatus || (s.scene && s.scene.status) || null;
  return `
    <header class="play-hud">
      <button class="holo-icon" data-act="go-library" aria-label="Library" title="Library">${icon("chevronLeft")}</button>
      <div class="hud" data-hud>
        ${help("hud")}
        <div class="hud-life" data-hud-life>
          ${icon("heart")}
          <div class="life-track"><div class="life-fill" style="width:${pct}%"></div></div>
          <span class="hud-num" data-hud-num="life">${p.life}/${p.maxLife}</span>
        </div>
        <div class="hud-points">${icon("star")}<span class="hud-num" data-hud-num="points">${p.points}</span></div>
      </div>
      ${s.currentGoal ? `<div class="hud-goal" title="Current goal">${icon("compass")}<span>${escapeHtml(s.currentGoal)}</span></div>` : ""}
      ${mood ? `<span class="mood-badge mood-${escapeHtml(mood)}">${escapeHtml(mood)}</span>` : ""}
      <button class="holo-icon" data-act="open-settings" aria-label="Menu" title="Menu / settings">${icon("settings")}</button>
    </header>`;
}

// The scene: a hero image (the "big thing") with name/mood overlaid, plus the
// scene's revealed items (6 slots) on one side and its actions + exits on the other.
function renderSceneBand(s) {
  const scene = s.scene;
  const name = (scene && scene.name) || titleCase(s.player.location || "Unknown");
  const desc = (scene && scene.description) || "";
  const mood = (scene && scene.status) || s.sceneStatus || null;
  const img = scene && scene.imageUrl;
  const hero = img
    ? `<img class="scene-img" src="${escapeHtml(scene.imageUrl)}" alt="${escapeHtml(name)}" loading="lazy" />`
    : `<div class="scene-img placeholder">${icon("landmark")}</div>`;

  const items = (scene && scene.items) || [];
  const actions = (scene && scene.actions) || [];
  const exits = (scene && scene.exits) || [];

  return `
    <section class="scene-band">
      <div class="scene-hero">
        ${hero}
        <div class="scene-hero-grad"></div>
        <div class="scene-hero-text">
          ${mood ? `<span class="mood-badge mood-${escapeHtml(mood)}">${escapeHtml(mood)}</span>` : ""}
          <h2 class="scene-name">${escapeHtml(name)}${help("scene")}</h2>
          ${desc ? `<p class="scene-desc">${escapeHtml(desc)}</p>` : ""}
        </div>
      </div>
      <div class="scene-rail">
        <div class="rail-block">
          <span class="rail-label">${icon("gem")}<span>Scene items</span></span>
          ${slotGrid(items, 6, "scene-items", sceneItemSlot)}
        </div>
        <div class="rail-block">
          <span class="rail-label">${icon("zap")}<span>Actions</span></span>
          <div class="act-row">
            ${actions.map((a) => sceneActionBtn(a)).join("")}
            ${!actions.length ? `<span class="muted small">Nothing obvious to do.</span>` : ""}
          </div>
        </div>
        <div class="rail-block">
          <span class="rail-label">${icon("compass")}<span>Ways out</span></span>
          <div class="act-row">
            ${exits.map((e) => exitBtn(e)).join("")}
            ${!exits.length ? `<span class="dead-end">${icon("x")}<span>Dead end: no way out revealed</span></span>` : ""}
          </div>
        </div>
      </div>
    </section>`;
}

function renderCharacters(s) {
  const present = presentCharacters(s);
  const presentIds = new Set(present.map((c) => c.id));
  // everyone known but not standing here: followers lagging, those left behind, the fallen.
  const elsewhere = (s.characters || []).filter((c) => c.name && !presentIds.has(c.id));

  const here = present.length
    ? `<div class="char-list">${present.map(renderCharacterCard).join("")}</div>`
    : `<p class="muted small char-empty">No one else is here right now.</p>`;

  const roster = elsewhere.length
    ? `<div class="cast-roster">
         <div class="col-head sub">${icon("eye")}<span>Elsewhere</span></div>
         ${elsewhere.map(castRow).join("")}
       </div>`
    : "";

  return here + roster;
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
  return `<div class="cast-row${c.alive ? "" : " dead"}" style="--speaker:${escapeHtml(c.color)}" title="${escapeHtml(c.name)} - ${escapeHtml(where)}">
            <span class="cast-portrait">${avatar}</span>
            <span class="cast-id"><span class="cast-name">${escapeHtml(c.name)}</span><span class="cast-where">${escapeHtml(where)}</span></span>
          </div>`;
}

function renderCharacterCard(c) {
  const portrait = c.faceUrl
    ? `<img src="${escapeHtml(c.faceUrl)}" alt="${escapeHtml(c.name)}" loading="lazy" />`
    : `<span class="char-fallback" style="background:${escapeHtml(c.color)}">${escapeHtml(initials(c.name))}</span>`;
  const hp =
    c.life != null && c.maxLife
      ? `<div class="char-hp" title="${c.life}/${c.maxLife}">
           <div class="hp-track"><div class="hp-fill" style="width:${Math.max(0, Math.min(100, (c.life / c.maxLife) * 100))}%"></div></div>
         </div>`
      : "";
  return `
    <article class="char-card" data-char-id="${escapeHtml(c.id)}" style="--speaker:${escapeHtml(c.color)}">
      <span class="card-corner tr"></span><span class="card-corner bl"></span>
      <div class="char-top">
        <span class="char-portrait">${portrait}</span>
        <div class="char-meta">
          <span class="char-name">${escapeHtml(c.name)}${c.following ? ` <span class="follow-tag" title="Following you">${icon("compass")}</span>` : ""}</span>
          <span class="disp-badge disp-${escapeHtml(c.disposition)}">${escapeHtml(c.disposition)}</span>
          ${hp}
        </div>
      </div>
      ${c.description ? `<p class="char-desc">${escapeHtml(c.description)}</p>` : ""}
      <div class="char-inv-row">
        <span class="inv-mini-label">Carrying</span>
        ${slotGrid(c.inventory, 3, "char-items")}
      </div>
      <div class="char-actions">
        ${c.actions.map((a) => charActionBtn(a, c)).join("")}
        <button type="button" class="chip-btn whisper" data-act="whisper" data-char-id="${escapeHtml(c.id)}" data-char-name="${escapeHtml(c.name)}" title="Whisper privately to ${escapeHtml(c.name)}">${icon("mic")}<span>Whisper</span></button>
      </div>
    </article>`;
}

// --- action buttons (button -> segment mapping is resolved in app.js) ---
function sceneActionBtn(a) {
  return `<button type="button" class="chip-btn" data-act="scene-action" data-type="${escapeHtml(a.type)}" data-label="${escapeHtml(a.label)}">${escapeHtml(a.label)}</button>`;
}
function exitBtn(e) {
  const ic = e.isBack ? "chevronLeft" : "compass";
  return `<button type="button" class="chip-btn exit${e.isBack ? " back" : ""}" data-act="exit" data-label="${escapeHtml(e.label)}" data-target="${escapeHtml(e.target || "")}">${icon(ic)}<span>${escapeHtml(e.label)}</span></button>`;
}
function charActionBtn(a, c) {
  return `<button type="button" class="chip-btn" data-act="char-action" data-type="${escapeHtml(a.type)}" data-label="${escapeHtml(a.label)}" data-char-id="${escapeHtml(c.id)}" data-char-name="${escapeHtml(c.name)}">${escapeHtml(a.label)}</button>`;
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

// non-interactive display slot (player / character inventories)
function filledSlot(it) {
  return `<span class="slot filled" data-item-id="${escapeHtml(it.id || "")}" data-item-name="${escapeHtml(it.name)}" title="${escapeHtml(slotTip(it))}">${slotInner(it)}</span>`;
}

// interactive scene-item slot: loot (fixed:false) can be TAKEN, scenery
// (fixed:true) can only be EXAMINED (the backend refuses to pocket the furniture).
function sceneItemSlot(it) {
  const act = it.fixed ? "examine-item" : "take-item";
  const kind = it.fixed ? "scenery" : "loot";
  const tag = it.fixed
    ? `<span class="slot-tag fixed" aria-hidden="true">${icon("landmark")}</span>`
    : `<span class="slot-tag loot" aria-hidden="true">${icon("plus")}</span>`;
  const verb = it.fixed ? "Examine" : "Take";
  return `<button type="button" class="slot filled item-${kind}" data-act="${act}" data-item-id="${escapeHtml(it.id || "")}" data-item-name="${escapeHtml(it.name)}" title="${escapeHtml(slotTip(it))} - ${verb}" aria-label="${verb} ${escapeHtml(it.name)}">${slotInner(it)}${tag}</button>`;
}

function renderActionBar(g, s, chat) {
  const placeholder = g.generating
    ? "The narrator is thinking..."
    : chat
      ? `${chat.mode === "private" ? "Whisper" : "Say"} to ${chat.name}...`
      : "What do you do?";
  return `
    <footer class="play-actionbar">
      <div class="player-inv">
        <span class="rail-label">${icon("gem")}<span>You</span>${help("inventory")}</span>
        ${slotGrid(s.player.inventory, 6, "player-items")}
      </div>
      ${renderQuickActions(g)}
      <form class="action-form ${chat ? `chat-${chat.mode}` : ""}" data-form="action">
        ${chat ? `<span class="chat-context">${icon(chat.mode === "private" ? "mic" : "mask")}<span>${chat.mode === "private" ? "Whispering to" : "Talking to"} ${escapeHtml(chat.name)}</span><button type="button" class="chat-close" data-act="end-chat" title="Leave chat">${icon("x")}</button></span>` : `<span class="action-help">${help("action")}</span>`}
        <input name="actionText" class="holo-input" autocomplete="off"
               placeholder="${escapeHtml(placeholder)}"
               ${g.generating ? "disabled" : ""} />
        <button class="holo-btn" type="submit" ${g.generating ? "disabled" : ""}>
          ${icon("send")}<span>Send</span>
        </button>
      </form>
    </footer>`;
}

// The story log. Public beats (private_with == null) render in the main stream.
// When a private (whisper) chat is open, the stream instead shows the 1:1 thread
// with that character - private beats never appear in the public story.
function renderStory(g) {
  const chat = g.chat;
  const privId = chat && chat.mode === "private" ? chat.charId : null;
  const beats = privId
    ? g.beats.filter((b) => b.privateWith === privId)
    : g.beats.filter((b) => !b.privateWith);

  const banner = privId
    ? `<div class="whisper-banner">${icon("mic")}<span>Private channel with ${escapeHtml(chat.name)}. No one else hears this.</span></div>`
    : "";

  if (!beats.length) {
    const empty = privId
      ? `Say something only ${escapeHtml(chat.name)} will hear.`
      : "The story has not begun yet.";
    return `${banner}<p class="story-prose muted">${empty}</p>`;
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
  return banner + trim + shown.map((b) => renderBeat(b, g)).join("");
}

function renderBeat(beat, g) {
  switch (beat.kind) {
    case "narration":
      return renderNarration(beat);
    case "dialogue":
      return renderDialogue(beat, g);
    case "action":
      return renderActionBeat(beat, g);
    case "system":
      return renderSystem(beat);
    default:
      return renderNarration(beat);
  }
}

// action beats are either the player's own echoed action or a CHARACTER's deed
// (e.g. "Vergonica draws her blade."). Render each distinctly.
function renderActionBeat(beat, g) {
  if (!beat.speaker || beat.speaker === "player" || beat.speaker === "narrator") {
    return renderPlayerAction(beat);
  }
  const ch = (g.state.characters || []).find((c) => c.id === beat.speaker);
  const color = (ch && ch.color) || "#a79fb3";
  const name = beat.speakerName || (ch && ch.name) || "";
  return `<p class="char-deed" data-beat-id="${escapeHtml(beat.id)}" style="--speaker:${escapeHtml(color)}">
            ${name ? `<b>${escapeHtml(name)}</b> ` : ""}${escapeHtml(beat.text)}
          </p>`;
}

// NARRATION = prose. No bubble, no speaker label. Just the story text, set like a book.
function renderNarration(beat) {
  const paras = String(beat.text)
    .split(/\n{2,}/)
    .map((p) => `<p>${escapeHtml(p).replace(/\n/g, "<br />")}</p>`)
    .join("");
  const playable = beat.voiceId ? speakBtn(beat) : "";
  return `<section class="narration" data-beat-id="${escapeHtml(beat.id)}">
            ${paras}${playable}
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

// SYSTEM = small animated badge (the juice).
function renderSystem(beat) {
  const tone = systemTone(beat.text);
  return `<div class="system-badge ${tone}" data-beat-id="${escapeHtml(beat.id)}" role="status">
            ${icon(systemIcon(tone))}<span>${escapeHtml(beat.text)}</span>
          </div>`;
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

function renderQuickActions(g) {
  const chips = g.quickActions || [];
  if (!chips.length || g.generating) return "";
  return `<div class="quick-actions">
    ${chips.map((c) => `<button type="button" class="chip" data-act="quick" data-text="${escapeHtml(c)}">${escapeHtml(c)}</button>`).join("")}
  </div>`;
}

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
  if (/(damage|hurt|hit|lose|wound|life)/.test(t)) return "danger";
  if (/(point|score)/.test(t)) return "points";
  if (/(item|found|gain|acquire|unlock|inventory)/.test(t)) return "item";
  if (/(quest|objective)/.test(t)) return "quest";
  return "neutral";
}

function systemIcon(tone) {
  return { danger: "flame", points: "star", item: "gem", quest: "scroll", neutral: "zap" }[tone] || "zap";
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
