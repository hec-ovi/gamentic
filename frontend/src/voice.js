// Real TTS playback (Maya1 stack).
//
// Playback uses `POST /voice/speak { text, voice_id }` -> { audio_url, duration_s }
// -> <audio>. NOT /voice/stream: verified in play, streamed WAV through an
// <audio> element cuts off mid-line (the stream's placeholder-size WAV header
// makes the element stop early). The render wait (~1.1x realtime) is masked by
// PIPELINING at the call site: prepare() beat N+1's audio while N plays, and
// the staged story reveal shows a speech beat when ITS audio is ready.
//
// Rules (voice-requirements.md + frontend-api.md s5):
//  - voice_id null/empty  -> SKIP entirely (the server 400s on empty voice_id).
//  - voice_id is OPAQUE: may be a long free-form description string; pass it
//    through verbatim, never display it (the UI labels by character name).
//  - disabled             -> do nothing (text already on screen).
//  - fetch/play error      -> swallow; never block the game on audio.
//  - volume               -> master * per-speaker (0..1).
//  - stop()               -> halts current playback.
//  - ONE GPU serves one generation: synthesis requests go through a strict
//    FIFO queue, never in parallel. Identical requests hit the server cache
//    (stable audio_url) and our local cache.

export class Voice {
  constructor({ fetchImpl, AudioImpl } = {}) {
    // Injectable for tests; default to the browser globals.
    this._fetch = fetchImpl || ((...a) => fetch(...a));
    this._Audio = AudioImpl || (typeof Audio !== "undefined" ? Audio : null);
    this.enabled = true;
    this.masterVolume = 0.7;
    this.speakerVolumes = {}; // { [speakerId]: 0..1 }
    this._audio = null;
    // Cache (text|voice) -> { audioUrl, duration } so replays don't re-synthesize.
    this._cache = new Map();
    // FIFO synthesis queue: the next render starts only when the previous done.
    this._queue = Promise.resolve();
  }

  applySettings(settings = {}) {
    if ("voiceEnabled" in settings) this.enabled = settings.voiceEnabled !== false;
    if ("masterVolume" in settings) this.masterVolume = clamp01(settings.masterVolume);
    if (settings.speakerVolumes) this.speakerVolumes = { ...settings.speakerVolumes };
  }

  volumeFor(speakerId) {
    const per = speakerId in this.speakerVolumes ? clamp01(this.speakerVolumes[speakerId]) : 1;
    return clamp01(this.masterVolume * per);
  }

  // Synthesize WITHOUT playing: returns { audioUrl, duration } or null.
  // Queued FIFO (one generation at a time); cached per (voice, text). This is
  // the pipelining primitive: call it for beat N+1 while beat N plays.
  prepare({ text, voiceId } = {}) {
    if (!this.enabled) return Promise.resolve(null);
    const clean = cleanText(text);
    if (!clean || !voiceId) return Promise.resolve(null);

    const key = `${voiceId} ${clean}`;
    const hit = this._cache.get(key);
    if (hit) return Promise.resolve(hit);

    const job = this._queue.then(async () => {
      const again = this._cache.get(key); // a queued duplicate may have landed
      if (again) return again;
      try {
        const res = await this._fetch("/voice/speak", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ text: clean, voice_id: voiceId }),
        });
        if (!res || !res.ok) return null;
        const data = await res.json();
        if (!data || !data.audio_url) return null;
        const entry = { audioUrl: data.audio_url, duration: Number(data.duration_s) || null };
        this._cache.set(key, entry);
        return entry;
      } catch {
        return null; // synthesis failed; text stays on screen
      }
    });
    this._queue = job.catch(() => {}); // the queue itself never rejects
    return job;
  }

  // Play an already-rendered audio_url. Returns the element (or null headless).
  playUrl(audioUrl, speakerId) {
    if (!this.enabled || !audioUrl || !this._Audio) return null;
    this.stop();
    try {
      const el = new this._Audio(audioUrl);
      el.volume = this.volumeFor(speakerId);
      this._audio = el;
      const p = el.play();
      if (p && typeof p.catch === "function") p.catch(() => {});
      return el;
    } catch {
      return null; // autoplay blocked or element error; ignore
    }
  }

  // Synthesize + play a single beat (the per-beat play button). Returns the
  // audio_url that was played, or null if skipped (disabled / no voice / error).
  async speak({ text, voiceId, speakerId } = {}) {
    const prepared = await this.prepare({ text, voiceId });
    if (!prepared) return null;
    if (!this._Audio) return prepared.audioUrl; // headless: report intent
    this.playUrl(prepared.audioUrl, speakerId);
    return prepared.audioUrl;
  }

  stop() {
    if (this._audio) {
      try {
        this._audio.pause();
        this._audio.currentTime = 0;
      } catch {
        /* ignore */
      }
      this._audio = null;
    }
  }
}

// Strip light markdown / stray emphasis so we send clean speakable text.
export function cleanText(value) {
  return String(value ?? "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/\*(.*?)\*/g, "$1")
    .replace(/`(.*?)`/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

function clamp01(n) {
  const v = Number(n);
  if (Number.isNaN(v)) return 1;
  return Math.max(0, Math.min(1, v));
}
