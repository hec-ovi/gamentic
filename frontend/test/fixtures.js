// Shared test fixtures: builders that produce backend-shaped GameState / Beat /
// turn payloads (the REAL wire shapes from docs/frontend-api.md), so component
// tests drive the app through realistic network responses.

export function makeState(over = {}) {
  return {
    game_id: "g-test",
    title: "Test Adventure",
    status: "active",
    scene_status: "tense",
    current_goal: "Find the brass key",
    narrator_voice_id: "af_alloy",
    settings: {
      narrator_gender: "",
      difficulty: "normal",
      history_beats: 80,
      summary_every: 10,
      context_tokens: 0,
      turn_voices: 2,
      turn_acts: 1,
      ...(over.settings || {}),
    },
    context: { used: 12000, max: 131072 },
    images_enabled: false,
    time: { minutes: 95, day: 1, hour: 9, part: "morning", label: "Day 1, morning" },
    scene: {
      id: "sc1",
      name: "The Last Breath",
      description: "A grimy cyberpunk bar, rain on the glass.",
      status: "tense",
      image_url: null,
      exits: [],
      items: [],
      available_actions: [
        { id: "s0", label: "Look around", type: "look" },
        { id: "s1", label: "Search", type: "search" },
      ],
      ...(over.scene || {}),
    },
    player: {
      life: 18,
      max_life: 20,
      points: 30,
      location: "The Last Breath",
      inventory: [{ id: "inv1", name: "credstick", description: "42 creds", qty: 1 }],
      flags: {},
      ...(over.player || {}),
    },
    quests: over.quests || [
      {
        id: "q1",
        title: "The brass key",
        description: "Get into the back room.",
        status: "active",
        objectives: [{ id: "o1", text: "Find the brass key", done: false, progress: null }],
      },
    ],
    characters:
      over.characters ||
      [
        {
          id: "c1",
          name: "Jacker",
          description: "The watchful bartender.",
          voice_id: null,
          color: null,
          context: { used: 2048, max: 131072 },
          present: true,
          location: "The Last Breath",
          life: 10,
          max_life: 10,
          alive: true,
          disposition: "neutral",
          following: false,
          face_url: null,
          body_url: null,
          inventory: [],
          available_actions: [
            { id: "b0", label: "Talk", type: "talk" },
            { id: "b1", label: "Give...", type: "give" },
            { id: "b2", label: "Provoke", type: "offer" },
          ],
        },
      ],
    ...stripScene(over),
  };
}

function stripScene(over) {
  // top-level overrides except the nested ones we already merged
  const { scene, player, quests, characters, settings, ...rest } = over;
  void settings;
  return rest;
}

export function makeBeat(over = {}) {
  return {
    id: "b" + Math.floor(Math.random() * 1e6),
    turn_index: 1,
    seq: 0,
    speaker: "narrator",
    speaker_name: "Narrator",
    kind: "narration",
    text: "Something happens.",
    emotion: "",
    location: "The Last Breath",
    image_url: null,
    audio_url: null,
    private_with: null,
    ...over,
  };
}

// The full-screen character profile (GET /games/{id}/characters/{cid}/profile).
export function makeProfile(over = {}) {
  return {
    id: "c1",
    name: "Jacker",
    description: "The watchful bartender.",
    gender: "male",
    disposition: "neutral",
    following: false,
    alive: true,
    life: 10,
    max_life: 10,
    face_url: null,
    body_url: null,
    voice_id: null,
    color: "#8ab",
    carrying: [],
    traits: [{ id: "t1", text: "distrusts authority", unlocked: "Day 2, evening" }],
    origin: [{ id: "or1", text: "He ran corp security before the fall.", learned: "Day 2, night" }],
    relation: "old friend",
    moments: [
      { id: "m1", text: "Turned friendly toward the player.", when: "Day 1, evening" },
      { id: "m2", text: "Received the brass key from the player.", when: "Day 2, morning" },
    ],
    memories: [{ image_url: "/media/g-test/bar.png", caption: "the bar at night", turn_index: 2 }],
    ...over,
  };
}

export const GAMES = [{ id: "g-test", title: "Test Adventure", status: "active", created_at: "2026-06-09" }];

// A controllable stand-in for the browser's EventSource (jsdom has none).
// Tests install it with vi.stubGlobal("EventSource", FakeEventSource), grab
// the instance the app opened, and emit() wire-shaped media-ready events.
export class FakeEventSource {
  static instances = [];
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.onmessage = null;
    this.onopen = null;
    this.onerror = null;
    FakeEventSource.instances.push(this);
  }
  emit(data) {
    this.onmessage && this.onmessage({ data: typeof data === "string" ? data : JSON.stringify(data) });
  }
  open() {
    this.readyState = 1;
    this.onopen && this.onopen({});
  }
  fail() {
    this.onerror && this.onerror({});
  }
  close() {
    this.readyState = 2;
  }
}
