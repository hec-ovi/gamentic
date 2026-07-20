// The live turn feed: the backend mirrors the running turn over SSE (phase,
// live_beat, live_text, live_text_done, turn_done, turn_stopped) and this module
// applies it to the open game as it happens - beats appear the moment the engine
// stores them, prose and dialogue GROW at real generation speed, and a phase line
// says who is working. Everything here is provisional-by-design: the POST response
// (resolveTurn) and /beats?since= stay the reconciliation of record; a failed turn
// takes its live content back, a missed event is healed by the turn_done catch-up.
// Streamed text needs no typewriter (the model's own pace IS the pacing), so live
// beats never enter the staged-reveal queue.

import { mapBeat } from "../adapters.js";
import { state, voice } from "./ctx.js";
import { pullBeats, refreshArt } from "./mediastream.js";
import { autoplayFor, followStory } from "./reveal.js";
import { withVoice } from "./speech.js";
import { render } from "./ui.js";

const LIVE_PREFIX = "live:";

export function isLiveStream(beat) {
  return typeof beat.id === "string" && beat.id.startsWith(LIVE_PREFIX);
}

// One live event, decoded, for the active game. Returns true when handled.
export function applyLiveEvent(g, ev) {
  switch (ev.kind) {
    case "phase":
      g.livePhase = { phase: ev.phase, name: ev.name || null };
      liveRender(g);
      return true;
    case "live_text":
      applyLiveText(g, ev);
      return true;
    case "live_text_done":
      if (dropStream(g, LIVE_PREFIX + ev.sid)) liveRender(g);
      return true;
    case "live_beat":
      applyLiveBeat(g, ev.beat);
      return true;
    case "turn_stopped":
      g.livePhase = null;
      liveRender(g);
      return true;
    case "turn_done":
      finishLiveTurn(g);
      return true;
    default:
      return false;
  }
}

// A provisional text stream: one growing pseudo-beat per sid, rendered through
// the normal beat renderers (narration prose or a dialogue bubble; private_with
// routes it into the whisper thread exactly like the real beat will be).
function applyLiveText(g, ev) {
  const id = LIVE_PREFIX + ev.sid;
  let b = g.beats.find((x) => x.id === id);
  if (!b) {
    if (!ev.text) return;
    b = {
      id,
      turnIndex: null,
      seq: 0,
      kind: ev.beat_kind === "narration" ? "narration" : "dialogue",
      speaker: ev.speaker,
      speakerName: ev.name,
      text: "",
      location: null,
      imageUrl: null,
      audioUrl: null,
      privateWith: ev.private_with || null,
      voiceId: null,
      viaProfile: g.liveVia || null,
      live: true,
    };
    g.beats = [...g.beats, b];
  }
  if (ev.op === "replace") {
    if (!ev.text) {
      dropStream(g, id);
    } else {
      b.text = ev.text;
    }
  } else {
    b.text = (b.text || "") + ev.text;
  }
  liveRender(g);
}

// A real stored beat, announced the moment the engine emitted it. If a stream
// bubble for the same voice is on screen, the beat takes its exact place, so the
// swap is gapless; otherwise it appends. The POST response re-sends every beat
// and dedupes by id, so nothing here can double.
function applyLiveBeat(g, wire) {
  const b = withVoice(mapBeat(wire));
  if (g.beats.some((x) => x.id === b.id)) return;
  if (g.liveVia) b.viaProfile = g.liveVia;
  (g.liveTurnIds || (g.liveTurnIds = new Set())).add(b.id);
  // a canonical player echo arriving live replaces its optimistic twin NOW
  // (resolveTurn's pending sweep only runs when the POST lands - without this,
  // the player's line shows twice for the whole generation)
  if ((!b.speaker || b.speaker === "player") && b.kind === "action") {
    const twin = g.beats.findIndex((x) => x.pending && (x.privateWith || null) === (b.privateWith || null));
    if (twin >= 0) g.beats = [...g.beats.slice(0, twin), ...g.beats.slice(twin + 1)];
  }
  const match = g.beats.findIndex(
    (x) =>
      isLiveStream(x) &&
      x.speaker === b.speaker &&
      x.kind === b.kind &&
      (x.privateWith || null) === (b.privateWith || null),
  );
  if (match >= 0) {
    g.beats = [...g.beats.slice(0, match), b, ...g.beats.slice(match + 1)];
  } else {
    g.beats = [...g.beats, b];
  }
  queueLiveVoice(g, b);
  liveRender(g);
}

// The turn committed. Whatever provisional residue is left goes; if no POST of
// ours is in flight (another tab took this turn), catch up through the normal
// pull so lastTurnIndex and late media stay exact.
function finishLiveTurn(g) {
  g.livePhase = null;
  g.liveTurnIds = new Set();
  const before = g.beats.length;
  g.beats = g.beats.filter((b) => !isLiveStream(b));
  if (!g.generating) {
    pullBeats(g);
    refreshArt(g);
  }
  if (g.beats.length !== before) liveRender(g);
}

// A failed POST rolled the turn back server-side: its live content was never
// committed, so it leaves the screen too (resolveTurn calls this in its catch).
export function discardLiveTurn(g) {
  const ids = g.liveTurnIds || new Set();
  g.beats = g.beats.filter((b) => !isLiveStream(b) && !ids.has(b.id));
  g.liveTurnIds = new Set();
  g.livePhase = null;
}

// An SSE drop may have swallowed live_text_done events: stale stream bubbles
// would sit forever. The reconnect catch-up clears them; committed beats stay.
export function clearLiveStreams(g) {
  const before = g.beats.length;
  g.beats = g.beats.filter((b) => !isLiveStream(b));
  return g.beats.length !== before;
}

function dropStream(g, id) {
  const before = g.beats.length;
  g.beats = g.beats.filter((b) => b.id !== id);
  return g.beats.length !== before;
}

function liveRender(g) {
  if (state.active !== g || state.view !== "play") return;
  render();
  followStory();
}

// Voice autoplay for live beats: the staged reveal used to pace playback one
// beat at a time; live beats bypass it, so a minimal chain serializes the same
// prepare -> play order (synthesis needs the full line, which a live_beat has).
let voiceChain = Promise.resolve();

function queueLiveVoice(g, beat) {
  if (!(beat.kind === "narration" || beat.kind === "dialogue")) return;
  if (!beat.voiceId || !voice.enabled || !autoplayFor(beat)) return;
  const req = { text: beat.text, voiceId: beat.voiceId, emotion: beat.emotion, gameId: g.id };
  voiceChain = voiceChain
    .then(async () => {
      if (state.active !== g) return;
      const prepared = await voice.prepare(req);
      if (prepared && state.active === g) await voice.playUrl(prepared.audioUrl, beat.speaker);
    })
    .catch(() => {});
}
