import { test, afterEach } from "vitest";
import assert from "node:assert/strict";
import { ApiError, createApi } from "../src/api.js";

// every test stubs globalThis.fetch; put the real one back so this file can
// never poison MSW's patched fetch if vitest isolation is ever relaxed
const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

function stubFetch(calls) {
  return async (url, opts) => {
    calls.push({ url, opts });
    return { ok: true, status: 200, text: async () => JSON.stringify({ ok: true }) };
  };
}

test("deleteGame issues a DELETE to /games/{id}", async () => {
  const calls = [];
  globalThis.fetch = stubFetch(calls);
  await createApi("http://x:8000").deleteGame("g1");
  assert.equal(calls[0].opts.method, "DELETE");
  assert.match(calls[0].url, /\/games\/g1$/);
});

test("clearBeats issues a DELETE to /games/{id}/beats", async () => {
  const calls = [];
  globalThis.fetch = stubFetch(calls);
  await createApi("http://x:8000").clearBeats("g1");
  assert.equal(calls[0].opts.method, "DELETE");
  assert.match(calls[0].url, /\/games\/g1\/beats$/);
});

test("takeAction with a string sends { action }", async () => {
  const calls = [];
  globalThis.fetch = stubFetch(calls);
  await createApi("http://x:8000").takeAction("g1", "I open the door.");
  assert.deepEqual(JSON.parse(calls[0].opts.body), { action: "I open the door." });
});

test("takeAction with an array sends { segments } (tagged buttons)", async () => {
  const calls = [];
  globalThis.fetch = stubFetch(calls);
  const segments = [{ type: "say", text: "hello", target: "Jacker" }];
  await createApi("http://x:8000").takeAction("g1", segments);
  assert.deepEqual(JSON.parse(calls[0].opts.body), { segments });
});

test("a hung request rejects with a friendly timeout ApiError instead of busy-locking forever", async () => {
  const { vi } = await import("vitest");
  vi.useFakeTimers();
  try {
    globalThis.fetch = () => new Promise(() => {}); // never settles
    const promise = createApi("http://x:8000").listGames();
    const rejected = assert.rejects(promise, (err) => {
      assert.ok(err instanceof ApiError);
      assert.equal(err.status, 0);
      assert.match(err.message, /taking too long/i);
      return true;
    });
    await vi.advanceTimersByTimeAsync(21000); // past the read budget
    await rejected;
  } finally {
    vi.useRealTimers();
  }
});

test("a turn is never cut off by a client ceiling, however long the model thinks", async () => {
  const { vi } = await import("vitest");
  vi.useFakeTimers();
  try {
    let settle;
    globalThis.fetch = () =>
      new Promise((resolve) => {
        settle = () => resolve({ ok: true, status: 200, text: async () => JSON.stringify({ beats: [] }) });
      });
    const promise = createApi("http://x:8000").takeAction("g1", "I look around.");
    let done = false;
    promise.then(() => { done = true; });
    await vi.advanceTimersByTimeAsync(600000); // ten minutes: past every old cutoff
    assert.equal(done, false, "the turn must still be waiting, not rejected");
    settle();
    assert.deepEqual(await promise, { beats: [] });
  } finally {
    vi.useRealTimers();
  }
});

test("the creator and continue calls wait without a ceiling too", async () => {
  const { vi } = await import("vitest");
  vi.useFakeTimers();
  try {
    globalThis.fetch = () => new Promise(() => {}); // never settles
    const api = createApi("http://x:8000");
    let rejected = false;
    api.continueStory("g1").catch(() => { rejected = true; });
    api.creatorMessage("s1", "a rainy port town").catch(() => { rejected = true; });
    await vi.advanceTimersByTimeAsync(600000);
    assert.equal(rejected, false);
  } finally {
    vi.useRealTimers();
  }
});

test("plain reads still fail fast: the no-ceiling change is LLM-bound calls only", async () => {
  const { vi } = await import("vitest");
  vi.useFakeTimers();
  try {
    globalThis.fetch = () => new Promise(() => {});
    const rejected = assert.rejects(createApi("http://x:8000").getState("g1"), (err) => {
      assert.ok(err instanceof ApiError);
      assert.match(err.message, /taking too long/i);
      return true;
    });
    await vi.advanceTimersByTimeAsync(21000);
    await rejected;
  } finally {
    vi.useRealTimers();
  }
});

test("a FastAPI 422 detail array flattens to its human messages (never [object Object])", async () => {
  globalThis.fetch = async () => ({
    ok: false,
    status: 422,
    statusText: "Unprocessable Entity",
    text: async () =>
      JSON.stringify({ detail: [{ loc: ["body", "history_beats"], msg: "ensure this value is at most 400", type: "value_error" }] }),
  });
  await assert.rejects(createApi("http://x:8000").patchSettings("g1", { history_beats: 9999 }), (err) => {
    assert.equal(err.status, 422);
    assert.equal(err.message, "ensure this value is at most 400");
    return true;
  });
});
