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
