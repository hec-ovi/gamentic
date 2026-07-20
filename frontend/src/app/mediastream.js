// Media-ready PUSH: one EventSource per open game on GET /games/{gid}/events.
// The backend announces the moment background media persists - scene art, a
// portrait, an item card, a late image beat - and we re-fetch the cheap
// endpoint that owns it: /state for scene/portrait, /beats?since= for beats,
// and BOTH for items (the unlock card is a beat, but the slot thumbnail lives
// in state's inventories - live: the card landed while the pack slot kept its
// initials). This replaces the blind polling timers (a 40s poll ceiling once
// lost a scene render that landed at +47s; only F5 recovered it).
// EventSource reconnects itself (the server sends retry: 3000); after a drop
// we owe one catch-up fetch of both. A slow 60s sweep stays as the fallback
// for proxies that break SSE - it is the only path when EventSource is
// missing entirely (old embedders, jsdom).

import { mapBeats, mapGameState } from "../adapters.js";
import { api, root, state } from "./ctx.js";
import { applyLiveEvent, clearLiveStreams } from "./livefeed.js";
import { announceImage, startReveal } from "./reveal.js";
import { withVoice } from "./speech.js";
import { lastTurnIndexOf } from "./turns.js";
import { render } from "./ui.js";

export const FALLBACK_INTERVAL = 60000;

let stream = null; // the live EventSource
let fallbackTimer = null; // the slow sweep
let dropped = false; // a reconnect owes a catch-up

export function watchMedia(g) {
  stopMediaWatch();
  if (!g) return;
  if (typeof EventSource !== "undefined") {
    const es = new EventSource(`${api.base}/games/${encodeURIComponent(g.id)}/events`);
    stream = es;
    es.onmessage = (e) => {
      if (stream !== es || state.active !== g) return;
      let ev;
      try {
        ev = JSON.parse(e.data);
      } catch {
        return; // keepalive noise / malformed line
      }
      if (ev.kind === "scene" || ev.kind === "portrait") refreshArt(g);
      else if (ev.kind === "item") {
        refreshArt(g); // the slot thumbnail (pack/scene/carrying) lives in /state
        pullBeats(g); // the unlock card is a beat
      } else if (ev.kind === "beat") pullBeats(g);
      else applyLiveEvent(g, ev); // the live turn feed (phase/live_beat/live_text/...)
    };
    es.onopen = () => {
      if (stream !== es || state.active !== g) return;
      if (dropped) {
        dropped = false;
        clearLiveStreams(g); // a drop may have orphaned stream bubbles mid-turn
        refreshArt(g); // a drop may have swallowed events: catch up on both
        pullBeats(g);
      }
    };
    es.onerror = () => {
      dropped = true; // the browser reconnects on its own (retry: 3000)
    };
  }
  fallbackTimer = setInterval(() => {
    if (state.active !== g) return stopMediaWatch();
    refreshArt(g);
    pullBeats(g);
  }, FALLBACK_INTERVAL);
}

export function stopMediaWatch() {
  if (stream) stream.close();
  stream = null;
  if (fallbackTimer) clearInterval(fallbackTimer);
  fallbackTimer = null;
  dropped = false;
}

// One-shot /state refetch: slot late-arriving art in (scene image, portraits).
// Never clobbers fresh post-turn state: the turn's own response wins.
export async function refreshArt(g) {
  if (state.active !== g || !g.state || g.generating) return;
  try {
    const mapped = mapGameState(await api.getState(g.id));
    if (state.active !== g || g.generating) return; // turned stale while awaiting
    const prev = g.state;
    const gainedPortrait = mapped.characters.some((c) => {
      const p = prev.characters.find((x) => x.id === c.id) || {};
      return (c.faceUrl && !p.faceUrl) || (c.bodyUrl && !p.bodyUrl);
    });
    const gainedScene = mapped.scene && mapped.scene.imageUrl && !(prev.scene && prev.scene.imageUrl);
    // an item thumbnail gain re-renders too: the unlock card may already sit in
    // the stream while the slot still shows initials (every inventory counts -
    // the pack, the scene grid, a character's carrying row)
    const itemArt = (st) => {
      const m = new Map();
      const take = (items) => (items || []).forEach((it) => it && it.id && m.set(it.id, it.imageUrl));
      take(st.player && st.player.inventory);
      take(st.scene && st.scene.items);
      (st.characters || []).forEach((c) => take(c.inventory));
      return m;
    };
    const prevItems = itemArt(prev);
    const gainedItemArt = [...itemArt(mapped)].some(([id, url]) => url && !prevItems.get(id));
    g.state = mapped;
    // don't yank the DOM out from under a running typewriter; the art shows
    // on the next natural render
    if ((gainedPortrait || gainedScene || gainedItemArt) && state.view === "play" && !g.revealing) {
      render();
      if (gainedScene) {
        const art = root.querySelector("#storyStream .prose-art img");
        if (art) announceImage(art.closest(".prose-art") || art);
      }
    }
  } catch {
    /* the fallback sweep retries */
  }
}

// One-shot /beats?since= pull: merge late beats (look images, item unlock
// cards) through the usual staged reveal. While a turn is resolving we stay
// out of its way and note the debt; resolveTurn settles it.
export async function pullBeats(g) {
  if (state.active !== g || !Number.isInteger(g.lastTurnIndex)) return;
  if (g.generating) {
    g.pullOwed = true; // resolveTurn pulls once the turn lands
    return;
  }
  try {
    const res = await api.getBeats(g.id, g.lastTurnIndex);
    if (state.active !== g || g.generating) return;
    const seen = new Set(g.beats.map((b) => b.id));
    const fresh = mapBeats((res && res.beats) || [])
      .filter((b) => !seen.has(b.id))
      .map((b) => withVoice(b));
    if (!fresh.length) return;
    g.beats = [...g.beats, ...fresh];
    g.lastTurnIndex = lastTurnIndexOf(g.beats, g.lastTurnIndex);
    if (fresh.some((b) => b.kind === "image" && b.speaker !== "system")) g.pendingView = false;
    // a panel-launched look's image lands here, seconds later: mirror it
    const tagged = g.lastVia ? fresh.map((b) => (b.kind === "image" ? { ...b, viaProfile: g.lastVia } : b)) : fresh;
    if (g.lastVia) g.beats = [...g.beats.filter((b) => !tagged.some((t) => t.id === b.id)), ...tagged];
    if (state.view === "play") {
      g.revealQueue = [...(g.revealQueue || []), ...fresh.map((b) => b.id)];
      render();
      startReveal(g);
    }
    // any other view: the beats are merged unveiled and simply stand in the
    // log when the player returns (no staged reveal for what they missed)
  } catch {
    /* the fallback sweep retries */
  }
}
