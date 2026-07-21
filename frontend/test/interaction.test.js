import { test } from "vitest";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { renderApp } from "../src/render.js";
import { mapGameState, mapBeats } from "../src/adapters.js";

// Render-level checks of the play composer + story controls (app wiring is
// covered end-to-end in play.component.test.js).
function mountPlay({ generating = false, composer } = {}) {
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
  root.innerHTML = renderApp({
    view: "play",
    active: { id: "g1", state, beats, generating, composer: composer || { mode: "do", stack: [] } },
  });
  return { dom, document, root };
}

test("the composer offers Do/Say modes, a chip line, the @ tagger and the + stack", () => {
  const { root } = mountPlay();
  const form = root.querySelector('[data-form="action"]');
  assert.ok(form, "action form present");
  const doBtn = form.querySelector('[data-act="cmp-mode"][data-mode="do"]');
  const sayBtn = form.querySelector('[data-act="cmp-mode"][data-mode="say"]');
  assert.ok(doBtn && sayBtn, "both modes present");
  assert.ok(doBtn.classList.contains("active"), "Do is the default mode");
  const input = form.querySelector("#cmpInput");
  assert.equal(input.getAttribute("contenteditable"), "true");
  assert.equal(input.getAttribute("role"), "textbox");
  assert.ok(form.querySelector('[data-act="open-tagger"][data-scope="cmp"]'), "@ tagger button");
  assert.ok(form.querySelector('[data-act="cmp-stack"]'), "+ stack button");
  assert.ok(form.querySelector('button[type="submit"]'), "send button");
});

test("while generating, the whole composer is locked, but no full-screen veil blocks reading", () => {
  const { root } = mountPlay({ generating: true });
  const form = root.querySelector('[data-form="action"]');
  assert.equal(form.querySelector("#cmpInput").getAttribute("contenteditable"), "false");
  for (const sel of ['[data-act="cmp-mode"]', '[data-act="open-tagger"]', '[data-act="cmp-stack"]', 'button[type="submit"]']) {
    assert.ok(form.querySelector(sel).hasAttribute("disabled"), `${sel} disabled while generating`);
  }
  assert.equal(root.querySelector(".busy-veil"), null, "the lock is partial: no stage veil");
});

test("stacked segments render as removable rows", () => {
  const { root } = mountPlay({
    composer: { mode: "do", stack: [{ type: "say", text: "hello", target: "Mara" }, { type: "do", text: "wave" }] },
  });
  const rows = root.querySelectorAll(".seg-stack .seg-row");
  assert.equal(rows.length, 2);
  assert.ok(/Say -> Mara: hello/.test(rows[0].textContent));
  assert.ok(rows[0].querySelector('[data-act="cmp-unstack"][data-index="0"]'), "row is removable");
});

test("there are NO synthesized quick-action chips (no repeated affordances)", () => {
  const { root } = mountPlay();
  assert.equal(root.querySelector('[data-act="quick"]'), null);
  assert.equal(root.querySelector(".quick-actions"), null);
});

test("clicking a beat's play button targets that beat id for voice", () => {
  const { root } = mountPlay();
  const speak = root.querySelector('[data-act="speak-beat"]');
  assert.ok(speak, "narration beat has a play-voice button (voice assigned)");
  assert.equal(speak.dataset.beatId, "b1");
});

// ---- the help popover never overflows the viewport (live: the composer's
// bottom-right ? pushed the pop past the bottom edge and grew a scrollbar) ----
test("help popover opens below its dot when there is room", async () => {
  const { helpPopTop } = await import("../src/app/cues.js");
  const rect = { top: 100, bottom: 120 };
  assert.equal(helpPopTop(rect, 150, 900, 0), 126); // below: bottom + 6
});

test("help popover flips above the dot at the bottom of the viewport", async () => {
  const { helpPopTop } = await import("../src/app/cues.js");
  const rect = { top: 850, bottom: 870 };            // a composer-row dot
  assert.equal(helpPopTop(rect, 150, 900, 0), 850 - 150 - 6); // above: top - height - 6
  // and it never goes past the top edge either
  assert.equal(helpPopTop({ top: 40, bottom: 60 }, 300, 200, 0), 8);
  // page scroll offsets ride along
  assert.equal(helpPopTop(rect, 150, 900, 500), 850 - 150 - 6 + 500);
});
