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

test("character column is a pure holder: art, carrying, an expand hint - no description, no buttons", () => {
  const el = parse(renderApp(scenePlay()));
  const col = el.querySelector('.char-col[data-char-id="c1"]');
  assert.ok(col, "character column present");
  const art = col.querySelector('.col-art[data-act="open-profile"][data-char-id="c1"]');
  assert.ok(art, "the tall art card opens the full-screen profile");
  assert.equal(art.dataset.charName, "Jacker");
  // the card is LIGHT: no description, no action buttons, no Talk/whisper
  assert.equal(col.querySelector(".char-desc"), null, "description is not on the card");
  assert.equal(/Bartender/.test(col.textContent), false, "no description text anywhere on the card");
  assert.equal(col.querySelector('[data-act="char-action"]'), null, "no action buttons on the card");
  assert.equal(col.querySelector('[data-act="open-private"]'), null, "no whisper button on the card either");
  // carrying stays, and the card hints at the panel
  assert.ok(col.querySelector(".char-inv .inv-mini-label"), "carrying row stays");
  assert.ok(/expand to interact/i.test(col.querySelector(".char-hint").textContent), "the interaction hint label");
});

test("the profile's status sheet hosts the Actions (give, provoke...; talk filtered)", () => {
  const el = parse(renderApp(profileOpen(PROFILE_DATA)));
  const pane = el.querySelector(".profile-pane");
  const actions = pane.querySelector(".profile-actions");
  assert.ok(actions, "Actions section on the status sheet");
  assert.ok(actions.querySelector('[data-act="char-action"][data-type="give"]'), "give action");
  assert.ok(actions.querySelector('[data-act="char-action"][data-type="offer"]'), "offers");
  assert.equal(actions.querySelector('[data-act="char-action"][data-type="talk"]'), null, "talk filtered out");
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
  gender: "male",
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
  origin: [{ id: "or1", text: "He ran corp security before the fall.", learned: "Day 2, night" }],
  relation: "old friend",
  moments: [
    { id: "m1", text: "Turned friendly toward the player.", when: "Day 1, evening" },
    { id: "m2", text: "Was wounded at the player's side.", when: "Day 2, night" },
  ],
  memories: [{ image_url: "/media/g2/bar.png", caption: "Jacker behind the bar at night, the neon flickering over a quiet talk.", turn_index: 2 }],
};

function profileOpen(data, extra = {}) {
  return scenePlay({
    profile: { charId: "c1", name: "Jacker", tab: "profile", mode: "say", stack: [], loading: false, data: data ? mapProfile(data) : null, error: "", ...extra },
  });
}

test("the profile is TABBED: Profile/Traits/Memory/Whisper, with the status sheet as the default", () => {
  const el = parse(renderApp(profileOpen(PROFILE_DATA)));
  const screen = el.querySelector(".profile-screen");
  assert.ok(screen, "full-screen profile present");
  assert.equal(screen.getAttribute("role"), "dialog");
  // the four tabs
  const tabs = [...screen.querySelectorAll('[data-act="profile-tab"]')].map((t) => t.dataset.tab);
  assert.deepEqual(tabs, ["profile", "traits", "memory", "whisper"]);
  assert.equal(screen.querySelector(".profile-tab.active").dataset.tab, "profile");
  // the default Profile tab is the status sheet: identity, gender, description, carrying
  assert.ok(screen.querySelector(".disp-badge"), "disposition on the status sheet");
  assert.ok([...screen.querySelectorAll(".ins-tag")].some((t) => t.textContent === "male"), "gender tag shown when set");
  assert.ok(/Bartender/.test(screen.querySelector(".profile-pane").textContent), "description on the status sheet");
  // "Their past": the origin pieces learned so far, stamped like traits
  const origin = screen.querySelector(".origin-list .trait.origin");
  assert.ok(origin, "origin entry on the status sheet");
  assert.ok(/ran corp security/.test(origin.textContent));
  assert.ok(/learned: Day 2, night/.test(origin.querySelector(".trait-stamp").textContent));
  const inv = screen.querySelector(".char-inv");
  assert.ok(inv, "carrying lives on the status sheet");
  assert.ok(inv.children[0].classList.contains("inv-mini-label"), "label row above the items row");
  // the big art + name stay outside the tabs
  assert.equal(screen.querySelector(".profile-art").getAttribute("src"), "/media/g2/jacker-body.png");
  assert.ok(/Jacker/.test(screen.querySelector(".profile-name").textContent));
  // other panes are NOT rendered while their tab is inactive (origin entries
  // live on the status sheet and share the trait card styling)
  assert.equal(screen.querySelector(".trait:not(.origin)"), null);
  assert.equal(screen.querySelector(".whisper-sec"), null);
});

test("the Traits tab lists the unlocked traits with their stamps", () => {
  const el = parse(renderApp(profileOpen(PROFILE_DATA, { tab: "traits" })));
  const trait = el.querySelector(".profile-pane .trait");
  assert.ok(/distrusts authority/.test(trait.textContent));
  assert.ok(/unlocked: Day 2, evening/.test(trait.querySelector(".trait-stamp").textContent));
});

test("the Memories tab: image strip with FULL concept captions + the pivotal-event timeline", () => {
  const el = parse(renderApp(profileOpen(PROFILE_DATA, { tab: "memory" })));
  const pane = el.querySelector(".profile-pane");
  // moments are a curated event TIMELINE with when-stamps, never chat bubbles
  const events = [...pane.querySelectorAll(".moment-timeline .moment-event")];
  assert.equal(events.length, 2);
  assert.ok(/Turned friendly toward the player\./.test(events[0].textContent));
  assert.equal(events[0].querySelector(".moment-when").textContent, "Day 1, evening");
  assert.equal(pane.querySelector(".moment.from-you, .moment.from-them"), null, "no chat-style moments");
  // memories carry the full 1-3 sentence concept caption
  assert.equal(pane.querySelector(".memory img").getAttribute("src"), "/media/g2/bar.png");
  assert.ok(/neon flickering over a quiet talk/.test(pane.querySelector(".memory figcaption").textContent), "full caption under the image");
});

test("the relation badge shows what they ARE to the player, on the card and in the profile", () => {
  const withRelation = mapGameState({
    game_id: "gr",
    scene: { id: "s1", name: "Vault", description: "", status: "calm", exits: [], items: [], available_actions: [] },
    player: { life: 9, max_life: 20, points: 0, location: "Vault", inventory: [] },
    characters: [{ id: "c1", name: "Edda", present: true, location: "Vault", alive: true, disposition: "friendly", relation: "old friend", available_actions: [] }],
  });
  const col = parse(renderApp({ view: "play", active: { id: "gr", state: withRelation, beats: [], generating: false } }))
    .querySelector('.char-col[data-char-id="c1"]');
  const badge = col.querySelector(".relation-badge");
  assert.ok(badge, "relation badge on the card");
  assert.equal(badge.textContent, "old friend");
  // and in the profile header tags (next to the disposition badge)
  const prof = parse(renderApp(profileOpen(PROFILE_DATA)));
  assert.equal(prof.querySelector(".profile-pane .relation-badge").textContent, "old friend");
  // '' until defined -> no badge
  const bare = parse(renderApp(scenePlay()));
  assert.equal(bare.querySelector('.char-col[data-char-id="c1"] .relation-badge'), null);
});

test("the scene inspect sheet shows the place's deeper story when the narrator has written it", () => {
  const withBg = mapGameState({
    game_id: "gb",
    scene: { id: "s1", name: "Vault", description: "A sealed vault.", background: "Built as a seed bank, looted in the first winter.", status: "calm", exits: [], items: [], available_actions: [] },
    player: { life: 9, max_life: 20, points: 0, location: "Vault", inventory: [] },
    characters: [],
  });
  const el = parse(renderApp({ view: "play", active: { id: "gb", state: withBg, beats: [], generating: false, inspect: { kind: "scene", key: "Vault" } } }));
  const modal = el.querySelector(".inspect-modal");
  assert.ok(/What this place is/.test(modal.textContent), "background section title");
  assert.ok(/seed bank, looted in the first winter/.test(modal.querySelector(".scene-background").textContent));
  // empty background -> the section is omitted
  const noBg = mapGameState({
    game_id: "gb2",
    scene: { id: "s1", name: "Vault", description: "A sealed vault.", status: "calm", exits: [], items: [], available_actions: [] },
    player: { life: 9, max_life: 20, points: 0, location: "Vault", inventory: [] },
    characters: [],
  });
  const el2 = parse(renderApp({ view: "play", active: { id: "gb2", state: noBg, beats: [], generating: false, inspect: { kind: "scene", key: "Vault" } } }));
  assert.equal(/What this place is/.test(el2.querySelector(".inspect-modal").textContent), false);
  // the deck's scene name is the way in
  assert.ok(el2.querySelector('.scene-name [data-act="inspect-scene"]'), "scene name opens the sheet");
});

test("settings: the Story memory panel renders the three controls with current values", () => {
  const st = mapGameState({
    game_id: "gm",
    settings: { narrator_gender: "", difficulty: "normal", history_beats: 80, summary_every: 10, context_tokens: 0 },
    context: { used: 4300, max: 131072 },
    scene: { id: "s1", name: "Vault", description: "", status: "calm", exits: [], items: [], available_actions: [] },
    player: { life: 9, max_life: 20, points: 0, location: "Vault", inventory: [] },
    characters: [],
  });
  const el = parse(renderApp({
    view: "settings",
    settings: { voiceEnabled: true, autoplayNarrator: false, autoplayCharacters: false, masterVolume: 0.7 },
    active: { id: "gm", state: st, beats: [], generating: false },
  }));
  const panel = el.querySelector(".memory-settings");
  assert.ok(panel, "Story memory panel");
  assert.ok(/compresses everything older into a recap/.test(panel.textContent), "the mental model in the copy");
  assert.equal(panel.querySelector('[data-mem-setting="history_beats"]').getAttribute("value"), "80");
  assert.equal(panel.querySelector('[data-mem-setting="summary_every"]').getAttribute("value"), "10");
  assert.equal(panel.querySelector('[data-mem-setting="context_tokens"]').getAttribute("value"), "0");
  assert.ok(panel.querySelector(".ctx-meter"), "the live context meter sits beside the budget control");
});

test("the Whisper tab hosts THE whisper composer (say/do/look)", () => {
  const el = parse(renderApp(profileOpen(PROFILE_DATA, { tab: "whisper" })));
  const whisper = el.querySelector(".profile-pane .whisper-sec");
  assert.ok(whisper, "whisper channel lives in the profile's whisper tab");
  assert.ok(/only jacker/i.test(whisper.querySelector(".pm-hint").textContent), "explains privacy");
  assert.ok(whisper.querySelector("#pmInput"), "own composer");
  assert.ok(whisper.querySelector('[data-act="pm-mode"][data-mode="do"]'), "say/do modes");
  assert.ok(whisper.querySelector('[data-act="pm-mode"][data-mode="look"]'), "look joins the panel composer");
});

test("the whisper thread renders look results: prose/images launched from this panel mirror in", () => {
  const beats = mapBeats([
    { id: "lkp", turn_index: 5, seq: 0, speaker: "narrator", kind: "narration", text: "Her scar catches the light." },
    { id: "lki", turn_index: 6, seq: 0, speaker: "narrator", kind: "image", text: "A thin scar over Jacker's brow, old and clean.", image_url: "/media/g2/scar.png" },
    { id: "pub", turn_index: 4, seq: 0, speaker: "narrator", kind: "narration", text: "Elsewhere, rain falls." },
  ]).map((b) => (b.id === "pub" ? b : { ...b, viaProfile: "c1" }));
  const st = profileOpen(PROFILE_DATA, { tab: "whisper" });
  st.active.beats = beats;
  const el = parse(renderApp(st));
  const thread = el.querySelector("#pmThread");
  assert.ok(/Her scar catches the light/.test(thread.textContent), "panel-launched prose mirrors in");
  const img = thread.querySelector('.pm-image[data-beat-id="lki"] img');
  assert.equal(img.getAttribute("src"), "/media/g2/scar.png", "the look image renders in the thread");
  assert.ok(/old and clean/.test(thread.querySelector(".pm-image figcaption").textContent), "with its full concept caption");
  assert.equal(/Elsewhere, rain falls/.test(thread.textContent), false, "unrelated public beats stay out");
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

test("the profile's whisper thread shows the private 1:1 beats (and only them); player lines mirror, quote-free", () => {
  const withEcho = [
    ...PRIV_BEATS,
    ...mapBeats([{ id: "p3", turn_index: 2, seq: 0, speaker: "player", kind: "action", text: 'you whisper to Jacker: "psst"', private_with: "c1" }]),
  ];
  const st = profileOpen(PROFILE_DATA, { tab: "whisper" });
  st.active.beats = withEcho;
  const el = parse(renderApp(st));
  const thread = el.querySelector("#pmThread");
  assert.ok(/Secret aside/.test(thread.textContent), "private beat shown in the profile thread");
  assert.equal(/Public line/.test(thread.textContent), false, "public beats stay out of the whisper thread");
  const mine = thread.querySelector('.pm-line.pm-you[data-beat-id="p3"]');
  assert.ok(mine, "the player's whisper echo mirrors as pm-you");
  assert.equal(mine.querySelector(".pm-text").textContent, "psst", "just what was said, no quote marks, no wrapper text");
  // and the public story behind the profile still hides the secret
  assert.equal(/Secret aside/.test(el.querySelector("#storyStream").textContent), false);
});

test("literal quote marks are stripped from speech: the bubble IS the quotation", () => {
  const beats = mapBeats([
    { id: "q1", turn_index: 1, seq: 0, speaker: "c1", speaker_name: "Edda", kind: "dialogue", text: '"Stay back."' },
    { id: "q2", turn_index: 1, seq: 1, speaker: "c1", speaker_name: "Edda", kind: "dialogue", text: "“Come closer.”" },
  ]);
  const el = parse(renderApp(playState({ beats })));
  assert.equal(el.querySelector('[data-beat-id="q1"] .bubble p').textContent, "Stay back.");
  assert.equal(el.querySelector('[data-beat-id="q2"] .bubble p').textContent, "Come closer.");
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
  assert.equal(game.querySelector('[data-act="export-game"]'), null, "export lives on the library cards, not here");
});

test("the library offers Import next to the archive and Export on every card", () => {
  const el = parse(
    renderApp({
      view: "library",
      backendOnline: true,
      backendError: "",
      games: [{ id: "g1", title: "Neon Decay", status: "active", created_at: "2026-06-09" }],
    }),
  );
  assert.ok(el.querySelector('[data-act="import-game"]'), "Import button");
  assert.ok(el.querySelector("#importFile"), "hidden file input");
  const exp = el.querySelector('[data-act="ask-export"][data-game-id="g1"]');
  assert.ok(exp, "card export button next to the trash");
  assert.equal(exp.dataset.gameTitle, "Neon Decay");
});

test("the export choice modal offers the two flavors for that card", () => {
  const el = parse(
    renderApp({
      view: "library",
      backendOnline: true,
      backendError: "",
      games: [{ id: "g1", title: "Neon Decay", status: "active", created_at: "2026-06-09" }],
      exportChoice: { gameId: "g1", title: "Neon Decay" },
    }),
  );
  const modal = el.querySelector(".holo-modal");
  assert.ok(/Neon Decay/.test(modal.textContent), "names the adventure");
  assert.ok(modal.querySelector('[data-act="export-game"][data-kind="template"][data-game-id="g1"]'), "share as adventure");
  assert.ok(modal.querySelector('[data-act="export-game"][data-kind="checkpoint"][data-game-id="g1"]'), "save this moment");
  assert.ok(modal.querySelector('[data-act="cancel-export"]'), "cancel");
});

test("the whisper hint sells privacy: only the character is named, never the narrator", () => {
  const el = parse(renderApp(profileOpen(PROFILE_DATA, { tab: "whisper" })));
  const hint = el.querySelector(".whisper-sec .pm-hint");
  assert.ok(/Only Jacker will ever know this\./.test(hint.textContent));
  assert.equal(/narrator/i.test(hint.textContent), false, "no narrator mention in the private channel");
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

// ---- consulting ABSENT / dead characters (work-order item I) ----

const AWAY_STATE = mapGameState({
  game_id: "ga",
  scene: { id: "s1", name: "The Bar", description: "", status: "calm", exits: [], items: [], available_actions: [] },
  player: { life: 9, max_life: 20, points: 0, location: "The Bar", inventory: [] },
  characters: [
    { id: "c1", name: "Jacker", gender: "male", present: true, location: "the docks", alive: true, disposition: "neutral",
      available_actions: [{ id: "b1", label: "Give...", type: "give" }] },
  ],
});

function awayProfile(extra = {}) {
  return {
    view: "play",
    active: {
      id: "ga", state: AWAY_STATE, beats: [], generating: false, composer: { mode: "do", stack: [] },
      profile: { charId: "c1", name: "Jacker", tab: "profile", mode: "say", stack: [], loading: false, data: mapProfile(PROFILE_DATA), error: "", ...extra },
    },
  };
}

test("an ELSEWHERE character: profile readable, actions replaced by a status line, card in the roster opens it", () => {
  const el = parse(renderApp(awayProfile()));
  // the cast roster shows them, openable, with where they are
  const row = el.querySelector('.cast-row[data-act="open-profile"][data-char-id="c1"]');
  assert.ok(row, "the elsewhere roster row opens the profile");
  assert.ok(/at The Docks/i.test(row.textContent), "marked with where they are");
  // the profile is fully readable (description, carrying) but offers NO actions
  const pane = el.querySelector(".profile-pane");
  assert.ok(/Bartender/.test(pane.textContent), "lore stays readable");
  assert.equal(pane.querySelector('[data-act="char-action"]'), null, "no action buttons for the absent");
  assert.ok(/He is elsewhere - at The Docks\./.test(pane.querySelector(".absence-line").textContent), "the status line says where");
});

test("an elsewhere character's Whisper tab: thread readable, composer replaced by the status line", () => {
  const el = parse(renderApp(awayProfile({ tab: "whisper" })));
  const sec = el.querySelector(".whisper-sec");
  assert.ok(sec.querySelector("#pmThread"), "the thread stays readable");
  assert.equal(sec.querySelector("#pmInput"), null, "no whisper composer for the absent");
  assert.equal(sec.querySelector('[data-form="private"]'), null, "no form either");
  assert.ok(/He is elsewhere - at The Docks\./.test(sec.querySelector(".absence-line").textContent));
});

test("a DEAD character: profile readable, the status line reads gone", () => {
  const dead = mapGameState({
    game_id: "gd",
    scene: { id: "s1", name: "The Bar", description: "", status: "calm", exits: [], items: [], available_actions: [] },
    player: { life: 9, max_life: 20, points: 0, location: "The Bar", inventory: [] },
    characters: [{ id: "c1", name: "Jacker", gender: "male", present: true, location: "The Bar", alive: false, disposition: "neutral", available_actions: [] }],
  });
  const st = awayProfile({ tab: "whisper" });
  st.active.state = dead;
  st.active.profile.data = mapProfile({ ...PROFILE_DATA, alive: false });
  const el = parse(renderApp(st));
  assert.ok(/He is gone\./.test(el.querySelector(".whisper-sec .absence-line").textContent));
  assert.equal(el.querySelector("#pmInput"), null);
});

test("item thumbnails render in SCENE and CARRYING slots too (letters only while image_url is null)", () => {
  const st = mapGameState({
    game_id: "gi",
    scene: {
      id: "s1", name: "Vault", description: "", status: "calm", exits: [], available_actions: [],
      items: [
        { id: "i1", name: "brass key", image_url: "/media/gi/key.png" },
        { id: "i2", name: "old rope", image_url: null },
      ],
    },
    player: { life: 9, max_life: 20, points: 0, location: "Vault", inventory: [] },
    characters: [
      { id: "c1", name: "Edda", present: true, location: "Vault", alive: true, disposition: "neutral",
        inventory: [{ id: "k1", name: "lockpick", image_url: "/media/gi/pick.png" }], available_actions: [] },
    ],
  });
  const el = parse(renderApp({ view: "play", active: { id: "gi", state: st, beats: [], generating: false } }));
  assert.equal(el.querySelector('.scene-items .slot img').getAttribute("src"), "/media/gi/key.png", "scene slot thumbnail");
  const sceneSlots = [...el.querySelectorAll(".scene-items .slot.filled")];
  assert.ok(/OR/.test(sceneSlots[1].textContent), "letter fallback only while image_url is null");
  assert.equal(el.querySelector('.char-col .char-items .slot img').getAttribute("src"), "/media/gi/pick.png", "carrying slot thumbnail");
});

test("whispered replies carry the per-message speak button (voiced like the story)", () => {
  const voiced = mapBeats([
    { id: "w1", turn_index: 1, seq: 0, speaker: "c1", speaker_name: "Jacker", kind: "dialogue", text: "Closer.", private_with: "c1" },
  ]).map((b) => ({ ...b, voiceId: "vx-jacker" }));
  const st = profileOpen(PROFILE_DATA, { tab: "whisper" });
  st.active.beats = voiced;
  const el = parse(renderApp(st));
  const line = el.querySelector('#pmThread .pm-line.pm-them[data-beat-id="w1"]');
  const btn = line.querySelector('[data-act="speak-beat"]');
  assert.ok(btn, "speak button on the whispered reply");
  assert.equal(btn.dataset.beatId, "w1");
  // the player's own whisper echo stays silent (no voice id, no button)
  const mineBeats = mapBeats([
    { id: "w2", turn_index: 1, seq: 1, speaker: "player", kind: "action", text: 'you whisper to Jacker: "psst"', private_with: "c1" },
  ]);
  st.active.beats = mineBeats;
  const el2 = parse(renderApp(st));
  assert.equal(el2.querySelector('#pmThread [data-act="speak-beat"]'), null);
});

test("a whisper turn shows its thinking IN the thread (visible processing feedback)", () => {
  const st = profileOpen(PROFILE_DATA, { tab: "whisper" });
  st.active.generating = true;
  const el = parse(renderApp(st));
  const dots = el.querySelector("#pmThread + .pm-thinking, #pmThread .pm-thinking");
  assert.ok(dots, "thinking dots in the whisper thread while the turn resolves");
  assert.ok(/Jacker considers/.test(dots.textContent));
  // idle: no dots
  const idle = parse(renderApp(profileOpen(PROFILE_DATA, { tab: "whisper" })));
  assert.equal(idle.querySelector(".pm-thinking"), null);
});

test("character deeds in the whisper thread are plain lines (pm-deed), speech stays a bubble", () => {
  const beats = mapBeats([
    { id: "wd1", turn_index: 1, seq: 0, speaker: "c1", speaker_name: "Jacker", kind: "action", text: "She takes a step closer.", private_with: "c1" },
    { id: "ws1", turn_index: 1, seq: 1, speaker: "c1", speaker_name: "Jacker", kind: "dialogue", text: "Listen.", private_with: "c1" },
  ]);
  const st = profileOpen(PROFILE_DATA, { tab: "whisper" });
  st.active.beats = beats;
  const el = parse(renderApp(st));
  const deed = el.querySelector('[data-beat-id="wd1"]');
  assert.ok(deed.classList.contains("pm-deed"), "deed line marked");
  const speech = el.querySelector('[data-beat-id="ws1"]');
  assert.equal(speech.classList.contains("pm-deed"), false, "speech stays a bubble");
  assert.ok(speech.classList.contains("pm-them"));
});

test("settings: the turn-pacing selects render the effective values plus a Default option", () => {
  const st = mapGameState({ settings: { turn_voices: 3, turn_acts: 1 } });
  const el = parse(renderApp({
    view: "settings",
    settings: { voiceEnabled: true, autoplayNarrator: false, autoplayCharacters: false, masterVolume: 0.7 },
    active: { id: "g2", state: st, beats: [], generating: false },
  }));
  const voices = el.querySelector('select[data-game-setting="turn_voices"]');
  const acts = el.querySelector('select[data-game-setting="turn_acts"]');
  assert.ok(voices, "voices-per-turn select");
  assert.ok(acts, "acts-per-voice select");
  assert.ok(voices.querySelector('option[value="3"]').hasAttribute("selected"), "effective voices value selected");
  assert.ok(acts.querySelector('option[value="1"]').hasAttribute("selected"), "effective acts value selected");
  assert.equal(voices.querySelector('option[value="0"]').textContent, "Default", "Default option sends 0");
  assert.equal(voices.querySelectorAll("option").length, 5, "Default + 1..4");
  assert.equal(acts.querySelectorAll("option").length, 4, "Default + 1..3");
  assert.ok(/how crowded a single turn can get/i.test(el.querySelector(".game-settings").textContent), "the copy explains the dial");
});

test("origin empty state: no 'Their past' section, but the grow note still shows for a fresh character", () => {
  const fresh = { ...PROFILE_DATA, traits: [], moments: [], memories: [], origin: [] };
  const el = parse(renderApp(profileOpen(fresh)));
  const screenEl = el.querySelector(".profile-screen");
  assert.equal(/Their past/.test(screenEl.textContent), false, "no origin section when nothing is learned");
  assert.ok(/grow from your interactions/.test(screenEl.textContent), "the grow note shows");
});

test("a memory whose image is still rendering (image_url null) is skipped, never a broken img", () => {
  const data = {
    ...PROFILE_DATA,
    moments: [],
    memories: [
      { image_url: null, caption: "still rendering", turn_index: 9 },
      { image_url: "/media/g2/done.png", caption: "a finished one", turn_index: 8 },
    ],
  };
  const el = parse(renderApp(profileOpen(data, { tab: "memory" })));
  const imgs = [...el.querySelectorAll(".memory-strip img")];
  assert.equal(imgs.length, 1, "only the ready memory renders");
  assert.equal(imgs[0].getAttribute("src"), "/media/g2/done.png");
  assert.equal(/still rendering/.test(el.textContent), false, "the pending one is absent entirely");
});
