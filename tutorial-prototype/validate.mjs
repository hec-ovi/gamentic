/* Local, dependency-free integrity check for the guided-tour prototype.
   Run: node validate.mjs
   It does NOT need a browser: it reads the three source files as text, recovers
   the step array by evaluating steps.js in a tiny fake-window sandbox, and asserts
   that every step points at markup that actually exists. It also syntax-checks
   tutorial.js by importing it under a stub DOM. Exits non-zero on any failure. */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const here = dirname(fileURLToPath(import.meta.url));
const read = (f) => readFileSync(join(here, f), "utf8");

let failures = 0;
const fail = (msg) => { failures++; console.error("  FAIL:", msg); };
const ok = (msg) => console.log("  ok:", msg);

// ---- 1. recover the steps array from steps.js ----------------------------
const stepsSrc = read("steps.js");
const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(stepsSrc, sandbox);
const steps = sandbox.window.TUTORIAL_STEPS;

if (!Array.isArray(steps) || !steps.length) {
  fail("steps.js did not define a non-empty window.TUTORIAL_STEPS");
} else {
  ok(`steps.js defines ${steps.length} steps`);
}

// ---- 2. collect the hooks present in index.html --------------------------
const html = read("index.html");
const collect = (attr) => {
  const set = new Set();
  const re = new RegExp(`data-${attr}="([^"]+)"`, "g");
  let m;
  while ((m = re.exec(html))) set.add(m[1]);
  return set;
};
const tutHooks = collect("tut");
const overlays = collect("overlay");
const reveals = collect("reveal");
ok(`markup exposes ${tutHooks.size} data-tut hooks, ${overlays.size} overlays, ${reveals.size} reveals`);

// ---- 3. every step resolves ---------------------------------------------
let intros = 0;
steps.forEach((s, idx) => {
  const at = `step ${idx + 1} ("${s.title || "?"}")`;
  if (!s.title || !s.body) fail(`${at}: missing title or body`);
  if (!s.sel) { intros++; }
  else {
    const m = /^\[data-tut="([^"]+)"\]$/.exec(s.sel);
    if (!m) fail(`${at}: selector "${s.sel}" is not a [data-tut="..."] hook`);
    else if (!tutHooks.has(m[1])) fail(`${at}: no element carries data-tut="${m[1]}"`);
  }
  if (s.stage && !overlays.has(s.stage)) fail(`${at}: no overlay data-overlay="${s.stage}"`);
  (s.show || []).forEach((k) => { if (!reveals.has(k)) fail(`${at}: no reveal data-reveal="${k}"`); });
});
ok(`resolved ${steps.length - intros} spotlight steps + ${intros} intro/outro cards`);

// ---- 4. tutorial.js parses under a stubbed DOM ---------------------------
try {
  const tutSrc = read("tutorial.js");
  const noop = () => {};
  const stubEl = new Proxy({}, {
    get: (_, p) => {
      if (p === "style" || p === "dataset" || p === "classList") return new Proxy({}, { get: () => noop });
      if (p === "children") return [];
      if (p === "hidden") return true;
      return typeof p === "string" && /^(add|remove|append|set|query|toggle|scroll|getBoundingClientRect)/.test(p) ? noop : "";
    },
    set: () => true,
  });
  const doc = {
    getElementById: () => stubEl, querySelector: () => null, querySelectorAll: () => [],
    createElement: () => stubEl, addEventListener: noop, readyState: "loading", body: stubEl,
  };
  const win = {
    TUTORIAL_STEPS: steps, addEventListener: noop, innerWidth: 1200, innerHeight: 800,
    requestAnimationFrame: noop, setTimeout: noop,
  };
  const ctx = { window: win, document: doc, requestAnimationFrame: noop, setTimeout: noop };
  vm.createContext(ctx);
  vm.runInContext(tutSrc, ctx);
  ok("tutorial.js parses and runs its top-level IIFE without throwing");
} catch (e) {
  fail("tutorial.js threw at load: " + e.message);
}

// ---- verdict -------------------------------------------------------------
if (failures) { console.error(`\n${failures} failure(s).`); process.exit(1); }
console.log("\nAll checks passed.");
