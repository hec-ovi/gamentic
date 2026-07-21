// Per-beat voice: resolving a beat's voice id and the speak-button state
// machine (idle -> loading -> playing -> idle).

import { voiceForBeat } from "../adapters.js";
import { root, state, voice } from "./ctx.js";
import { render } from "./ui.js";

// the per-beat speak button state: { beatId, phase: "loading" | "playing" }
export let speaking = null;

// ---------------------------------------------------------------------------
// voice
// ---------------------------------------------------------------------------

export function withVoice(beat) {
  return { ...beat, voiceId: voiceForBeat(beat, state.active && state.active.state) };
}

// The per-beat speak button is a little state machine: click -> LOADING while
// the line synthesizes, PLAYING while the audio runs (click again to stop),
// then back to the plain speaker when it finishes.
export async function speakBeat(beatId) {
  const g = state.active;
  const beat = g && g.beats.find((b) => b.id === beatId);
  if (!beat) return;
  if (speaking && speaking.beatId === beatId) {
    // clicking the busy beat again stops it - and empties the autoplay queue
    // too (an explicit stop means silence, not "the next line starts")
    voice.stopAll();
    setSpeaking(null);
    return;
  }
  setSpeaking({ beatId, phase: "loading" });
  // g.id rides as game_id so the voice-api manifest knows this game claims the
  // wav (ownership deletion: delete the adventure, its audio dies with it)
  const prepared = await voice.prepare({ text: beat.text, voiceId: beat.voiceId, emotion: beat.emotion, gameId: g.id });
  if (!speaking || speaking.beatId !== beatId) return; // stopped or superseded meanwhile
  if (!prepared) return setSpeaking(null); // synth failed; the text is on screen
  voice.stopAll(); // an explicit play takes the channel: queued autoplay lines drop
  const el = voice.playUrl(prepared.audioUrl, beat.speaker);
  if (!el) return setSpeaking(null);
  setSpeaking({ beatId, phase: "playing" });
  const done = () => {
    if (speaking && speaking.beatId === beatId) setSpeaking(null);
  };
  el.addEventListener("ended", done);
  el.addEventListener("pause", done); // stop() pauses
  el.addEventListener("error", done);
}

export function setSpeaking(next) {
  speaking = next;
  applySpeakStates();
}

// The speak icon reflects the beat's VOICE state, so autoplay (which prepares
// audio in the background and now also PLAYS through the queue) shows the
// same lifecycle a click does. Four looks on the speaker glyph:
//   idle       - not synthesized yet (dim) -> click to voice it
//   generating - queued or synthesizing now (red + a ring spinning around it)
//   ready      - audio cached, plays instantly; already-played lines rest
//                here too (green)
//   playing    - audio is out loud right now (yellow, pulsing scale)
// The click state (speaking) wins while it is set; otherwise the voice cache /
// in-flight queue / live playback decide. voice.onStatus repaints these as
// prepares land and as playback starts and ends.
const SPEAK_LABEL = {
  generating: "Preparing voice...",
  ready: "Play voice (ready)",
  playing: "Stop voice",
  idle: "Play voice",
};

function speakState(g, id) {
  const mine = speaking && id === speaking.beatId;
  if (mine && speaking.phase === "playing") return "playing";
  if (mine && speaking.phase === "loading") return "generating";
  const beat = g && g.beats.find((b) => b.id === id);
  if (!beat) return "idle";
  const vs = voice.status({ text: beat.text, voiceId: beat.voiceId, emotion: beat.emotion, gameId: g.id });
  return vs === "generating" || vs === "ready" || vs === "playing" ? vs : "idle";
}

// Patch the speak buttons in place (no full render: never disturb reading or a
// running typewriter). render() re-applies it after every rebuild.
export function applySpeakStates() {
  const g = state.active;
  root.querySelectorAll('[data-act="speak-beat"]').forEach((btn) => {
    const s = speakState(g, btn.dataset.beatId);
    btn.classList.toggle("speak-generating", s === "generating");
    btn.classList.toggle("speak-ready", s === "ready");
    btn.classList.toggle("speak-loading", s === "generating"); // legacy alias
    btn.classList.toggle("speak-playing", s === "playing");
    btn.setAttribute("aria-label", SPEAK_LABEL[s]);
    btn.setAttribute("title", SPEAK_LABEL[s]);
  });
}

// Background prepares (autoplay pipelining) flip a beat idle -> generating ->
// ready without a render; repaint the icons when that happens.
voice.onStatus = applySpeakStates;
