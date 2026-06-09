import { test } from "vitest";
import assert from "node:assert/strict";
import { diffState, buildNotices } from "../src/transitions.js";
import { mapGameState } from "../src/adapters.js";

// build a mapped state from a partial raw payload
function st(over = {}) {
  return mapGameState({
    game_id: "g",
    scene: { id: "s1", name: "Bar", status: "tense", exits: [], items: [], available_actions: [] },
    player: { life: 20, max_life: 20, points: 0, location: "Bar", inventory: [] },
    quests: [],
    characters: [],
    ...over,
  });
}

test("diffState reports a scene change when scene id changes", () => {
  const a = st();
  const b = st({ scene: { id: "s2", name: "Street", exits: [], items: [], available_actions: [] }, player: { location: "Street" } });
  const ch = diffState(a, b);
  assert.equal(ch.sceneChanged, true);
  assert.equal(ch.sceneName, "Street");
});

test("diffState detects item revealed and taken within the same scene", () => {
  const a = st({ scene: { id: "s1", name: "Bar", items: [{ id: "i1", name: "key" }], exits: [], available_actions: [] } });
  const b = st({ scene: { id: "s1", name: "Bar", items: [{ id: "i2", name: "chip" }], exits: [], available_actions: [] } });
  const ch = diffState(a, b);
  assert.deepEqual(ch.itemsAdded, ["i2"]);
  assert.deepEqual(ch.itemsRemoved, ["i1"]);
});

test("diffState surfaces follow / disposition / death / join transitions", () => {
  const base = { id: "c1", name: "Jacker", present: true, location: "Bar", alive: true, disposition: "neutral", following: false, life: 10, max_life: 10 };
  const a = st({ characters: [base] });
  const b = st({ characters: [{ ...base, following: true, disposition: "friendly" }] });
  const ch = diffState(a, b);
  assert.deepEqual(ch.charFollowing.map((c) => c.name), ["Jacker"]);
  assert.deepEqual(ch.charDisposition.map((c) => c.to), ["friendly"]);

  const dead = diffState(a, st({ characters: [{ ...base, alive: false }] }));
  assert.deepEqual(dead.charDied.map((c) => c.name), ["Jacker"]);

  // joined: was elsewhere, now co-located
  const away = st({ characters: [{ ...base, location: "Street" }] });
  const here = st({ characters: [base] });
  assert.deepEqual(diffState(away, here).charJoined.map((c) => c.name), ["Jacker"]);
  assert.deepEqual(diffState(here, away).charLeft.map((c) => c.name), ["Jacker"]);
});

test("diffState tracks goal, objective completion, deltas and story end", () => {
  const a = st({ current_goal: "Find key", quests: [{ id: "q1", title: "Q", status: "active", objectives: [{ id: "o1", text: "do it", done: false }] }], player: { points: 0, life: 20, max_life: 20, location: "Bar" } });
  const b = st({ current_goal: "Open door", status: "won", quests: [{ id: "q1", title: "Q", status: "done", objectives: [{ id: "o1", text: "do it", done: true }] }], player: { points: 10, life: 15, max_life: 20, location: "Bar" } });
  const ch = diffState(a, b);
  assert.equal(ch.goalChanged, true);
  assert.deepEqual(ch.objectivesDone, ["do it"]);
  assert.deepEqual(ch.questResolved, [{ title: "Q", status: "done" }]);
  assert.equal(ch.pointsDelta, 10);
  assert.equal(ch.lifeDelta, -5);
  assert.equal(ch.storyEnded, "won");
});

test("first load yields no transitions", () => {
  const ch = diffState(null, st());
  assert.equal(ch.firstLoad, true);
  assert.equal(buildNotices(ch).length, 0);
});

test("buildNotices renders human-readable notices for the changes", () => {
  const base = { id: "c1", name: "Vera", present: true, location: "Bar", alive: true, disposition: "neutral", following: false, life: 8, max_life: 8 };
  const a = st({ characters: [base] });
  const b = st({ current_goal: "Run", characters: [{ ...base, following: true }], scene: { id: "s2", name: "Alley", exits: [], items: [], available_actions: [] }, player: { location: "Alley" } });
  const texts = buildNotices(diffState(a, b)).map((n) => n.text);
  assert.ok(texts.some((t) => /Entered Alley/.test(t)));
  assert.ok(texts.some((t) => /Vera now follows you/.test(t)));
  assert.ok(texts.some((t) => /New goal: Run/.test(t)));
});
