// Settings controllers: FE-local audio settings and the per-game PATCH.

import { api, saveSettings, setApi, state, voice } from "./ctx.js";
import { showToast } from "./cues.js";
import { render } from "./ui.js";

export function updateSetting(el) {
  const key = el.dataset.setting;
  let value = el.value;
  if (el.type === "checkbox") value = el.checked;
  if (el.type === "range") value = Number(el.value);
  state.settings[key] = value;
  if (key === "backendUrl") setApi(value);
  if (key === "voiceEnabled" && !value) voice.stop();
  voice.applySettings(state.settings);
  saveSettings();
  if (el.type !== "range") render();
}

// (the old synchronous "See" eye-flow is gone: LOOK is a first-class action
// segment now, and its image arrives async as a late image beat)

// ---------------------------------------------------------------------------
// game settings (PATCH /games/{id}/settings) + export / import
// ---------------------------------------------------------------------------

// Keys whose wire value is an integer (selects deliver strings; 0 = default).
export const NUMERIC_GAME_SETTINGS = new Set(["turn_voices", "turn_acts"]);

export async function patchGameSettings(key, value) {
  const g = state.active;
  if (!g || !g.state || g.settingsSaving) return;
  if (NUMERIC_GAME_SETTINGS.has(key)) value = Number(value) || 0;
  g.settingsSaving = true;
  render();
  try {
    const res = await api.patchSettings(g.id, { [key]: value });
    if (res && res.settings) {
      g.state.settings = {
        difficulty: res.settings.difficulty || "normal",
        narratorGender: res.settings.narrator_gender || "",
        historyBeats: Number(res.settings.history_beats) || 0,
        summaryEvery: Number(res.settings.summary_every) || 0,
        contextTokens: Number(res.settings.context_tokens) || 0,
        turnVoices: Number(res.settings.turn_voices) || 0,
        turnActs: Number(res.settings.turn_acts) || 0,
      };
    }
    // a narrator_gender change redesigns the narrator voice from the next line
    if (res && "narrator_voice_id" in res) g.state.narratorVoiceId = res.narrator_voice_id || null;
    state.backendOnline = true;
  } catch (err) {
    showToast(err.message || "Could not change that setting.");
  } finally {
    g.settingsSaving = false;
    render();
  }
}

// The story-memory numeric controls (history_beats / summary_every /
// context_tokens). 0 always means "back to the default"; anything else must
// sit inside the backend's range or it never leaves the client (the field
// just marks itself invalid).
export const MEMORY_RANGES = {
  history_beats: [8, 400],
  summary_every: [2, 50],
  context_tokens: [4000, 120000],
};

export function applyMemorySetting(el) {
  const key = el.dataset.memSetting;
  const range = MEMORY_RANGES[key];
  if (!range) return;
  const n = Number(el.value);
  const valid = Number.isFinite(n) && (n === 0 || (n >= range[0] && n <= range[1]));
  el.classList.toggle("invalid", !valid);
  if (!valid) return; // out of range: nothing is sent
  patchGameSettings(key, n);
}
