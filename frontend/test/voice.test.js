import { test } from "vitest";
import assert from "node:assert/strict";
import { Voice, cleanText, parseWavHeader } from "../src/voice.js";

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
// streaming path (Maya1): /voice/stream WAV chunks -> AudioContext scheduling
// ---------------------------------------------------------------------------

// Minimal valid 16-bit PCM WAV bytes.
function wavBytes(samples, { rate = 24000, channels = 1 } = {}) {
  const dataLen = samples.length * 2;
  const buf = new ArrayBuffer(44 + dataLen);
  const v = new DataView(buf);
  const w = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  w(0, "RIFF"); v.setUint32(4, 36 + dataLen, true); w(8, "WAVE");
  w(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, channels, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * channels * 2, true);
  v.setUint16(32, channels * 2, true); v.setUint16(34, 16, true);
  w(36, "data"); v.setUint32(40, dataLen, true);
  samples.forEach((s, i) => v.setInt16(44 + i * 2, s, true));
  return new Uint8Array(buf);
}

function makeAudioContextImpl() {
  class FakeGain {
    constructor() { this.gain = { value: 1 }; }
    connect() {}
    disconnect() { this.disconnected = true; }
  }
  class FakeSource {
    constructor(ctx) { this.ctx = ctx; }
    connect() {}
    start(at) { this.startedAt = at; this.ctx.started.push(this); }
    stop() { this.stopped = true; }
  }
  class FakeCtx {
    constructor() {
      this.currentTime = 0;
      this.state = "running";
      this.started = [];
      this.destination = {};
      FakeCtx.instances.push(this);
    }
    createGain() { this.lastGain = new FakeGain(); return this.lastGain; }
    createBuffer(channels, frames, rate) {
      return {
        duration: frames / rate,
        _ch: Array.from({ length: channels }, () => new Float32Array(frames)),
        getChannelData(i) { return this._ch[i]; },
      };
    }
    createBufferSource() { return new FakeSource(this); }
  }
  FakeCtx.instances = [];
  return FakeCtx;
}

// fetch returning a streaming body that yields `chunks` in order.
function makeStreamFetch(chunks, { ok = true } = {}) {
  const calls = [];
  const fn = async (url, opts) => {
    calls.push({ url, opts, body: opts && opts.body ? JSON.parse(opts.body) : null });
    let i = 0;
    return {
      ok,
      json: async () => ({ audio_url: "/audio/fallback.wav" }),
      body: {
        getReader: () => ({
          read: async () => (i < chunks.length ? { done: false, value: chunks[i++] } : { done: true, value: undefined }),
          cancel: async () => {},
        }),
      },
    };
  };
  fn.calls = calls;
  return fn;
}

test("speak() prefers /voice/stream when an AudioContext exists, scheduling PCM as it arrives", async () => {
  const wav = wavBytes(Array.from({ length: 4800 }, (_, i) => (i % 2 ? 8000 : -8000)));
  // split mid-header and mid-data to prove chunk reassembly works
  const chunks = [wav.subarray(0, 30), wav.subarray(30, 2000), wav.subarray(2000)];
  const fetchImpl = makeStreamFetch(chunks);
  const AudioContextImpl = makeAudioContextImpl();
  const v = new Voice({ fetchImpl, AudioContextImpl, AudioImpl: null });
  v.applySettings({ masterVolume: 0.5 });

  const result = await v.speak({ text: "stream me", voiceId: "a long free-form maya1 description", speakerId: "c1" });

  assert.equal(result, "/voice/stream");
  assert.equal(fetchImpl.calls.length, 1);
  assert.equal(fetchImpl.calls[0].url, "/voice/stream");
  assert.deepEqual(fetchImpl.calls[0].body, { text: "stream me", voice_id: "a long free-form maya1 description" });
  const ctx = AudioContextImpl.instances[0];
  assert.ok(ctx.started.length >= 1, "PCM chunks were scheduled");
  assert.ok(Math.abs(ctx.lastGain.gain.value - 0.5) < 1e-9, "volume applied via the gain node");
});

test("speak() falls back to /voice/speak when the stream endpoint fails", async () => {
  const calls = [];
  const fetchImpl = async (url, opts) => {
    calls.push(url);
    if (url === "/voice/stream") return { ok: false };
    return { ok: true, json: async () => ({ audio_url: "/audio/legacy.wav" }) };
  };
  const v = new Voice({ fetchImpl, AudioContextImpl: makeAudioContextImpl(), AudioImpl: makeAudio() });
  const result = await v.speak({ text: "hi", voiceId: "vx" });
  assert.deepEqual(calls, ["/voice/stream", "/voice/speak"]);
  assert.equal(result, "/audio/legacy.wav");
});

test("stop() halts the scheduled stream sources", async () => {
  const wav = wavBytes(Array.from({ length: 2400 }, () => 1000));
  const fetchImpl = makeStreamFetch([wav]);
  const AudioContextImpl = makeAudioContextImpl();
  const v = new Voice({ fetchImpl, AudioContextImpl, AudioImpl: null });
  await v.speak({ text: "line", voiceId: "vx" });
  v.stop();
  const ctx = AudioContextImpl.instances[0];
  assert.ok(ctx.started.length >= 1);
  assert.ok(ctx.started.every((s) => s.stopped), "all scheduled sources stopped");
});

test("parseWavHeader: valid header parses; truncated needs more; non-WAV is bad", () => {
  const wav = wavBytes([0, 0, 0, 0]);
  const parsed = parseWavHeader(wav);
  assert.deepEqual(parsed, { ok: true, channels: 1, sampleRate: 24000, dataOffset: 44 });
  assert.equal(parseWavHeader(wav.subarray(0, 20)), null, "incomplete header asks for more bytes");
  assert.deepEqual(parseWavHeader(new TextEncoder().encode("HTTP/1.1 502 oops...")), { bad: true });
});
