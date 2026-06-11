import { test } from "vitest";
import assert from "node:assert/strict";
import { Voice, cleanText } from "../src/voice.js";

// A fake fetch that records the call and returns a canned /voice/speak response.
function makeFetch({ ok = true, audioUrl = "/audio/abc.wav", throws = false } = {}) {
  const calls = [];
  const fn = async (url, opts) => {
    calls.push({ url, opts, body: opts && opts.body ? JSON.parse(opts.body) : null });
    if (throws) throw new Error("network down");
    return {
      ok,
      json: async () => ({ audio_url: audioUrl, duration_s: 1.2, sample_rate: 24000 }),
    };
  };
  fn.calls = calls;
  return fn;
}

// A fake Audio element capturing src + volume + play().
function makeAudio() {
  const made = [];
  class FakeAudio {
    constructor(src) {
      this.src = src;
      this.volume = 1;
      this.currentTime = 0;
      this.played = false;
      made.push(this);
    }
    play() {
      this.played = true;
      return Promise.resolve();
    }
    pause() {
      this.paused = true;
    }
  }
  FakeAudio.made = made;
  return FakeAudio;
}

test("speak() POSTs /voice/speak with {text, voice_id} and plays the returned audio_url", async () => {
  const fetchImpl = makeFetch({ audioUrl: "/audio/xyz.wav" });
  const AudioImpl = makeAudio();
  const v = new Voice({ fetchImpl, AudioImpl });

  const result = await v.speak({ text: "Hello *world*", voiceId: "af_alloy", speakerId: "narrator" });

  assert.equal(fetchImpl.calls.length, 1);
  assert.equal(fetchImpl.calls[0].url, "/voice/speak");
  assert.equal(fetchImpl.calls[0].opts.method, "POST");
  assert.deepEqual(fetchImpl.calls[0].body, { text: "Hello world", voice_id: "af_alloy" });
  assert.equal(result, "/audio/xyz.wav");
  assert.equal(AudioImpl.made.length, 1);
  assert.equal(AudioImpl.made[0].src, "/audio/xyz.wav");
  assert.equal(AudioImpl.made[0].played, true);
});

test("speak() does nothing when voice is disabled", async () => {
  const fetchImpl = makeFetch();
  const v = new Voice({ fetchImpl, AudioImpl: makeAudio() });
  v.applySettings({ voiceEnabled: false });

  const result = await v.speak({ text: "hi", voiceId: "af_alloy" });
  assert.equal(result, null);
  assert.equal(fetchImpl.calls.length, 0);
});

test("speak() skips synthesis entirely when voice_id is null (server 400s on empty)", async () => {
  const fetchImpl = makeFetch();
  const v = new Voice({ fetchImpl, AudioImpl: makeAudio() });

  const result = await v.speak({ text: "narration with no voice", voiceId: null });
  assert.equal(result, null);
  assert.equal(fetchImpl.calls.length, 0, "must not call the server with empty voice");
});

test("speak() returns null on fetch error and does not throw", async () => {
  const fetchImpl = makeFetch({ throws: true });
  const v = new Voice({ fetchImpl, AudioImpl: makeAudio() });

  const result = await v.speak({ text: "hi", voiceId: "af_alloy" });
  assert.equal(result, null);
});

test("speak() returns null when server responds not-ok", async () => {
  const fetchImpl = makeFetch({ ok: false });
  const v = new Voice({ fetchImpl, AudioImpl: makeAudio() });
  const result = await v.speak({ text: "hi", voiceId: "af_alloy" });
  assert.equal(result, null);
});

test("volume = master * per-speaker", async () => {
  const AudioImpl = makeAudio();
  const v = new Voice({ fetchImpl: makeFetch(), AudioImpl });
  v.applySettings({ masterVolume: 0.5, speakerVolumes: { c1: 0.4 } });
  await v.speak({ text: "hi", voiceId: "vx", speakerId: "c1" });
  assert.ok(Math.abs(AudioImpl.made[0].volume - 0.2) < 1e-9);
});

test("stop() pauses the current audio", async () => {
  const AudioImpl = makeAudio();
  const v = new Voice({ fetchImpl: makeFetch(), AudioImpl });
  await v.speak({ text: "hi", voiceId: "vx" });
  v.stop();
  assert.equal(AudioImpl.made[0].paused, true);
});

test("repeated speak of the same text+voice only synthesizes once (cache)", async () => {
  const fetchImpl = makeFetch();
  const v = new Voice({ fetchImpl, AudioImpl: makeAudio() });
  await v.speak({ text: "same line", voiceId: "vx" });
  await v.speak({ text: "same line", voiceId: "vx" });
  assert.equal(fetchImpl.calls.length, 1);
});

test("cleanText strips markdown emphasis and collapses whitespace", () => {
  assert.equal(cleanText("**bold** and *italic* and `code`"), "bold and italic and code");
  assert.equal(cleanText("  spaced\n\nout  "), "spaced out");
});


// ---------------------------------------------------------------------------
// the pipelining primitives: prepare() (queued synth, no playback) + playUrl()
// ---------------------------------------------------------------------------

test("playback NEVER touches /voice/stream (it cuts off mid-line in <audio>)", async () => {
  const fetchImpl = makeFetch();
  const v = new Voice({ fetchImpl, AudioImpl: makeAudio() });
  await v.speak({ text: "line one", voiceId: "vx" });
  await v.prepare({ text: "line two", voiceId: "vx" });
  assert.ok(fetchImpl.calls.length >= 2);
  for (const c of fetchImpl.calls) assert.equal(c.url, "/voice/speak");
});

test("prepare() renders without playing and returns { audioUrl, duration }", async () => {
  const fetchImpl = makeFetch({ audioUrl: "/audio/n1.wav" });
  const AudioImpl = makeAudio();
  const v = new Voice({ fetchImpl, AudioImpl });
  const out = await v.prepare({ text: "next line", voiceId: "vx" });
  assert.deepEqual(out, { audioUrl: "/audio/n1.wav", duration: 1.2 });
  assert.equal(AudioImpl.made.length, 0, "prepare must not play");
});

test("playUrl() plays a prepared url at the speaker's volume", () => {
  const AudioImpl = makeAudio();
  const v = new Voice({ fetchImpl: makeFetch(), AudioImpl });
  v.applySettings({ masterVolume: 0.5, speakerVolumes: { c1: 0.4 } });
  v.playUrl("/audio/n1.wav", "c1");
  assert.equal(AudioImpl.made.length, 1);
  assert.equal(AudioImpl.made[0].src, "/audio/n1.wav");
  assert.equal(AudioImpl.made[0].played, true);
  assert.ok(Math.abs(AudioImpl.made[0].volume - 0.2) < 1e-9);
});

test("synthesis is a strict FIFO queue: one render at a time, never parallel", async () => {
  let active = 0;
  let maxActive = 0;
  const order = [];
  const fetchImpl = async (url, opts) => {
    active += 1;
    maxActive = Math.max(maxActive, active);
    const body = JSON.parse(opts.body);
    order.push(body.text);
    await new Promise((r) => setTimeout(r, 20));
    active -= 1;
    return { ok: true, json: async () => ({ audio_url: `/audio/${body.text}.wav`, duration_s: 1 }) };
  };
  const v = new Voice({ fetchImpl, AudioImpl: null });
  const [a, b] = await Promise.all([
    v.prepare({ text: "first", voiceId: "vx" }),
    v.prepare({ text: "second", voiceId: "vx" }),
  ]);
  assert.equal(maxActive, 1, "renders must not overlap (one GPU)");
  assert.deepEqual(order, ["first", "second"], "FIFO order preserved");
  assert.equal(a.audioUrl, "/audio/first.wav");
  assert.equal(b.audioUrl, "/audio/second.wav");
});

test("prepare() failures resolve null and do not poison the queue", async () => {
  let n = 0;
  const fetchImpl = async () => {
    n += 1;
    if (n === 1) throw new Error("boom");
    return { ok: true, json: async () => ({ audio_url: "/audio/ok.wav", duration_s: 1 }) };
  };
  const v = new Voice({ fetchImpl, AudioImpl: null });
  assert.equal(await v.prepare({ text: "bad", voiceId: "vx" }), null);
  assert.deepEqual(await v.prepare({ text: "good", voiceId: "vx" }), { audioUrl: "/audio/ok.wav", duration: 1 });
});

test("prepare passes the beat's emotion through to /voice/speak (omitted when empty)", async () => {
  const calls = [];
  const fetchImpl = async (url, opts) => {
    calls.push(JSON.parse(opts.body));
    return { ok: true, json: async () => ({ audio_url: "/audio/e.wav", duration_s: 1 }) };
  };
  const v = new Voice({ fetchImpl, AudioImpl: null });
  await v.prepare({ text: "Stay back.", voiceId: "v1", emotion: "angry" });
  assert.deepEqual(calls[0], { text: "Stay back.", voice_id: "v1", emotion: "angry" });
  // same line, no emotion: a separate render, and the field stays off the wire
  await v.prepare({ text: "Stay back.", voiceId: "v1" });
  assert.equal(calls.length, 2);
  assert.equal("emotion" in calls[1], false);
});

test("cloud audio passthrough: an audio/* response becomes a playable object URL", async () => {
  // when nginx retargets /voice at the orchestrator (cloud provider, keys
  // server-side), the response is raw audio bytes, not { audio_url }
  const fetchImpl = async () => ({
    ok: true,
    headers: { get: (k) => (k.toLowerCase() === "content-type" ? "audio/wav" : null) },
    blob: async () => ({ size: 4, type: "audio/wav" }),
  });
  const hadCreate = typeof URL.createObjectURL === "function";
  const orig = URL.createObjectURL;
  URL.createObjectURL = () => "blob:cloud-line-1";
  try {
    const v = new Voice({ fetchImpl });
    const got = await v.prepare({ text: "Hush now.", voiceId: "v-cloud" });
    assert.deepEqual(got, { audioUrl: "blob:cloud-line-1", duration: null });
    // and it caches like the url shape does
    const again = await v.prepare({ text: "Hush now.", voiceId: "v-cloud" });
    assert.equal(again.audioUrl, "blob:cloud-line-1");
  } finally {
    if (hadCreate) URL.createObjectURL = orig;
    else delete URL.createObjectURL;
  }
});

test("the local { audio_url } shape is untouched by the bytes branch", async () => {
  const fetchImpl = async () => ({
    ok: true,
    headers: { get: (k) => (k.toLowerCase() === "content-type" ? "application/json" : null) },
    json: async () => ({ audio_url: "/audio/x.wav", duration_s: 2.5 }),
  });
  const v = new Voice({ fetchImpl });
  const got = await v.prepare({ text: "hi", voiceId: "v1" });
  assert.deepEqual(got, { audioUrl: "/audio/x.wav", duration: 2.5 });
});
