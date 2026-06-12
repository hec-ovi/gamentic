import { test, beforeEach } from "vitest";
import assert from "node:assert/strict";
import {
  mapGameState, mapBeat, mapBeats, voiceForBeat, presentCharacters,
  unreadPmCount, markPmSeen, beatOrdinal, pmSeenKey,
} from "../src/adapters.js";

// Real-shaped payload captured from the live orchestrator.
const RAW_STATE = {
  game_id: "g1",
  title: "The Hollow Vigil",
  narrator_voice_id: "af_alloy",
  player: {
    life: 18,
    max_life: 20,
    points: 30,
    location: "tower stair",
    inventory: [{ name: "rusty dagger", description: "", qty: 1 }],
    flags: { door_opened: "true" },
  },
  quests: [
    {
      id: "q1",
      title: "Escape",
      status: "active",
      objectives: [{ id: "o1", text: "Find the altar", done: true, progress: null }],
    },
  ],
  characters: [
    {
      id: "c1",
      name: "Edda",
      voice_id: "af_aoede",
      color: null,
      present: true,
      location: "tower stair",
      face_url: "/image/file?filename=gamentic_00012_.png&subfolder=&type=output",
      body_front_url: "/image/file?filename=gamentic_00013_.png",
      body_side_url: null,
    },
    {
      id: "c2",
      name: "Cormac",
      voice_id: "af_bella",
      color: "#8ab",
      present: true,
      location: "elsewhere",
      face_url: null,
      body_front_url: null,
      body_side_url: null,
    },
  ],
};

test("narrator voice comes from state.narrator_voice_id", () => {
  const s = mapGameState(RAW_STATE);
  assert.equal(s.narratorVoiceId, "af_alloy");
});

test("character voice ids and colors are mapped; null color falls back", () => {
  const s = mapGameState(RAW_STATE);
  assert.equal(s.characters[0].voiceId, "af_aoede");
  assert.equal(s.characters[1].voiceId, "af_bella");
  assert.ok(s.characters[0].color, "null color should get a palette fallback");
  assert.equal(s.characters[1].color, "#8ab");
});

test("relative media URLs are preserved exactly (no rewriting)", () => {
  const s = mapGameState(RAW_STATE);
  assert.equal(s.characters[0].faceUrl, "/image/file?filename=gamentic_00012_.png&subfolder=&type=output");
  assert.equal(s.characters[0].bodyFrontUrl, "/image/file?filename=gamentic_00013_.png");
  assert.equal(s.characters[0].bodySideUrl, null);
});

test("private_with maps to privateWith (and defaults to null)", () => {
  const [priv] = mapBeats([{ id: "x", kind: "dialogue", speaker: "c1", text: "psst", private_with: "c1" }]);
  assert.equal(priv.privateWith, "c1");
  const [pub] = mapBeats([{ id: "y", kind: "narration", speaker: "narrator", text: "hi" }]);
  assert.equal(pub.privateWith, null);
});

test("player fields and inventory map through", () => {
  const s = mapGameState(RAW_STATE);
  assert.equal(s.player.life, 18);
  assert.equal(s.player.maxLife, 20);
  assert.equal(s.player.points, 30);
  assert.equal(s.player.location, "tower stair");
  assert.equal(s.player.inventory[0].name, "rusty dagger");
});

test("beats map by kind and preserve relative image/audio urls", () => {
  const beats = mapBeats([
    { id: "b1", turn_index: 1, seq: 0, speaker: "narrator", kind: "narration", text: "The stair creaks.", image_url: "/image/file?filename=x.png" },
    { id: "b2", turn_index: 2, seq: 0, speaker: "player", kind: "action", text: "I climb." },
    { id: "b3", turn_index: 2, seq: 1, speaker: "c1", speaker_name: "Edda", kind: "dialogue", text: "Wait." },
    { id: "b4", turn_index: 2, seq: 2, speaker: "system", kind: "system", text: "Objective updated." },
  ]);
  assert.deepEqual(beats.map((b) => b.kind), ["narration", "action", "dialogue", "system"]);
  assert.equal(beats[0].imageUrl, "/image/file?filename=x.png");
  assert.equal(beats[2].speakerName, "Edda");
});

test("voiceForBeat: narration -> narrator voice, dialogue -> character voice, others silent", () => {
  const s = mapGameState(RAW_STATE);
  const narration = mapBeat({ id: "n", kind: "narration", speaker: "narrator", text: "x" });
  const dialogue = mapBeat({ id: "d", kind: "dialogue", speaker: "c1", text: "x" });
  const action = mapBeat({ id: "a", kind: "action", speaker: "player", text: "x" });
  const system = mapBeat({ id: "sy", kind: "system", speaker: "system", text: "x" });

  assert.equal(voiceForBeat(narration, s), "af_alloy");
  assert.equal(voiceForBeat(dialogue, s), "af_aoede");
  assert.equal(voiceForBeat(action, s), null);
  assert.equal(voiceForBeat(system, s), null);
});

test("presentCharacters: only present AND co-located with player", () => {
  const s = mapGameState(RAW_STATE);
  const present = presentCharacters(s);
  // Edda is present + same location; Cormac is present but elsewhere.
  assert.deepEqual(present.map((c) => c.name), ["Edda"]);
});

test("scene items carry the fixed flag (scenery vs loot)", () => {
  const s = mapGameState({
    scene: { id: "s1", name: "Bar", items: [
      { id: "i1", name: "altar", fixed: true },
      { id: "i2", name: "key", fixed: false },
      { id: "i3", name: "coin" },
    ] },
  });
  assert.equal(s.scene.items[0].fixed, true);
  assert.equal(s.scene.items[1].fixed, false);
  assert.equal(s.scene.items[2].fixed, false); // absent -> false
});

test("exits are NOT capped at 3 (auto back-exit can make 4) and back is flagged", () => {
  const s = mapGameState({
    scene: { id: "s1", name: "Bar", exits: [
      { id: "e1", label: "the street", target: "street" },
      { id: "e2", label: "the cellar", target: "cellar" },
      { id: "e3", label: "the roof", target: "roof" },
      { id: "e4", label: "back to The Alley", target: "alley" },
    ] },
  });
  assert.equal(s.scene.exits.length, 4);
  assert.equal(s.scene.exits[3].isBack, true);
  assert.equal(s.scene.exits[0].isBack, false);
});

test("tolerates missing fields without throwing", () => {
  const s = mapGameState({});
  assert.equal(s.title, "Untitled Adventure");
  assert.equal(s.narratorVoiceId, null);
  assert.deepEqual(s.characters, []);
  assert.equal(s.player.life, 0);
});

// ---- unread-whisper tracking (the shared count for card dot + tab badge) ----

beforeEach(() => localStorage.clear());

function pmGame(beats) {
  return { id: "g-x", beats };
}
function pm(over) {
  return { id: "p", turnIndex: 1, seq: 0, kind: "dialogue", speaker: "c1", privateWith: "c1", pending: false, ...over };
}

test("beatOrdinal: turn index outranks seq; missing turn index sorts below everything", () => {
  assert.ok(beatOrdinal({ turnIndex: 2, seq: 0 }) > beatOrdinal({ turnIndex: 1, seq: 99 }));
  assert.ok(beatOrdinal({ turnIndex: 1, seq: 1 }) > beatOrdinal({ turnIndex: 1, seq: 0 }));
  assert.equal(beatOrdinal({ turnIndex: null, seq: 3 }), -1);
  assert.equal(beatOrdinal(null), -1);
});

test("unreadPmCount counts only a CHARACTER's private beats, never the player's own or pending echoes", () => {
  const g = pmGame([
    pm({ id: "a", speaker: "c1" }),                          // from the character: counts
    pm({ id: "b", speaker: "player", seq: 1 }),              // player's own echo: never
    pm({ id: "c", speaker: "c1", seq: 2, pending: true }),   // optimistic pending: never
    { id: "d", turnIndex: 1, seq: 3, kind: "dialogue", speaker: "c1", privateWith: null }, // public: never
  ]);
  assert.equal(unreadPmCount(g, "c1"), 1);
});

test("markPmSeen clears the count, and only newer beats reopen it", () => {
  const g = pmGame([pm({ id: "a", turnIndex: 1, seq: 0 })]);
  assert.equal(unreadPmCount(g, "c1"), 1);
  markPmSeen(g, "c1");
  assert.equal(unreadPmCount(g, "c1"), 0); // seen
  g.beats.push(pm({ id: "b", turnIndex: 2, seq: 0 }));
  assert.equal(unreadPmCount(g, "c1"), 1); // a newer whisper is unread again
  markPmSeen(g, "c1");
  assert.equal(unreadPmCount(g, "c1"), 0);
});

test("the seen marker is namespaced per game id (no cross-talk)", () => {
  const a = { id: "game-a", beats: [pm({ id: "a", turnIndex: 3, seq: 0 })] };
  const b = { id: "game-b", beats: [pm({ id: "b", turnIndex: 3, seq: 0 })] };
  markPmSeen(a, "c1"); // only game-a's marker is written
  assert.equal(localStorage.getItem(pmSeenKey("game-a", "c1")), "300000");
  assert.equal(localStorage.getItem(pmSeenKey("game-b", "c1")), null);
  assert.equal(unreadPmCount(a, "c1"), 0); // seen in game-a
  assert.equal(unreadPmCount(b, "c1"), 1); // still unread in game-b
});

test("a character keeps four action buttons (3 base + the rotating offer); scene actions stay capped at 3", () => {
  const s = mapGameState({
    characters: [{ id: "c9", name: "Mara", present: true, available_actions: [
      { id: "b0", label: "Talk", type: "talk" },
      { id: "b1", label: "Give...", type: "give" },
      { id: "b2", label: "Provoke", type: "offer" },
      { id: "o1", label: "Ask about the scar", type: "offer" },
    ] }],
    scene: { id: "s1", name: "Bar", available_actions: [
      { id: "s0", label: "Look around", type: "look" },
      { id: "s1", label: "Search", type: "search" },
      { id: "s2", label: "Pray", type: "offer" },
      { id: "s3", label: "Overflow", type: "offer" },
    ] },
  });
  assert.deepEqual(s.characters[0].actions.map((a) => a.label),
    ["Talk", "Give...", "Provoke", "Ask about the scar"]);
  assert.equal(s.scene.actions.length, 3);
});
