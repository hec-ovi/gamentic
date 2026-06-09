import { test, beforeAll as before } from "vitest";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { renderApp } from "../src/render.js";
import { mapGameState, mapBeats } from "../src/adapters.js";

let document;

before(() => {
  const dom = new JSDOM("<!doctype html><body><div id='app'></div></body>", { url: "http://localhost:5173/" });
  document = dom.window.document;
  // render.js uses only string building; no globals needed. jsdom is for parsing.
});

function parse(html) {
  const el = document.createElement("div");
  el.innerHTML = html;
  return el;
}

const STATE = mapGameState({
  game_id: "g1",
  title: "The Hollow Vigil",
  narrator_voice_id: "af_alloy",
  player: { life: 18, max_life: 20, points: 30, location: "tower stair", inventory: [] },
  quests: [{ id: "q1", title: "Climb", status: "active", objectives: [{ id: "o1", text: "Reach the top", done: false }] }],
  characters: [{ id: "c1", name: "Edda", voice_id: "af_aoede", color: "#8ab", present: true, location: "tower stair" }],
});

const BEATS = mapBeats([
  { id: "b1", turn_index: 1, seq: 0, speaker: "narrator", kind: "narration", text: "The stair creaks beneath you." },
  { id: "b2", turn_index: 2, seq: 0, speaker: "player", kind: "action", text: "I climb toward the hum." },
  { id: "b3", turn_index: 2, seq: 1, speaker: "system", kind: "system", text: "Objective updated." },
  { id: "b4", turn_index: 2, seq: 2, speaker: "c1", speaker_name: "Edda", kind: "dialogue", text: "Wait for me." },
]).map((b) => ({ ...b, voiceId: b.kind === "narration" ? "af_alloy" : b.kind === "dialogue" ? "af_aoede" : null }));

function playState(overrides = {}) {
  return {
    view: "play",
    active: { id: "g1", state: STATE, beats: BEATS, quickActions: ["Look around"], generating: false, ...overrides },
  };
}

test("narration renders as prose, with NO speaker-label element and NO 'Narrator' tag", () => {
  const el = parse(renderApp(playState()));
  const narration = el.querySelector(".narration");
  assert.ok(narration, "narration block present");
  // It is a prose <section>/<p>, not a chat bubble.
  assert.ok(narration.querySelector("p"), "narration is paragraph prose");
  assert.equal(narration.querySelector(".bubble-name"), null, "narration must not carry a speaker name label");
  // No 'Narrator' label leaks anywhere in the narration text.
  assert.equal(/narrator:/i.test(narration.textContent), false);
  assert.ok(narration.textContent.includes("The stair creaks beneath you."));
});

test("dialogue renders as a distinct named bubble with the character's name", () => {
  const el = parse(renderApp(playState()));
  const dialogue = el.querySelector(".dialogue");
  assert.ok(dialogue, "dialogue card present");
  const name = dialogue.querySelector(".bubble-name");
  assert.ok(name, "dialogue carries a speaker name label");
  assert.equal(name.textContent, "Edda");
  assert.ok(dialogue.querySelector(".bubble p").textContent.includes("Wait for me."));
});

test("player action renders as a quiet inline marker (not a big bubble)", () => {
  const el = parse(renderApp(playState()));
  const action = el.querySelector(".player-action");
  assert.ok(action, "player action marker present");
  assert.equal(action.querySelector(".bubble"), null, "player action is not a chat bubble");
  assert.ok(action.textContent.includes("I climb toward the hum."));
});

test("system beat renders as an animated badge with a tone class", () => {
  const el = parse(renderApp(playState()));
  const badge = el.querySelector(".system-badge");
  assert.ok(badge, "system badge present");
  assert.ok(badge.classList.contains("quest"), "objective text -> quest tone");
  assert.ok(badge.textContent.includes("Objective updated."));
});

test("HUD shows life and points; help '?' dots exist on major panels", () => {
  const el = parse(renderApp(playState()));
  assert.ok(el.querySelector('[data-hud-num="life"]').textContent.includes("18/20"));
  assert.ok(el.querySelector('[data-hud-num="points"]').textContent.includes("30"));
  const helpKeys = [...el.querySelectorAll("[data-help]")].map((h) => h.dataset.help);
  for (const k of ["hud", "party", "scene", "inventory", "story", "action"]) {
    assert.ok(helpKeys.includes(k), `help dot for ${k} present`);
  }
});

test("play screen has NO always-on volume/settings clutter (tucked behind a menu)", () => {
  const el = parse(renderApp(playState()));
  assert.equal(el.querySelector('input[type="range"]'), null, "no volume slider during play");
  assert.equal(el.querySelector('[data-setting]'), null, "no inline settings during play");
  // Settings reachable only via the menu button.
  assert.ok(el.querySelector('[data-act="open-settings"]'), "settings live behind a menu button");
});

test("action input is enabled with a Send button when idle", () => {
  const el = parse(renderApp(playState()));
  const input = el.querySelector('[data-form="action"] input[name="actionText"]');
  const btn = el.querySelector('[data-form="action"] button[type="submit"]');
  assert.ok(input);
  assert.equal(input.hasAttribute("disabled"), false);
  assert.equal(btn.hasAttribute("disabled"), false);
});

test("while generating, the action input and Send button are disabled (invalid state handled)", () => {
  const el = parse(renderApp(playState({ generating: true })));
  const input = el.querySelector('[data-form="action"] input[name="actionText"]');
  const btn = el.querySelector('[data-form="action"] button[type="submit"]');
  assert.equal(input.hasAttribute("disabled"), true);
  assert.equal(btn.hasAttribute("disabled"), true);
  assert.ok(el.querySelector(".narrating"), "thinking indicator shown");
});

test("play view with state not yet loaded renders a loading screen (no crash)", () => {
  const el = parse(renderApp({ view: "play", active: { id: "g1", state: null, beats: [], quickActions: [], generating: true } }));
  assert.ok(el.querySelector(".play-loading"), "loading screen shown while state is null");
  assert.ok(/loading/i.test(el.textContent));
});

const SCENE_STATE = mapGameState({
  game_id: "g2",
  title: "Demo",
  status: "active",
  scene_status: "tense",
  current_goal: "Find the brass key",
  scene: {
    id: "s1",
    name: "The Bar",
    description: "A dim bar.",
    status: "tense",
    exits: [{ id: "e1", label: "the street", target: "street" }],
    items: [{ id: "i1", name: "bottle", description: "gin" }],
    available_actions: [{ id: "a1", label: "Look", type: "look" }],
  },
  player: { life: 18, max_life: 20, points: 30, location: "The Bar", inventory: [{ name: "key card" }] },
  characters: [
    {
      id: "c1",
      name: "Jacker",
      description: "Bartender.",
      present: true,
      location: "The Bar",
      life: 10,
      max_life: 10,
      disposition: "neutral",
      available_actions: [
        { id: "b0", label: "Talk", type: "talk" },
        { id: "b1", label: "Give...", type: "give" },
        { id: "b2", label: "Provoke", type: "offer" },
      ],
    },
  ],
});

function scenePlay(overrides = {}) {
  return { view: "play", active: { id: "g2", state: SCENE_STATE, beats: [], quickActions: [], generating: false, ...overrides } };
}

test("character card exposes talk/give actions + a whisper button carrying the char name", () => {
  const el = parse(renderApp(scenePlay()));
  const card = el.querySelector('.char-card[data-char-id="c1"]');
  assert.ok(card, "character card present");
  assert.ok(card.querySelector('[data-act="char-action"][data-type="talk"]'), "talk action");
  assert.ok(card.querySelector('[data-act="char-action"][data-type="give"]'), "give action");
  const whisper = card.querySelector('[data-act="whisper"][data-char-id="c1"]');
  assert.ok(whisper, "whisper button");
  assert.equal(whisper.dataset.charName, "Jacker");
});

test("scene band renders exits, scene actions and the current goal", () => {
  const el = parse(renderApp(scenePlay()));
  assert.ok(el.querySelector('[data-act="exit"][data-label="the street"]'), "exit button");
  assert.ok(el.querySelector('[data-act="scene-action"][data-label="Look"]'), "scene action button");
  assert.ok(/Find the brass key/.test(el.querySelector(".hud-goal").textContent), "goal chip");
});

test("fixed-slot grids: player inventory shows 6 slots, one filled (caps as maximums)", () => {
  const grid = parse(renderApp(scenePlay())).querySelector(".player-items");
  assert.equal(grid.querySelectorAll(".slot").length, 6);
  assert.equal(grid.querySelectorAll(".slot.filled").length, 1);
});

test("an open directed chat shows the chat context and an exit button", () => {
  const el = parse(renderApp(scenePlay({ chat: { mode: "directed", charId: "c1", name: "Jacker" } })));
  const ctx = el.querySelector(".chat-context");
  assert.ok(ctx, "chat context shown");
  assert.ok(/Talking to Jacker/.test(ctx.textContent));
  assert.ok(el.querySelector('[data-act="end-chat"]'), "leave-chat button");
});

test("private chat (whisper) is visually distinct from a directed chat", () => {
  const el = parse(renderApp(scenePlay({ chat: { mode: "private", charId: "c1", name: "Jacker" } })));
  assert.ok(el.querySelector(".action-form.chat-private"), "private chat styling");
  assert.ok(/Whispering to Jacker/.test(el.querySelector(".chat-context").textContent));
});

const PRIV_BEATS = mapBeats([
  { id: "p1", turn_index: 1, seq: 0, speaker: "narrator", kind: "narration", text: "Public line." },
  { id: "p2", turn_index: 1, seq: 1, speaker: "c1", speaker_name: "Jacker", kind: "dialogue", text: "Secret aside.", private_with: "c1" },
]);

test("private (whisper) beats never appear in the public story stream", () => {
  const story = parse(renderApp(scenePlay({ beats: PRIV_BEATS }))).querySelector("#storyStream");
  assert.ok(/Public line/.test(story.textContent), "public beat shown");
  assert.equal(/Secret aside/.test(story.textContent), false, "private beat hidden from public story");
});

test("whisper mode shows the private 1:1 thread (and only it) with a banner", () => {
  const el = parse(renderApp(scenePlay({ beats: PRIV_BEATS, chat: { mode: "private", charId: "c1", name: "Jacker" } })));
  const story = el.querySelector("#storyStream");
  assert.ok(el.querySelector(".whisper-banner"), "private channel banner");
  assert.ok(/Secret aside/.test(story.textContent), "private beat shown in whisper view");
  assert.equal(/Public line/.test(story.textContent), false, "public beats hidden in whisper view");
});

test("give-picker modal lists the player's items and targets the character", () => {
  const el = parse(renderApp(scenePlay({ give: { charId: "c1", name: "Jacker" } })));
  const pick = el.querySelector('[data-act="pick-give"][data-item="key card"]');
  assert.ok(pick, "inventory item is a give choice");
  assert.equal(pick.dataset.target, "Jacker");
});

test("offline library shows an honest offline state, never fake games", () => {
  const el = parse(renderApp({ view: "library", games: [], backendOnline: false, backendError: "unreachable" }));
  assert.ok(el.querySelector(".empty-state.offline"));
  assert.ok(/backend offline/i.test(el.textContent));
  assert.equal(el.querySelector(".game-card"), null, "no game cards when offline");
});

test("empty (online) library invites creating a real game", () => {
  const el = parse(renderApp({ view: "library", games: [], backendOnline: true, backendError: "" }));
  assert.ok(/no adventures yet/i.test(el.textContent));
  assert.ok(el.querySelector('[data-act="new-game"]'));
});

test("each library card offers Enter and a Delete action carrying its id + title", () => {
  const el = parse(
    renderApp({
      view: "library",
      backendOnline: true,
      backendError: "",
      games: [{ id: "g1", title: "Neon Decay", status: "active", created_at: "2026-06-09" }],
    }),
  );
  assert.ok(el.querySelector('[data-act="continue-game"][data-game-id="g1"]'), "Enter button");
  const del = el.querySelector('[data-act="ask-delete"][data-game-id="g1"]');
  assert.ok(del, "Delete button");
  assert.equal(del.dataset.gameTitle, "Neon Decay");
});

test("delete confirmation modal names the game and carries a confirm-delete action", () => {
  const el = parse(
    renderApp({ view: "library", backendOnline: true, games: [], confirm: { gameId: "g9", title: "Neon Decay" } }),
  );
  const modal = el.querySelector(".holo-modal");
  assert.ok(modal, "modal present when state.confirm is set");
  assert.ok(/Neon Decay/.test(modal.textContent), "modal names the game");
  assert.ok(el.querySelector('[data-act="confirm-delete"][data-game-id="g9"]'), "confirm action carries the id");
  assert.ok(el.querySelector('[data-act="cancel-delete"]'), "cancel action present");
});
