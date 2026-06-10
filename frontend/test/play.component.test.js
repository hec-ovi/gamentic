// Component / integration tests: mount the REAL app, drive it like a player with
// user-event, and intercept the network with MSW. Asserts the living-scene
// rendering, the integrated deck, the composer (chips, stacking), the private
// modal, the busy-lock, and the turn flow.

import { test, expect, beforeEach } from "vitest";
import { screen, within, waitFor } from "@testing-library/dom";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse, delay } from "msw";
import { server, mountApp } from "./setup.js";
import { makeState, makeBeat } from "./fixtures.js";

const API = "http://localhost:8000";
const user = () => userEvent.setup({ delay: null });

// menu -> library -> into the (only) game -> play view rendered
async function gotoPlay(u) {
  await mountApp();
  await u.click(await screen.findByRole("button", { name: /enter your saved worlds/i }));
  await u.click(await screen.findByRole("button", { name: /^enter$/i }));
  // scene name renders in the deck (and possibly again as the art caption)
  await screen.findAllByText("The Last Breath");
}

const composerLive = () =>
  expect(document.querySelector("#cmpInput").getAttribute("contenteditable")).toBe("true");

beforeEach(() => {
  document
    .querySelectorAll(".notice-stack, .toast, .help-pop, .tagger-pop, .see-pop, .lightbox-overlay")
    .forEach((n) => n.remove());
});

test("library lists games from the network and entering one shows the living scene", async () => {
  const u = user();
  await mountApp();
  await u.click(await screen.findByRole("button", { name: /enter your saved worlds/i }));
  // the game card from GET /games
  expect(await screen.findByText("Test Adventure")).toBeTruthy();
  await u.click(await screen.findByRole("button", { name: /^enter$/i }));

  // ONE integrated deck: scene identity, goal, vitals, clock, memory meter
  expect(await screen.findByText("The Last Breath")).toBeTruthy();
  const deck = document.querySelector(".play-deck");
  expect(deck).toBeTruthy();
  expect(within(deck).getByText(/Find the brass key/)).toBeTruthy();
  expect(within(deck).getByText("Day 1, morning")).toBeTruthy();
  expect(deck.querySelector(".ctx-meter")).toBeTruthy();
  // exactly one goal chip and one mood badge anywhere (no repeated affordances)
  expect(document.querySelectorAll(".hud-goal").length).toBe(1);
  expect(document.querySelectorAll(".mood-badge").length).toBe(1);
  // the present character renders as a tall column
  const col = document.querySelector('.char-col[data-char-id="c1"]');
  expect(col).toBeTruthy();
  expect(within(col).getByText("Jacker")).toBeTruthy();
  // dead end (no exits)
  expect(document.querySelector(".dead-end")).toBeTruthy();
});

test("a free-text Do turn posts a plain action and appends the new narration beat", async () => {
  const u = user();
  let body;
  server.use(
    http.post(`${API}/games/:id/action`, async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ beats: [makeBeat({ id: "n2", text: "The door creaks open." })], state: makeState() });
    }),
  );
  await gotoPlay(u);
  await u.type(screen.getByRole("textbox"), "open the door");
  await u.click(screen.getByRole("button", { name: /send/i }));

  await waitFor(() => expect(screen.getByText("The door creaks open.")).toBeTruthy());
  expect(body).toEqual({ action: "open the door" });
});

test("Say mode sends a say segment instead of a plain action", async () => {
  const u = user();
  let body;
  server.use(
    http.post(`${API}/games/:id/action`, async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ beats: [makeBeat({ text: "ok" })], state: makeState() });
    }),
  );
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /^say$/i }));
  await u.type(screen.getByRole("textbox"), "hello room");
  await u.click(screen.getByRole("button", { name: /send/i }));
  await waitFor(() => expect(body).toBeTruthy());
  expect(body.segments).toEqual([{ type: "say", text: "hello room" }]);
});

test("busy-lock: while a turn is in flight everything is blocked, then unlocks", async () => {
  const u = user();
  let posts = 0;
  server.use(
    http.post(`${API}/games/:id/action`, async () => {
      posts += 1;
      await delay(60);
      return HttpResponse.json({ beats: [makeBeat({ text: "Resolved." })], state: makeState() });
    }),
  );
  await gotoPlay(u);
  await u.type(screen.getByRole("textbox"), "wait");
  await u.click(screen.getByRole("button", { name: /send/i }));
  // mid-turn: composer locked, veil up, thinking shown
  expect(screen.getByRole("textbox").getAttribute("contenteditable")).toBe("false");
  expect(document.querySelector(".busy-veil")).toBeTruthy();
  expect(screen.getByText(/the narrator is thinking/i)).toBeTruthy();
  // every other affordance is disabled; clicking one fires nothing
  const search = screen.getByRole("button", { name: /^search$/i });
  expect(search.disabled).toBe(true);
  await u.click(search).catch(() => {});
  // after: unlocked, and only the one POST went out
  await waitFor(composerLive);
  expect(document.querySelector(".busy-veil")).toBeNull();
  expect(posts).toBe(1);
});

test("tagging an entity chips it into the line and sends segments with refs", async () => {
  const u = user();
  let body;
  server.use(
    http.post(`${API}/games/:id/action`, async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ beats: [makeBeat({ text: "ok" })], state: makeState() });
    }),
  );
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /tag a character or item/i }));
  // the tagger lists the present character and the player's item
  const pop = document.querySelector(".tagger-pop");
  expect(pop).toBeTruthy();
  expect(within(pop).getByText("Jacker")).toBeTruthy();
  expect(within(pop).getByText("credstick")).toBeTruthy();
  await u.click(within(pop).getByText("Jacker"));
  // the chip is in the line, non-editable, character-flavored
  const chip = document.querySelector("#cmpInput .ent-chip");
  expect(chip).toBeTruthy();
  expect(chip.getAttribute("contenteditable")).toBe("false");
  expect(chip.classList.contains("chip-character")).toBe(true);

  await u.type(screen.getByRole("textbox"), " follow me");
  await u.click(screen.getByRole("button", { name: /send/i }));
  await waitFor(() => expect(body).toBeTruthy());
  expect(body.segments).toEqual([
    { type: "do", text: "Jacker follow me", refs: [{ kind: "character", id: "c1", name: "Jacker" }] },
  ]);
});

test("stacking composes several segments that execute together as ONE turn", async () => {
  const u = user();
  let body;
  let posts = 0;
  server.use(
    http.post(`${API}/games/:id/action`, async ({ request }) => {
      posts += 1;
      body = await request.json();
      return HttpResponse.json({ beats: [makeBeat({ text: "ok" })], state: makeState() });
    }),
  );
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /^say$/i }));
  await u.type(screen.getByRole("textbox"), "we should run");
  await u.click(screen.getByRole("button", { name: /stack this line/i }));
  // the stacked row renders and is removable
  expect(document.querySelector(".seg-stack .seg-row")).toBeTruthy();
  // second line in Do mode
  await u.click(screen.getByRole("button", { name: /^do$/i }));
  await u.type(screen.getByRole("textbox"), "bolt for the door");
  await u.click(screen.getByRole("button", { name: /send/i }));

  await waitFor(() => expect(body).toBeTruthy());
  expect(posts).toBe(1);
  expect(body.segments).toEqual([
    { type: "say", text: "we should run" },
    { type: "do", text: "bolt for the door" },
  ]);
});

test("loot items send a 'take', scenery items send an 'examine' (the fixed flag)", async () => {
  const u = user();
  const withItems = makeState({
    scene: {
      id: "sc1",
      name: "The Last Breath",
      description: "d",
      status: "tense",
      exits: [],
      available_actions: [],
      items: [
        { id: "i1", name: "brass key", description: "", fixed: false },
        { id: "i2", name: "iron altar", description: "", fixed: true },
      ],
    },
  });
  server.use(http.get(`${API}/games/:id/state`, () => HttpResponse.json(withItems)));
  let body;
  server.use(
    http.post(`${API}/games/:id/action`, async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ beats: [makeBeat({ text: "ok" })], state: withItems });
    }),
  );
  await gotoPlay(u);

  // loot: tap -> inspect modal -> Take
  await u.click(screen.getByRole("button", { name: /inspect brass key/i }));
  let modal = await screen.findByRole("dialog", { name: /brass key/i });
  expect(within(modal).getByText(/can be taken/i)).toBeTruthy();
  await u.click(within(modal).getByRole("button", { name: /take brass key/i }));
  await waitFor(() => expect(body).toBeTruthy());
  expect(body.segments[0]).toMatchObject({ type: "do" });
  expect(body.segments[0].text).toMatch(/take/i);
  expect(body.segments[0].text).toMatch(/brass key/i);
  expect(screen.queryByRole("dialog")).toBeNull(); // acting closes the modal
  await waitFor(composerLive); // let the turn fully resolve before the next action

  // scenery: tap -> inspect modal -> Examine (no Take offered)
  body = null;
  await u.click(screen.getByRole("button", { name: /inspect iron altar/i }));
  modal = await screen.findByRole("dialog", { name: /iron altar/i });
  expect(within(modal).getByText(/part of the scene/i)).toBeTruthy();
  expect(within(modal).queryByRole("button", { name: /take/i })).toBeNull();
  await u.click(within(modal).getByRole("button", { name: /examine iron altar/i }));
  await waitFor(() => expect(body).toBeTruthy());
  expect(body.segments[0].text).toMatch(/examine/i);
});

test("tap-to-inspect: an inventory item expands and 'ask what this is' fetches the narrator's aside", async () => {
  const u = user();
  let explainBody;
  server.use(
    http.post(`${API}/games/:id/explain`, async ({ request }) => {
      explainBody = await request.json();
      return HttpResponse.json({ text: "A chipped credstick, forty-two creds of someone else's bad week." });
    }),
  );
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /inspect credstick/i }));
  const modal = await screen.findByRole("dialog", { name: /credstick/i });
  expect(within(modal).getByText(/in your pack/i)).toBeTruthy();
  await u.click(within(modal).getByRole("button", { name: /ask what this is/i }));
  expect(await screen.findByText(/forty-two creds/i)).toBeTruthy();
  expect(explainBody).toEqual({ kind: "item", key: "inv1" }); // the id, not the name
});

test("tap-to-inspect: 404 from /explain reads as 'nothing more can be seen'", async () => {
  const u = user();
  server.use(http.post(`${API}/games/:id/explain`, () => new HttpResponse(null, { status: 404 })));
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /inspect credstick/i }));
  const modal = await screen.findByRole("dialog", { name: /credstick/i });
  await u.click(within(modal).getByRole("button", { name: /ask what this is/i }));
  expect(await screen.findByText(/nothing more can be seen/i)).toBeTruthy();
});

test("tap-to-inspect: a character card expands with disposition and asks about them", async () => {
  const u = user();
  let explainBody;
  server.use(
    http.post(`${API}/games/:id/explain`, async ({ request }) => {
      explainBody = await request.json();
      return HttpResponse.json({ text: "The bartender who has seen everything and says nothing." });
    }),
  );
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /inspect jacker/i }));
  const modal = await screen.findByRole("dialog", { name: /jacker/i });
  expect(within(modal).getByText("neutral")).toBeTruthy();
  expect(within(modal).getByText(/watchful bartender/i)).toBeTruthy();
  await u.click(within(modal).getByRole("button", { name: /ask what this is/i }));
  expect(await screen.findByText(/says nothing/i)).toBeTruthy();
  expect(explainBody).toEqual({ kind: "character", key: "c1" });
});

test("the goal chip opens the quest log; a quest expands to its objectives and can be asked about", async () => {
  const u = user();
  let explainBody;
  server.use(
    http.post(`${API}/games/:id/explain`, async ({ request }) => {
      explainBody = await request.json();
      return HttpResponse.json({ text: "The back room hides what you came for." });
    }),
  );
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /find the brass key/i }));
  const goalModal = await screen.findByRole("dialog", { name: /current goal/i });
  expect(within(goalModal).getByText("Find the brass key")).toBeTruthy();
  // the quest row -> the quest detail with its checklist
  await u.click(within(goalModal).getByRole("button", { name: /the brass key/i }));
  const questModal = await screen.findByRole("dialog", { name: /the brass key/i });
  expect(within(questModal).getByText(/get into the back room/i)).toBeTruthy();
  expect(within(questModal).getByText("Find the brass key")).toBeTruthy(); // the objective row
  await u.click(within(questModal).getByRole("button", { name: /ask what this is/i }));
  expect(await screen.findByText(/hides what you came for/i)).toBeTruthy();
  expect(explainBody).toEqual({ kind: "quest", key: "q1" });
});

test("a system receipt beat is tappable and asks with its beat_id", async () => {
  const u = user();
  let explainBody;
  server.use(
    http.post(`${API}/games/:id/action`, () =>
      HttpResponse.json({ beats: [makeBeat({ id: "sys9", kind: "system", speaker: "system", text: "Obtained: brass key." })], state: makeState() }),
    ),
    http.post(`${API}/games/:id/explain`, async ({ request }) => {
      explainBody = await request.json();
      return HttpResponse.json({ text: "The key you pried from the bar's underside." });
    }),
  );
  await gotoPlay(u);
  await u.type(screen.getByRole("textbox"), "grab it");
  await u.click(screen.getByRole("button", { name: /send/i }));
  await u.click(await screen.findByText("Obtained: brass key."));
  const modal = await screen.findByRole("dialog", { name: /what just happened/i });
  expect(within(modal).getByText("Obtained: brass key.")).toBeTruthy();
  await u.click(within(modal).getByRole("button", { name: /ask what this is/i }));
  expect(await screen.findByText(/pried from the bar/i)).toBeTruthy();
  expect(explainBody).toEqual({ kind: "beat", beat_id: "sys9" });
});

test("Talk opens the modal over the scene and routes a directed 'say'; the reply shows in the thread", async () => {
  const u = user();
  let body;
  server.use(
    http.post(`${API}/games/:id/action`, async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({
        beats: [makeBeat({ kind: "dialogue", speaker: "c1", speaker_name: "Jacker", text: "Aye." })],
        state: makeState(),
      });
    }),
  );
  await gotoPlay(u);
  const col = document.querySelector('.char-col[data-char-id="c1"]');
  await u.click(within(col).getByRole("button", { name: /^talk$/i }));

  // the modal is OVER the scene and the main composer is gone
  const modal = await screen.findByRole("dialog", { name: /talk to jacker/i });
  expect(document.querySelector('[data-form="action"]')).toBeNull();

  await u.type(within(modal).getByRole("textbox"), "you there?");
  await u.click(within(modal).getByRole("button", { name: /execute/i }));
  await waitFor(() => expect(body).toBeTruthy());
  expect(body.segments).toEqual([{ type: "say", text: "you there?", target: "Jacker" }]);
  // the modal stays open and the character's answer lands in its thread
  await waitFor(() => expect(within(document.querySelector("#pmThread")).getByText("Aye.")).toBeTruthy());
});

test("Whisper sends private segments; the secret renders in the modal, never in the public story", async () => {
  const u = user();
  let body;
  server.use(
    http.post(`${API}/games/:id/action`, async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({
        beats: [makeBeat({ kind: "dialogue", speaker: "c1", speaker_name: "Jacker", text: "Under the stool.", private_with: "c1" })],
        state: makeState(),
      });
    }),
  );
  await gotoPlay(u);
  const col = document.querySelector('.char-col[data-char-id="c1"]');
  await u.click(within(col).getByRole("button", { name: /^whisper$/i }));

  const modal = await screen.findByRole("dialog", { name: /whisper to jacker/i });
  expect(modal.classList.contains("is-whisper")).toBe(true);

  await u.type(within(modal).getByRole("textbox"), "tell me the secret");
  await u.click(within(modal).getByRole("button", { name: /execute/i }));
  await waitFor(() => expect(body).toBeTruthy());
  expect(body.segments).toEqual([{ type: "whisper", text: "tell me the secret", target: "Jacker", mode: "say" }]);

  // the private reply lives in the modal thread...
  await waitFor(() => expect(within(document.querySelector("#pmThread")).getByText("Under the stool.")).toBeTruthy());
  // ...and after closing, the public story still never shows it
  await u.click(within(modal).getByRole("button", { name: /^close$/i }));
  expect(document.querySelector("#pmThread")).toBeNull();
  expect(within(document.querySelector("#storyStream")).queryByText("Under the stool.")).toBeNull();
});

test("the modal's Do mode whispers a discreet private action (mode: do)", async () => {
  const u = user();
  let body;
  server.use(
    http.post(`${API}/games/:id/action`, async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ beats: [makeBeat({ text: "ok", private_with: "c1" })], state: makeState() });
    }),
  );
  await gotoPlay(u);
  const col = document.querySelector('.char-col[data-char-id="c1"]');
  await u.click(within(col).getByRole("button", { name: /^whisper$/i }));
  const modal = await screen.findByRole("dialog", { name: /whisper to jacker/i });
  await u.click(within(modal).getByRole("button", { name: /^do$/i }));
  await u.type(within(modal).getByRole("textbox"), "slip him the key");
  await u.click(within(modal).getByRole("button", { name: /execute/i }));
  await waitFor(() => expect(body).toBeTruthy());
  expect(body.segments).toEqual([{ type: "whisper", text: "slip him the key", target: "Jacker", mode: "do" }]);
});

test("Give opens an item picker and sends a give segment with the item id", async () => {
  const u = user();
  let body;
  server.use(
    http.post(`${API}/games/:id/action`, async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ beats: [makeBeat({ text: "Taken." })], state: makeState() });
    }),
  );
  await gotoPlay(u);
  const col = document.querySelector('.char-col[data-char-id="c1"]');
  await u.click(within(col).getByRole("button", { name: /give/i }));
  // picker lists the player's inventory item; the segment carries its id
  const pick = await screen.findByRole("button", { name: /^credstick$/i });
  await u.click(pick);
  await waitFor(() => expect(body).toBeTruthy());
  expect(body.segments[0]).toEqual({ type: "give", item: "inv1", target: "Jacker" });
});

test("a turn that reveals an exit shows a transition notice and the exit becomes clickable", async () => {
  const u = user();
  const moved = makeState({
    scene: {
      id: "sc1",
      name: "The Last Breath",
      description: "d",
      status: "tense",
      items: [],
      available_actions: [],
      exits: [{ id: "e1", label: "the back room", target: "back" }],
    },
  });
  server.use(
    http.post(`${API}/games/:id/action`, () => HttpResponse.json({ beats: [makeBeat({ text: "A door clicks." })], state: moved })),
  );
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /^search$/i }));
  // notice fires for the newly revealed way out
  expect(await screen.findByText(/A way opens: the back room/i)).toBeTruthy();
  // and the exit is now a button
  expect(screen.getByRole("button", { name: /the back room/i })).toBeTruthy();
});

test("art polling fills the scene image into the prose once it is generated", async () => {
  const u = user();
  const pending = makeState({ images_enabled: true });
  const ready = makeState({
    images_enabled: true,
    scene: { id: "sc1", name: "The Last Breath", description: "d", status: "tense", image_url: "/media/g/scene.png", exits: [], items: [], available_actions: [] },
  });
  let calls = 0;
  server.use(
    http.get(`${API}/games/:id/state`, () => {
      calls += 1;
      return HttpResponse.json(calls > 1 ? ready : pending);
    }),
  );
  await gotoPlay(u);
  // images on + no art yet -> a loader card in the story
  expect(document.querySelector("#storyStream .prose-art.art-loading")).toBeTruthy();
  // the poll (2.5s interval) swaps the real image in
  await waitFor(() => expect(document.querySelector('#storyStream .prose-art img[src="/media/g/scene.png"]')).toBeTruthy(), {
    timeout: 7000,
  });
}, 10000);

// state override with images enabled + scene art present (no poll loader noise)
const IMAGED = () =>
  makeState({
    images_enabled: true,
    scene: { id: "sc1", name: "The Last Breath", description: "d", status: "tense", image_url: "/media/g/scene.png", exits: [], items: [], available_actions: [] },
  });

test("See asks for an optional focus, locks the button, and the image beat lands with its caption", async () => {
  const u = user();
  let viewBody = "unset";
  server.use(
    http.get(`${API}/games/:id/state`, () => HttpResponse.json(IMAGED())),
    http.post(`${API}/games/:id/view`, async ({ request }) => {
      viewBody = await request.text();
      await delay(50);
      return HttpResponse.json({
        beat: makeBeat({ id: "img1", kind: "image", text: "", image_url: "/media/g-test/view1.png" }),
        image_url: "/media/g-test/view1.png",
      });
    }),
  );
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /see the scene/i }));
  // the focus popover: empty = the whole scene
  const focusInput = await screen.findByLabelText(/look at what/i);
  await u.click(within(focusInput.closest("form")).getByRole("button", { name: /^see$/i }));
  // in flight: loader + lock (one at a time)
  await waitFor(() => expect(document.querySelector(".see-btn.seeing")).toBeTruthy());
  expect(document.querySelector(".see-btn").disabled).toBe(true);
  // the image beat lands inline in the story and the button unlocks
  await waitFor(() => expect(document.querySelector('.beat-image img[src="/media/g-test/view1.png"]')).toBeTruthy());
  expect(viewBody).toBe(""); // empty focus -> no body
  expect(document.querySelector(".beat-image figcaption")).toBeNull(); // empty text -> no caption
  expect(document.querySelector(".see-btn.seeing")).toBeNull();
  expect(document.querySelector(".see-btn").disabled).toBe(false);
});

test("a typed focus rides the request body and renders as the image caption", async () => {
  const u = user();
  let viewBody;
  server.use(
    http.get(`${API}/games/:id/state`, () => HttpResponse.json(IMAGED())),
    http.post(`${API}/games/:id/view`, async ({ request }) => {
      viewBody = await request.json();
      return HttpResponse.json({
        beat: makeBeat({ id: "img2", kind: "image", text: "what Jacker is doing", image_url: "/media/g-test/view2.png" }),
        image_url: "/media/g-test/view2.png",
      });
    }),
  );
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /see the scene/i }));
  const focusInput = await screen.findByLabelText(/look at what/i);
  await u.type(focusInput, "what Jacker is doing");
  await u.click(within(focusInput.closest("form")).getByRole("button", { name: /^see$/i }));

  await waitFor(() => expect(viewBody).toEqual({ focus: "what Jacker is doing" }));
  await waitFor(() => {
    const cap = document.querySelector(".beat-image figcaption");
    expect(cap).toBeTruthy();
    expect(cap.textContent).toMatch(/what Jacker is doing/);
  });
});

test("See on a downed image service toasts 'the vision fades' and re-enables", async () => {
  const u = user();
  server.use(
    http.get(`${API}/games/:id/state`, () => HttpResponse.json(IMAGED())),
    http.post(`${API}/games/:id/view`, () => new HttpResponse(null, { status: 502 })),
  );
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /see the scene/i }));
  const focusInput = await screen.findByLabelText(/look at what/i);
  await u.click(within(focusInput.closest("form")).getByRole("button", { name: /^see$/i }));
  await waitFor(() => expect(document.querySelector(".toast")).toBeTruthy());
  expect(document.querySelector(".toast").textContent).toMatch(/the vision fades/i);
  expect(document.querySelector(".see-btn").disabled).toBe(false);
  expect(document.querySelector(".beat-image")).toBeNull();
});

test("there is NO See button when images are disabled (fixture default)", async () => {
  const u = user();
  await gotoPlay(u); // makeState() has images_enabled: false
  expect(document.querySelector(".see-btn")).toBeNull();
});

test("a game image that fails to load is retried with a cache-buster (file still persisting)", async () => {
  const u = user();
  const withImages = makeState({
    images_enabled: true,
    scene: { id: "sc1", name: "The Last Breath", description: "d", status: "tense", image_url: "/media/g/scene.png", exits: [], items: [], available_actions: [] },
  });
  server.use(http.get(`${API}/games/:id/state`, () => HttpResponse.json(withImages)));
  await gotoPlay(u);
  const img = document.querySelector('#storyStream .prose-art img');
  expect(img).toBeTruthy();
  img.dispatchEvent(new Event("error")); // jsdom never loads images; simulate the failure
  await waitFor(() => expect(img.getAttribute("src")).toBe("/media/g/scene.png?r=1"), { timeout: 2500 });
}, 6000);

test("staged reveal: system beats land instantly, prose types, later beats wait their turn", async () => {
  const u = user();
  server.use(
    http.post(`${API}/games/:id/action`, () =>
      HttpResponse.json({
        beats: [
          makeBeat({ id: "s1", kind: "system", speaker: "system", text: "You gain a key." }),
          makeBeat({ id: "n1", kind: "narration", text: "The lock clicks open and the corridor breathes out cold air." }),
          makeBeat({ id: "d1", kind: "dialogue", speaker: "c1", speaker_name: "Jacker", text: "Careful now." }),
        ],
        state: makeState(),
      }),
    ),
  );
  await gotoPlay(u);
  await u.type(screen.getByRole("textbox"), "open the lock");
  await u.click(screen.getByRole("button", { name: /send/i }));

  // the system beat shows as soon as the turn lands...
  await screen.findByText("You gain a key.");
  // ...while the dialogue is still veiled behind the typing narration
  const dlgVeil = document.querySelector('[data-beat-id="d1"]').closest(".veil-wrap");
  expect(dlgVeil).toBeTruthy();
  expect(dlgVeil.classList.contains("veiled")).toBe(true);
  // then everything lands, in order
  await waitFor(
    () => expect(document.querySelector('[data-beat-id="d1"]').closest(".veil-wrap").classList.contains("veiled")).toBe(false),
    { timeout: 5000 },
  );
  await waitFor(() => expect(screen.getByText("Careful now.")).toBeTruthy());
  await waitFor(() => expect(screen.getByText(/corridor breathes out cold air/)).toBeTruthy());
}, 10000);

test("a story click instant-finishes the staged reveal", async () => {
  const u = user();
  const LONG = "A very long passage that would take several seconds to type out at the readable pace the reveal uses by default. ".repeat(3);
  server.use(
    http.post(`${API}/games/:id/action`, () =>
      HttpResponse.json({
        beats: [makeBeat({ id: "n9", kind: "narration", text: LONG }), makeBeat({ id: "d9", kind: "dialogue", speaker: "c1", speaker_name: "Jacker", text: "Done already?" })],
        state: makeState(),
      }),
    ),
  );
  await gotoPlay(u);
  await u.type(screen.getByRole("textbox"), "read the wall");
  await u.click(screen.getByRole("button", { name: /send/i }));
  await waitFor(() => expect(document.querySelector('[data-beat-id="n9"]')).toBeTruthy());
  // click the story: everything finishes instantly
  await u.click(document.querySelector("#storyStream"));
  await waitFor(() => {
    expect(document.querySelector('[data-beat-id="n9"] p').textContent).toBe(LONG);
    expect(document.querySelector('[data-beat-id="d9"]').closest(".veil-wrap").classList.contains("veiled")).toBe(false);
    expect(screen.getByText("Done already?")).toBeTruthy();
  });
}, 10000);

test("anchoring: the scene image does NOT move when new narration arrives", async () => {
  const u = user();
  server.use(
    http.get(`${API}/games/:id/state`, () => HttpResponse.json(IMAGED())),
    http.post(`${API}/games/:id/action`, () =>
      HttpResponse.json({ beats: [makeBeat({ id: "n2", text: "More prose lands." })], state: IMAGED() }),
    ),
  );
  await gotoPlay(u);
  const holderBefore = document.querySelector(".prose-art").closest("[data-beat-id]").dataset.beatId;
  await u.type(screen.getByRole("textbox"), "look");
  await u.click(screen.getByRole("button", { name: /send/i }));
  await waitFor(() => expect(screen.getByText("More prose lands.")).toBeTruthy(), { timeout: 5000 });
  const holderAfter = document.querySelector(".prose-art").closest("[data-beat-id]").dataset.beatId;
  expect(holderAfter).toBe(holderBefore);
  expect(holderAfter).not.toBe("n2");
}, 10000);

test("clicking a story image opens the lightbox; Escape closes it", async () => {
  const u = user();
  server.use(http.get(`${API}/games/:id/state`, () => HttpResponse.json(IMAGED())));
  await gotoPlay(u);
  const img = document.querySelector('#storyStream .prose-art img');
  await u.click(img);
  const box = document.querySelector(".lightbox-overlay");
  expect(box).toBeTruthy();
  expect(box.querySelector("img").getAttribute("src")).toBe("/media/g/scene.png");
  await u.keyboard("{Escape}");
  expect(document.querySelector(".lightbox-overlay")).toBeNull();
  // click-outside also closes
  await u.click(img);
  await u.click(document.querySelector(".lightbox-overlay"));
  expect(document.querySelector(".lightbox-overlay")).toBeNull();
});

test("deleting a game from the library asks to confirm, then removes it", async () => {
  const u = user();
  let deleted = false;
  server.use(
    http.get(`${API}/games`, () => HttpResponse.json({ games: deleted ? [] : [{ id: "g-test", title: "Test Adventure", status: "active", created_at: "x" }] })),
    http.delete(`${API}/games/:id`, () => {
      deleted = true;
      return HttpResponse.json({ deleted: "g-test" });
    }),
  );
  await mountApp();
  await u.click(await screen.findByRole("button", { name: /enter your saved worlds/i }));
  await screen.findByText("Test Adventure");
  await u.click(screen.getByRole("button", { name: /delete adventure/i }));
  // confirm modal
  expect(await screen.findByText(/delete adventure\?/i)).toBeTruthy();
  await u.click(screen.getByRole("button", { name: /^delete$/i }));
  // gone
  await waitFor(() => expect(screen.queryByText("Test Adventure")).toBeNull());
});
