// The live turn feed, driven like a player: prose grows in place at generation
// speed (no typewriter), live beats swap gaplessly into their stream bubbles and
// never double when the POST resolves, a failed turn takes its provisional
// content back, whispers stream into the private thread, and the Stop button
// interrupts the running turn. Wire shapes mirror orchestrator/app/engine/live.py.

import { test, expect, beforeEach, vi } from "vitest";
import { screen, within, waitFor } from "@testing-library/dom";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server, mountApp } from "./setup.js";
import { FakeEventSource, makeState, makeBeat, makeProfile } from "./fixtures.js";

const API = "http://localhost:8000";
const user = () => userEvent.setup({ delay: null });

async function gotoPlay(u) {
  await mountApp();
  await u.click(await screen.findByRole("button", { name: /enter your saved worlds/i }));
  await u.click(await screen.findByRole("button", { name: /^enter$/i }));
  await screen.findAllByText("The Last Breath");
}

const cmpBox = () => screen.getByRole("textbox", { name: /what you (do|say|look)/i });
const es = () => FakeEventSource.instances[FakeEventSource.instances.length - 1];
const story = () => document.querySelector("#storyStream");

beforeEach(() => {
  vi.stubGlobal("EventSource", FakeEventSource);
  FakeEventSource.instances.length = 0;
  document.querySelectorAll(".notice-stack, .toast").forEach((n) => n.remove());
});

// A controllable /action: resolves only when the test says so.
function pendingAction(payload) {
  let release;
  const gate = new Promise((res) => (release = res));
  server.use(
    http.post(`${API}/games/:id/action`, async () => {
      await gate;
      return payload instanceof HttpResponse ? payload : HttpResponse.json(payload);
    }),
  );
  return () => release();
}

test("prose streams into the story as it generates, then the real beat swaps in without doubling", async () => {
  const u = user();
  const finalBeat = makeBeat({ id: "n9", turn_index: 2, text: "The rain stops all at once, and the street goes quiet." });
  const release = pendingAction({ beats: [finalBeat], state: makeState(), stopped: false });
  await gotoPlay(u);
  await u.type(cmpBox(), "wait and listen");
  await u.click(screen.getByRole("button", { name: /send/i }));

  // the phase line says who is working, and the Stop button is offered
  es().emit({ kind: "phase", phase: "narrator" });
  await waitFor(() => expect(screen.getByText(/the narrator is writing/i)).toBeTruthy());
  expect(screen.getByRole("button", { name: /stop/i })).toBeTruthy();

  // streamed fragments GROW one narration in place - real streaming, no typewriter
  es().emit({ kind: "live_text", sid: "s1", op: "append", text: "The rain stops all at once,", speaker: "narrator", name: "Narrator", beat_kind: "narration", private_with: null });
  await waitFor(() => expect(within(story()).getByText(/The rain stops all at once,$/)).toBeTruthy());
  es().emit({ kind: "live_text", sid: "s1", op: "append", text: " and the street goes quiet.", speaker: "narrator", name: "Narrator", beat_kind: "narration", private_with: null });
  await waitFor(() => expect(within(story()).getByText(/street goes quiet\./)).toBeTruthy());
  expect(story().querySelector('[data-beat-id="live:s1"]')).toBeTruthy();

  // the stored beat lands: it takes the stream bubble's place, one copy only
  es().emit({ kind: "live_beat", beat: finalBeat });
  es().emit({ kind: "live_text_done", sid: "s1" });
  await waitFor(() => expect(story().querySelector('[data-beat-id="n9"]')).toBeTruthy());
  expect(story().querySelector('[data-beat-id^="live:"]')).toBeNull();

  // the POST resolves with the same beats: still one copy, indicator gone
  es().emit({ kind: "turn_done", turn_index: 2, stopped: false });
  release();
  await waitFor(() => expect(screen.queryByText(/the narrator is writing/i)).toBeNull());
  expect(screen.getAllByText(/street goes quiet\./).length).toBe(1);
});

test("the Stop button cancels the turn: rollback honored, streamed text gone, words restored", async () => {
  const u = user();
  let stopped = false;
  server.use(
    http.post(`${API}/games/:id/stop`, () => {
      stopped = true;
      return HttpResponse.json({ stopping: true });
    }),
  );
  const release = pendingAction({ beats: [], state: makeState(), stopped: true });
  await gotoPlay(u);
  await u.type(cmpBox(), "do something dramatic");
  await u.click(screen.getByRole("button", { name: /send/i }));
  es().emit({ kind: "phase", phase: "narrator" });
  es().emit({ kind: "live_text", sid: "s1", op: "append", text: "Words that will be taken back by the rollback.", speaker: "narrator", name: "Narrator", beat_kind: "narration", private_with: null });
  await waitFor(() => expect(within(story()).getByText(/taken back by the rollback/)).toBeTruthy());

  await u.click(await screen.findByRole("button", { name: /^stop$/i }));
  expect(stopped).toBe(true);
  await waitFor(() => expect(screen.getByText(/stopping/i)).toBeTruthy());

  es().emit({ kind: "turn_stopped" });
  es().emit({ kind: "turn_done", turn_index: null, stopped: true });
  release();
  // the turn never happened: streamed prose gone, echo gone, the player is told,
  // the lock lifts and the typed words return to the composer
  await waitFor(() => expect(document.querySelector(".toast")?.textContent).toMatch(/stopped/i));
  await waitFor(() => expect(document.querySelector("#cmpInput").getAttribute("contenteditable")).toBe("true"));
  expect(within(story()).queryByText(/taken back by the rollback/)).toBeNull();
  expect(within(story()).queryByText(/do something dramatic/)).toBeNull();
  await waitFor(() => expect(document.querySelector("#cmpInput").textContent).toBe("do something dramatic"));
});

test("the player's line never shows twice: the live canonical echo replaces the optimistic one", async () => {
  const u = user();
  const echo = makeBeat({ id: "e1", turn_index: 2, kind: "action", speaker: "player", speaker_name: null, text: "who is the ferryman?" });
  const release = pendingAction({ beats: [echo], state: makeState(), stopped: false });
  await gotoPlay(u);
  await u.type(cmpBox(), "who is the ferryman?");
  await u.click(screen.getByRole("button", { name: /send/i }));

  // the optimistic echo is on screen; then the canonical echo arrives LIVE,
  // mid-generation (live: the prompt showed repeated for the whole turn)
  await waitFor(() => expect(within(story()).getAllByText(/who is the ferryman\?/).length).toBe(1));
  es().emit({ kind: "live_beat", beat: echo });
  await waitFor(() => expect(story().querySelector('[data-beat-id="e1"]')).toBeTruthy());
  expect(within(story()).getAllByText(/who is the ferryman\?/).length).toBe(1);

  // and still exactly one after the POST resolves
  es().emit({ kind: "turn_done", turn_index: 2, stopped: false });
  release();
  await waitFor(() => expect(document.querySelector("#cmpInput").getAttribute("contenteditable")).toBe("true"));
  expect(within(story()).getAllByText(/who is the ferryman\?/).length).toBe(1);
});

test("a failed turn takes its live-streamed content back", async () => {
  const u = user();
  const release = pendingAction(HttpResponse.json({ detail: "the narrator choked" }, { status: 500 }));
  await gotoPlay(u);
  await u.type(cmpBox(), "poke the hornet nest");
  await u.click(screen.getByRole("button", { name: /send/i }));

  es().emit({ kind: "live_text", sid: "s1", op: "append", text: "A provisional sentence that will be rolled back.", speaker: "narrator", name: "Narrator", beat_kind: "narration", private_with: null });
  es().emit({ kind: "live_beat", beat: makeBeat({ id: "doomed", turn_index: 2, kind: "system", speaker: "system", speaker_name: null, text: "An uncommitted receipt." }) });
  await waitFor(() => expect(within(story()).getByText(/provisional sentence/)).toBeTruthy());

  release();
  await waitFor(() => expect(screen.queryByText(/provisional sentence/)).toBeNull());
  expect(screen.queryByText(/An uncommitted receipt/)).toBeNull();
  expect(document.querySelector('[data-beat-id^="live:"]')).toBeNull();
});

test("a whisper streams into the private thread, never the public story", async () => {
  const u = user();
  server.use(
    http.get(`${API}/games/:id/characters/:cid/profile`, () => HttpResponse.json(makeProfile())),
  );
  const release = pendingAction({ beats: [], state: makeState(), stopped: false });
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /open jacker's profile/i }));
  await screen.findByRole("dialog", { name: /jacker's profile/i });
  const profileEl = () => document.querySelector(".profile-screen");
  await waitFor(() => expect(within(profileEl()).getByRole("tab", { name: /whisper/i })).toBeTruthy());
  await u.click(within(profileEl()).getByRole("tab", { name: /whisper/i }));
  await u.type(within(profileEl()).getByRole("textbox", { name: /what you say/i }), "what do you know");
  await u.keyboard("{Enter}");

  // the canonical PRIVATE echo arrives live: it replaces the optimistic one in
  // the thread instead of doubling it (same bug class as the public story)
  const pmEcho = makeBeat({ id: "we1", turn_index: 2, kind: "action", speaker: "player", speaker_name: null, text: 'you whisper to Jacker: "what do you know"', private_with: "c1" });
  es().emit({ kind: "live_beat", beat: pmEcho });
  await waitFor(() => expect(document.querySelector('[data-beat-id="we1"]')).toBeTruthy());
  expect(within(document.querySelector("#pmThread")).getAllByText(/what do you know/).length).toBe(1);

  es().emit({ kind: "live_text", sid: "w1", op: "append", text: "Not here. The walls listen.", speaker: "c1", name: "Jacker", beat_kind: "dialogue", private_with: "c1" });
  await waitFor(() => expect(within(document.querySelector("#pmThread")).getByText(/The walls listen/)).toBeTruthy());
  expect(within(story()).queryByText(/The walls listen/)).toBeNull();
  release();
});

test("the unread whisper badge counts literal messages only - never actions, receipts or memories", async () => {
  const u = user();
  await gotoPlay(u);
  const cardBadge = () => document.querySelector('.char-col[data-char-id="c1"] .pm-unread');
  const priv = (over) => makeBeat({ turn_index: 5, speaker: "c1", speaker_name: "Jacker", private_with: "c1", ...over });

  // an action, a gift receipt and a trait event land privately, then ONE literal
  // whispered line: the badge must say exactly 1 (a count of 4 means the
  // non-messages counted; private beats render nowhere until the thread opens,
  // so the badge is the only observable)
  es().emit({ kind: "live_beat", beat: priv({ id: "pa1", kind: "action", text: "He slides the ledger across." }) });
  es().emit({ kind: "live_beat", beat: priv({ id: "ps1", kind: "system", speaker: "system", speaker_name: null, text: "Obtained: sealed ledger." }) });
  es().emit({ kind: "live_beat", beat: priv({ id: "ps2", kind: "system", speaker: "system", speaker_name: null, text: "Trait unlocked: Jacker - keeps receipts." }) });
  es().emit({ kind: "live_beat", beat: priv({ id: "pd1", kind: "dialogue", text: "Keep this between us." }) });
  await waitFor(() => expect(cardBadge()?.textContent).toBe("1"));
});

test("a turn taken elsewhere (no POST of ours) still lands live and reconciles on turn_done", async () => {
  const u = user();
  await gotoPlay(u);
  const beat = makeBeat({ id: "remote1", turn_index: 4, text: "Somewhere, another hand moves the story." });
  es().emit({ kind: "phase", phase: "narrator" });
  es().emit({ kind: "live_beat", beat });
  await waitFor(() => expect(within(story()).getByText(/another hand moves the story/)).toBeTruthy());
  es().emit({ kind: "turn_done", turn_index: 4, stopped: false });
  // reconciliation keeps exactly one copy and clears the phase line
  await waitFor(() => expect(screen.queryByText(/the narrator is writing/i)).toBeNull());
  expect(screen.getAllByText(/another hand moves the story/).length).toBe(1);
});

// ---------------------------------------------------------------------------
// autoplay follows the eyes (owner 2026-07-21): a PUBLIC line autoplays only
// while no whisper window is open; a PRIVATE line only inside ITS whisper
// window. Playback goes through the queue (playQueued), never playUrl.
// ---------------------------------------------------------------------------

test("a public live line does NOT autoplay while a whisper window is open; it does once closed", async () => {
  const u = user();
  server.use(http.get(`${API}/games/:id/characters/:cid/profile`, () => HttpResponse.json(makeProfile())));
  const app = await mountApp();
  await u.click(await screen.findByRole("button", { name: /enter your saved worlds/i }));
  await u.click(await screen.findByRole("button", { name: /^enter$/i }));
  await screen.findAllByText("The Last Breath");
  app.state.settings.autoplayNarrator = true;
  const prepared = vi.spyOn(app.voice, "prepare").mockResolvedValue({ audioUrl: "/audio/n.wav", duration: 1 });
  const queued = vi.spyOn(app.voice, "playQueued").mockResolvedValue(undefined);

  // into Jacker's whisper window
  await u.click(screen.getByRole("button", { name: /open jacker's profile/i }));
  await screen.findByRole("dialog", { name: /jacker's profile/i });
  await waitFor(() => expect(within(document.querySelector(".profile-screen")).getByRole("tab", { name: /whisper/i })).toBeTruthy());
  await u.click(within(document.querySelector(".profile-screen")).getByRole("tab", { name: /whisper/i }));

  // a public narration lands live: eyes are in the whisper window, so SILENCE
  es().emit({ kind: "live_beat", beat: makeBeat({ id: "pub1", turn_index: 3, text: "Far off, the market roars." }) });
  await waitFor(() => expect(app.state.active.beats.some((b) => b.id === "pub1")).toBe(true));
  expect(prepared).not.toHaveBeenCalled();
  expect(queued).not.toHaveBeenCalled();

  // back to the scene: the next public line speaks, through the QUEUE
  await u.click(within(document.querySelector(".profile-screen")).getByRole("button", { name: /back to the scene/i }));
  es().emit({ kind: "live_beat", beat: makeBeat({ id: "pub2", turn_index: 3, text: "The rain returns." }) });
  await waitFor(() => expect(queued).toHaveBeenCalledWith("/audio/n.wav", "narrator"));
  expect(prepared).toHaveBeenCalledTimes(1);
});

test("a private live line autoplays ONLY inside its whisper window", async () => {
  const u = user();
  const voiced = makeState();
  voiced.characters[0].voice_id = "vx-jacker";
  server.use(
    http.get(`${API}/games/:id/state`, () => HttpResponse.json(voiced)),
    http.get(`${API}/games/:id/characters/:cid/profile`, () => HttpResponse.json(makeProfile())),
  );
  const app = await mountApp();
  await u.click(await screen.findByRole("button", { name: /enter your saved worlds/i }));
  await u.click(await screen.findByRole("button", { name: /^enter$/i }));
  await screen.findAllByText("The Last Breath");
  app.state.settings.autoplayCharacters = true;
  const prepared = vi.spyOn(app.voice, "prepare").mockResolvedValue({ audioUrl: "/audio/w.wav", duration: 1 });
  const queued = vi.spyOn(app.voice, "playQueued").mockResolvedValue(undefined);
  const priv = (id, text) => makeBeat({ id, turn_index: 3, kind: "dialogue", speaker: "c1",
    speaker_name: "Jacker", text, private_with: "c1", emotion: "whisper" });

  // whisper window CLOSED: the private line stays silent
  es().emit({ kind: "live_beat", beat: priv("pw1", "They must not hear this.") });
  await waitFor(() => expect(app.state.active.beats.some((b) => b.id === "pw1")).toBe(true));
  expect(prepared).not.toHaveBeenCalled();
  expect(queued).not.toHaveBeenCalled();

  // inside Jacker's whisper window: the next private line speaks, queued
  await u.click(screen.getByRole("button", { name: /open jacker's profile/i }));
  await screen.findByRole("dialog", { name: /jacker's profile/i });
  await waitFor(() => expect(within(document.querySelector(".profile-screen")).getByRole("tab", { name: /whisper/i })).toBeTruthy());
  await u.click(within(document.querySelector(".profile-screen")).getByRole("tab", { name: /whisper/i }));
  es().emit({ kind: "live_beat", beat: priv("pw2", "Good. Lean closer.") });
  await waitFor(() => expect(queued).toHaveBeenCalledWith("/audio/w.wav", "c1"));
  expect(prepared).toHaveBeenCalledTimes(1);
});

test("a stacked turn's echoes land one per line, in place, each keeping its own shape", async () => {
  const u = user();
  // the wire echoes ONE player beat PER stacked line, in stack order
  const wireEchoes = [
    makeBeat({ id: "e1", turn_index: 2, seq: 0, kind: "action", speaker: "player", speaker_name: null, text: "check the door" }),
    makeBeat({ id: "e2", turn_index: 2, seq: 1, kind: "action", speaker: "player", speaker_name: null, text: 'you say "we should run"' }),
    makeBeat({ id: "e3", turn_index: 2, seq: 2, kind: "action", speaker: "player", speaker_name: null, text: "bolt for the window" }),
  ];
  const narration = makeBeat({ id: "n1", turn_index: 2, seq: 3, text: "You bolt." });
  const release = pendingAction({ beats: [...wireEchoes, narration], state: makeState(), stopped: false });
  await gotoPlay(u);
  // stack [do, say] and send with a third DO line: one turn, three lines
  await u.click(screen.getByRole("button", { name: /^do$/i }));
  await u.type(cmpBox(), "check the door");
  await u.click(screen.getByRole("button", { name: /stack this line/i }));
  await u.click(screen.getByRole("button", { name: /^say$/i }));
  await u.type(cmpBox(), "we should run");
  await u.click(screen.getByRole("button", { name: /stack this line/i }));
  await u.click(screen.getByRole("button", { name: /^do$/i }));
  await u.type(cmpBox(), "bolt for the window");
  await u.click(screen.getByRole("button", { name: /send/i }));

  // three optimistic lines show, in the stacked order
  await waitFor(() => expect(document.querySelectorAll('#storyStream [data-beat-id^="pending-"]').length).toBe(3));

  // the canonical echoes stream in: each replaces its twin IN PLACE (appending
  // them scrambled the stack's order for as long as the narrator kept writing)
  for (const e of wireEchoes) es().emit({ kind: "live_beat", beat: e });
  await waitFor(() => expect(story().querySelector('[data-beat-id="e3"]')).toBeTruthy());
  expect(document.querySelectorAll('[data-beat-id^="pending-"]').length).toBe(0);

  // order preserved: do, say, do - and the SAY still renders as a speech bubble
  const ids = [...story().querySelectorAll("[data-beat-id]")].map((n) => n.getAttribute("data-beat-id"));
  expect(ids.filter((id) => /^e\d$/.test(id))).toEqual(["e1", "e2", "e3"]);
  expect(story().querySelector('[data-beat-id="e2"] .bubble')).toBeTruthy();
  expect(story().querySelector('[data-beat-id="e1"] .bubble')).toBeFalsy(); // a do stays an act row

  // whatever streams next stays BELOW the echoes
  es().emit({ kind: "live_beat", beat: narration });
  await waitFor(() => expect(story().querySelector('[data-beat-id="n1"]')).toBeTruthy());
  const posAfter = story().querySelector('[data-beat-id="e3"]').compareDocumentPosition(story().querySelector('[data-beat-id="n1"]'));
  expect(posAfter & 4).toBeTruthy(); // DOCUMENT_POSITION_FOLLOWING: echoes first, narration after

  // the POST resolves with the same beats: still exactly one copy of each line
  es().emit({ kind: "turn_done", turn_index: 2, stopped: false });
  release();
  await waitFor(() => expect(screen.getAllByText(/we should run/).length).toBe(1));
  expect(screen.getAllByText(/check the door/).length).toBe(1);
});
