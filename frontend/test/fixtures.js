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
  const { scene, player, quests, characters, ...rest } = over;
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
    location: "The Last Breath",
    image_url: null,
    audio_url: null,
    private_with: null,
    ...over,
  };
}

export const GAMES = [{ id: "g-test", title: "Test Adventure", status: "active", created_at: "2026-06-09" }];
