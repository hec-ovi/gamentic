// Component / integration tests: mount the REAL app, drive it like a player with
// user-event, and intercept the network with MSW. Asserts the living-scene
// rendering, turn flow, button->segment routing, chat modes, and transitions.

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
  await screen.findByText("The Last Breath");
}

beforeEach(() => {
  document.querySelectorAll(".notice-stack, .toast, .help-pop").forEach((n) => n.remove());
});

test("library lists games from the network and entering one shows the living scene", async () => {
  const u = user();
  await mountApp();
  await u.click(await screen.findByRole("button", { name: /enter your saved worlds/i }));
  // the game card from GET /games
  expect(await screen.findByText("Test Adventure")).toBeTruthy();
  await u.click(await screen.findByRole("button", { name: /^enter$/i }));

  // scene, goal, and the present character all render from state
  expect(await screen.findByText("The Last Breath")).toBeTruthy();
  expect(within(document.querySelector(".hud-goal")).getByText(/Find the brass key/)).toBeTruthy();
  const card = document.querySelector('.char-card[data-char-id="c1"]');
  expect(card).toBeTruthy();
  expect(within(card).getByText("Jacker")).toBeTruthy();
  // dead end (no exits)
  expect(document.querySelector(".dead-end")).toBeTruthy();
});

test("a free-text turn posts the action and appends the new narration beat", async () => {
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

test("the action input is disabled while a turn is generating, then re-enabled", async () => {
  const u = user();
  server.use(
    http.post(`${API}/games/:id/action`, async () => {
      await delay(40);
      return HttpResponse.json({ beats: [makeBeat({ text: "Resolved." })], state: makeState() });
    }),
  );
  await gotoPlay(u);
  await u.type(screen.getByRole("textbox"), "wait");
  await u.click(screen.getByRole("button", { name: /send/i }));
  // mid-turn: disabled
  expect(screen.getByRole("textbox").disabled).toBe(true);
  expect(screen.getByText(/the narrator is thinking/i)).toBeTruthy();
  // after: enabled again
  await waitFor(() => expect(screen.getByRole("textbox").disabled).toBe(false));
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

  const settled = () => expect(document.querySelector(".action-form input").disabled).toBe(false);

  await u.click(screen.getByRole("button", { name: /take brass key/i }));
  await waitFor(() => expect(body).toBeTruthy());
  expect(body.segments[0]).toMatchObject({ type: "do" });
  expect(body.segments[0].text).toMatch(/take/i);
  expect(body.segments[0].text).toMatch(/brass key/i);
  await waitFor(settled); // let the turn fully resolve before the next action

  body = null;
  await u.click(screen.getByRole("button", { name: /examine iron altar/i }));
  await waitFor(() => expect(body).toBeTruthy());
  expect(body.segments[0].text).toMatch(/examine/i);
});

test("Talk opens a directed chat that routes a 'say' segment to the character", async () => {
  const u = user();
  let body;
  server.use(
    http.post(`${API}/games/:id/action`, async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ beats: [makeBeat({ kind: "dialogue", speaker: "c1", speaker_name: "Jacker", text: "Aye." })], state: makeState() });
    }),
  );
  await gotoPlay(u);
  const card = document.querySelector('.char-card[data-char-id="c1"]');
  await u.click(within(card).getByRole("button", { name: /^talk$/i }));
  // chat context appears
  expect(screen.getByText(/Talking to Jacker/i)).toBeTruthy();
  await u.type(screen.getByRole("textbox"), "you there?");
  await u.click(screen.getByRole("button", { name: /send/i }));
  await waitFor(() => expect(body).toBeTruthy());
  expect(body.segments[0]).toEqual({ type: "say", text: "you there?", target: "Jacker" });
});

test("Whisper opens a private channel; a whisper segment is sent and public beats stay hidden", async () => {
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
  const card = document.querySelector('.char-card[data-char-id="c1"]');
  await u.click(within(card).getByRole("button", { name: /whisper/i }));
  expect(document.querySelector(".action-form.chat-private")).toBeTruthy();
  expect(screen.getByText(/Whispering to Jacker/i)).toBeTruthy();

  await u.type(screen.getByRole("textbox"), "tell me the secret");
  await u.click(screen.getByRole("button", { name: /send/i }));
  await waitFor(() => expect(body).toBeTruthy());
  expect(body.segments[0]).toEqual({ type: "whisper", text: "tell me the secret", target: "Jacker" });
  // the private reply renders in the whisper view with its banner
  expect(await screen.findByText("Under the stool.")).toBeTruthy();
  expect(document.querySelector(".whisper-banner")).toBeTruthy();
});

test("Give opens an item picker and sends a give segment with the chosen item", async () => {
  const u = user();
  let body;
  server.use(
    http.post(`${API}/games/:id/action`, async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ beats: [makeBeat({ text: "Taken." })], state: makeState() });
    }),
  );
  await gotoPlay(u);
  const card = document.querySelector('.char-card[data-char-id="c1"]');
  await u.click(within(card).getByRole("button", { name: /give/i }));
  // picker lists the player's inventory item
  const pick = await screen.findByRole("button", { name: /credstick/i });
  await u.click(pick);
  await waitFor(() => expect(body).toBeTruthy());
  expect(body.segments[0]).toEqual({ type: "give", item: "credstick", target: "Jacker" });
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
