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
//  - gameId (optional)    -> rides as "game_id": ties the rendered wav to its
//    adventure in the voice-api ownership manifest, so deleting the adventure
//    deletes its wavs (ownership deletion, no retention timers - owner
//    decision 2026-06-11). Outside a game there is no owner: field omitted.
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
    // Generation token: flush() bumps it so queued-but-unstarted jobs from an
    // abandoned game resolve null instead of occupying the single GPU.
    this._gen = 0;
    // Keys whose synthesis is queued or running right now (for the per-beat
    // voice-icon status: idle -> generating -> ready). One GPU, FIFO, so several
    // beats can be "generating" (waiting) while only one actually synthesizes.
    this._inflight = new Set();
    // Optional callback fired whenever a key's status changes (queued, done),
    // so the UI can repaint the speak icons without a full render.
    this.onStatus = null;
  }

  // The cache/inflight key for a request (null when nothing to synthesize).
  // MUST match the key prepare() builds, so status() and the cache agree.
  _statusKey({ text, voiceId, emotion, gameId } = {}) {
    const clean = cleanText(text);
    if (!clean || !voiceId || !this.enabled) return null;
    return `${gameId || ""}|${voiceId}|${emotion || ""} ${clean}`;
  }

  // Per-beat voice status for the icon: "ready" (audio cached, plays instantly),
  // "generating" (queued or synthesizing now), or "idle" (not made yet). "none"
  // when the line can't be voiced at all (no voice id / disabled).
  status(req) {
    const key = this._statusKey(req);
    if (!key) return "none";
    if (this._cache.has(key)) return "ready";
    if (this._inflight.has(key)) return "generating";
    return "idle";
  }

  _emitStatus() {
    if (typeof this.onStatus === "function") {
      try {
        this.onStatus();
      } catch {
        /* a repaint failure must never break synthesis */
      }
    }
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
  prepare({ text, voiceId, emotion, gameId } = {}) {
    if (!this.enabled) return Promise.resolve(null);
    const clean = cleanText(text);
    if (!clean || !voiceId) return Promise.resolve(null);

    // gameId is part of the cache key ON PURPOSE: the voice-api only learns
    // that a game claims a wav when that game's id rides a request. A
    // cross-game local-cache hit would skip the POST, the manifest would list
    // only the first game, and deleting that game would take a wav this one
    // still replays. The extra POST per game is cheap: the server cache
    // returns the same stable audio_url.
    const key = `${gameId || ""}|${voiceId}|${emotion || ""} ${clean}`;
    const hit = this._cache.get(key);
    if (hit) return Promise.resolve(hit);

    // mark it in-flight NOW (queued counts as generating: the icon spins until the
    // audio lands, even while it waits its turn behind the single GPU)
    const wasIdle = !this._inflight.has(key);
    this._inflight.add(key);
    if (wasIdle) this._emitStatus();

    const gen = this._gen;
    const settle = () => {
      this._inflight.delete(key);
      this._emitStatus();
    };
    const job = this._queue.then(async () => {
      if (gen !== this._gen) {
        settle();
        return null; // flushed while queued (game switch)
      }
      const again = this._cache.get(key); // a queued duplicate may have landed
      if (again) {
        settle();
        return again;
      }
      try {
        const res = await this._fetch("/voice/speak", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          // game_id ties the wav to its adventure in the voice-api manifest
          // (delete the adventure, the wav dies with it); no active game, no
          // owner, no field. The cloud-bytes path POSTs this same body - the
          // response branch below only changes how the AUDIO comes back.
          body: JSON.stringify({
            text: clean,
            voice_id: voiceId,
            ...(emotion ? { emotion } : {}),
            ...(gameId ? { game_id: gameId } : {}),
          }),
        });
        if (!res || !res.ok) return null;
        // Cloud audio passthrough (frontend-api.md): when the nginx /voice
        // proxy is retargeted at the orchestrator (a cloud provider holds the
        // keys server-side), the response is the AUDIO BYTES themselves, not
        // { audio_url }. Branch on content-type; the local shape is unchanged.
        const type = String((res.headers && res.headers.get && res.headers.get("content-type")) || "");
        let entry = null;
        if (type.startsWith("audio/")) {
          if (typeof URL === "undefined" || !URL.createObjectURL || typeof res.blob !== "function") return null;
          entry = { audioUrl: URL.createObjectURL(await res.blob()), duration: null };
        } else {
          const data = await res.json();
          if (!data || !data.audio_url) return null;
          entry = { audioUrl: data.audio_url, duration: Number(data.duration_s) || null };
        }
        this._cache.set(key, entry);
        return entry;
      } catch {
        return null; // synthesis failed; text stays on screen
      } finally {
        settle(); // ready (cache set) or idle (failed) - either way, stop spinning
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
  async speak({ text, voiceId, speakerId, emotion, gameId } = {}) {
    const prepared = await this.prepare({ text, voiceId, emotion, gameId });
    if (!prepared) return null;
    if (!this._Audio) return prepared.audioUrl; // headless: report intent
    this.playUrl(prepared.audioUrl, speakerId);
    return prepared.audioUrl;
  }

  // Abandon every queued-but-unstarted synthesis job (a left game's lines must
  // not delay the next game's first voiced beat). The cache survives.
  flush() {
    this._gen += 1;
    this._queue = Promise.resolve();
    // queued-but-unstarted jobs are abandoned; their beats are no longer
    // generating (a running job clears its own key in its finally).
    if (this._inflight.size) {
      this._inflight.clear();
      this._emitStatus();
    }
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
