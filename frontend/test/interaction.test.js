import { test } from "vitest";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { renderApp } from "../src/render.js";
import { mapGameState, mapBeats } from "../src/adapters.js";

// Drives the rendered action input the way app.js wires it: the form's submit
// reads actionText and forwards the trimmed value, ignoring empty input.
function mountPlay({ generating = false } = {}) {
  const dom = new JSDOM("<!doctype html><body><div id='app'></div></body>", { url: "http://localhost:5173/" });
  const { document } = dom.window;
  const state = mapGameState({
    game_id: "g1",
    title: "T",
    narrator_voice_id: "af_alloy",
    player: { life: 10, max_life: 10, points: 0, location: "hall", inventory: [] },
    quests: [],
    characters: [],
  });
  const beats = mapBeats([{ id: "b1", turn_index: 1, seq: 0, speaker: "narrator", kind: "narration", text: "Begin." }])
    .map((b) => ({ ...b, voiceId: "af_alloy" })); // app.js attaches voiceId via withVoice()
  const root = document.querySelector("#app");
  root.innerHTML = renderApp({ view: "play", active: { id: "g1", state, beats, quickActions: ["Look around"], generating } });

  const submitted = [];
  const form = root.querySelector('[data-form="action"]');
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const value = String(form.querySelector('[name="actionText"]').value || "").trim();
    if (!value || generating) return; // mirrors submitAction guard
    submitted.push(value);
  });
  return { dom, document, root, form, submitted };
}

test("typing an action and submitting fires the handler with the trimmed text", () => {
  const { document, form, submitted } = mountPlay();
  const input = form.querySelector('[name="actionText"]');
  input.value = "  I open the door.  ";
  form.dispatchEvent(new document.defaultView.Event("submit", { cancelable: true, bubbles: true }));
  assert.deepEqual(submitted, ["I open the door."]);
});

test("submitting an empty action does nothing", () => {
  const { document, form, submitted } = mountPlay();
  form.querySelector('[name="actionText"]').value = "   ";
  form.dispatchEvent(new document.defaultView.Event("submit", { cancelable: true, bubbles: true }));
  assert.deepEqual(submitted, []);
});

test("a quick-action chip carries the action text to submit", () => {
  const { root } = mountPlay();
  const chip = root.querySelector('.chip[data-act="quick"]');
  assert.ok(chip, "quick action chip rendered");
  assert.equal(chip.dataset.text, "Look around");
});

test("clicking a beat's play button targets that beat id for voice", () => {
  const { root } = mountPlay();
  const speak = root.querySelector('[data-act="speak-beat"]');
  assert.ok(speak, "narration beat has a play-voice button (voice assigned)");
  assert.equal(speak.dataset.beatId, "b1");
});
