// The static setup face (setup.html + infra/setup/setup.js): a plain script
// pair that must run from file:// with zero network. Both files are evaluated
// into the jsdom window exactly the way a browser would run them, then the
// wizard is driven like a user would.

import { test, expect, afterEach, vi } from "vitest";
import { readFileSync } from "node:fs";
import { screen, waitFor } from "@testing-library/dom";
import userEvent from "@testing-library/user-event";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");
const schemaSrc = read("../../infra/setup/schema.js");
const setupSrc = read("../../infra/setup/setup.js");
const htmlSrc = read("../../setup.html");

// plain scripts, not modules: indirect eval runs them in global scope where
// jsdom's window lives, so the window.* globals appear like in a browser
(0, eval)(schemaSrc);
(0, eval)(setupSrc);
const schema = window.GAMENTIC_SETUP_SCHEMA;
const S = window.GamenticSetup;

const user = () => userEvent.setup({ delay: null });

function mountWizard(opts) {
  document.body.innerHTML = '<div id="setup-root"></div>';
  S.mount(document.getElementById("setup-root"), schema, opts);
}

afterEach(() => {
  delete window.showSaveFilePicker;
  delete window.URL.createObjectURL;
});

// the help "?" buttons are labeled with the prompt too, so target the control
const byLabel = (text) => screen.getByLabelText(text, { selector: "input" });

// ---------- pure helpers ----------

test("parseEnv tolerates comments, blanks, export and quotes; serializeEnv round-trips", () => {
  const parsed = S.parseEnv(
    "# a comment\n\nexport FOO=bar\nMODELS_DIR=/x\nQUOTED=\"a b\"\nnot a kv line\n",
  );
  expect(parsed).toEqual({ FOO: "bar", MODELS_DIR: "/x", QUOTED: "a b" });

  const out = S.serializeEnv({ MODELS_DIR: "/x" }, schema, ["FOO=bar"]);
  const round = S.parseEnv(out);
  // the answer survives, every unasked setting lands with its schema default
  for (const s of schema.settings) {
    expect(round[s.key]).toBe(s.key === "MODELS_DIR" ? "/x" : s.default);
  }
  // the constant is written verbatim
  expect(round.COMPOSE_PROFILES).toBe("local-inference-anna-false,anna-agent-anna-true");
  // the unknown line is preserved, under a labeled unmanaged section at the end
  expect(round.FOO).toBe("bar");
  expect(out).toContain("unmanaged");
  expect(out.indexOf("FOO=bar")).toBeGreaterThan(out.indexOf("COMPOSE_PROFILES="));
});

test("validate: bad ports and non-literal bools are rejected, blanks pass where allowed", () => {
  expect(S.validate({ type: "port" }, "70000")).toBeTruthy();
  expect(S.validate({ type: "port" }, "0")).toBeTruthy();
  expect(S.validate({ type: "port" }, "abc")).toBeTruthy();
  expect(S.validate({ type: "port" }, "8080")).toBeNull();
  expect(S.validate({ type: "int" }, "-1")).toBeTruthy();
  expect(S.validate({ type: "int" }, "12")).toBeNull();
  expect(S.validate({ type: "bool" }, "TRUE")).toBeTruthy(); // LITERAL true/false only
  expect(S.validate({ type: "bool" }, "true")).toBeNull();
  expect(S.validate({ type: "choice", choices: ["a", "b"] }, "c")).toBeTruthy();
  expect(S.validate({ type: "choice", choices: ["a", "b"] }, "b")).toBeNull();
  expect(S.validate({ type: "path" }, "")).toBeTruthy();
  expect(S.validate({ type: "path-relative" }, "m/m.gguf")).toBeNull();
  expect(S.validate({ type: "secret" }, "")).toBeNull();
  expect(S.validate({ type: "string" }, "")).toBeNull();
});

test("visibleSettings: setByMode and advanced are skipped per mode, custom asks everything", () => {
  expect(S.visibleSettings(schema, "anna").map((s) => s.key)).toEqual(["ANNA_API_KEY"]);
  expect(S.visibleSettings(schema, "local").map((s) => s.key)).toEqual([
    "MODELS_DIR",
    "LLM_TEXT_MODEL",
    "COMFY_MODELS_DIR",
    "RENDER_GID",
    "VIDEO_GID",
  ]);
  const custom = S.visibleSettings(schema, "custom").map((s) => s.key);
  expect(custom).toContain("ANNA"); // setByMode has no custom entry, so it IS asked
  expect(custom).toContain("LLM_ALIAS"); // advanced is asked in custom
  expect(custom).toHaveLength(schema.settings.length);
});

// ---------- the full anna-mode flow ----------

test("anna flow: load .env, pick the mode card, type the key, masked review, full save, done", async () => {
  const u = user();
  let saved = null;
  mountWizard({
    envText: "# old file\nADMIN_TOKEN=keep-me-around\nMODELS_DIR=/data/gguf\nANNA=false\n",
    save: async (text) => {
      saved = text;
      return "picker";
    },
  });

  // welcome: the privacy promise and the loaded-file note (secrets shown nowhere)
  expect(screen.getByText(/never leave the page/i)).toBeTruthy();
  expect(screen.getByText(/Loaded 2 known values/)).toBeTruthy();
  expect(screen.getByText(/1 unfamiliar key/)).toBeTruthy();
  await u.click(screen.getByRole("button", { name: /^start$/i }));

  // mode cards carry the schema label and help verbatim
  const anna = schema.modes.find((m) => m.id === "anna");
  expect(screen.getByText(anna.help)).toBeTruthy();
  await u.click(screen.getByRole("button", { name: /Anna \(no GPU, no local inference\)/ }));

  // the only anna question: the API key, asked as a password input
  const keySetting = schema.settings.find((s) => s.key === "ANNA_API_KEY");
  const input = byLabel(/Anna API key/);
  expect(input.type).toBe("password");

  // "?" reveals the schema help verbatim, and toggles back
  const helpBtn = screen.getByRole("button", { name: /help: Anna API key/i });
  expect(screen.getByText(keySetting.help).hidden).toBe(true);
  await u.click(helpBtn);
  expect(screen.getByText(keySetting.help).hidden).toBe(false);

  await u.type(input, "sk-test-secret-123");
  // the show toggle flips the input to plain text and back
  await u.click(screen.getByRole("button", { name: /^show$/i }));
  expect(input.type).toBe("text");
  await u.click(screen.getByRole("button", { name: /^hide$/i }));
  expect(input.type).toBe("password");
  await u.click(screen.getByRole("button", { name: /^next$/i }));

  // review: grouped, the secret is masked, the mode-set ANNA boolean is shown
  expect(screen.getByRole("heading", { name: /review/i })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Anna" })).toBeTruthy();
  expect(document.body.textContent).not.toContain("sk-test-secret-123");
  expect(document.body.textContent).toContain("••••••••");
  const annaRow = screen.getByText("ANNA").closest("div");
  expect(annaRow.textContent).toContain("true");

  await u.click(screen.getByRole("button", { name: /^save \.env$/i }));
  await waitFor(() => expect(saved).toBeTruthy());

  // the file is complete: mode answer, typed secret, constant, prefilled known
  // key the anna mode never asked about, and the unknown key preserved verbatim
  expect(saved).toContain("ANNA=true");
  expect(saved).toContain("ANNA_API_KEY=sk-test-secret-123");
  expect(saved).toContain("COMPOSE_PROFILES=local-inference-anna-false,anna-agent-anna-true");
  expect(saved).toContain("MODELS_DIR=/data/gguf");
  expect(saved).toContain("ADMIN_TOKEN=keep-me-around");
  expect(saved.indexOf("ADMIN_TOKEN=")).toBeGreaterThan(saved.indexOf("unmanaged"));
  // every schema setting is present even though anna asked one question
  for (const s of schema.settings) expect(saved).toMatch(new RegExp("^" + s.key + "=", "m"));

  // done: the schema doneMessage verbatim plus the anna sign-in note
  expect(document.body.textContent).toContain(schema.doneMessage);
  expect(screen.getByText(/localhost:19001/)).toBeTruthy();
});

test("local flow: a non-numeric gid blocks the advance with a field error", async () => {
  const u = user();
  mountWizard();
  await u.click(screen.getByRole("button", { name: /^start$/i }));
  await u.click(screen.getByRole("button", { name: /Local \(full stack, GPU\)/ }));

  // models step comes prefilled with the schema defaults
  expect(byLabel(/Folder that holds your GGUF/).value).toBe(
    schema.settings.find((s) => s.key === "MODELS_DIR").default,
  );
  await u.click(screen.getByRole("button", { name: /^next$/i }));

  // gpu step: feed it garbage
  const gid = byLabel(/render group id/);
  await u.clear(gid);
  await u.type(gid, "abc");
  await u.click(screen.getByRole("button", { name: /^next$/i }));
  expect(screen.getByText(/must be a whole number/i)).toBeTruthy();
  expect(screen.queryByRole("heading", { name: /review/i })).toBeNull();

  // fix it and the review opens
  await u.clear(gid);
  await u.type(gid, "990");
  await u.click(screen.getByRole("button", { name: /^next$/i }));
  expect(screen.getByRole("heading", { name: /review/i })).toBeTruthy();
});

// ---------- saving ----------

async function driveAnnaToSave(u) {
  await u.click(screen.getByRole("button", { name: /^start$/i }));
  await u.click(screen.getByRole("button", { name: /Anna \(no GPU, no local inference\)/ }));
  await u.click(screen.getByRole("button", { name: /^next$/i }));
  await u.click(screen.getByRole("button", { name: /^save \.env$/i }));
}

test("save prefers the File System Access picker (suggestedName .env), no rename note", async () => {
  const u = user();
  const writes = [];
  window.showSaveFilePicker = vi.fn(async (o) => {
    expect(o.suggestedName).toBe(".env");
    return {
      createWritable: async () => ({
        write: async (t) => writes.push(t),
        close: async () => {},
      }),
    };
  });
  mountWizard(); // no save opt: the real browser save path runs
  await driveAnnaToSave(u);

  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toContain("ANNA=true");
  await waitFor(() => expect(document.body.textContent).toContain(schema.doneMessage));
  expect(screen.queryByText(/rename/i)).toBeNull();
});

test("picker failure falls back to a blob download and the done screen says what to rename", async () => {
  const u = user();
  window.showSaveFilePicker = vi.fn(async () => {
    throw new Error("sandboxed");
  });
  const click = vi.spyOn(window.HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  // jsdom has no createObjectURL at all; stub it (removed again in afterEach)
  const objectUrl = vi.fn(() => "blob:fake");
  window.URL.createObjectURL = objectUrl;
  mountWizard();
  await driveAnnaToSave(u);

  await waitFor(() => expect(document.body.textContent).toContain(schema.doneMessage));
  expect(click).toHaveBeenCalled();
  expect(objectUrl).toHaveBeenCalled();
  const note = screen.getByText(/rename it to exactly/i);
  expect(note.textContent).toContain('".env"');
  expect(note.textContent).toContain("gamentic folder");
});

test("cancelling the picker stays on review without forcing a download", async () => {
  const u = user();
  window.showSaveFilePicker = vi.fn(async () => {
    const e = new Error("user said no");
    e.name = "AbortError";
    throw e;
  });
  const click = vi.spyOn(window.HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  mountWizard();
  await driveAnnaToSave(u);

  await waitFor(() => expect(window.showSaveFilePicker).toHaveBeenCalled());
  expect(screen.getByRole("heading", { name: /review/i })).toBeTruthy();
  expect(document.body.textContent).not.toContain(schema.doneMessage);
  expect(click).not.toHaveBeenCalled();
});

// ---------- the no-network pin ----------

test("setup.js and setup.html carry no fetch, no XHR, no external URLs", () => {
  for (const src of [setupSrc, htmlSrc]) {
    expect(src).not.toContain("fetch(");
    expect(src).not.toContain("XMLHttpRequest");
    expect(src).not.toContain("https://");
  }
});
