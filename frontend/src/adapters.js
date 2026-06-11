// Map raw orchestrator payloads into a clean view model the renderer consumes.
//
// v0.2 is scene-centric (docs/frontend-api.md s3, scene-and-interaction-model.md):
//  - state.scene: { name, description, status, image_url, exits<=3, items<=6,
//    available_actions<=3 }.
//  - state.current_goal, state.status (story FSM), state.scene_status.
//  - characters carry description, disposition, life/max_life, alive, following,
//    face_url/body_url, inventory<=3, available_actions<=3.
//  - All caps are MAXIMUMS the backend enforces; we slice defensively anyway.
//
// Correctness points carried over from v0.1:
//  - narration voice == state.narrator_voice_id (NOT a hardcoded "narrator").
//  - each character's voice == character.voice_id.
//  - media URLs are RELATIVE; preserve them verbatim for the same-origin proxy.
//  - beats are keyed off `kind` (narration | dialogue | action | system).

const PALETTE = ["#45d2b1", "#f2b84b", "#d95f7b", "#91c96b", "#a98bff", "#e05d39"];

const SCENE_ITEM_SLOTS = 6;
const CHAR_ITEM_SLOTS = 3;
const ACTION_SLOTS = 3;
const PLAYER_INV_SLOTS = 6;
// NOTE: exits are NOT capped here. The backend sends up to 3 narrator exits PLUS
// an automatic "back to X" return exit, so a scene can legitimately have 4.
// scene-and-interaction-model.md s3: "render whatever exits are in scene.exits".

export function mapGameState(state = {}) {
  const characters = (state.characters || []).map((c, i) => ({
    id: c.id,
    name: c.name || "Unknown",
    description: c.description || "",
    voiceId: c.voice_id || null,
    color: c.color || PALETTE[i % PALETTE.length],
    present: Boolean(c.present),
    location: c.location || null,
    life: numOrNull(c.life),
    maxLife: numOrNull(c.max_life) ?? numOrNull(c.life),
    alive: c.alive !== false,
    // ''|'female'|'male' - the single stored truth (portrait, pronouns and
    // voice all follow it)
    gender: c.gender || "",
    // what they ARE to the player, free 1-2 words ('' until defined);
    // humanize backend snake_case ("mystic_stranger" -> "mystic stranger")
    relation: String(c.relation || "").replace(/_/g, " "),
    disposition: c.disposition || "unknown",
    following: Boolean(c.following),
    // each character is its own agent context on the shared model; 0 until
    // they first speak. Rendered as a small meter on the card / profile.
    context: mapContext(c.context),
    // personality traits unlocked through play (the full set + moments +
    // memories live on the profile endpoint)
    traits: (c.traits || []).map((t) => ({ id: t.id || null, text: t.text || "", unlocked: t.unlocked || "" })),
    faceUrl: c.face_url || null,
    bodyUrl: c.body_url || c.body_front_url || null,
    bodyFrontUrl: c.body_front_url || null,
    bodySideUrl: c.body_side_url || null,
    inventory: (c.inventory || []).slice(0, CHAR_ITEM_SLOTS).map(mapItem),
    actions: (c.available_actions || []).slice(0, ACTION_SLOTS).map(mapAction),
  }));

  const player = state.player || {};
  return {
    gameId: state.game_id || null,
    title: state.title || "Untitled Adventure",
    status: state.status || "active", // story FSM: active | won | lost
    sceneStatus: state.scene_status || (state.scene && state.scene.status) || null,
    currentGoal: state.current_goal || "",
    narratorVoiceId: state.narrator_voice_id || null,
    // live game settings (PATCH /games/{id}/settings)
    settings: {
      difficulty: (state.settings && state.settings.difficulty) || "normal",
      narratorGender: (state.settings && state.settings.narrator_gender) || "",
      // story memory: verbatim window depth, recap cadence, hard context cap
      historyBeats: num(state.settings && state.settings.history_beats),
      summaryEvery: num(state.settings && state.settings.summary_every),
      contextTokens: num(state.settings && state.settings.context_tokens),
      // turn pacing: voices the narrator may pull into ONE turn, acts each may
      // take before it ends (effective values; 0 was "server default" on send)
      turnVoices: num(state.settings && state.settings.turn_voices),
      turnActs: num(state.settings && state.settings.turn_acts),
    },
    // prompt-token usage -> the header context meter (green -> amber -> red)
    context: mapContext(state.context),
    // true + null image_url = art still generating (loader); false = images off (static placeholder)
    imagesEnabled: Boolean(state.images_enabled),
    // fictional story clock; render `label` in the header
    time: mapTime(state.time),
    scene: mapScene(state.scene),
    player: {
      life: num(player.life),
      maxLife: num(player.max_life, num(player.life)),
      points: num(player.points),
      location: player.location || null,
      inventory: (player.inventory || []).slice(0, PLAYER_INV_SLOTS).map((it) => ({
        id: it.id || null, // inventory items carry ids now (preferred for give/refs)
        name: it.name || "Item",
        description: it.description || "",
        imageUrl: it.image_url || null,
        qty: num(it.qty, 1),
      })),
      flags: player.flags || {},
    },
    quests: (state.quests || []).map((q) => ({
      id: q.id,
      title: q.title || "Quest",
      description: q.description || "",
      status: q.status || "active",
      objectives: (q.objectives || []).map((o) => ({
        id: o.id,
        text: o.text || "",
        done: Boolean(o.done),
        progress: o.progress || null,
      })),
    })),
    characters,
  };
}

// The scene is a first-class object now. Null when the backend has not sent one
// (older shape / not yet built) so the renderer can fall back gracefully.
function mapScene(scene) {
  if (!scene || typeof scene !== "object") return null;
  return {
    id: scene.id || null,
    name: scene.name || "",
    description: scene.description || "",
    // the place's deeper story, narrator-written over time ('' until it is)
    background: scene.background || "",
    status: scene.status || "calm", // calm | tense | dangerous
    imageUrl: scene.image_url || null,
    // render ALL exits (narrator exits + the auto "back to X"); flag the return one
    exits: (scene.exits || []).map((e) => ({
      id: e.id || null,
      label: e.label || "",
      target: e.target || null,
      isBack: /^back\b|^back to /i.test(e.label || ""),
    })),
    items: (scene.items || []).slice(0, SCENE_ITEM_SLOTS).map(mapItem),
    actions: (scene.available_actions || []).slice(0, ACTION_SLOTS).map(mapAction),
  };
}

// { used, max } prompt-token usage, plus the precomputed ratio for the meter.
// Null when the backend does not send it (hide the meter).
function mapContext(ctx) {
  if (!ctx || typeof ctx !== "object") return null;
  const used = num(ctx.used);
  const max = num(ctx.max);
  return { used, max, ratio: max > 0 ? Math.min(1, used / max) : 0 };
}

// Fictional story clock. `label` is what the header shows ("Day 1, morning").
function mapTime(t) {
  if (!t || typeof t !== "object" || !t.label) return null;
  return {
    label: String(t.label),
    day: num(t.day, 1),
    hour: num(t.hour),
    part: t.part || "",
    minutes: num(t.minutes),
  };
}

function mapItem(it = {}) {
  return {
    id: it.id || null,
    name: it.name || "Item",
    description: it.description || "",
    imageUrl: it.image_url || null,
    // scene items only: true = scenery (cannot be taken), false/absent = loose loot
    fixed: Boolean(it.fixed),
  };
}

function mapAction(a = {}) {
  return { id: a.id || null, label: a.label || "", type: a.type || "do" };
}

export function mapBeat(beat = {}) {
  return {
    id: beat.id,
    turnIndex: num(beat.turn_index),
    seq: num(beat.seq),
    // narration|dialogue|action|system; default to narration defensively.
    kind: beat.kind || "narration",
    speaker: beat.speaker || "narrator",
    speakerName: beat.speaker_name || null,
    text: beat.text || "",
    // voice acting: '' | 'angry' | 'whisper' | 'sad' | ... - rides /voice/speak
    emotion: beat.emotion || "",
    location: beat.location || null,
    imageUrl: beat.image_url || null,
    audioUrl: beat.audio_url || null,
    // non-null character id => private 1:1 beat; render in the whisper view, not
    // the public story stream (frontend-api.md s3).
    privateWith: beat.private_with || null,
  };
}

export function mapBeats(beats = []) {
  return beats.map(mapBeat);
}

// Resolve the TTS voice id for a beat against the mapped state.
// narration -> narrator_voice_id; dialogue -> that character's voice_id; else null.
export function voiceForBeat(beat, mappedState) {
  if (!beat || !mappedState) return null;
  if (beat.kind === "narration") return mappedState.narratorVoiceId || null;
  if (beat.kind === "dialogue") {
    const ch = (mappedState.characters || []).find((c) => c.id === beat.speaker);
    return (ch && ch.voiceId) || null;
  }
  return null; // action / system are silent
}

// Mirror of the backend's norm_name (underscore/space collapse): the ONE
// location-equality rule, shared by the story's scene anchor, the presence
// checks and the whisper guard (strict equality drifted between them before).
export function sameLocation(a, b) {
  const norm = (v) => String(v || "").toLowerCase().replace(/[_\s]+/g, " ").trim();
  return norm(a) === norm(b);
}

// Characters whose card appears this scene: present, co-located with the player,
// and alive. The scene shows up to 3 (the backend cap).
export function presentCharacters(mappedState) {
  if (!mappedState) return [];
  const here = mappedState.player.location;
  return (mappedState.characters || [])
    .filter((c) => c.present && c.alive && (!here || sameLocation(c.location, here)))
    .slice(0, 3);
}

// The full-screen character profile (GET /games/{id}/characters/{cid}/profile):
// public card data + traits unlocked through play + the moments shared with the
// player (private exchanges marked) + story images as memories. Spoiler-safe by
// construction; media URLs stay relative.
export function mapProfile(p = {}) {
  return {
    id: p.id,
    name: p.name || "Unknown",
    description: p.description || "",
    gender: p.gender || "",
    relation: String(p.relation || "").replace(/_/g, " "),
    disposition: p.disposition || "unknown",
    following: Boolean(p.following),
    alive: p.alive !== false,
    life: numOrNull(p.life),
    maxLife: numOrNull(p.max_life) ?? numOrNull(p.life),
    faceUrl: p.face_url || null,
    bodyUrl: p.body_url || null,
    voiceId: p.voice_id || null,
    color: p.color || PALETTE[0],
    carrying: (p.carrying || []).map(mapItem),
    traits: (p.traits || []).map((t) => ({ id: t.id || null, text: t.text || "", unlocked: t.unlocked || "" })),
    // the pieces of their PAST the player has LEARNED so far (the full
    // backstory is server-private; empty = nothing learned yet)
    origin: (p.origin || []).map((o) => ({ id: o.id || null, text: o.text || "", learned: o.learned || "" })),
    // CURATED PIVOTAL EVENTS (bonds, wounds, gifts, partings), each with a
    // story-clock `when` - a timeline, never chat transcript
    moments: (p.moments || []).map((m) => ({ id: m.id || null, text: m.text || "", when: m.when || "" })),
    memories: (p.memories || []).map((m) => ({
      imageUrl: m.image_url || null,
      caption: m.caption || "",
      turnIndex: num(m.turn_index),
    })),
  };
}

function num(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function numOrNull(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}
