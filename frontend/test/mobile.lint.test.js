// The mobile-adapter contract, enforced: phones get their layout fixes from ONE
// additive @media (max-width: 640px) block at the end of styles.css. Desktop
// rules never change for mobile's sake; the adapter only ever overrides inside
// its breakpoint. These pins protect the load-bearing overrides (the ones that
// un-break iPhone-SE width, verified in a real browser) from silent deletion.

import { test } from "vitest";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const at = (p) => fileURLToPath(new URL(p, import.meta.url));

function mobileBlock() {
  const css = readFileSync(at("../styles.css"), "utf8");
  const start = css.indexOf("@media (max-width: 640px)");
  assert.notEqual(start, -1, "the mobile adapter block (@media max-width: 640px) is gone");
  // the block runs to its matching closing brace
  let depth = 0;
  let i = css.indexOf("{", start);
  const open = i;
  for (; i < css.length; i++) {
    if (css[i] === "{") depth++;
    if (css[i] === "}") depth--;
    if (depth === 0) break;
  }
  return css.slice(open, i);
}

test("the mobile adapter keeps its load-bearing overrides", () => {
  const block = mobileBlock();
  // the composer must wrap into rows or Send falls off a 375px screen
  assert.match(block, /\.composer\s*{[^}]*flex-wrap:\s*wrap/);
  // system badges must cap at the panel, never the 64ch prose measure
  assert.match(block, /\.system-badge\s*{[^}]*max-width:\s*100%/);
  // dialogue bubbles must be allowed to shrink (flex min-width gotcha)
  assert.match(block, /\.bubble\s*{[^}]*min-width:\s*0/);
  // the affordance board stacks; the diagonal separators go
  assert.match(block, /\.board-sep\s*{[^}]*display:\s*none/);
  // the story always keeps a reading window
  assert.match(block, /\.play-body\s*{[^}]*min-height/);
});

test("mobile overrides live ONLY inside media queries (desktop untouched)", () => {
  let css = readFileSync(at("../styles.css"), "utf8");
  // strip every @media block (balanced braces); what remains is the desktop layer
  let start;
  while ((start = css.indexOf("@media")) !== -1) {
    let depth = 0;
    let i = css.indexOf("{", start);
    for (; i < css.length; i++) {
      if (css[i] === "{") depth++;
      if (css[i] === "}") depth--;
      if (depth === 0) break;
    }
    css = css.slice(0, start) + css.slice(i + 1);
  }
  // spot-check: the desktop composer still lays out as a single row
  const composer = css.match(/\.composer\s*{[^}]*}/);
  assert.ok(composer, ".composer base rule must stay defined outside the media blocks");
  assert.doesNotMatch(composer[0], /flex-wrap:\s*wrap/, "composer wrapping leaked into the desktop rule");
});
