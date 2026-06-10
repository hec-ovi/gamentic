// The full-screen character profile: tabs, panes, the whisper channel.

import { icon } from "../icons.js";
import { escapeHtml, holoFx, initials, stripWrappingQuotes } from "./common.js";
import { playerSpeech } from "./story.js";
import { contextMeter, renderComposer, renderStack, slotGrid } from "./widgets.js";

// ---------------------------------------------------------------------------
// The FULL-SCREEN character profile (GET /characters/{cid}/profile): the image
// large, the traits unlocked through play (the personality card collection),
// the moments shared with them, story images as memories, and THE private
// whisper channel (its composer lives here now; "Talk" no longer exists).
// ---------------------------------------------------------------------------
export function renderProfile(s, g) {
  const pf = g.profile; // { charId, name, mode, stack, loading, data, error }
  const c = (s.characters || []).find((x) => x.id === pf.charId) || { id: pf.charId, name: pf.name, color: "#2fe6ff" };
  const d = pf.data;
  const name = (d && d.name) || c.name || pf.name;
  const color = (d && d.color) || c.color || "#2fe6ff";

  let body;
  if (pf.loading && !d) {
    body = `<div class="narrating profile-loading"><span class="dot"></span><span class="dot"></span><span class="dot"></span><em>remembering ${escapeHtml(name)}...</em></div>`;
  } else if (!d) {
    body = `<p class="modal-body">${escapeHtml(pf.error || "No trace of them remains.")}</p>`;
  } else {
    body = profileBody(s, g, d);
  }

  return `
    <div class="profile-screen${pf.arrive ? " arrive" : ""}" role="dialog" aria-modal="true" aria-label="${escapeHtml(name)}'s profile" style="--speaker:${escapeHtml(color)}">
      ${holoFx()}
      <header class="profile-bar">
        <button type="button" class="holo-icon" data-act="close-profile" aria-label="Back to the scene" title="Back to the scene">${icon("chevronLeft")}</button>
        <span class="hud-tag">// ${escapeHtml(name.toUpperCase())}</span>
      </header>
      <div class="profile-main">${body}</div>
    </div>`;
}

// The right column is TABBED: Profile (status: who they are, what they carry),
// Traits (the personality card collection), Memory (shared moments + image
// memories), Whisper (the private channel). The art + name stay on the left.
export const PROFILE_TABS = [
  { id: "profile", label: "Profile", icon: "mask" },
  { id: "traits", label: "Traits", icon: "sparkles" },
  { id: "memory", label: "Memories", icon: "eye" },
  { id: "whisper", label: "Whisper", icon: "mic" },
];

export const GROW_NOTE = `<p class="profile-empty muted">The more you interact with your characters, the more their traits and personality will grow from your interactions.</p>`;

export function profileBody(s, g, d) {
  const pf = g.profile;
  const tab = pf.tab || "profile";
  const art = d.bodyUrl || d.faceUrl
    ? `<img class="profile-art" data-art="${escapeHtml(d.bodyUrl || d.faceUrl)}" src="${escapeHtml(d.bodyUrl || d.faceUrl)}" alt="${escapeHtml(d.name)}" />`
    : `<div class="profile-art fallback" role="img" aria-label="${escapeHtml(d.name)}"><span class="col-initial">${escapeHtml(initials(d.name))}</span></div>`;

  const tabBar = `
    <div class="profile-tabs" role="tablist" aria-label="Character view">
      ${PROFILE_TABS.map(
        (t) =>
          `<button type="button" role="tab" class="profile-tab${tab === t.id ? " active" : ""}" aria-selected="${tab === t.id}"
                   data-act="profile-tab" data-tab="${t.id}">${icon(t.icon)}<span>${t.label}</span></button>`,
      ).join("")}
    </div>`;

  return `
    <div class="profile-cols">
      <div class="profile-left">
        ${art}
        <h3 class="profile-name">${escapeHtml(d.name)}</h3>
      </div>
      <div class="profile-right">
        ${tabBar}
        <div class="profile-pane" role="tabpanel">${renderProfilePane(s, g)}</div>
      </div>
    </div>`;
}

// Just the active tab's pane content. Exported so a tab switch can patch the
// pane IN PLACE (no full re-render: the screen and its art never flicker).
export function renderProfilePane(s, g) {
  const pf = g.profile;
  const d = pf && pf.data;
  if (!d) return "";
  const tab = pf.tab || "profile";
  if (tab === "traits") return profileTraitsPane(d);
  if (tab === "memory") return profileMemoryPane(d);
  if (tab === "whisper") return renderWhisperChannel(g, d.name, Boolean(g.generating));
  return profileStatusPane(s, d);
}

// Profile tab: the status sheet - who they are, how they stand, what they
// carry, and the pieces of their PAST the story has revealed.
export function profileStatusPane(s, d) {
  const hp =
    d.life != null && d.maxLife
      ? `<div class="char-hp" title="${d.life}/${d.maxLife}"><div class="hp-track"><div class="hp-fill" style="width:${Math.max(0, Math.min(100, (d.life / d.maxLife) * 100))}%"></div></div></div>`
      : "";
  // the character's own agent memory lives in state (not the profile endpoint)
  const stateChar = (s.characters || []).find((x) => x.id === d.id);
  const sparse = !d.traits.length && d.moments.length < 3;
  const origin = d.origin.length
    ? `<section class="profile-sec">
         <h4 class="profile-sec-head">${icon("scroll")}<span>Their past</span></h4>
         <ul class="trait-list origin-list">
           ${d.origin
             .map(
               (o) =>
                 `<li class="trait origin"><span class="trait-text">${escapeHtml(o.text)}</span>${o.learned ? `<span class="trait-stamp">learned: ${escapeHtml(o.learned)}</span>` : ""}</li>`,
             )
             .join("")}
         </ul>
       </section>`
    : "";
  return `
    <div class="profile-id">
      <p class="ins-tags">
        ${d.gender ? `<span class="ins-tag">${escapeHtml(d.gender)}</span>` : ""}
        <span class="disp-badge disp-${escapeHtml(d.disposition)}">${escapeHtml(d.disposition)}</span>
        ${d.following ? `<span class="ins-tag">following you</span>` : ""}
        ${!d.alive ? `<span class="ins-tag">fallen</span>` : ""}
      </p>
      ${hp}
      ${d.description ? `<p class="modal-body">${escapeHtml(d.description)}</p>` : ""}
      ${stateChar ? contextMeter(stateChar.context, { mini: true, label: `${d.name}'s memory` }) : ""}
      <div class="char-inv">
        <span class="inv-mini-label">Carrying</span>
        ${slotGrid(d.carrying, 3, "char-items")}
      </div>
      ${origin}
      ${sparse ? GROW_NOTE : ""}
    </div>`;
}

// Traits tab: the personality card collection unlocked through play.
export function profileTraitsPane(d) {
  if (!d.traits.length) return GROW_NOTE;
  return `
    <ul class="trait-list">
      ${d.traits
        .map(
          (t) =>
            `<li class="trait"><span class="trait-text">${escapeHtml(t.text)}</span>${t.unlocked ? `<span class="trait-stamp">unlocked: ${escapeHtml(t.unlocked)}</span>` : ""}</li>`,
        )
        .join("")}
    </ul>`;
}

// Memories tab: the image strip first, then the moments shared with them.
export function profileMemoryPane(d) {
  if (!d.moments.length && !d.memories.length) {
    return `<p class="profile-empty muted">Nothing shared yet. The moments you live together will gather here.</p>`;
  }
  const moments = d.moments.length
    ? `<section class="profile-sec">
         <h4 class="profile-sec-head">${icon("scroll")}<span>Moments</span></h4>
         <ul class="moment-list">
           ${d.moments
             .map(
               (m) =>
                 `<li class="moment ${m.speaker === "player" ? "from-you" : "from-them"}${m.private ? " private" : ""}">
                    <span class="moment-who">${m.speaker === "player" ? "You" : escapeHtml(d.name)}${m.private ? ` <i class="moment-private" title="A private exchange">${icon("mic")}private</i>` : ""}</span>
                    <span class="moment-text">${escapeHtml(stripWrappingQuotes(m.text))}</span>
                  </li>`,
             )
             .join("")}
         </ul>
       </section>`
    : "";
  const memories = d.memories.length
    ? `<section class="profile-sec">
         <h4 class="profile-sec-head">${icon("eye")}<span>Memories</span></h4>
         <div class="memory-strip">
           ${d.memories
             .map(
               (m) =>
                 `<figure class="memory"><img src="${escapeHtml(m.imageUrl)}" alt="${escapeHtml(m.caption || "A remembered moment")}" loading="lazy" />${m.caption ? `<figcaption>${escapeHtml(m.caption)}</figcaption>` : ""}</figure>`,
             )
             .join("")}
         </div>
       </section>`
    : "";
  return memories + moments;
}

// The private channel: whisper-only, 1:1, lives in the profile. private_with
// beats render here and never in the public story; replies speak with the
// character's own voice through the same pipeline as public dialogue.
export function renderWhisperChannel(g, name, locked) {
  const pf = g.profile;
  const beats = g.beats.filter((b) => b.privateWith === pf.charId);
  const veiled = g.revealQueue && g.revealQueue.length ? new Set(g.revealQueue) : null;
  const thread = beats.length
    ? beats
        .slice(-40)
        .map((b) => {
          const html = renderPmBeat(b);
          return veiled && veiled.has(b.id) ? `<div class="veil-wrap veiled">${html}</div>` : html;
        })
        .join("")
    : `<p class="pm-empty muted">Say something only ${escapeHtml(name)} will hear.</p>`;

  return `
    <section class="profile-sec whisper-sec">
      <h4 class="profile-sec-head">${icon("mic")}<span>Whisper</span></h4>
      <p class="pm-hint">Only ${escapeHtml(name)} will ever know this.</p>
      <div class="pm-thread" id="pmThread">${thread}</div>
      ${renderStack(pf.stack, "pm")}
      <form class="pm-form" data-form="private">
        ${renderComposer({
          id: "pm",
          mode: pf.mode,
          locked,
          placeholders: {
            say: `Whisper to ${name}...`,
            do: `A discreet act only ${name} notices...`,
          },
          submitLabel: locked ? "Resolving..." : "Whisper",
        })}
      </form>
    </section>`;
}

// Compact beat rendering inside the private whisper thread. data-beat-id + the
// .pm-text span let the staged reveal typewrite private replies too. Narration
// stays unlabeled here too (no "Narrator" tag anywhere), and no literal quote
// marks: the player's own speech echoes show just what was said.
export function renderPmBeat(beat) {
  if (beat.kind === "system") {
    return `<div class="pm-line pm-system" data-beat-id="${escapeHtml(beat.id)}">${escapeHtml(beat.text)}</div>`;
  }
  if (beat.kind === "narration" || beat.speaker === "narrator") {
    return `<div class="pm-line pm-narration" data-beat-id="${escapeHtml(beat.id)}"><span class="pm-text">${escapeHtml(beat.text)}</span></div>`;
  }
  const mine = !beat.speaker || beat.speaker === "player";
  const deed = beat.kind === "action";
  const sp = mine ? playerSpeech(beat) : null;
  const text = sp ? sp.quote : stripWrappingQuotes(beat.text);
  return `<div class="pm-line ${mine ? "pm-you" : "pm-them"}${deed && !sp ? " pm-deed" : ""}${beat.pending ? " pending" : ""}" data-beat-id="${escapeHtml(beat.id)}">
            ${!mine && beat.speakerName ? `<b>${escapeHtml(beat.speakerName)}</b> ` : ""}<span class="pm-text">${escapeHtml(text)}</span>
          </div>`;
}
