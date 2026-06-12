// The turn loop: action/continue resolution, the optimistic player echo, the
// wish line, failure restore, and the post-turn late-image-beat watch.

import { mapBeats, mapGameState } from "../adapters.js";
import { diffState } from "../transitions.js";
import { api, root, state } from "./ctx.js";
import { applyTransitions, showToast } from "./cues.js";
import { pullBeats } from "./mediastream.js";
import { refreshProfile } from "./profilectl.js";
import { startReveal } from "./reveal.js";
import { withVoice } from "./speech.js";
import { focusComposer, render } from "./ui.js";

// ---------------------------------------------------------------------------
// take a turn
// ---------------------------------------------------------------------------

// Take a turn. `input` is either a plain string (freeform) or an array of tagged
// segments (what the composers build). One POST -> { beats, state }; only the
// state-mutating surfaces lock until the response lands (the partial busy-lock).
// `via` (a character id) marks a turn fired from that character's panel: its
// results mirror into the whisper thread, public or not.
export async function takeTurn(input, via = null) {
  const g = state.active;
  if (!g || g.generating) return;
  const empty = Array.isArray(input) ? !input.length : !String(input || "").trim();
  if (empty) return;
  const wish = captureWish(g);
  // a private study (whisper mode:"look") earns its guaranteed image too -
  // it just lands in the thread instead of the public story
  const look = Array.isArray(input) && input.some((s) => s.type === "look" || (s.type === "whisper" && s.mode === "look"));
  return resolveTurn(g, () => api.takeAction(g.id, input, wish), { look, echo: echoBeats(g, input, via), restore: input, wish, via });
}

// Optimistic echo: the player's own line shows the moment they send it (the
// backend's canonical echo replaces it when the turn resolves). The texts
// mirror the wire's echo phrasing so speech renders as speech immediately.
export let pendingSeq = 0;

export function echoBeats(g, input, via = null) {
  const mk = (text, privateWith = null) => ({
    id: `pending-${++pendingSeq}`,
    turnIndex: null,
    seq: 0,
    kind: "action",
    speaker: "player",
    speakerName: null,
    text,
    location: null,
    imageUrl: null,
    audioUrl: null,
    privateWith,
    voiceId: null,
    viaProfile: via,
    pending: true,
  });
  if (!Array.isArray(input)) return [mk(String(input))];
  const beats = [];
  for (const seg of input) {
    if (seg.type === "say") {
      beats.push(mk(`you say "${seg.text}"${seg.target ? ` to ${seg.target}` : ""}`));
    } else if (seg.type === "whisper") {
      // route into the open profile's private thread
      const pf = g.profile;
      const cid = pf && (pf.name === seg.target || pf.charId === seg.target) ? pf.charId : seg.target;
      beats.push(
        mk(
          seg.mode === "do"
            ? `you discreetly: ${seg.text}`
            : seg.mode === "look"
              ? `you quietly study ${seg.target}${seg.text ? ` - ${seg.text}` : ""}`
              : `you whisper to ${seg.target}: "${seg.text}"`,
          cid,
        ),
      );
    } else if (seg.type === "look") {
      beats.push(mk(seg.text ? `you look at ${seg.text}` : "you study the scene"));
    } else if (seg.type === "attack") {
      beats.push(mk(`you attack ${displayName(g, seg.target)}`));
    } else if (seg.type === "give") {
      beats.push(mk(`you offer ${itemName(g, seg.item)} to ${displayName(g, seg.target)}`));
    } else if (seg.text) {
      beats.push(mk(seg.text));
    }
  }
  return beats;
}

// The echoed line always shows NAMES, never raw ids (segments built from
// buttons carry ids; the wire prefers them, but the player must not read them).
function displayName(g, target) {
  const ch = ((g.state && g.state.characters) || []).find((c) => c.id === target);
  return (ch && ch.name) || target;
}

function itemName(g, item) {
  const inv = (g.state && g.state.player && g.state.player.inventory) || [];
  const it = inv.find((i) => i.id === item || i.name === item);
  return (it && it.name) || item;
}

// "Continue": the narrator advances the story with no player input. Same
// locking and reveal as /action; no player beat comes back.
export async function continueStory() {
  const g = state.active;
  if (!g || g.generating) return;
  const wish = captureWish(g);
  await resolveTurn(g, () => api.continueStory(g.id, wish), { wish });
}

// The wish is a hope whispered to the storyteller, never an action: it rides
// along on the next send (action or continue) and clears after each send.
export function captureWish(g) {
  const el = root.querySelector("#wishInput");
  const wish = String((el && el.value) || g.wish || "").trim();
  g.wish = "";
  if (el) el.value = "";
  return wish || null;
}

// Shared turn resolver (action / continue): one POST -> { beats, state },
// then the diff cues, the staged reveal, and the post-turn image watch. The
// optimistic `echo` beats render instantly and are swapped for the backend's
// canonical player echoes when the response lands; on failure the echo is
// taken back and the typed content (`restore`, plus the wish) returns to its
// composer so nothing is lost.
export async function resolveTurn(g, send, { look = false, echo = null, restore = null, wish = null, via = null } = {}) {
  g.generating = true;
  g.skipReveal = true; // fast-forward any reveal still running from last turn
  if (echo && echo.length) g.beats = [...g.beats, ...echo];
  render();
  let failed = false;

  try {
    const turn = await send();
    g.beats = g.beats.filter((b) => !b.pending); // the canonical echoes replace ours
    const prevState = g.state;
    g.state = mapGameState(turn.state);
    g.changes = diffState(prevState, g.state); // what transitioned this turn
    const seen = new Set(g.beats.map((b) => b.id));
    const newBeats = mapBeats(turn.beats || [])
      .filter((b) => !seen.has(b.id))
      .map((b) => (via ? { ...withVoice(b), viaProfile: via } : withVoice(b)));
    g.beats = [...g.beats, ...newBeats];
    g.lastVia = via; // late image beats from this turn mirror to the same panel
    g.lastTurnIndex = lastTurnIndexOf(g.beats, g.lastTurnIndex);
    g.revealQueue = newBeats.map((b) => b.id); // staged reveal, in seq order
    g.skipReveal = false;
    // a look turn may earn an image; it renders in the background and lands as
    // a late image beat (the watcher below catches it)
    g.pendingView = Boolean(look && g.state.imagesEnabled);
    state.backendOnline = true;
  } catch (err) {
    failed = true;
    g.beats = g.beats.filter((b) => !b.pending); // the turn never happened
    if (wish) g.wish = wish; // the wish returns to its line too
    state.backendError = err.message || "Turn failed";
    if (err.status === 0) state.backendOnline = false;
    showToast(err.message || "The backend did not accept that action.");
  } finally {
    g.generating = false;
    render();
    if (failed) restoreInput(g, restore);
    applyTransitions(g); // notices + one-shot flashes from the diff
    startReveal(g);
    if (g.pullOwed) {
      g.pullOwed = false;
      pullBeats(g); // a media-ready event fired mid-turn; settle the debt now
    }
    if (g.profile) refreshProfile(g); // the open profile reflects the new turn
    refocusComposer(g); // the lock lifted: hand the keyboard straight back
  }
  return !failed;
}

// The reply landed and the composer unlocked: focus the active input so the
// player never has to click the box again after every turn (owner request).
// Never steal focus from another control they are actively using (the wish
// line, a settings field, a different composer).
function refocusComposer(g) {
  if (state.active !== g || state.view !== "play") return;
  const focused = typeof document !== "undefined" ? document.activeElement : null;
  if (
    focused &&
    focused !== document.body &&
    (focused.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(focused.tagName))
  ) {
    return;
  }
  const pm = g.profile && g.profile.tab === "whisper";
  focusComposer(pm ? "#pmInput" : "#cmpInput");
}

// Put the typed content back where it came from after a failed turn: a single
// line returns to its composer (mode restored), several segments return to the
// stack ready to re-send. Button-born segments (attack/give/exit) have nothing
// typed to restore.
export function restoreInput(g, input) {
  if (input == null || state.active !== g) return;
  if (!Array.isArray(input)) return restoreLine(g.composer, "cmp", "do", String(input));
  if (input.length === 1) {
    const seg = input[0];
    if (seg.type === "whisper" && g.profile) {
      g.profile.tab = "whisper";
      return restoreLine(g.profile, "pm", seg.mode === "do" ? "do" : "say", seg.text);
    }
    if (seg.type === "say" || seg.type === "do" || seg.type === "look") {
      return restoreLine(g.composer, "cmp", seg.type, seg.text);
    }
    return;
  }
  const pm = input.every((s) => s.type === "whisper");
  const holder = pm ? g.profile : g.composer;
  if (!holder) return;
  if (pm) holder.tab = "whisper";
  holder.stack = [...input];
  render();
}

export function restoreLine(holder, scope, mode, text) {
  if (!holder) return;
  holder.mode = mode;
  render();
  const input = root.querySelector(`#${scope}Input`);
  if (input) {
    input.textContent = text || "";
    input.focus();
  }
}

export function lastTurnIndexOf(beats, fallback = 0) {
  let max = Number.isInteger(fallback) ? fallback : 0;
  for (const b of beats) if (Number.isInteger(b.turnIndex) && b.turnIndex > max) max = b.turnIndex;
  return max;
}
