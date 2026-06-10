// The story log: beats by kind, player speech parsing, scene-art anchoring.

import { icon } from "../icons.js";
import { escapeHtml, initials, stripWrappingQuotes } from "./common.js";

// The story log. Only public beats (private_with == null) ever render here;
// private exchanges live in the private modal. The current scene's art is mixed
// INTO the prose, anchored at the ESTABLISHING beat of the current scene visit.
export function renderStory(g) {
  const beats = g.beats.filter((b) => !b.privateWith);
  const artCard = sceneArtCard(g.state);

  if (!beats.length) {
    return artCard + `<p class="story-prose muted">The story has not begun yet.</p>`;
  }

  // window very long logs so the DOM does not grow unbounded (perf requirement)
  const MAX = 120;
  let shown = beats;
  let trimmed = 0;
  if (beats.length > MAX) {
    trimmed = beats.length - MAX;
    shown = beats.slice(-MAX);
  }
  const trim = trimmed ? `<p class="story-trim muted small">${trimmed} earlier moments are behind you.</p>` : "";

  // ANCHORING RULE (round-2 fix): the scene-art card pins to the FIRST
  // narration of the CURRENT scene visit - its establishing beat - never the
  // latest one (anchoring to "latest" relocated the image on every new
  // narration). The current visit is the trailing run of beats whose location
  // matches where the player is now (location-less beats don't break the run).
  // If the visit has no narration in the window, the card stands alone at the
  // top of this visit's beats.
  const here = g.state && (g.state.player.location || (g.state.scene && g.state.scene.name)) || null;
  let visitStart = 0;
  for (let i = shown.length - 1; i >= 0; i--) {
    if (here && shown[i].location && !sameLocation(shown[i].location, here)) {
      visitStart = i + 1;
      break;
    }
  }
  let anchorIdx = -1;
  for (let i = visitStart; i < shown.length; i++) {
    if (shown[i].kind === "narration") {
      anchorIdx = i;
      break;
    }
  }

  // beats queued for the staged reveal render veiled until their turn
  const veiled = g.revealQueue && g.revealQueue.length ? new Set(g.revealQueue) : null;
  const parts = shown.map((b, i) => {
    const html = renderBeat(b, g, i === anchorIdx ? artCard : "");
    return veiled && veiled.has(b.id) ? `<div class="veil-wrap veiled">${html}</div>` : html;
  });
  if (anchorIdx === -1 && artCard) parts.splice(visitStart, 0, artCard);
  return trim + parts.join("");
}

// Mirror of the backend's norm_location (underscore/space collapse).
export function sameLocation(a, b) {
  const norm = (v) => String(v || "").toLowerCase().replace(/[_\s]+/g, " ").trim();
  return norm(a) === norm(b);
}

// The scene image as a collectible card living inside the prose. Loader rule:
// null + images_enabled -> a developing-photo skeleton; images off -> nothing
// (pure text must read like a book, not a grid of dead boxes).
export function sceneArtCard(s) {
  const scene = s && s.scene;
  if (!scene) return "";
  const name = scene.name || "";
  if (scene.imageUrl) {
    return `<figure class="prose-art">
              <span class="card-corner tr"></span><span class="card-corner bl"></span>
              <img data-art="${escapeHtml(scene.imageUrl)}" src="${escapeHtml(scene.imageUrl)}" alt="${escapeHtml(name)}" loading="lazy" />
              ${name ? `<figcaption>${escapeHtml(name)}</figcaption>` : ""}
            </figure>`;
  }
  if (s.imagesEnabled) {
    return `<figure class="prose-art art-loading" role="img" aria-label="Scene art is being painted">
              <span class="art-scan" aria-hidden="true"></span>
              <span class="art-hint">visual manifesting...</span>
            </figure>`;
  }
  return "";
}

export function renderBeat(beat, g, embed = "") {
  switch (beat.kind) {
    case "narration":
      return renderNarration(beat, embed);
    case "dialogue":
      // never render a "Narrator" bubble: narrator speech IS the prose
      if (beat.speaker === "narrator") return renderNarration(beat, embed);
      return renderDialogue(beat, g);
    case "action":
      return renderActionBeat(beat, g);
    case "system":
      return renderSystem(beat);
    case "image":
      return renderImageBeat(beat);
    default:
      return renderNarration(beat, embed);
  }
}

// IMAGE beats come in two sizes (frontend-api.md s3). speaker "narrator" = a
// story shot (look results, dramatic moments): the hero treatment, inline, the
// look text as caption. speaker "system" = an ITEM UNLOCK CARD: a small square
// card labeled with the item name. Both open the lightbox; both persist.
export function renderImageBeat(beat) {
  if (!beat.imageUrl) return "";
  if (beat.speaker === "system") {
    return `<figure class="beat-image item-card" data-beat-id="${escapeHtml(beat.id)}">
              <span class="card-corner tr"></span><span class="card-corner bl"></span>
              <img data-art="${escapeHtml(beat.imageUrl)}" src="${escapeHtml(beat.imageUrl)}" alt="${escapeHtml(beat.text || "A new item")}" loading="lazy" />
              <figcaption>${icon("gem")}<span>${escapeHtml(beat.text || "New item")}</span></figcaption>
            </figure>`;
  }
  return `<figure class="beat-image" data-beat-id="${escapeHtml(beat.id)}">
            <span class="card-corner tr"></span><span class="card-corner bl"></span>
            <img data-art="${escapeHtml(beat.imageUrl)}" src="${escapeHtml(beat.imageUrl)}" alt="${escapeHtml(beat.text || "The scene as it is right now")}" loading="lazy" />
            ${beat.text ? `<figcaption>${escapeHtml(beat.text)}</figcaption>` : ""}
          </figure>`;
}

// action beats are either the player's own echoed action or a CHARACTER's deed
// (e.g. "Vergonica draws her blade."). Render each distinctly; a player echo
// that is SPEECH (say/whisper) becomes a mirrored dialogue bubble.
export function renderActionBeat(beat, g) {
  if (!beat.speaker || beat.speaker === "player" || beat.speaker === "narrator") {
    const sp = playerSpeech(beat);
    if (sp) return renderPlayerSpeech(beat, sp);
    return renderPlayerAction(beat);
  }
  const ch = (g.state.characters || []).find((c) => c.id === beat.speaker);
  const color = (ch && ch.color) || "#a79fb3";
  const name = beat.speakerName || (ch && ch.name) || "";
  return `<p class="char-deed" data-beat-id="${escapeHtml(beat.id)}" style="--speaker:${escapeHtml(color)}">
            ${name ? `<b>${escapeHtml(name)}</b> ` : ""}${escapeHtml(beat.text)}
          </p>`;
}

export const PLAYER_COLOR = "#2fe6ff";

// Detect a player SPEECH echo. The wire gives player echoes as kind "action"
// with texts like `you say "..." to Vex` or `you whisper to Mara: "..."`;
// the quoted span is what was said.
export function playerSpeech(beat) {
  if (beat.kind !== "action" || (beat.speaker && beat.speaker !== "player")) return null;
  const t = String(beat.text || "");
  const m = t.match(/^you\s+(say|whisper|tell|ask|shout|reply|respond|call)\b/i);
  if (!m) return null;
  const q = t.match(/[“]([\s\S]+?)[”]|"([\s\S]+?)"/);
  if (!q) return null;
  const quote = q[1] != null ? q[1] : q[2];
  const tm = t.match(/\bto\s+([^:."“]+?)\s*(?::|\.|$)/i);
  return { quote, verb: m[1].toLowerCase(), target: tm ? tm[1].trim() : null };
}

// Player speech = a dialogue bubble MIRRORED: right-aligned, avatar on the
// right, the player's color. Speech should look like speech (owner playtest).
// An optimistic (pending) echo renders slightly dimmed until the turn lands.
export function renderPlayerSpeech(beat, sp) {
  const whisper = sp.verb === "whisper";
  const meta = sp.target ? `${whisper ? "whispered to" : "to"} ${sp.target}` : whisper ? "whispered" : "";
  return `
    <article class="dialogue from-player${whisper ? " whispered" : ""}${beat.pending ? " pending" : ""}" data-beat-id="${escapeHtml(beat.id)}" style="--speaker:${PLAYER_COLOR}">
      <span class="bubble-avatar fallback you" style="background:${PLAYER_COLOR}">YOU</span>
      <div class="bubble">
        <span class="bubble-name">You${meta ? ` <i class="bubble-meta">${escapeHtml(meta)}</i>` : ""}</span>
        <p>${escapeHtml(sp.quote)}</p>
      </div>
    </article>`;
}

// NARRATION = prose. No bubble, no speaker label. Just the story text, set like
// a book. `embed` is the scene-art card floated into this passage so the image
// reads as part of the text, and a beat may carry its own moment art too.
export function renderNarration(beat, embed = "") {
  const paras = String(beat.text)
    .split(/\n{2,}/)
    .map((p) => `<p>${escapeHtml(p).replace(/\n/g, "<br />")}</p>`)
    .join("");
  const beatArt = beat.imageUrl
    ? `<figure class="prose-art beat-art">
         <span class="card-corner tr"></span><span class="card-corner bl"></span>
         <img data-art="${escapeHtml(beat.imageUrl)}" src="${escapeHtml(beat.imageUrl)}" alt="" loading="lazy" />
       </figure>`
    : "";
  const playable = beat.voiceId ? speakBtn(beat) : "";
  return `<section class="narration" data-beat-id="${escapeHtml(beat.id)}">
            ${embed}${beatArt}${paras}${playable}
          </section>`;
}

// DIALOGUE = a distinct named bubble with the character's identity.
export function renderDialogue(beat, g) {
  const ch = (g.state.characters || []).find((c) => c.id === beat.speaker);
  const color = (ch && ch.color) || "#f2b84b";
  const name = beat.speakerName || (ch && ch.name) || "Someone";
  const avatar = ch && ch.faceUrl
    ? `<img class="bubble-avatar" src="${escapeHtml(ch.faceUrl)}" alt="${escapeHtml(name)}" loading="lazy" />`
    : `<span class="bubble-avatar fallback" style="background:${escapeHtml(color)}">${escapeHtml(initials(name))}</span>`;
  return `
    <article class="dialogue" data-beat-id="${escapeHtml(beat.id)}" style="--speaker:${escapeHtml(color)}">
      ${avatar}
      <div class="bubble">
        <span class="bubble-name">${escapeHtml(name)}</span>
        <p>${escapeHtml(stripWrappingQuotes(beat.text))}</p>
        ${beat.voiceId ? speakBtn(beat) : ""}
      </div>
    </article>`;
}

// PLAYER action = quiet inline marker, right-aligned, not a big bubble.
export function renderPlayerAction(beat) {
  return `<p class="player-action${beat.pending ? " pending" : ""}" data-beat-id="${escapeHtml(beat.id)}">
            ${icon("compass")}<span>${escapeHtml(beat.text)}</span>
          </p>`;
}

// SYSTEM = small animated badge (the juice). Tappable: a receipt like
// "Obtained: brass key" opens the inspect modal to ask what it was about.
export function renderSystem(beat) {
  const tone = systemTone(beat.text);
  return `<button type="button" class="system-badge ${tone}" data-beat-id="${escapeHtml(beat.id)}" data-act="inspect-beat" role="status" title="Tap to inspect">
            ${icon(systemIcon(tone))}<span>${escapeHtml(beat.text)}</span>
          </button>`;
}

export function speakBtn(beat) {
  return `<button type="button" class="speak-btn" data-act="speak-beat" data-beat-id="${escapeHtml(beat.id)}" aria-label="Play voice" title="Play voice">${icon("volume2")}</button>`;
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

export function systemTone(text) {
  const t = String(text).toLowerCase();
  // a trait receipt ("Trait unlocked: Mara - distrusts authority.") or an
  // origin reveal ("You learn of Vex's past: ...") gets the card-unlock
  // celebration treatment
  if (/^trait unlocked/.test(t) || /^you learn of .+ past:/.test(t)) return "trait";
  // adjudication: a rejected attempt ("You don't have X.", "Mara is not here.")
  // or a narrator veto ("Mara steps back, refusing the coin.")
  if (/(don't have|do not have|not here|refus|cannot|can't)/.test(t)) return "veto";
  if (/(damage|hurt|hit|lose|wound|life)/.test(t)) return "danger";
  if (/(point|score)/.test(t)) return "points";
  if (/(item|found|gain|acquire|unlock|inventory)/.test(t)) return "item";
  if (/(quest|objective)/.test(t)) return "quest";
  return "neutral";
}

export function systemIcon(tone) {
  return { trait: "sparkles", veto: "x", danger: "flame", points: "star", item: "gem", quest: "scroll", neutral: "zap" }[tone] || "zap";
}
