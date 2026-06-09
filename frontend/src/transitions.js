// State-transition engine: the frontend must make every change LEGIBLE.
//
// Each turn the backend returns the full fresh state. We diff the previous mapped
// state against the new one to find what changed (scene entered, item taken,
// character joined / left / now-following / died / disposition shifted, goal /
// quest / objective changes, deltas) and turn that into:
//   - transient "notices" (animated chips that fade) for narrative changes, and
//   - one-shot flash targets (ids) the controller animates on the cards/slots.
//
// Pure functions only (no DOM), so this is unit-testable in isolation.

const PRESENT = (c, loc) => c && c.present && c.alive && (!loc || c.location === loc);

export function emptyChanges() {
  return {
    firstLoad: false,
    sceneChanged: false,
    sceneName: null,
    prevSceneName: null,
    itemsAdded: [], // ids revealed in the SAME scene
    itemsRemoved: [], // ids taken / gone in the SAME scene
    exitsAdded: [], // labels of newly revealed exits
    charSpawned: [], // {id,name}
    charJoined: [], // {id,name} now co-located, weren't
    charLeft: [], // {id,name} were co-located, now gone elsewhere
    charDied: [], // {id,name}
    charFollowing: [], // {id,name} started following
    charUnfollowing: [], // {id,name} stopped following
    charDisposition: [], // {id,name,from,to}
    charHurt: [], // ids whose life dropped
    goalChanged: false,
    goal: null,
    questsAdded: [], // titles
    objectivesDone: [], // texts
    questResolved: [], // {title,status}
    pointsDelta: 0,
    lifeDelta: 0,
    invAdded: [], // names gained
    invRemoved: [], // names lost
    storyEnded: null, // 'won' | 'lost'
  };
}

export function diffState(prev, next) {
  const ch = emptyChanges();
  if (!next) return ch;
  if (!prev) {
    ch.firstLoad = true;
    return ch;
  }

  // --- scene ---
  const prevScene = prev.scene || {};
  const nextScene = next.scene || {};
  const sameScene = (prevScene.id || prevScene.name) === (nextScene.id || nextScene.name);
  ch.sceneChanged = !sameScene;
  ch.sceneName = nextScene.name || next.player.location || null;
  ch.prevSceneName = prevScene.name || prev.player.location || null;

  // items / exits only diff within the SAME scene (a new scene has a fresh roster)
  if (sameScene) {
    const prevItemIds = new Set((prevScene.items || []).map((i) => i.id));
    const nextItemIds = new Set((nextScene.items || []).map((i) => i.id));
    ch.itemsAdded = (nextScene.items || []).filter((i) => !prevItemIds.has(i.id)).map((i) => i.id);
    ch.itemsRemoved = (prevScene.items || []).filter((i) => !nextItemIds.has(i.id)).map((i) => i.id);
    const prevExitLabels = new Set((prevScene.exits || []).map((e) => e.label));
    ch.exitsAdded = (nextScene.exits || []).filter((e) => !prevExitLabels.has(e.label)).map((e) => e.label);
  }

  // --- characters (compare the full roster by id) ---
  const prevById = new Map((prev.characters || []).map((c) => [c.id, c]));
  const prevLoc = prev.player.location;
  const nextLoc = next.player.location;
  for (const c of next.characters || []) {
    const p = prevById.get(c.id);
    const tag = { id: c.id, name: c.name };
    if (!p) {
      ch.charSpawned.push(tag);
    } else {
      if (p.alive && !c.alive) ch.charDied.push(tag);
      if (!p.following && c.following) ch.charFollowing.push(tag);
      if (p.following && !c.following) ch.charUnfollowing.push(tag);
      if (p.disposition !== c.disposition) ch.charDisposition.push({ ...tag, from: p.disposition, to: c.disposition });
      if (c.life != null && p.life != null && c.life < p.life) ch.charHurt.push(c.id);
      // join/leave the scene only meaningful when the scene didn't change
      if (sameScene) {
        const wasHere = PRESENT(p, prevLoc);
        const isHere = PRESENT(c, nextLoc);
        if (isHere && !wasHere) ch.charJoined.push(tag);
        if (wasHere && !isHere) ch.charLeft.push(tag);
      }
    }
  }

  // --- goal ---
  if ((prev.currentGoal || "") !== (next.currentGoal || "") && next.currentGoal) {
    ch.goalChanged = true;
    ch.goal = next.currentGoal;
  }

  // --- quests / objectives ---
  const prevQuests = new Map((prev.quests || []).map((q) => [q.id, q]));
  for (const q of next.quests || []) {
    const pq = prevQuests.get(q.id);
    if (!pq) {
      if (q.status === "active") ch.questsAdded.push(q.title);
      continue;
    }
    if (pq.status !== q.status && (q.status === "done" || q.status === "failed")) {
      ch.questResolved.push({ title: q.title, status: q.status });
    }
    const prevObjDone = new Map((pq.objectives || []).map((o) => [o.id, o.done]));
    for (const o of q.objectives || []) {
      if (o.done && !prevObjDone.get(o.id)) ch.objectivesDone.push(o.text);
    }
  }

  // --- player deltas + inventory ---
  ch.pointsDelta = (next.player.points || 0) - (prev.player.points || 0);
  ch.lifeDelta = (next.player.life || 0) - (prev.player.life || 0);
  const prevInv = new Map((prev.player.inventory || []).map((i) => [i.name, i.qty || 1]));
  const nextInv = new Map((next.player.inventory || []).map((i) => [i.name, i.qty || 1]));
  for (const [name, qty] of nextInv) if (!prevInv.has(name) || qty > prevInv.get(name)) ch.invAdded.push(name);
  for (const [name] of prevInv) if (!nextInv.has(name)) ch.invRemoved.push(name);

  // --- story end ---
  if (prev.status === "active" && (next.status === "won" || next.status === "lost")) {
    ch.storyEnded = next.status;
  }

  return ch;
}

// Turn a changes object into transient on-screen notices (icon + text + tone).
// We deliberately SKIP points/items here (the backend emits system beats for those
// and the HUD/slots flash); notices cover state changes that have no beat of their own.
export function buildNotices(ch) {
  const out = [];
  if (!ch) return out;
  if (ch.sceneChanged && ch.sceneName) out.push({ icon: "compass", tone: "scene", text: `Entered ${ch.sceneName}` });
  for (const e of ch.exitsAdded) out.push({ icon: "compass", tone: "info", text: `A way opens: ${e}` });
  for (const c of ch.charSpawned) out.push({ icon: "mask", tone: "info", text: `${c.name} appears` });
  for (const c of ch.charJoined) out.push({ icon: "mask", tone: "info", text: `${c.name} arrives` });
  for (const c of ch.charLeft) out.push({ icon: "mask", tone: "muted", text: `${c.name} leaves` });
  for (const c of ch.charFollowing) out.push({ icon: "compass", tone: "good", text: `${c.name} now follows you` });
  for (const c of ch.charUnfollowing) out.push({ icon: "compass", tone: "muted", text: `${c.name} stays behind` });
  for (const c of ch.charDisposition) out.push({ icon: "mask", tone: dispTone(c.to), text: `${c.name} is now ${c.to}` });
  for (const c of ch.charDied) out.push({ icon: "flame", tone: "danger", text: `${c.name} has fallen` });
  if (ch.goalChanged) out.push({ icon: "compass", tone: "gold", text: `New goal: ${ch.goal}` });
  for (const t of ch.questsAdded) out.push({ icon: "scroll", tone: "gold", text: `New quest: ${t}` });
  for (const t of ch.objectivesDone) out.push({ icon: "check", tone: "good", text: `Objective done: ${t}` });
  for (const q of ch.questResolved)
    out.push({ icon: "scroll", tone: q.status === "failed" ? "danger" : "good", text: `Quest ${q.status}: ${q.title}` });
  if (ch.storyEnded === "won") out.push({ icon: "star", tone: "gold", text: "Victory" });
  if (ch.storyEnded === "lost") out.push({ icon: "flame", tone: "danger", text: "You have fallen" });
  return out;
}

function dispTone(d) {
  return { friendly: "good", hostile: "danger", neutral: "info", unknown: "muted" }[d] || "info";
}
