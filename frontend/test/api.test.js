import { test } from "vitest";
import assert from "node:assert/strict";
import { createApi } from "../src/api.js";

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
