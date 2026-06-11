// The theming contract, enforced: every color literal lives in themes/*.css.
// styles.css is structure (layout, shape, motion) consuming tokens, and the
// JS render layer emits var(--token) references, never hexes - so a whole
// theme (high tech today, medieval tomorrow) swaps by replacing ONE file.

import { test } from "vitest";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const at = (p) => fileURLToPath(new URL(p, import.meta.url));

// hex colors, rgb()/rgba()/hsl() calls. NOT color-mix (that's how alpha
// variants derive FROM tokens) and not &#039;-style HTML entities.
const CSS_COLOR = /(?<!&)#[0-9a-fA-F]{3,8}\b|(?<![-\w])rgba?\(|(?<![-\w])hsla?\(/;
const JS_HEX = /(?<!&)#[0-9a-fA-F]{6}\b|(?<!&)#[0-9a-fA-F]{3}(?![0-9a-zA-Z])/;

function stripComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, "");
}

test("styles.css carries no raw color literals (tokens only; masks exempt)", () => {
  const lines = readFileSync(at("../styles.css"), "utf8").split("\n");
  const offenders = [];
  lines.forEach((line, i) => {
    if (/mask/.test(line)) return; // alpha masks paint SHAPE; their stops stay literal
    if (CSS_COLOR.test(stripComments(line))) offenders.push(`${i + 1}: ${line.trim()}`);
  });
  assert.deepEqual(offenders, []);
});

test("the JS render layer carries no hex colors (identity fallbacks ride tokens)", () => {
  const dirs = ["../src", "../src/app", "../src/render"];
  const offenders = [];
  for (const dir of dirs) {
    for (const file of readdirSync(at(dir))) {
      if (!file.endsWith(".js")) continue;
      readFileSync(at(`${dir}/${file}`), "utf8")
        .split("\n")
        .forEach((line, i) => {
          if (JS_HEX.test(line)) offenders.push(`${dir.replace("../", "")}/${file}:${i + 1}: ${line.trim()}`);
        });
    }
  }
  assert.deepEqual(offenders, []);
});

test("the theme file defines every token styles.css consumes", () => {
  const theme = readFileSync(at("../themes/hightech.css"), "utf8");
  const defined = new Set([...theme.matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1]));
  const consumed = new Set(
    [...stripComments(readFileSync(at("../styles.css"), "utf8")).matchAll(/var\((--[\w-]+)[),]/g)].map((m) => m[1]),
  );
  // per-element data properties are set inline by JS, not by the theme
  const runtime = new Set(["--speaker", "--meter", "--i", "--c"]);
  const missing = [...consumed].filter((t) => !defined.has(t) && !runtime.has(t));
  assert.deepEqual(missing, []);
});
