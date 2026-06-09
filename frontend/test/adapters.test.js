import { test } from "vitest";
import assert from "node:assert/strict";
import { mapGameState, mapBeat, mapBeats, voiceForBeat, presentCharacters } from "../src/adapters.js";

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
