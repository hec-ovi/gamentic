// The tagged-segment composer (docs/frontend-api.md s2, "Entity chips (refs)").
//
// The player writes in a contenteditable line and can tag entities (characters,
// items) into it. A tagged entity renders as a NON-EDITABLE chip: one click
// selects it, backspace removes the whole chip at once, and each kind carries
// its own icon. On send the chip's display name goes inline into the segment
// `text` and the chip itself is appended to that segment's `refs` array as
// { kind, id, name } - ids straight from GameState, so the backend resolves
// them without name-matching.
//
// Pure DOM helpers, no app state: app.js owns when to insert/serialize/clear.

import { icon } from "./icons.js";

// local copy (render.js imports from this module; importing back would cycle)
function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

// kind -> icon: a character chip and an item chip must read differently at a glance.
const CHIP_ICON = { character: "mask", item: "gem" };

export function chipHtml(ref) {
  const kind = ref.kind === "character" ? "character" : "item";
  return (
    `<span class="ent-chip chip-${kind}" data-chip contenteditable="false" tabindex="-1"` +
    ` data-kind="${kind}" data-id="${escapeHtml(ref.id || "")}" data-name="${escapeHtml(ref.name || "")}">` +
    `${icon(CHIP_ICON[kind])}<span class="chip-name">${escapeHtml(ref.name || "")}</span></span>`
  );
}

// Insert a chip at the caret if the selection is inside the editor, else append.
// A trailing space keeps typing flowing after the chip.
export function insertChip(editor, ref) {
  const chip = document.createElement("template");
  chip.innerHTML = chipHtml(ref) + " ";
  const frag = chip.content;

  const sel = typeof window !== "undefined" && window.getSelection ? window.getSelection() : null;
  if (sel && sel.rangeCount && editor.contains(sel.anchorNode)) {
    const range = sel.getRangeAt(0);
    range.deleteContents();
    const last = frag.lastChild;
    range.insertNode(frag);
    range.setStartAfter(last);
    range.collapse(true);
    sel.removeAllRanges();
    sel.addRange(range);
  } else {
    editor.appendChild(frag);
  }
  editor.dispatchEvent(new Event("input", { bubbles: true }));
}

// Walk the editor: text nodes -> text, chips -> display name inline + refs entry.
// Returns { text, refs } ready to drop into a segment.
export function serializeComposer(editor) {
  if (!editor) return { text: "", refs: [] };
  const refs = [];
  let text = "";
  editor.childNodes.forEach((node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      text += node.textContent;
    } else if (node.nodeType === Node.ELEMENT_NODE && node.hasAttribute("data-chip")) {
      const name = node.dataset.name || "";
      text += name;
      refs.push({ kind: node.dataset.kind || "item", id: node.dataset.id || null, name });
    } else if (node.nodeType === Node.ELEMENT_NODE) {
      // pasted markup / browser-inserted <br>: keep only its text
      text += node.textContent;
    }
  });
  return { text: text.replace(/ /g, " ").replace(/\s+/g, " ").trim(), refs };
}

export function clearComposer(editor) {
  if (editor) editor.innerHTML = "";
}

// Build the wire segment for one composed line.
//   mode: "say" | "do" | "look"
//   channel: null (public scene) | { kind: "conversation", target } (the private channel)
// Whisper is the private channel: "do" becomes a discreet private action via
// whisper mode:"do", and "look" a quiet PRIVATE study (whisper mode:"look") -
// its echo and resulting image land in the thread, never the public story, and
// no reply comes back (a gaze isn't an address). A public look is a real story
// action: study the scene (empty text) or something specific.
export function buildSegment({ mode, text, refs, channel }) {
  const base = refs && refs.length ? { refs } : {};
  if (channel && channel.kind === "conversation") {
    const m = mode === "do" ? "do" : mode === "look" ? "look" : "say";
    return { type: "conversation", text, target: channel.target, mode: m, ...base };
  }
  if (mode === "look") {
    // chip names are already inline in the text
    return { type: "look", text };
  }
  if (mode === "say") {
    const target = channel ? channel.target : undefined;
    return { type: "say", text, ...(target ? { target } : {}), ...base };
  }
  return { type: "do", text, ...base };
}

// Human line for a stacked segment row ("Say -> Mara: hello").
export function describeSegment(seg) {
  const verb =
    seg.type === "conversation"
      ? seg.mode === "do"
        ? "Discreetly"
        : seg.mode === "look"
          ? "Study"
          : "Whisper"
      : seg.type === "look"
        ? "Look"
        : seg.type === "say"
          ? "Say"
          : "Do";
  const target = seg.target ? ` -> ${seg.target}` : "";
  const fallback = seg.type === "look" ? "the whole scene" : seg.type === "conversation" && seg.mode === "look" ? "them, quietly" : "";
  return `${verb}${target}: ${seg.text || fallback}`;
}
