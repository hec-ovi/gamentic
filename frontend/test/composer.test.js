// The tagged-segment composer: chips serialize to inline names + refs, and
// buildSegment maps (mode, channel) onto the wire segment shapes from
// docs/frontend-api.md s2.

import { test } from "vitest";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { chipHtml, insertChip, serializeComposer, clearComposer, buildSegment, describeSegment } from "../src/composer.js";

function editor(html = "") {
  const dom = new JSDOM(`<!doctype html><body><div id="ed" contenteditable="true">${html}</div></body>`, {
    url: "http://localhost:5173/",
  });
  global.Node = dom.window.Node; // serializeComposer walks nodeType
  return { dom, ed: dom.window.document.querySelector("#ed") };
}

test("serialize: plain text only", () => {
  const { ed } = editor("  open the door  ");
  assert.deepEqual(serializeComposer(ed), { text: "open the door", refs: [] });
});

test("serialize: chips become inline names AND refs entries, in order", () => {
  const { ed } = editor(
    `hello ${chipHtml({ kind: "character", id: "c1", name: "Mara" })} take the ${chipHtml({ kind: "item", id: "i9", name: "brass key" })}`,
  );
  const out = serializeComposer(ed);
  assert.equal(out.text, "hello Mara take the brass key");
  assert.deepEqual(out.refs, [
    { kind: "character", id: "c1", name: "Mara" },
    { kind: "item", id: "i9", name: "brass key" },
  ]);
});

test("chip markup is non-editable and kind-distinct (character vs item icon class)", () => {
  const { dom } = editor(chipHtml({ kind: "character", id: "c1", name: "Mara" }) + chipHtml({ kind: "item", id: "i1", name: "key" }));
  const [a, b] = dom.window.document.querySelectorAll("[data-chip]");
  assert.equal(a.getAttribute("contenteditable"), "false");
  assert.ok(a.classList.contains("chip-character"));
  assert.ok(b.classList.contains("chip-item"));
  assert.ok(a.querySelector("svg"), "chip carries an icon");
});

test("chip escapes hostile names", () => {
  const { ed } = editor(chipHtml({ kind: "item", id: "i1", name: `<img onerror=x>` }));
  assert.equal(ed.querySelector("img"), null, "no element injection through a name");
  assert.equal(serializeComposer(ed).refs[0].name, "<img onerror=x>");
});

test("insertChip appends when there is no caret, and fires an input event", () => {
  const { dom, ed } = editor("give her ");
  global.window = dom.window;
  global.document = dom.window.document;
  let fired = false;
  ed.addEventListener("input", () => (fired = true));
  insertChip(ed, { kind: "item", id: "i2", name: "coin" });
  assert.equal(serializeComposer(ed).text, "give her coin");
  assert.ok(fired, "input event fired");
  clearComposer(ed);
  assert.equal(ed.innerHTML, "");
  delete global.window;
  delete global.document;
});

test("buildSegment: public say / do, with refs only when present", () => {
  assert.deepEqual(buildSegment({ mode: "do", text: "kick it", refs: [], channel: null }), { type: "do", text: "kick it" });
  assert.deepEqual(buildSegment({ mode: "say", text: "hi", refs: [], channel: null }), { type: "say", text: "hi" });
  const refs = [{ kind: "character", id: "c1", name: "Mara" }];
  assert.deepEqual(buildSegment({ mode: "say", text: "hi Mara", refs, channel: null }), { type: "say", text: "hi Mara", refs });
});

test("buildSegment: talk channel directs say at the target; do stays public", () => {
  const ch = { kind: "talk", target: "Mara" };
  assert.deepEqual(buildSegment({ mode: "say", text: "you there?", refs: [], channel: ch }), {
    type: "say",
    text: "you there?",
    target: "Mara",
  });
  assert.deepEqual(buildSegment({ mode: "do", text: "lean in", refs: [], channel: ch }), { type: "do", text: "lean in" });
});

test("buildSegment: private channel -> conversation segments with mode say|do", () => {
  const ch = { kind: "conversation", target: "Mara" };
  assert.deepEqual(buildSegment({ mode: "say", text: "psst", refs: [], channel: ch }), {
    type: "conversation",
    text: "psst",
    target: "Mara",
    mode: "say",
  });
  assert.deepEqual(buildSegment({ mode: "do", text: "slip her the key", refs: [], channel: ch }), {
    type: "conversation",
    text: "slip her the key",
    target: "Mara",
    mode: "do",
  });
});

test("describeSegment reads as a human line", () => {
  assert.equal(describeSegment({ type: "say", text: "hello", target: "Mara" }), "Say -> Mara: hello");
  assert.equal(describeSegment({ type: "do", text: "kick" }), "Do: kick");
  assert.equal(describeSegment({ type: "conversation", mode: "do", text: "pass key", target: "Mara" }), "Discreetly -> Mara: pass key");
});
