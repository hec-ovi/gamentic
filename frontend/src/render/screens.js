// The non-play screens: menu, library (delete/export/import), creator, settings.

import { icon } from "../icons.js";
import { cardCorners, escapeHtml, help, holoFrame, holoFx } from "./common.js";
import { contextMeter, hudStat, iconBtn, modalShell, narratingDots, secHead } from "./widgets.js";

export function menuNode({ act, icon: ic, label, sub, kind }) {
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

export function renderMenu(state) {
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
        ${hudStat(online)}
      </header>

      <div class="menu-title">
        <h1 class="title-glyph" data-text="GAMENTIC">GAMENTIC</h1>
        <p class="title-sub">A self-hosted AI dungeon</p>
      </div>

      <nav class="menu-deck">
        ${nodes.map(menuNode).join("")}
      </nav>

      <footer class="menu-foot">
        <span class="foot-chip">v1.0</span>
        <span class="foot-line"></span>
        <span class="foot-chip dim">LOCAL AI DUNGEON</span>
      </footer>
    </div>`;
}

// ---------------------------------------------------------------------------
// Library
// ---------------------------------------------------------------------------

export function renderLibrary(state) {
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
        <p>Forge your first real world to begin.</p>
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
        ${iconBtn({ act: "go-menu", icon: "chevronLeft", label: "Main menu" })}
        <span class="hud-tag">// ADVENTURES</span>
        ${help("library")}
        ${hudStat(backendOnline)}
        <button class="holo-btn lib-import" data-act="import-game" title="Import an exported adventure (template or checkpoint)" ${state.importing ? "disabled" : ""}>
          ${icon("rotate")}<span>${state.importing ? "Importing..." : "Import"}</span>
        </button>
        <input type="file" id="importFile" accept=".json,application/json" hidden aria-label="Adventure export file" />
        ${iconBtn({ act: "open-settings", icon: "settings", label: "Settings" })}
      </header>
      <main class="lib-main">${body}</main>
      ${state.confirm ? renderConfirm(state.confirm) : ""}
      ${state.exportChoice ? renderExportChoice(state.exportChoice) : ""}
    </div>`;
}

export function renderGameCard(game) {
  return `
    <article class="holo-card" data-game-id="${escapeHtml(game.id)}">
      ${cardCorners()}
      <span class="card-status">${escapeHtml(game.status || "active")}</span>
      <h3 class="card-title">${escapeHtml(game.title)}</h3>
      <p class="card-meta">${escapeHtml(game.created_at || "")}</p>
      <div class="card-actions">
        <button class="holo-btn" data-act="continue-game" data-game-id="${escapeHtml(game.id)}">
          ${icon("play")}<span>Enter</span>
        </button>
        ${iconBtn({ act: "ask-export", icon: "send", label: "Export adventure", title: "Export", data: { "game-id": game.id, "game-title": game.title } })}
        ${iconBtn({ act: "ask-delete", icon: "trash", label: "Delete adventure", title: "Delete", cls: "danger", data: { "game-id": game.id, "game-title": game.title } })}
      </div>
    </article>`;
}

// Export choice: one adventure, two flavors. Template = the world as designed
// (a fresh start anyone can import); checkpoint = the full save, this moment.
export function renderExportChoice(ex) {
  return modalShell({
    overlayAct: "cancel-export",
    title: `Export "${ex.title}"`,
    titleIcon: "send",
    ariaLabel: `Export "${ex.title}"`,
    body: `<p class="modal-body">Share the adventure as a fresh start, or save this exact moment as a full checkpoint. Either downloads a file the library can import.</p>`,
    actionsCls: "export-actions",
    actions: `
      <button class="holo-btn" data-act="export-game" data-kind="template" data-game-id="${escapeHtml(ex.gameId)}" data-game-title="${escapeHtml(ex.title)}">
        ${icon("sparkles")}<span>Share as adventure</span>
      </button>
      <button class="holo-btn" data-act="export-game" data-kind="checkpoint" data-game-id="${escapeHtml(ex.gameId)}" data-game-title="${escapeHtml(ex.title)}">
        ${icon("scroll")}<span>Save this moment</span>
      </button>
      <button class="holo-btn" data-act="cancel-export">Cancel</button>`,
  });
}

export function renderConfirm(c) {
  return modalShell({
    overlayAct: "cancel-delete",
    title: "Delete adventure?",
    titleIcon: "trash",
    body: `<p class="modal-body">"${escapeHtml(c.title)}" will be wiped: characters, scenes, quests, and history. This cannot be undone.</p>`,
    actions: `
      <button class="holo-btn" data-act="cancel-delete">Cancel</button>
      <button class="holo-btn danger" data-act="confirm-delete" data-game-id="${escapeHtml(c.gameId)}">${icon("trash")}<span>Delete</span></button>`,
  });
}

// ---------------------------------------------------------------------------
// Creator
// ---------------------------------------------------------------------------

export function renderCreator(state) {
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
         ${narratingDots("shaping the world...")}
       </div>`
    : "";
  const restored = c.restored
    ? `<div class="forge-restored">${icon("rotate")}<span>Picked up where you left off. This conversation survived.</span></div>`
    : "";

  return `
    <div class="holo-stage forge-stage" data-stage>
      ${holoFx()}
      <header class="holo-bar">
        ${iconBtn({ act: "go-library", icon: "chevronLeft", label: "Back", title: "Back to adventures" })}
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
        <button class="holo-btn primary forge-begin" data-act="begin-adventure" ${c.busy || !c.ready ? "disabled" : ""}
                title="${c.ready ? "Forge this world and begin" : "The world-builder unlocks this when your world is ready"}">
          ${icon("flame")}<span>${c.busy ? "Summoning..." : c.ready ? "Begin the Adventure" : "Begin (not ready yet)"}</span>
        </button>
      </footer>
      ${c.finalizing ? renderCrafting() : ""}
    </div>`;
}

// Full-screen takeover while the backend forges the world (finalize can take a
// while: it builds scenes, characters, portraits, voices). Blocks the chat.
export function renderCrafting() {
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

// (Quick-action chips were removed on purpose: each affordance comes from ONE
// state field and renders in ONE place - synthesized suggestion chips restated
// the goal / scene actions / character actions and read as noise.)

// ---------------------------------------------------------------------------
// Settings (tucked away; NOT shown during play)
// ---------------------------------------------------------------------------

export function holoSwitch(key, on) {
  return `<span class="holo-switch">
            <input type="checkbox" data-setting="${key}" ${on ? "checked" : ""} />
            <span class="switch-track"></span>
          </span>`;
}

export function renderSettings(state) {
  const st = state.settings;
  const pct = Math.round((Number(st.masterVolume) || 0) * 100);
  return `
    <div class="holo-stage set-stage" data-stage>
      ${holoFx()}
      <header class="holo-bar">
        ${iconBtn({ act: "close-settings", icon: "chevronLeft", label: "Back" })}
        <span class="hud-tag">// SYSTEM</span>
        ${help("settings")}
      </header>
      <main class="set-main">
        <div class="set-col">
        <section class="holo-panel">
          ${cardCorners()}
          ${secHead("h3", "panel-head", "mic", "Audio")}

          <label class="set-row">
            <span class="set-label">Voice<small>Narration & character speech</small></span>
            ${holoSwitch("voiceEnabled", st.voiceEnabled)}
          </label>

          <label class="set-row">
            <span class="set-label">Narrator voice<small>Auto-speak narration as it arrives</small></span>
            ${holoSwitch("autoplayNarrator", st.autoplayNarrator)}
          </label>

          <label class="set-row">
            <span class="set-label">Character voices<small>Auto-speak character lines as they arrive</small></span>
            ${holoSwitch("autoplayCharacters", st.autoplayCharacters)}
          </label>

          <label class="set-row">
            <span class="set-label">Master volume<small>Overall loudness</small></span>
            <span class="holo-range">
              <input type="range" min="0" max="1" step="0.05" data-setting="masterVolume" value="${Number(st.masterVolume) || 0}" />
              <span class="range-val">${pct}%</span>
            </span>
          </label>
        </section>

        ${state.active && state.active.state ? renderMemorySettings(state.active) : ""}
        </div>

        <div class="set-col">
        ${state.active && state.active.state ? renderGameSettings(state.active) : ""}
        <section class="holo-panel danger-zone">
          ${cardCorners()}
          ${secHead("h3", "panel-head", "flame", "Danger")}
          <div class="set-row">
            <span class="set-label">Wipe all memory<small>Every adventure, its history, characters and images. No undo.</small></span>
            <button type="button" class="holo-btn danger" data-act="ask-wipe">${icon("trash")}<span>Wipe all memory</span></button>
          </div>
        </section>
        </div>

        <p class="set-foot">${icon("radio")}<span>Game server linked automatically // media via same-origin proxy</span></p>
      </main>
      ${state.wipe ? renderWipeConfirm(state.wipe) : ""}
    </div>`;
}

// The wipe-all double confirm: the first click ARMS the button, the second
// erases. There is no undo, so the dialog says exactly what it deletes.
export function renderWipeConfirm(w) {
  return modalShell({
    overlayAct: "cancel-wipe",
    title: "Wipe all memory?",
    titleIcon: "flame",
    body: `<p class="modal-body">This deletes EVERY adventure, its history, characters and images. There is no undo.</p>
        ${w.stage > 1 ? `<p class="modal-body wipe-armed">Last chance. Click once more and it is all gone.</p>` : ""}`,
    actions: `
      <button class="holo-btn" data-act="cancel-wipe" ${w.busy ? "disabled" : ""}>Cancel</button>
      <button class="holo-btn danger" data-act="confirm-wipe" ${w.busy ? "disabled" : ""}>
        ${icon("trash")}<span>${w.busy ? "Erasing..." : w.stage > 1 ? "Yes, erase everything" : "Erase everything"}</span>
      </button>`,
  });
}

// Story memory (PATCH /games/{id}/settings): how the narrator remembers. The
// mental model in the copy: recent story rides verbatim, everything older is
// auto-compressed into a recap, so the story is never lost. Three controls;
// 0 always returns a control to its default. context_tokens is the one that
// actually CAPS turn latency, so the live meter sits next to it.
function renderMemorySettings(g) {
  const st = g.state.settings || {};
  const saving = g.settingsSaving ? "disabled" : "";
  const memRow = (key, value, label, sub, min, max, step) => `
    <label class="set-row mem-row">
      <span class="set-label">${escapeHtml(label)}<small>${escapeHtml(sub)}</small></span>
      <input type="number" class="holo-input mem-input" data-mem-setting="${key}" aria-label="${escapeHtml(label)}"
             value="${Number(value) || 0}" min="0" max="${max}" step="${step}" ${saving} />
    </label>`;
  return `
    <section class="holo-panel memory-settings">
      ${cardCorners()}
      ${secHead("h3", "panel-head", "gauge", "Story memory")}
      <p class="set-note">The narrator re-reads the recent story word for word and automatically compresses everything older into a recap, so the story is never lost. 0 returns a control to its default.</p>
      ${memRow("history_beats", st.historyBeats, "Memory depth", "How much recent story rides verbatim (8-400). Deeper = richer continuity, slower turns.", 8, 400, 4)}
      ${memRow("summary_every", st.summaryEvery, "Auto-summarize every N turns", "How often older chapters fold into the recap (2-50).", 2, 50, 1)}
      ${memRow("context_tokens", st.contextTokens, "Context budget (auto)", "Hard size target for the narrator's reading (4000-120000; 0 = off). This caps turn latency.", 4000, 120000, 1000)}
      ${contextMeter(g.state.context)}
    </section>`;
}

// Per-adventure settings (PATCH /games/{id}/settings), shown only when settings
// is opened from inside a game. Difficulty is how much the world bends toward
// the player; the narrator gender redesigns the voice from the next line.
export const DIFFICULTY_COPY = {
  easy: "The story bends toward you: attempts succeed, danger warns first, wishes come true.",
  normal: "A fair world: the narrator weighs your attempts and your wishes on their merits.",
  hard: "The world is strict: attempts can be refused, mistakes cost you, wishes are just whispers.",
};

export function renderGameSettings(g) {
  const gs = g.state.settings || { difficulty: "normal", narratorGender: "" };
  const saving = g.settingsSaving ? "disabled" : "";
  const radio = (group, value, current, label, sub) => `
    <label class="set-radio${current === value ? " active" : ""}">
      <input type="radio" name="${group}" value="${escapeHtml(value)}" data-game-setting="${group}"
             ${current === value ? "checked" : ""} ${saving} />
      <span class="set-label">${escapeHtml(label)}${sub ? `<small>${escapeHtml(sub)}</small>` : ""}</span>
    </label>`;

  return `
    <section class="holo-panel game-settings">
      ${cardCorners()}
      ${secHead("h3", "panel-head", "sigil", "This adventure")}

      <fieldset class="set-group" data-group="difficulty">
        <legend class="set-legend">Difficulty</legend>
        ${radio("difficulty", "easy", gs.difficulty, "Easy", DIFFICULTY_COPY.easy)}
        ${radio("difficulty", "normal", gs.difficulty, "Normal", DIFFICULTY_COPY.normal)}
        ${radio("difficulty", "hard", gs.difficulty, "Hard", DIFFICULTY_COPY.hard)}
      </fieldset>

      <fieldset class="set-group" data-group="narrator_gender">
        <legend class="set-legend">Narrator voice</legend>
        ${radio("narrator_gender", "", gs.narratorGender, "Default", "The voice the world was born with")}
        ${radio("narrator_gender", "female", gs.narratorGender, "Female", "Takes effect on the next spoken line")}
        ${radio("narrator_gender", "male", gs.narratorGender, "Male", "Takes effect on the next spoken line")}
      </fieldset>

      <fieldset class="set-group" data-group="turn_pacing">
        <legend class="set-legend">Turn pacing</legend>
        <p class="set-note">How crowded a single turn can get: how many characters the narrator may pull into one turn, and how many times each of them may act before the turn ends. Default lets the narrator pace itself.</p>
        ${pacingSelect("turn_voices", gs.turnVoices, "Voices per turn", "Characters who may speak or act in one turn (1-4).", 4, saving)}
        ${pacingSelect("turn_acts", gs.turnActs, "Acts per voice", "Times each of those may act before the turn ends (1-3).", 3, saving)}
      </fieldset>

    </section>`;
}

// One turn-pacing select: Default (sends 0, back to the narrator's own pace)
// plus the explicit 1..max values. Shows the EFFECTIVE value from state.
function pacingSelect(key, value, label, sub, max, saving) {
  const options = [];
  for (let v = 1; v <= max; v++) {
    options.push(`<option value="${v}" ${Number(value) === v ? "selected" : ""}>${v}</option>`);
  }
  return `
    <label class="set-row">
      <span class="set-label">${escapeHtml(label)}<small>${escapeHtml(sub)}</small></span>
      <select class="holo-input pace-select" data-game-setting="${key}" aria-label="${escapeHtml(label)}" ${saving}>
        <option value="0">Default</option>
        ${options.join("")}
      </select>
    </label>`;
}
