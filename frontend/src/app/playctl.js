// Play-surface interactions: scene/character action buttons, tap-to-inspect,
// /explain, the give flow and the @ entity tagger.

import { presentCharacters } from "../adapters.js";
import { insertChip } from "../composer.js";
import { icon } from "../icons.js";
import { api, root, state } from "./ctx.js";
import { openWhisper } from "./profilectl.js";
import { takeTurn } from "./turns.js";
import { render } from "./ui.js";

// The scene's base actions are real story actions. Look around / Search map to
// the `look` segment (they can reveal the scene's hidden items and exits);
// anything else stays a freeform do with the button's label.
export function takeSceneAction(type, label) {
  if (type === "look") return takeTurn([{ type: "look", text: "" }]);
  if (type === "search") return takeTurn([{ type: "look", text: "for anything hidden or useful here" }]);
  takeTurn([{ type: "do", text: label }]);
}

// Map a character action button (its `type`) to the right segment / panel.
// (Talk is GONE as an affordance: whisper is the private channel and it lives
// in the character profile screen.)
export function onCharAction(el) {
  const g = state.active;
  if (!g) return;
  const { type, charId, charName, label } = el.dataset;
  switch (type) {
    case "attack":
      takeTurn([{ type: "attack", target: charId || charName }]);
      break;
    case "give":
      g.give = { charId, name: charName };
      render();
      break;
    default:
      // talk/trade/offer/follow/observe/back-away/provoke: a freeform action
      // aimed at the character, so the narrator knows the target.
      takeTurn([{ type: "do", text: `${label} ${charName}`.trim() }]);
      break;
  }
}

// ---------------------------------------------------------------------------
// tap-to-inspect: the detail modal + the /explain narrator aside
// ---------------------------------------------------------------------------

export function openInspect(spec) {
  const g = state.active;
  if (!g || !g.state) return;
  g.inspect = { ...spec, asking: false, answer: null };
  render();
}

export async function doExplain() {
  const g = state.active;
  const ins = g && g.inspect;
  if (!ins || ins.asking) return;
  ins.asking = true;
  ins.answer = null;
  render();
  try {
    const payload = ins.kind === "beat" ? { kind: "beat", beat_id: ins.beatId } : { kind: ins.kind, key: ins.key };
    const res = await api.explain(g.id, payload);
    ins.answer = (res && res.text) || "";
  } catch (err) {
    ins.answer = err.status === 404 ? "Nothing more can be seen." : "The narrator is silent right now.";
  } finally {
    if (g.inspect === ins) {
      ins.asking = false;
      render();
    }
  }
}

export async function doGive(item, target) {
  const g = state.active;
  if (!g) return;
  // remember WHO is receiving (id for routing, name for the open) before the
  // picker state is cleared - the give modal carries both.
  const recipient = g.give ? { charId: g.give.charId, name: g.give.name } : null;
  g.give = null;
  const ok = await takeTurn([{ type: "give", item, target }]);
  // the turn resolved (the backend answered the give with private beats from
  // the receiver): drop the player straight into that character's whisper
  // thread, scrolled to the newest line (owner request). Only on success and
  // only if we are still on this game's play screen.
  if (ok && recipient && recipient.charId && state.active === g && state.view === "play") {
    openWhisper(recipient.charId, recipient.name);
  }
}

// document-level dismiss listener for the tagger popover (tracked so a stale
// one can never close the next popover)
export let taggerDismiss = null;

// ---------------------------------------------------------------------------
// the entity tagger ("@"): pick a character or item to chip into the line
// ---------------------------------------------------------------------------

export function closeTagger() {
  document.querySelectorAll(".tagger-pop").forEach((p) => p.remove());
  if (taggerDismiss) {
    document.removeEventListener("click", taggerDismiss);
    taggerDismiss = null;
  }
}

export function openTagger(btn) {
  const g = state.active;
  if (!g || !g.state) return;
  closeTagger();
  const scope = btn.dataset.scope || "cmp";
  const s = g.state;

  const entities = [
    ...presentCharacters(s).map((c) => ({ kind: "character", id: c.id, name: c.name })),
    ...((s.scene && s.scene.items) || []).map((it) => ({ kind: "item", id: it.id, name: it.name })),
    ...(s.player.inventory || []).map((it) => ({ kind: "item", id: it.id, name: it.name })),
  ].filter((e) => e.name);

  const pop = document.createElement("div");
  pop.className = "tagger-pop";
  pop.setAttribute("role", "listbox");
  pop.setAttribute("aria-label", "Tag a character or item");
  pop.innerHTML = entities.length
    ? entities
        .map(
          (e, i) =>
            `<button type="button" role="option" class="tag-opt kind-${e.kind}" data-index="${i}">
               ${icon(e.kind === "character" ? "mask" : "gem")}<span></span>
             </button>`,
        )
        .join("")
    : `<p class="tag-empty">Nothing here to tag yet.</p>`;
  pop.querySelectorAll(".tag-opt span").forEach((span, i) => {
    span.textContent = entities[i].name;
  });
  pop.querySelectorAll(".tag-opt").forEach((opt) => {
    opt.addEventListener("click", (e) => {
      e.stopPropagation();
      const ref = entities[Number(opt.dataset.index)];
      const editor = root.querySelector(`#${scope}Input`);
      if (editor && ref) insertChip(editor, ref);
      closeTagger();
      if (editor) editor.focus();
    });
  });
  document.body.appendChild(pop);
  const r = btn.getBoundingClientRect();
  pop.style.left = `${Math.max(8, Math.min(window.innerWidth - 248, r.left + window.scrollX - 110))}px`;
  pop.style.top = `${Math.max(8, r.top + window.scrollY - pop.offsetHeight - 8)}px`;
  taggerDismiss = (ev) => {
    if (!pop.contains(ev.target) && ev.target !== btn) closeTagger();
  };
  setTimeout(() => {
    if (taggerDismiss) document.addEventListener("click", taggerDismiss);
  }, 0);
}
