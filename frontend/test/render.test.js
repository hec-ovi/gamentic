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
    active: { id: "g1", state: STATE, beats: BEATS, generating: false, composer: { mode: "do", stack: [] }, ...overrides },
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

test("the composer is live with a Send button when idle", () => {
  const el = parse(renderApp(playState()));
  const input = el.querySelector('[data-form="action"] #cmpInput');
  const btn = el.querySelector('[data-form="action"] button[type="submit"]');
  assert.equal(input.getAttribute("contenteditable"), "true");
  assert.equal(btn.hasAttribute("disabled"), false);
});

test("while generating, the composer is locked and the stage is veiled (busy-lock)", () => {
  const el = parse(renderApp(playState({ generating: true })));
  const input = el.querySelector('[data-form="action"] #cmpInput');
  const btn = el.querySelector('[data-form="action"] button[type="submit"]');
  assert.equal(input.getAttribute("contenteditable"), "false");
  assert.equal(btn.hasAttribute("disabled"), true);
  assert.ok(el.querySelector(".narrating"), "thinking indicator shown");
  assert.ok(el.querySelector(".busy-veil"), "interaction veil over the stage");
});

test("play view with state not yet loaded renders a loading screen (no crash)", () => {
  const el = parse(renderApp({ view: "play", active: { id: "g1", state: null, beats: [], generating: true } }));
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
  return {
    view: "play",
    active: { id: "g2", state: SCENE_STATE, beats: [], generating: false, composer: { mode: "do", stack: [] }, ...overrides },
  };
}

test("character column exposes talk/give actions + a whisper entry to the private modal", () => {
  const el = parse(renderApp(scenePlay()));
  const col = el.querySelector('.char-col[data-char-id="c1"]');
  assert.ok(col, "character column present");
  assert.ok(col.querySelector(".col-art"), "tall art slot present");
  assert.ok(col.querySelector('[data-act="char-action"][data-type="talk"]'), "talk action");
  assert.ok(col.querySelector('[data-act="char-action"][data-type="give"]'), "give action");
  const whisper = col.querySelector('[data-act="open-private"][data-channel="whisper"][data-char-id="c1"]');
  assert.ok(whisper, "whisper button opens the private modal");
  assert.equal(whisper.dataset.charName, "Jacker");
});

test("the integrated deck renders exits, scene actions and the current goal in ONE header", () => {
  const el = parse(renderApp(scenePlay()));
  const deck = el.querySelector(".play-deck");
  assert.ok(deck, "one integrated header");
  assert.ok(deck.querySelector('[data-act="exit"][data-label="the street"]'), "exit button lives in the deck");
  assert.ok(deck.querySelector('[data-act="scene-action"][data-label="Look"]'), "scene action lives in the deck");
  assert.ok(/Find the brass key/.test(deck.querySelector(".hud-goal").textContent), "goal chip lives in the deck");
  assert.ok(deck.querySelector(".scene-name"), "scene identity lives in the deck");
  assert.equal(el.querySelector(".scene-band"), null, "no separate scene band below the header");
});

test("no repeated affordances: goal once, mood once, no quick chips", () => {
  const el = parse(renderApp(scenePlay()));
  assert.equal(el.querySelectorAll(".hud-goal").length, 1, "exactly one goal chip");
  assert.equal(el.querySelectorAll(".mood-badge").length, 1, "exactly one mood badge");
  assert.equal(el.querySelector('[data-act="quick"]'), null, "no synthesized suggestion chips");
});

test("fixed-slot grids: player inventory shows 6 slots, one filled (caps as maximums)", () => {
  const grid = parse(renderApp(scenePlay())).querySelector(".player-items");
  assert.equal(grid.querySelectorAll(".slot").length, 6);
  assert.equal(grid.querySelectorAll(".slot.filled").length, 1);
});

test("Talk opens the private modal over the scene; the main composer is hidden", () => {
  const el = parse(
    renderApp(scenePlay({ privateChat: { charId: "c1", name: "Jacker", channel: "talk", mode: "say", stack: [] } })),
  );
  const modal = el.querySelector(".private-modal");
  assert.ok(modal, "modal present");
  assert.equal(modal.getAttribute("role"), "dialog");
  assert.ok(/Jacker/.test(modal.querySelector(".pm-name").textContent));
  assert.ok(/anyone in the scene can hear/i.test(modal.querySelector(".pm-hint").textContent), "talk explains it is aloud");
  assert.ok(modal.querySelector("#pmInput"), "modal has its own composer");
  assert.ok(modal.querySelector('[data-act="pm-mode"][data-mode="do"]'), "modal composer separates say and do");
  assert.equal(el.querySelector('[data-form="action"]'), null, "main composer hidden while the modal is open");
});

test("the whisper channel is visually distinct and explains the difference", () => {
  const el = parse(
    renderApp(scenePlay({ privateChat: { charId: "c1", name: "Jacker", channel: "whisper", mode: "say", stack: [] } })),
  );
  const modal = el.querySelector(".private-modal");
  assert.ok(modal.classList.contains("is-whisper"), "whisper styling");
  assert.ok(/only jacker/i.test(modal.querySelector(".pm-hint").textContent), "whisper explains privacy");
  const tab = modal.querySelector('[data-act="pm-channel"][data-channel="whisper"]');
  assert.equal(tab.getAttribute("aria-selected"), "true");
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

test("the whisper modal thread shows the private 1:1 beats (and only them)", () => {
  const el = parse(
    renderApp(
      scenePlay({ beats: PRIV_BEATS, privateChat: { charId: "c1", name: "Jacker", channel: "whisper", mode: "say", stack: [] } }),
    ),
  );
  const thread = el.querySelector("#pmThread");
  assert.ok(/Secret aside/.test(thread.textContent), "private beat shown in the modal thread");
  assert.equal(/Public line/.test(thread.textContent), false, "public beats stay out of the whisper thread");
  // and the public story behind the modal still hides the secret
  assert.equal(/Secret aside/.test(el.querySelector("#storyStream").textContent), false);
});

// ---- the new contract fields in the deck ----

const METER_STATE = mapGameState({
  game_id: "g3",
  title: "Meter",
  context: { used: 117000, max: 131072 }, // ~89% -> red
  time: { minutes: 95, day: 2, hour: 21, part: "night", label: "Day 2, night" },
  images_enabled: true,
  scene: { id: "s1", name: "Vault", description: "", status: "calm", image_url: null, exits: [], items: [], available_actions: [] },
  player: { life: 9, max_life: 20, points: 4, location: "Vault", inventory: [] },
  characters: [],
});

test("context meter renders with the right tone color and the Xk/Yk reading; time label shows", () => {
  const el = parse(renderApp({ view: "play", active: { id: "g3", state: METER_STATE, beats: [], generating: false } }));
  const meter = el.querySelector(".deck-vitals .ctx-meter");
  assert.ok(meter, "context meter present");
  assert.ok(meter.classList.contains("tone-red"), "89% usage renders red");
  assert.equal(meter.getAttribute("aria-valuenow"), "89");
  assert.ok(/114k\/128k/.test(meter.textContent), "permanent Xk/Yk reading");
  assert.ok(/Day 2, night/.test(el.querySelector(".time-chip").textContent), "story clock label in the deck");
});

test("context meter is ALWAYS visible: used=0 before the first turn still renders (green)", () => {
  const zero = mapGameState({
    game_id: "g0",
    context: { used: 0, max: 131072 },
    scene: { id: "s1", name: "Vault", description: "", status: "calm", exits: [], items: [], available_actions: [] },
    player: { life: 9, max_life: 20, points: 0, location: "Vault", inventory: [] },
    characters: [],
  });
  const meter = parse(renderApp({ view: "play", active: { id: "g0", state: zero, beats: [], generating: false } }))
    .querySelector(".deck-vitals .ctx-meter");
  assert.ok(meter, "meter present at used=0");
  assert.ok(meter.classList.contains("tone-green"));
  assert.ok(/0\/128k/.test(meter.textContent));
});

test("no context data -> no meter; no time -> no clock (older backend tolerated)", () => {
  const el = parse(renderApp(playState())); // STATE has neither
  assert.equal(el.querySelector(".ctx-meter"), null);
  assert.equal(el.querySelector(".time-chip"), null);
});

test("each character carries their OWN small context meter (their agent's memory)", () => {
  const withCtx = mapGameState({
    game_id: "g7",
    context: { used: 1000, max: 131072 },
    scene: { id: "s1", name: "Vault", description: "", status: "calm", exits: [], items: [], available_actions: [] },
    player: { life: 9, max_life: 20, points: 0, location: "Vault", inventory: [] },
    characters: [
      { id: "c1", name: "Edda", present: true, location: "Vault", alive: true, disposition: "neutral",
        context: { used: 4200, max: 131072 }, available_actions: [] },
    ],
  });
  const el = parse(renderApp({ view: "play", active: { id: "g7", state: withCtx, beats: [], generating: false } }));
  const mini = el.querySelector('.char-col[data-char-id="c1"] .ctx-meter.mini');
  assert.ok(mini, "mini meter on the character column");
  assert.ok(/4k\/128k/.test(mini.textContent));
  assert.ok(/Edda/.test(mini.getAttribute("aria-label")), "labeled by character name");
});

test("an image beat renders as an inline picture in the story flow (no bubble)", () => {
  const beats = mapBeats([
    { id: "n1", turn_index: 1, seq: 0, speaker: "narrator", kind: "narration", text: "The bar hums." },
    { id: "v1", turn_index: 2, seq: 0, speaker: "narrator", kind: "image", text: "", image_url: "/media/g/view.png" },
  ]);
  const story = parse(renderApp(playState({ beats }))).querySelector("#storyStream");
  const fig = story.querySelector('.beat-image[data-beat-id="v1"]');
  assert.ok(fig, "image beat figure present");
  assert.equal(fig.querySelector("img").getAttribute("src"), "/media/g/view.png");
  assert.equal(fig.querySelector(".bubble"), null, "no bubble around an image beat");
});

test("the See button shows only when images are enabled, and locks while seeing", () => {
  // images off (playState STATE): no button at all
  assert.equal(parse(renderApp(playState())).querySelector(".see-btn"), null);
  // images on: present and live
  const on = parse(renderApp({ view: "play", active: { id: "g3", state: METER_STATE, beats: [], generating: false } }));
  const btn = on.querySelector(".see-btn");
  assert.ok(btn, "See button in the scene wing");
  assert.equal(btn.hasAttribute("disabled"), false);
  // in flight: disabled with a loader
  const busy = parse(renderApp({ view: "play", active: { id: "g3", state: METER_STATE, beats: [], generating: false, seeing: true } }));
  const seeing = busy.querySelector(".see-btn");
  assert.ok(seeing.classList.contains("seeing"));
  assert.equal(seeing.hasAttribute("disabled"), true);
});

// ---- art loaders / placeholders / the in-prose scene card ----

test("images on + scene art not ready -> a developing-card loader inside the story", () => {
  const el = parse(renderApp({ view: "play", active: { id: "g3", state: METER_STATE, beats: BEATS, generating: false } }));
  const art = el.querySelector("#storyStream .prose-art");
  assert.ok(art, "scene art card lives in the story stream");
  assert.ok(art.classList.contains("art-loading"), "renders as a loader while generating");
});

test("scene art present -> the image card floats inside the latest narration", () => {
  const withArt = mapGameState({
    game_id: "g4",
    images_enabled: true,
    scene: { id: "s1", name: "Vault", description: "", status: "calm", image_url: "/media/g4/scene.png", exits: [], items: [], available_actions: [] },
    player: { life: 9, max_life: 20, points: 4, location: "Vault", inventory: [] },
    characters: [],
  });
  const el = parse(renderApp({ view: "play", active: { id: "g4", state: withArt, beats: BEATS, generating: false } }));
  const img = el.querySelector(".narration .prose-art img");
  assert.ok(img, "art card embedded in narration prose");
  assert.equal(img.getAttribute("src"), "/media/g4/scene.png");
  assert.equal(img.dataset.art, "/media/g4/scene.png", "tracked for the one-shot card reveal");
});

test("images OFF -> no loader anywhere; character column falls back to color + initial", () => {
  const off = mapGameState({
    game_id: "g5",
    images_enabled: false,
    scene: { id: "s1", name: "Vault", description: "", status: "calm", image_url: null, exits: [], items: [], available_actions: [] },
    player: { life: 9, max_life: 20, points: 4, location: "Vault", inventory: [] },
    characters: [{ id: "c1", name: "Edda", present: true, location: "Vault", alive: true, disposition: "neutral", available_actions: [] }],
  });
  const el = parse(renderApp({ view: "play", active: { id: "g5", state: off, beats: BEATS, generating: false } }));
  assert.equal(el.querySelector(".art-loading"), null, "no loaders when images are off");
  const body = el.querySelector('.char-col[data-char-id="c1"] .col-body');
  assert.ok(body.classList.contains("art-off"), "static placeholder");
  assert.ok(/E/.test(body.textContent), "initial shown");
});

test("images ON + body art missing -> the column shows a loader, not a dead box", () => {
  const loading = mapGameState({
    game_id: "g6",
    images_enabled: true,
    scene: { id: "s1", name: "Vault", description: "", status: "calm", image_url: "/media/x.png", exits: [], items: [], available_actions: [] },
    player: { life: 9, max_life: 20, points: 4, location: "Vault", inventory: [] },
    characters: [{ id: "c1", name: "Edda", present: true, location: "Vault", alive: true, disposition: "neutral", available_actions: [] }],
  });
  const el = parse(renderApp({ view: "play", active: { id: "g6", state: loading, beats: [], generating: false } }));
  const body = el.querySelector('.char-col[data-char-id="c1"] .col-body');
  assert.ok(body.classList.contains("art-loading"), "loader while the body render generates");
});

test("an adjudication rejection renders as a veto-toned system badge", () => {
  const beats = mapBeats([{ id: "v1", turn_index: 1, seq: 0, speaker: "system", kind: "system", text: "You don't have the coin." }]);
  const el = parse(renderApp(playState({ beats })));
  const badge = el.querySelector(".system-badge");
  assert.ok(badge.classList.contains("veto"), "rejection tone");
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
