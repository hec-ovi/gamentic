import { test, beforeAll as before } from "vitest";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { renderApp } from "../src/render.js";
import { mapGameState, mapBeats, mapProfile } from "../src/adapters.js";

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

test("while generating, the lock is PARTIAL: composer locked, read-only surfaces stay live", () => {
  const el = parse(renderApp(playState({ generating: true })));
  const input = el.querySelector('[data-form="action"] #cmpInput');
  const btn = el.querySelector('[data-form="action"] button[type="submit"]');
  assert.equal(input.getAttribute("contenteditable"), "false");
  assert.equal(btn.hasAttribute("disabled"), true);
  assert.equal(el.querySelector(".continue-btn").hasAttribute("disabled"), true, "Continue locks too");
  assert.ok(el.querySelector(".narrating"), "thinking indicator shown");
  // the full-screen veil is GONE: reading stays interactive
  assert.equal(el.querySelector(".busy-veil"), null, "no interaction veil over the stage");
  // read-only surfaces render ENABLED mid-turn
  const profileBtn = el.querySelector('[data-act="open-profile"]');
  assert.equal(profileBtn.hasAttribute("disabled"), false, "character profile opens mid-turn");
  assert.equal(el.querySelector('[data-act="open-settings"]').hasAttribute("disabled"), false, "settings stay reachable");
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

test("character column: tapping the card opens the PROFILE; Talk is gone as an affordance", () => {
  const el = parse(renderApp(scenePlay()));
  const col = el.querySelector('.char-col[data-char-id="c1"]');
  assert.ok(col, "character column present");
  const art = col.querySelector('.col-art[data-act="open-profile"][data-char-id="c1"]');
  assert.ok(art, "the tall art card opens the full-screen profile");
  assert.equal(art.dataset.charName, "Jacker");
  assert.equal(col.querySelector('[data-act="char-action"][data-type="talk"]'), null, "no Talk button");
  assert.equal(col.querySelector('[data-act="open-private"]'), null, "no whisper button on the card either");
  assert.ok(col.querySelector('[data-act="char-action"][data-type="give"]'), "give action stays");
  assert.ok(col.querySelector('[data-act="char-action"][data-type="offer"]'), "offers stay");
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

// a loaded profile (the raw wire shape from GET /characters/{cid}/profile)
const PROFILE_DATA = {
  id: "c1",
  name: "Jacker",
  description: "Bartender.",
  disposition: "neutral",
  following: false,
  alive: true,
  life: 10,
  max_life: 10,
  face_url: null,
  body_url: "/media/g2/jacker-body.png",
  voice_id: "v1",
  color: "#8ab",
  carrying: [{ id: "k1", name: "brass key", description: "" }],
  traits: [{ id: "t1", text: "distrusts authority", unlocked: "Day 2, evening" }],
  moments: [
    { turn_index: 3, kind: "dialogue", text: "Stay sharp.", speaker: "character", private: false },
    { turn_index: 4, kind: "dialogue", text: "Keep this between us.", speaker: "character", private: true },
    { turn_index: 4, kind: "action", text: "you nod", speaker: "player", private: false },
  ],
  memories: [{ image_url: "/media/g2/bar.png", caption: "the bar at night", turn_index: 2 }],
};

function profileOpen(data, extra = {}) {
  return scenePlay({
    profile: { charId: "c1", name: "Jacker", mode: "say", stack: [], loading: false, data: data ? mapProfile(data) : null, error: "", ...extra },
  });
}

test("the full-screen profile shows traits with unlock stamps, moments (private marked) and memories", () => {
  const el = parse(renderApp(profileOpen(PROFILE_DATA)));
  const screen = el.querySelector(".profile-screen");
  assert.ok(screen, "full-screen profile present");
  assert.equal(screen.getAttribute("role"), "dialog");
  // traits as bullets with their unlock stamp
  const trait = screen.querySelector(".trait");
  assert.ok(/distrusts authority/.test(trait.textContent));
  assert.ok(/unlocked: Day 2, evening/.test(trait.querySelector(".trait-stamp").textContent));
  // moments: shared lines, private ones marked
  const moments = [...screen.querySelectorAll(".moment")];
  assert.equal(moments.length, 3);
  assert.ok(moments[1].classList.contains("private"), "the private exchange is marked");
  assert.ok(/private/.test(moments[1].querySelector(".moment-private").textContent));
  // memories: the image strip
  const memory = screen.querySelector(".memory img");
  assert.equal(memory.getAttribute("src"), "/media/g2/bar.png");
  // the big art
  assert.equal(screen.querySelector(".profile-art").getAttribute("src"), "/media/g2/jacker-body.png");
  // carrying block: label row above the items row
  const inv = screen.querySelector(".char-inv");
  assert.ok(inv.children[0].classList.contains("inv-mini-label"));
});

test("the profile hosts THE whisper composer (say/do, no look); the main composer keeps rendering behind", () => {
  const el = parse(renderApp(profileOpen(PROFILE_DATA)));
  const screen = el.querySelector(".profile-screen");
  const whisper = screen.querySelector(".whisper-sec");
  assert.ok(whisper, "whisper channel lives in the profile");
  assert.ok(/only jacker/i.test(whisper.querySelector(".pm-hint").textContent), "explains privacy");
  assert.ok(whisper.querySelector("#pmInput"), "own composer");
  assert.ok(whisper.querySelector('[data-act="pm-mode"][data-mode="do"]'), "say/do modes");
  assert.equal(whisper.querySelector('[data-act="pm-mode"][data-mode="look"]'), null, "no look in the private channel");
});

test("a fresh character's profile shows the grow-from-interactions empty-state copy", () => {
  const fresh = { ...PROFILE_DATA, traits: [], moments: [], memories: [] };
  const el = parse(renderApp(profileOpen(fresh)));
  assert.ok(
    /The more you interact with your characters, the more their traits and personality will grow from your interactions\./.test(
      el.querySelector(".profile-screen").textContent,
    ),
  );
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

test("the profile's whisper thread shows the private 1:1 beats (and only them); player lines mirror", () => {
  const withEcho = [
    ...PRIV_BEATS,
    ...mapBeats([{ id: "p3", turn_index: 2, seq: 0, speaker: "player", kind: "action", text: 'you whisper to Jacker: "psst"', private_with: "c1" }]),
  ];
  const st = profileOpen(PROFILE_DATA);
  st.active.beats = withEcho;
  const el = parse(renderApp(st));
  const thread = el.querySelector("#pmThread");
  assert.ok(/Secret aside/.test(thread.textContent), "private beat shown in the profile thread");
  assert.equal(/Public line/.test(thread.textContent), false, "public beats stay out of the whisper thread");
  assert.ok(thread.querySelector('.pm-line.pm-you[data-beat-id="p3"]'), "the player's whisper echo mirrors as pm-you");
  // and the public story behind the profile still hides the secret
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
  assert.ok(/114k \/ 128k/.test(meter.textContent), "integers above 10k, spaced separator");
  assert.ok(/Day 2, night/.test(el.querySelector(".time-chip").textContent), "story clock label in the deck");
});

test("context meter formats one decimal below 10k: 4300 tokens reads 4.2k / 128k", () => {
  const st = mapGameState({
    game_id: "gk",
    context: { used: 4300, max: 131072 },
    scene: { id: "s1", name: "Vault", description: "", status: "calm", exits: [], items: [], available_actions: [] },
    player: { life: 9, max_life: 20, points: 0, location: "Vault", inventory: [] },
    characters: [],
  });
  const meter = parse(renderApp({ view: "play", active: { id: "gk", state: st, beats: [], generating: false } }))
    .querySelector(".deck-vitals .ctx-meter");
  assert.ok(/4\.2k \/ 128k/.test(meter.textContent), "one decimal below 10k");
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
  assert.ok(/0 \/ 128k/.test(meter.textContent));
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
  assert.ok(/4\.1k \/ 128k/.test(mini.textContent));
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

test("the composer offers Look at the same level as Do and Say; the old See eye is gone", () => {
  const el = parse(renderApp(playState()));
  const look = el.querySelector('[data-act="cmp-mode"][data-mode="look"]');
  assert.ok(look, "Look mode button next to Do/Say");
  assert.equal(el.querySelector(".see-btn"), null, "the synchronous See eye-flow is removed");
  // look mode shows its own placeholder on the line
  const looking = parse(renderApp(playState({ composer: { mode: "look", stack: [] } })));
  assert.ok(/look at what\?/i.test(looking.querySelector("#cmpInput").dataset.placeholder));
});

test("Continue and the wish line sit at the composer level", () => {
  const el = parse(renderApp(playState({ wish: "let it rain" })));
  const cont = el.querySelector('.continue-btn[data-act="continue-story"]');
  assert.ok(cont, "Continue affordance present");
  const wish = el.querySelector("#wishInput");
  assert.ok(wish, "wish input present");
  assert.equal(wish.getAttribute("value"), "let it rain", "the typed wish survives re-renders");
  assert.ok(/wish to happen next/i.test(wish.getAttribute("placeholder")));
});

test("a system image beat renders as a SMALL item card labeled with the item name", () => {
  const beats = mapBeats([
    { id: "n1", turn_index: 1, seq: 0, speaker: "narrator", kind: "narration", text: "The bar hums." },
    { id: "ic1", turn_index: 2, seq: 0, speaker: "system", kind: "image", text: "brass key", image_url: "/media/g/item-key.png" },
  ]);
  const story = parse(renderApp(playState({ beats }))).querySelector("#storyStream");
  const card = story.querySelector('.beat-image.item-card[data-beat-id="ic1"]');
  assert.ok(card, "small item card, not the hero treatment");
  assert.ok(/brass key/.test(card.querySelector("figcaption").textContent), "item name as the label");
  // narrator image beats keep the hero treatment (no item-card class)
  const heroBeats = mapBeats([{ id: "v1", turn_index: 3, seq: 0, speaker: "narrator", kind: "image", text: "the hatch", image_url: "/media/g/v.png" }]);
  const hero = parse(renderApp(playState({ beats: heroBeats }))).querySelector(".beat-image");
  assert.equal(hero.classList.contains("item-card"), false);
});

test("a trait receipt renders with the celebration tone and stays tappable", () => {
  const beats = mapBeats([
    { id: "t1", turn_index: 1, seq: 0, speaker: "system", kind: "system", text: "Trait unlocked: Mara - distrusts authority." },
  ]);
  const badge = parse(renderApp(playState({ beats }))).querySelector(".system-badge");
  assert.ok(badge.classList.contains("trait"), "trait celebration tone");
  assert.equal(badge.dataset.act, "inspect-beat", "tappable via the inspect modal");
});

test("item thumbnails: an inventory item with image_url shows the image in its slot", () => {
  const st = mapGameState({
    game_id: "gt",
    scene: { id: "s1", name: "Vault", description: "", status: "calm", exits: [], items: [], available_actions: [] },
    player: { life: 9, max_life: 20, points: 0, location: "Vault", inventory: [{ id: "i1", name: "brass key", image_url: "/media/gt/key.png" }] },
    characters: [],
  });
  const slot = parse(renderApp({ view: "play", active: { id: "gt", state: st, beats: [], generating: false } }))
    .querySelector(".player-items .slot.filled");
  assert.equal(slot.querySelector("img").getAttribute("src"), "/media/gt/key.png");
});

test("settings: autoplay is split and a live game adds difficulty/voice/export", () => {
  const noGame = parse(renderApp({ view: "settings", settings: { voiceEnabled: true, autoplayNarrator: true, autoplayCharacters: false, masterVolume: 0.7 }, active: null }));
  assert.ok(noGame.querySelector('[data-setting="autoplayNarrator"]'), "narrator autoplay toggle");
  assert.ok(noGame.querySelector('[data-setting="autoplayCharacters"]'), "character autoplay toggle");
  assert.equal(noGame.querySelector('[data-setting="autoplayVoice"]'), null, "the old single toggle is gone");
  assert.equal(noGame.querySelector(".game-settings"), null, "no game section outside a game");

  const inGame = parse(renderApp({
    view: "settings",
    settings: { voiceEnabled: true, autoplayNarrator: false, autoplayCharacters: false, masterVolume: 0.7 },
    active: { id: "g2", state: SCENE_STATE, beats: [], generating: false },
  }));
  const game = inGame.querySelector(".game-settings");
  assert.ok(game, "per-adventure section when opened from play");
  const normal = game.querySelector('[data-game-setting="difficulty"][value="normal"]');
  assert.ok(normal.hasAttribute("checked"), "current difficulty checked");
  assert.ok(/attempts succeed/.test(game.textContent), "easy copy explains the mode");
  assert.ok(/attempts can be refused/.test(game.textContent), "hard copy explains the mode");
  assert.ok(game.querySelector('[data-game-setting="narrator_gender"][value="female"]'), "narrator voice radios");
  assert.ok(game.querySelector('[data-act="export-game"][data-kind="template"]'), "share as adventure");
  assert.ok(game.querySelector('[data-act="export-game"][data-kind="checkpoint"]'), "save this moment");
});

test("the library offers Import next to the archive", () => {
  const el = parse(renderApp({ view: "library", games: [], backendOnline: true, backendError: "" }));
  assert.ok(el.querySelector('[data-act="import-game"]'), "Import button");
  assert.ok(el.querySelector("#importFile"), "hidden file input");
});

// ---- art loaders / placeholders / the in-prose scene card ----

test("images on + scene art not ready -> a developing-card loader inside the story", () => {
  const el = parse(renderApp({ view: "play", active: { id: "g3", state: METER_STATE, beats: BEATS, generating: false } }));
  const art = el.querySelector("#storyStream .prose-art");
  assert.ok(art, "scene art card lives in the story stream");
  assert.ok(art.classList.contains("art-loading"), "renders as a loader while generating");
});

test("anchoring: the scene card pins to the FIRST narration of the current visit, not the latest", () => {
  const st = mapGameState({
    game_id: "g8",
    images_enabled: true,
    scene: { id: "s2", name: "Vault", description: "", status: "calm", image_url: "/media/g8/vault.png", exits: [], items: [], available_actions: [] },
    player: { life: 9, max_life: 20, points: 0, location: "Vault", inventory: [] },
    characters: [],
  });
  const beats = mapBeats([
    { id: "a1", turn_index: 1, seq: 0, kind: "narration", speaker: "narrator", text: "The bar hums.", location: "The Bar" },
    { id: "b1", turn_index: 2, seq: 0, kind: "narration", speaker: "narrator", text: "You enter the vault.", location: "Vault" },
    { id: "b2", turn_index: 3, seq: 0, kind: "narration", speaker: "narrator", text: "Dust settles.", location: "Vault" },
    { id: "b3", turn_index: 4, seq: 0, kind: "narration", speaker: "narrator", text: "A coin glints.", location: "Vault" },
  ]);
  const story = parse(renderApp({ view: "play", active: { id: "g8", state: st, beats, generating: false } })).querySelector("#storyStream");
  const holder = story.querySelector(".prose-art").closest(".narration");
  assert.equal(holder.dataset.beatId, "b1", "art lives in the visit's establishing narration");
  // and the previous scene's narration does NOT get it
  assert.equal(story.querySelector('[data-beat-id="a1"] .prose-art'), null);
});

test("anchoring fallback: a visit with no narration shows the card standalone at its top", () => {
  const st = mapGameState({
    game_id: "g9",
    images_enabled: true,
    scene: { id: "s2", name: "Vault", description: "", status: "calm", image_url: "/media/g9/vault.png", exits: [], items: [], available_actions: [] },
    player: { life: 9, max_life: 20, points: 0, location: "Vault", inventory: [] },
    characters: [],
  });
  const beats = mapBeats([
    { id: "a1", turn_index: 1, seq: 0, kind: "narration", speaker: "narrator", text: "The bar hums.", location: "The Bar" },
    { id: "b1", turn_index: 2, seq: 0, kind: "dialogue", speaker: "c9", speaker_name: "Edda", text: "In here.", location: "Vault" },
  ]);
  const story = parse(renderApp({ view: "play", active: { id: "g9", state: st, beats, generating: false } })).querySelector("#storyStream");
  const art = story.querySelector(".prose-art");
  assert.ok(art, "card present");
  assert.equal(art.closest(".narration"), null, "standalone, not inside the other scene's narration");
  // it sits before the visit's first beat
  assert.equal(art.nextElementSibling.dataset.beatId, "b1");
});

test("player speech echoes render as MIRRORED dialogue bubbles; deeds stay quiet markers", () => {
  const beats = mapBeats([
    { id: "e1", turn_index: 1, seq: 0, kind: "action", speaker: "player", text: 'you say "hello there" to Jacker' },
    { id: "e2", turn_index: 1, seq: 1, kind: "action", speaker: "player", text: 'you whisper to Jacker: "psst, the key"' },
    { id: "e3", turn_index: 1, seq: 2, kind: "action", speaker: "player", text: "you kick the door open" },
  ]);
  const el = parse(renderApp(playState({ beats })));
  const say = el.querySelector('[data-beat-id="e1"]');
  assert.ok(say.classList.contains("from-player"), "say echo is a player bubble");
  assert.equal(say.querySelector(".bubble p").textContent, "hello there", "the quote is the bubble body");
  assert.ok(/You/.test(say.querySelector(".bubble-name").textContent));
  assert.ok(/to Jacker/.test(say.querySelector(".bubble-meta").textContent));
  const whisper = el.querySelector('[data-beat-id="e2"]');
  assert.ok(whisper.classList.contains("whispered"), "whisper echo styled as a whisper");
  assert.equal(whisper.querySelector(".bubble p").textContent, "psst, the key");
  const deed = el.querySelector('[data-beat-id="e3"]');
  assert.ok(deed.classList.contains("player-action"), "a deed stays the quiet inline marker");
  assert.equal(deed.querySelector(".bubble"), null);
});

test("character card carrying block stacks label ABOVE the items (rows, not columns)", () => {
  const col = parse(renderApp(scenePlay())).querySelector('.char-col[data-char-id="c1"]');
  const inv = col.querySelector(".char-inv");
  assert.ok(inv, "carrying block present");
  assert.equal(col.querySelector(".char-inv-row"), null, "old 2-column row layout is gone");
  const kids = [...inv.children];
  assert.ok(kids[0].classList.contains("inv-mini-label"), "label is the first row");
  assert.ok(kids[1].classList.contains("slot-grid"), "items grid is the row below");
});

test("scene art present -> the image card floats inside the establishing narration", () => {
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
