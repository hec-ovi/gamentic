// Shared rendering primitives: text safety, the help copy, the holo chrome.


export const HELP = {
  menu: "The main deck. Play drops you into your saved worlds, New forges a fresh adventure, and Settings tunes sound and the backend. Everything else is just light.",
  hud: "Your vitals. The heart bar is your life; if it empties the story turns against you. Points are story score earned by clever and brave actions. Memory shows how much of the tale the narrator can still hold in mind: green is fine, red means it is nearly full.",
  quests: "Your current goals. Each quest has a checklist of objectives. The narrator ticks them off as you make progress, and may add new ones as the story unfolds.",
  party: "Characters standing here with you, full figure. Each card shows their mood toward you, health, and what they carry. Tap a character to open their full profile: the traits the story has revealed, your shared moments, their memories, and the private whisper channel only they can hear.",
  scene: "Where you are right now. Its mood (calm, tense, dangerous) shifts with the story, and the clock is story time, not yours. Alongside are the objects revealed here, the things you can try, and the ways out. A dead end means no way out has been revealed yet.",
  inventory: "What you are carrying. Empty slots show how much more you can hold. Use a character's Give button to hand something over.",
  story: "The story itself. Plain flowing text is the narrator telling the tale, just read it. Coloured cards with a name are characters speaking to you. Small badges are things that just happened (damage, items, points). Scene art develops here like a photograph as it is painted.",
  action: "Just type what you do or say in your own words and press Enter - the game understands speech, deeds, attacks, gifts and even whispers from plain text. Look studies the scene or one thing closely (it can reveal what is hidden, and may earn a picture). Continue lets the story advance on its own, and the wish line is a hope whispered to the storyteller, not an action. The @ tag and the + stack are there when you want precise control.",
  creator: "Describe the world you want in plain language and chat with the world-builder. When it has enough, press Begin the Adventure and it spins up a real game.",
  settings: "Sound options and, during play, the rules of this adventure: difficulty (how much the world bends toward you), the narrator's voice, and exporting the adventure to share or save. The game server connects automatically.",
  library: "Your saved adventures. Continue one, or start a brand new world. These are real games stored on the backend.",
};

export function help(key) {
  return `<button type="button" class="help-dot" data-help="${key}" aria-label="What is this?" title="What is this?">?</button>`;
}

// Speech text sometimes arrives wrapped in literal quote marks; the bubble IS
// the quotation, so showing them doubles up. Strip one wrapping pair only.
export function stripWrappingQuotes(value) {
  const t = String(value ?? "").trim();
  const pairs = [
    ['"', '"'],
    ["“", "”"], // curly double
    ["‘", "’"], // curly single
  ];
  for (const [a, b] of pairs) {
    if (t.length > 1 && t.startsWith(a) && t.endsWith(b)) {
      return t.slice(a.length, t.length - b.length).trim();
    }
  }
  return t;
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

// ---------------------------------------------------------------------------
// Main menu / title (the holographic landing deck)
// ---------------------------------------------------------------------------
//
// Phase 1 of the UI redesign: an ice-cyan sci-fi HUD landing screen. Three
// chamfered "nodes" (New / Play / Settings) with rotating dial rings, corner
// brackets and bloom. Pure CSS motion; no canvas, no framework. The nodes route
// straight into the existing views (Play -> library, New -> creator, etc.).

// Shared holographic background FX. Scanlines only (the nebula spheres, bloom
// halo and perspective grid were removed at the owner's request - too busy).
export function holoFx() {
  return `<div class="menu-fx" aria-hidden="true">
            <span class="fx-scan"></span>
          </div>`;
}

export function holoFrame() {
  // Four crisp corner brackets that hug a chamfered frame.
  return `<span class="holo-frame" aria-hidden="true">
            <i class="corner tl"></i><i class="corner tr"></i>
            <i class="corner bl"></i><i class="corner br"></i>
          </span>`;
}

// The diagonal corner accents on a holo card / modal / panel: top-right and
// bottom-left. Pure decoration, so they hide from screen readers (the sibling
// holoFrame above does the same with its four brackets).
export function cardCorners() {
  return `<span class="card-corner tr" aria-hidden="true"></span><span class="card-corner bl" aria-hidden="true"></span>`;
}

export function initials(name) {
  return String(name || "?")
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0] || "")
    .join("")
    .toUpperCase();
}

export function titleCase(value) {
  return String(value || "")
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (l) => l.toUpperCase());
}
