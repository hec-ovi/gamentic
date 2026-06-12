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
    // clicking the busy beat again stops it
    voice.stop();
    setSpeaking(null);
    return;
  }
  setSpeaking({ beatId, phase: "loading" });
  // g.id rides as game_id so the voice-api manifest knows this game claims the
  // wav (ownership deletion: delete the adventure, its audio dies with it)
  const prepared = await voice.prepare({ text: beat.text, voiceId: beat.voiceId, emotion: beat.emotion, gameId: g.id });
  if (!speaking || speaking.beatId !== beatId) return; // stopped or superseded meanwhile
  if (!prepared) return setSpeaking(null); // synth failed; the text is on screen
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

// Patch the speak buttons in place (no full render: never disturb reading or a
// running typewriter). render() re-applies it after every rebuild.
export function applySpeakStates() {
  root.querySelectorAll('[data-act="speak-beat"]').forEach((btn) => {
    const mine = speaking && btn.dataset.beatId === speaking.beatId;
    const loading = Boolean(mine && speaking.phase === "loading");
    const playing = Boolean(mine && speaking.phase === "playing");
    btn.classList.toggle("speak-loading", loading);
    btn.classList.toggle("speak-playing", playing);
    const label = loading ? "Preparing voice..." : playing ? "Stop voice" : "Play voice";
    btn.setAttribute("aria-label", label);
    btn.setAttribute("title", label);
  });
}
