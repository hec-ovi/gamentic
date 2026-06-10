// Component / integration tests: mount the REAL app, drive it like a player with
// user-event, and intercept the network with MSW. Asserts the living-scene
// rendering, the integrated deck, the composer (chips, stacking, Look), the
// character profile + whisper channel, Continue/wish, the PARTIAL busy-lock,
// export/import, and the turn flow.

import { test, expect, beforeEach, vi } from "vitest";
import { screen, within, waitFor } from "@testing-library/dom";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse, delay } from "msw";
import { server, mountApp } from "./setup.js";
import { makeState, makeBeat, makeProfile } from "./fixtures.js";

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
// the main composer line (its aria-label tracks the mode); the wish input is a textbox too
const cmpBox = () => screen.getByRole("textbox", { name: /what you (do|say|look)/i });
// the profile is re-rendered when its data lands: always query the LIVE node
const profileEl = () => document.querySelector(".profile-screen");
const pmBox = (re) => within(profileEl()).getByRole("textbox", { name: re });

beforeEach(() => {
  document
    .querySelectorAll(".notice-stack, .toast, .help-pop, .tagger-pop, .lightbox-overlay")
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
  await u.type(cmpBox(), "open the door");
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
  await u.type(cmpBox(), "hello room");
  await u.click(screen.getByRole("button", { name: /send/i }));
  await waitFor(() => expect(body).toBeTruthy());
  expect(body.segments).toEqual([{ type: "say", text: "hello room" }]);
});

test("PARTIAL lock: mutating surfaces block mid-turn, but the lightbox and inspect stay live", async () => {
  const u = user();
  let posts = 0;
  // a character with face art + a past dialogue beat, so an avatar image exists
  const faced = makeState();
  faced.characters[0].face_url = "/media/g-test/jacker-face.png";
  server.use(
    http.get(`${API}/games/:id/state`, () => HttpResponse.json(faced)),
    http.get(`${API}/games/:id/beats`, ({ request }) =>
      new URL(request.url).searchParams.has("since")
        ? HttpResponse.json({ beats: [] })
        : HttpResponse.json({
            beats: [
              makeBeat({ id: "open", text: "Rain hammers the window of The Last Breath." }),
              makeBeat({ id: "dlg", kind: "dialogue", speaker: "c1", speaker_name: "Jacker", text: "Evening." }),
            ],
          }),
    ),
    http.post(`${API}/games/:id/action`, async () => {
      posts += 1;
      await delay(600); // a long-running turn: everything below happens MID-TURN
      return HttpResponse.json({ beats: [makeBeat({ text: "Resolved." })], state: faced });
    }),
    http.post(`${API}/games/:id/explain`, () => HttpResponse.json({ text: "Forty-two creds." })),
  );
  await gotoPlay(u);
  await u.type(cmpBox(), "wait");
  await u.click(screen.getByRole("button", { name: /send/i }));

  // mid-turn: composer + mutating buttons locked, thinking shown, NO full veil
  expect(cmpBox().getAttribute("contenteditable")).toBe("false");
  expect(screen.getByText(/the narrator is thinking/i)).toBeTruthy();
  expect(document.querySelector(".busy-veil")).toBeNull();
  const search = screen.getByRole("button", { name: /^search$/i });
  expect(search.disabled).toBe(true);
  await u.click(search).catch(() => {});

  // ...but READ-ONLY interactions still work: the dialogue avatar opens the lightbox
  await u.click(document.querySelector('.dialogue .bubble-avatar'));
  const box = document.querySelector(".lightbox-overlay");
  expect(box).toBeTruthy();
  expect(box.querySelector("img").getAttribute("src")).toBe("/media/g-test/jacker-face.png");
  await u.keyboard("{Escape}");

  // ...and tap-to-inspect + "ask what this is" answer mid-turn too
  await u.click(screen.getByRole("button", { name: /inspect credstick/i }));
  const modal = await screen.findByRole("dialog", { name: /credstick/i });
  await u.click(within(modal).getByRole("button", { name: /ask what this is/i }));
  expect(await screen.findByText(/forty-two creds/i)).toBeTruthy();
  await u.click(within(modal).getByRole("button", { name: /^close$/i }));

  // after: unlocked, and only the one POST went out
  await waitFor(composerLive);
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

  await u.type(cmpBox(), " follow me");
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
  await u.type(cmpBox(), "we should run");
  await u.click(screen.getByRole("button", { name: /stack this line/i }));
  // the stacked row renders and is removable
  expect(document.querySelector(".seg-stack .seg-row")).toBeTruthy();
  // second line in Do mode
  await u.click(screen.getByRole("button", { name: /^do$/i }));
  await u.type(cmpBox(), "bolt for the door");
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

test("clicking a character card opens the FULL-SCREEN profile fed by GET /profile", async () => {
  const u = user();
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /open jacker's profile/i }));
  expect(await screen.findByRole("dialog", { name: /jacker's profile/i })).toBeTruthy();
  // the default tab is the status sheet (the data lands async and the screen
  // re-renders, so query the live node each time)
  await waitFor(() => expect(within(profileEl()).getByText("neutral")).toBeTruthy());
  expect(within(profileEl()).getByText(/watchful bartender/i)).toBeTruthy();
  // Traits tab: the unlock stamps
  await u.click(within(profileEl()).getByRole("tab", { name: /traits/i }));
  expect(within(profileEl()).getByText(/distrusts authority/)).toBeTruthy();
  expect(within(profileEl()).getByText(/unlocked: Day 2, evening/)).toBeTruthy();
  // Memory tab: moments (private marked) + the image strip
  await u.click(within(profileEl()).getByRole("tab", { name: /memories/i }));
  expect(within(profileEl()).getByText("Keep it quiet.")).toBeTruthy();
  expect(document.querySelector(".moment.private")).toBeTruthy();
  expect(document.querySelector('.memory img[src="/media/g-test/bar.png"]')).toBeTruthy();
  // closing returns to the scene
  await u.click(within(profileEl()).getByRole("button", { name: /back to the scene/i }));
  expect(document.querySelector(".profile-screen")).toBeNull();
});

test("the profile tab SURVIVES the post-turn refetch (no bounce back to tab 1)", async () => {
  const u = user();
  server.use(
    http.post(`${API}/games/:id/action`, () =>
      HttpResponse.json({
        beats: [makeBeat({ kind: "dialogue", speaker: "c1", speaker_name: "Jacker", text: "Noted.", private_with: "c1" })],
        state: makeState(),
      }),
    ),
  );
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /open jacker's profile/i }));
  await screen.findByRole("dialog", { name: /jacker's profile/i });
  await waitFor(() => expect(within(profileEl()).getByRole("tab", { name: /whisper/i })).toBeTruthy());
  await u.click(within(profileEl()).getByRole("tab", { name: /whisper/i }));
  await waitFor(() => expect(pmBox(/what you say/i)).toBeTruthy());

  // a turn resolves while the profile is open -> the profile refetches...
  await u.type(pmBox(/what you say/i), "remember this");
  await u.click(within(profileEl()).getByRole("button", { name: /^whisper$/i }));
  await waitFor(() => expect(within(document.querySelector("#pmThread")).getByText("Noted.")).toBeTruthy(), { timeout: 4000 });

  // ...and the Whisper tab is still the active one
  const active = within(profileEl()).getByRole("tab", { selected: true });
  expect(active.textContent).toMatch(/whisper/i);
}, 10000);

test("an origin receipt ('You learn of ... past') celebrates like a trait unlock", async () => {
  const u = user();
  server.use(
    http.post(`${API}/games/:id/action`, () =>
      HttpResponse.json({
        beats: [makeBeat({ id: "or9", kind: "system", speaker: "system", text: "You learn of Jacker's past: he ran corp security before the fall." })],
        state: makeState(),
      }),
    ),
  );
  await gotoPlay(u);
  await u.type(cmpBox(), "ask about his past");
  await u.click(screen.getByRole("button", { name: /send/i }));
  const badge = await screen.findByText(/You learn of Jacker's past/);
  expect(badge.closest(".system-badge").classList.contains("trait")).toBe(true);
});

test("a fresh character's profile shows the grow-from-interactions copy", async () => {
  const u = user();
  server.use(
    http.get(`${API}/games/:id/characters/:cid/profile`, () =>
      HttpResponse.json(makeProfile({ traits: [], moments: [], memories: [] })),
    ),
  );
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /open jacker's profile/i }));
  expect(
    await screen.findByText(
      /The more you interact with your characters, the more their traits and personality will grow from your interactions\./,
    ),
  ).toBeTruthy();
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
  await u.type(cmpBox(), "grab it");
  await u.click(screen.getByRole("button", { name: /send/i }));
  await u.click(await screen.findByText("Obtained: brass key."));
  const modal = await screen.findByRole("dialog", { name: /what just happened/i });
  expect(within(modal).getByText("Obtained: brass key.")).toBeTruthy();
  await u.click(within(modal).getByRole("button", { name: /ask what this is/i }));
  expect(await screen.findByText(/pried from the bar/i)).toBeTruthy();
  expect(explainBody).toEqual({ kind: "beat", beat_id: "sys9" });
});

test("the whisper channel lives in the profile: the secret renders in its thread, never in the public story", async () => {
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
  await u.click(screen.getByRole("button", { name: /open jacker's profile/i }));
  await screen.findByRole("dialog", { name: /jacker's profile/i });
  await waitFor(() => expect(within(profileEl()).getByRole("tab", { name: /whisper/i })).toBeTruthy());
  await u.click(within(profileEl()).getByRole("tab", { name: /whisper/i }));
  await waitFor(() => expect(within(profileEl()).getAllByText(/only jacker/i).length).toBeGreaterThan(0));

  await u.type(pmBox(/what you say/i), "tell me the secret");
  await u.click(within(profileEl()).getByRole("button", { name: /^whisper$/i }));
  await waitFor(() => expect(body).toBeTruthy());
  expect(body.segments).toEqual([{ type: "whisper", text: "tell me the secret", target: "Jacker", mode: "say" }]);

  // the private reply lands in the profile's thread...
  await waitFor(() => expect(within(document.querySelector("#pmThread")).getByText("Under the stool.")).toBeTruthy(), { timeout: 4000 });
  // ...and after closing, the public story still never shows it
  await u.click(within(profileEl()).getByRole("button", { name: /back to the scene/i }));
  expect(document.querySelector("#pmThread")).toBeNull();
  expect(within(document.querySelector("#storyStream")).queryByText("Under the stool.")).toBeNull();
}, 10000);

test("the whisper thread pins itself to the newest line when a reply lands", async () => {
  const u = user();
  // jsdom has no layout: give every element a virtual scrollable height
  const spy = vi.spyOn(window.Element.prototype, "scrollHeight", "get").mockReturnValue(500);
  try {
    server.use(
      http.post(`${API}/games/:id/action`, () =>
        HttpResponse.json({
          beats: [makeBeat({ kind: "dialogue", speaker: "c1", speaker_name: "Jacker", text: "Closer.", private_with: "c1" })],
          state: makeState(),
        }),
      ),
    );
    await gotoPlay(u);
    await u.click(screen.getByRole("button", { name: /open jacker's profile/i }));
    await screen.findByRole("dialog", { name: /jacker's profile/i });
    await waitFor(() => expect(within(profileEl()).getByRole("tab", { name: /whisper/i })).toBeTruthy());
    await u.click(within(profileEl()).getByRole("tab", { name: /whisper/i }));
    await waitFor(() => expect(pmBox(/what you say/i)).toBeTruthy());
    await u.type(pmBox(/what you say/i), "come closer");
    await u.click(within(profileEl()).getByRole("button", { name: /^whisper$/i }));
    await waitFor(() => expect(within(document.querySelector("#pmThread")).getByText("Closer.")).toBeTruthy(), { timeout: 4000 });
    // pinned to the newest line (scrollTop driven to the virtual scrollHeight)
    await waitFor(() => expect(document.querySelector("#pmThread").scrollTop).toBe(500));
  } finally {
    spy.mockRestore();
  }
}, 10000);

test("whisper replies SPEAK with the character's voice through the speak pipeline", async () => {
  const u = user();
  const voiced = makeState();
  voiced.characters[0].voice_id = "vx-jacker";
  server.use(
    http.get(`${API}/games/:id/state`, () => HttpResponse.json(voiced)),
    http.post(`${API}/games/:id/action`, () =>
      HttpResponse.json({
        beats: [makeBeat({ kind: "dialogue", speaker: "c1", speaker_name: "Jacker", text: "Hush now.", private_with: "c1" })],
        state: voiced,
      }),
    ),
  );
  const app = await mountApp();
  app.state.settings.autoplayCharacters = true; // character voices ON, narrator OFF
  const prepared = vi.spyOn(app.voice, "prepare").mockResolvedValue(null);
  await u.click(await screen.findByRole("button", { name: /enter your saved worlds/i }));
  await u.click(await screen.findByRole("button", { name: /^enter$/i }));
  await screen.findAllByText("The Last Breath");

  await u.click(screen.getByRole("button", { name: /open jacker's profile/i }));
  await screen.findByRole("dialog", { name: /jacker's profile/i });
  await waitFor(() => expect(within(profileEl()).getByRole("tab", { name: /whisper/i })).toBeTruthy());
  await u.click(within(profileEl()).getByRole("tab", { name: /whisper/i }));
  await waitFor(() => expect(pmBox(/what you say/i)).toBeTruthy());
  await u.type(pmBox(/what you say/i), "shh");
  await u.click(within(profileEl()).getByRole("button", { name: /^whisper$/i }));

  await waitFor(() =>
    expect(prepared).toHaveBeenCalledWith(expect.objectContaining({ text: "Hush now.", voiceId: "vx-jacker" })),
  );
}, 10000);

test("optimistic echo: the player's line shows the moment it is sent, then the canonical echo replaces it", async () => {
  const u = user();
  server.use(
    http.post(`${API}/games/:id/action`, async () => {
      await delay(400);
      return HttpResponse.json({
        beats: [
          makeBeat({ id: "pe1", kind: "action", speaker: "player", text: 'you say "hello there" to Jacker' }),
          makeBeat({ id: "pn1", kind: "narration", text: "Jacker raises an eyebrow." }),
        ],
        state: makeState(),
      });
    }),
  );
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /^say$/i }));
  await u.type(cmpBox(), "hello there");
  await u.click(screen.getByRole("button", { name: /send/i }));

  // BEFORE the backend answers: the line is already on screen, as a mirrored speech bubble
  const pending = document.querySelector('#storyStream [data-beat-id^="pending-"]');
  expect(pending).toBeTruthy();
  expect(pending.classList.contains("from-player")).toBe(true);
  expect(pending.classList.contains("pending")).toBe(true); // dimmed until the turn lands
  expect(pending.querySelector(".bubble p").textContent).toBe("hello there");

  // AFTER: the canonical echo replaced it - exactly one copy of the line remains
  await waitFor(() => expect(screen.getByText(/raises an eyebrow/)).toBeTruthy(), { timeout: 4000 });
  expect(document.querySelector('[data-beat-id^="pending-"]')).toBeNull();
  expect(screen.getAllByText("hello there").length).toBe(1);
}, 10000);

test("optimistic echo in the whisper thread; a failed turn takes the echo back", async () => {
  const u = user();
  server.use(http.post(`${API}/games/:id/action`, async () => {
    await delay(300);
    return new HttpResponse(null, { status: 502 });
  }));
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /open jacker's profile/i }));
  await screen.findByRole("dialog", { name: /jacker's profile/i });
  await waitFor(() => expect(within(profileEl()).getByRole("tab", { name: /whisper/i })).toBeTruthy());
  await u.click(within(profileEl()).getByRole("tab", { name: /whisper/i }));
  await waitFor(() => expect(pmBox(/what you say/i)).toBeTruthy());
  await u.type(pmBox(/what you say/i), "psst");
  await u.click(within(profileEl()).getByRole("button", { name: /^whisper$/i }));

  // instantly in the PRIVATE thread (and nowhere else), just the said words
  const mine = document.querySelector('#pmThread [data-beat-id^="pending-"]');
  expect(mine).toBeTruthy();
  expect(mine.querySelector(".pm-text").textContent).toBe("psst");
  expect(within(document.querySelector("#storyStream")).queryByText(/psst/)).toBeNull();

  // the turn fails: the echo is taken back (the toast explains)...
  await waitFor(() => expect(document.querySelector(".toast")).toBeTruthy(), { timeout: 4000 });
  await waitFor(() => expect(document.querySelector('[data-beat-id^="pending-"]')).toBeNull());
  // ...and the typed line RETURNS to the whisper composer, nothing lost
  await waitFor(() => expect(document.querySelector("#pmInput").textContent).toBe("psst"));
}, 10000);

test("the speak button walks loading -> playing -> back to idle", async () => {
  const u = user();
  const app = await mountApp();
  // a controllable voice: prepare resolves when we say so; playUrl hands back a fake element
  let releasePrepare;
  app.voice.prepare = vi.fn(() => new Promise((res) => (releasePrepare = res)));
  const fakeAudio = document.createElement("audio");
  app.voice.playUrl = vi.fn(() => fakeAudio);
  await u.click(await screen.findByRole("button", { name: /enter your saved worlds/i }));
  await u.click(await screen.findByRole("button", { name: /^enter$/i }));
  await screen.findAllByText("The Last Breath");

  const btn = document.querySelector('[data-act="speak-beat"]');
  expect(btn).toBeTruthy();
  await u.click(btn);

  // synthesizing: the loading state
  expect(btn.classList.contains("speak-loading")).toBe(true);
  expect(btn.getAttribute("aria-label")).toMatch(/preparing voice/i);

  // audio ready: the playing state
  releasePrepare({ audioUrl: "/audio/x.wav", duration: 2 });
  await waitFor(() => expect(btn.classList.contains("speak-playing")).toBe(true));
  expect(btn.getAttribute("aria-label")).toMatch(/stop voice/i);

  // playback finished: back to the plain speaker
  fakeAudio.dispatchEvent(new Event("ended"));
  await waitFor(() => {
    expect(btn.classList.contains("speak-playing")).toBe(false);
    expect(btn.classList.contains("speak-loading")).toBe(false);
  });
  expect(btn.getAttribute("aria-label")).toMatch(/play voice/i);
});

test("the profile composer's Do mode whispers a discreet private action (mode: do)", async () => {
  const u = user();
  let body;
  server.use(
    http.post(`${API}/games/:id/action`, async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ beats: [makeBeat({ text: "ok", private_with: "c1" })], state: makeState() });
    }),
  );
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /open jacker's profile/i }));
  await screen.findByRole("dialog", { name: /jacker's profile/i });
  await waitFor(() => expect(within(profileEl()).getByRole("tab", { name: /whisper/i })).toBeTruthy());
  await u.click(within(profileEl()).getByRole("tab", { name: /whisper/i }));
  await waitFor(() => expect(within(profileEl()).getByRole("button", { name: /^do$/i })).toBeTruthy());
  await u.click(within(profileEl()).getByRole("button", { name: /^do$/i }));
  await u.type(pmBox(/what you do/i), "slip him the key");
  await u.click(within(profileEl()).getByRole("button", { name: /^whisper$/i }));
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

test("Look is a first-class action: the typed focus sends a look segment", async () => {
  const u = user();
  let body;
  server.use(
    http.post(`${API}/games/:id/action`, async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ beats: [makeBeat({ text: "You study the hatch." })], state: makeState() });
    }),
  );
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /^look$/i }));
  await u.type(cmpBox(), "the rusted hatch");
  await u.click(screen.getByRole("button", { name: /send/i }));
  await waitFor(() => expect(body).toBeTruthy());
  expect(body.segments).toEqual([{ type: "look", text: "the rusted hatch" }]);
  await screen.findByText("You study the hatch.");
});

test("an EMPTY Look line still sends (study the whole scene)", async () => {
  const u = user();
  let body;
  server.use(
    http.post(`${API}/games/:id/action`, async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ beats: [makeBeat({ text: "The room sharpens." })], state: makeState() });
    }),
  );
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /^look$/i }));
  await u.click(screen.getByRole("button", { name: /send/i }));
  await waitFor(() => expect(body).toBeTruthy());
  expect(body.segments).toEqual([{ type: "look", text: "" }]);
});

test("the scene base actions rewire: 'Look around' and 'Search' send look segments", async () => {
  const u = user();
  const bodies = [];
  server.use(
    http.post(`${API}/games/:id/action`, async ({ request }) => {
      bodies.push(await request.json());
      return HttpResponse.json({ beats: [makeBeat({ text: "ok" })], state: makeState() });
    }),
  );
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /look around/i }));
  await waitFor(() => expect(bodies.length).toBe(1));
  expect(bodies[0].segments).toEqual([{ type: "look", text: "" }]);
  await waitFor(composerLive);
  await u.click(screen.getByRole("button", { name: /^search$/i }));
  await waitFor(() => expect(bodies.length).toBe(2));
  expect(bodies[1].segments).toEqual([{ type: "look", text: "for anything hidden or useful here" }]);
});

test("after a look turn, late image beats are polled in and the rendering hint resolves", async () => {
  const u = user();
  let polled = 0;
  server.use(
    http.get(`${API}/games/:id/state`, () => HttpResponse.json(IMAGED())),
    http.post(`${API}/games/:id/action`, () =>
      HttpResponse.json({ beats: [makeBeat({ id: "lk1", turn_index: 2, text: "You take it all in." })], state: IMAGED() }),
    ),
    http.get(`${API}/games/:id/beats`, ({ request }) => {
      const since = new URL(request.url).searchParams.get("since");
      if (since === null)
        return HttpResponse.json({ beats: [makeBeat({ id: "open", turn_index: 1, text: "Rain hammers the window of The Last Breath." })] });
      polled += 1;
      // the narrator-granted image + an item unlock card land on the SECOND poll
      if (Number(since) >= 2 && polled > 1) {
        return HttpResponse.json({
          beats: [
            makeBeat({ id: "li1", turn_index: 3, seq: 0, speaker: "narrator", kind: "image", text: "the whole scene", image_url: "/media/g-test/look1.png" }),
            makeBeat({ id: "li2", turn_index: 3, seq: 1, speaker: "system", kind: "image", text: "brass key", image_url: "/media/g-test/item1.png" }),
          ],
        });
      }
      return HttpResponse.json({ beats: [] });
    }),
  );
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /^look$/i }));
  await u.click(screen.getByRole("button", { name: /send/i }));
  await screen.findByText("You take it all in.");

  // the subtle hint shows while the look image renders in the background
  await waitFor(() => expect(document.querySelector(".render-hint")).toBeTruthy());

  // the late beats land via GET /beats?since= (3s cadence), through the staged reveal
  await waitFor(() => expect(document.querySelector('.beat-image img[src="/media/g-test/look1.png"]')).toBeTruthy(), {
    timeout: 12000,
  });
  // the narrator shot is the hero; the item card is SMALL with its name label
  const hero = document.querySelector('[data-beat-id="li1"]');
  expect(hero.classList.contains("item-card")).toBe(false);
  expect(hero.querySelector("figcaption").textContent).toMatch(/the whole scene/);
  await waitFor(() => {
    const card = document.querySelector('[data-beat-id="li2"]');
    expect(card).toBeTruthy();
    expect(card.classList.contains("item-card")).toBe(true);
    expect(card.querySelector("figcaption").textContent).toMatch(/brass key/);
  });
  // and the hint resolves once the image arrives
  await waitFor(() => expect(document.querySelector(".render-hint")).toBeNull());
}, 20000);

test("Continue advances the story with NO player input and renders no player beat", async () => {
  const u = user();
  let contBody = "unset";
  server.use(
    http.post(`${API}/games/:id/continue`, async ({ request }) => {
      contBody = await request.json();
      return HttpResponse.json({
        beats: [makeBeat({ id: "c-n1", kind: "narration", text: "The rain stops, suddenly." })],
        state: makeState(),
      });
    }),
  );
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /^continue$/i }));
  await screen.findByText("The rain stops, suddenly.");
  expect(contBody).toEqual({}); // no wish typed -> empty body
  expect(document.querySelector(".player-action")).toBeNull(); // no player beat, no echo
});

test("the wish rides /continue and /action, then clears; it is never echoed as a player beat", async () => {
  const u = user();
  let contBody;
  let actionBody;
  server.use(
    http.post(`${API}/games/:id/continue`, async ({ request }) => {
      contBody = await request.json();
      return HttpResponse.json({ beats: [makeBeat({ text: "A stranger walks in." })], state: makeState() });
    }),
    http.post(`${API}/games/:id/action`, async ({ request }) => {
      actionBody = await request.json();
      return HttpResponse.json({ beats: [makeBeat({ text: "Done." })], state: makeState() });
    }),
  );
  await gotoPlay(u);

  // wish + Continue
  await u.type(screen.getByLabelText(/wish to happen next/i), "let someone new arrive");
  await u.click(screen.getByRole("button", { name: /^continue$/i }));
  await screen.findByText("A stranger walks in.");
  expect(contBody).toEqual({ wish: "let someone new arrive" });
  expect(screen.getByLabelText(/wish to happen next/i).value).toBe(""); // cleared after the send
  expect(within(document.querySelector("#storyStream")).queryByText(/let someone new arrive/)).toBeNull();
  await waitFor(composerLive);

  // wish + a normal action send
  await u.type(screen.getByLabelText(/wish to happen next/i), "rain harder");
  await u.type(screen.getByRole("textbox", { name: /what you do/i }), "open the door");
  await u.click(screen.getByRole("button", { name: /send/i }));
  await waitFor(() => expect(actionBody).toBeTruthy());
  expect(actionBody).toEqual({ action: "open the door", wish: "rain harder" });
  expect(screen.getByLabelText(/wish to happen next/i).value).toBe("");
}, 10000);

test("game settings PATCH round-trip: picking a difficulty updates the live game", async () => {
  const u = user();
  let patchBody;
  server.use(
    http.patch(`${API}/games/:id/settings`, async ({ request }) => {
      patchBody = await request.json();
      return HttpResponse.json({ settings: { narrator_gender: "", difficulty: "hard" }, narrator_voice_id: "af_alloy" });
    }),
  );
  await gotoPlay(u);
  await u.click(screen.getByRole("button", { name: /^menu$/i }));
  const hard = await screen.findByRole("radio", { name: /hard/i });
  await u.click(hard);
  await waitFor(() => expect(patchBody).toEqual({ difficulty: "hard" }));
  // the response is the new truth: the radio stays checked after the re-render
  await waitFor(() => expect(screen.getByRole("radio", { name: /hard/i }).checked).toBe(true));
});

test("the autoplay split persists narrator and character voices independently", async () => {
  const u = user();
  const app = await mountApp();
  await u.click(await screen.findByRole("button", { name: /settings/i }));
  const narr = (await screen.findByText(/narrator voice/i)).closest(".set-row").querySelector("input");
  await u.click(narr);
  expect(app.state.settings.autoplayNarrator).toBe(true);
  expect(app.state.settings.autoplayCharacters).toBe(false);
  const saved = JSON.parse(localStorage.getItem("gamentic.v2"));
  expect(saved.autoplayNarrator).toBe(true);
  expect(saved.autoplayCharacters).toBe(false);
});

test("a library card's Export opens the share/save choice and hands over a named download", async () => {
  const u = user();
  server.use(
    http.get(`${API}/games/:id/export`, ({ request }) =>
      new URL(request.url).searchParams.get("kind") === "template"
        ? HttpResponse.json({ kind: "template", title: "Test Adventure" })
        : new HttpResponse(null, { status: 422 }),
    ),
  );
  const createUrl = vi.fn(() => "blob:gamentic-export");
  const revokeUrl = vi.fn();
  window.URL.createObjectURL = createUrl;
  window.URL.revokeObjectURL = revokeUrl;
  const clicked = vi.spyOn(window.HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  try {
    await mountApp();
    await u.click(await screen.findByRole("button", { name: /enter your saved worlds/i }));
    await screen.findByText("Test Adventure");
    // the card carries an Export next to its trash; it opens the two-flavor choice
    await u.click(screen.getByRole("button", { name: /export adventure/i }));
    expect(document.querySelector(".holo-modal")).toBeTruthy();
    await u.click(screen.getByRole("button", { name: /share as adventure/i }));
    await waitFor(() => expect(clicked).toHaveBeenCalled());
    expect(createUrl).toHaveBeenCalled();
    const blob = createUrl.mock.calls[0][0];
    expect(blob.type).toBe("application/json");
    const anchor = clicked.mock.instances[0];
    expect(anchor.download).toBe("test-adventure-template.json");
    expect(document.querySelector(".holo-modal")).toBeNull(); // the choice closes after exporting
    expect(document.querySelector(".toast")?.textContent || "").toMatch(/exported/i);
  } finally {
    clicked.mockRestore();
    delete window.URL.createObjectURL;
    delete window.URL.revokeObjectURL;
  }
});

test("Import reads the file, posts it, and enters the new game; a bad file surfaces the 400", async () => {
  const u = user();
  let importBody;
  server.use(
    http.post(`${API}/games/import`, async ({ request }) => {
      importBody = await request.json();
      return HttpResponse.json({ game_id: "g-test" });
    }),
  );
  await mountApp();
  await u.click(await screen.findByRole("button", { name: /enter your saved worlds/i }));
  const file = new File([JSON.stringify({ gamentic: true, kind: "template", title: "Shared World" })], "shared.json", {
    type: "application/json",
  });
  await u.upload(document.querySelector("#importFile"), file);
  // posts the parsed JSON and navigates into the returned game
  await waitFor(() => expect(importBody).toEqual({ gamentic: true, kind: "template", title: "Shared World" }));
  await screen.findAllByText("The Last Breath");

  // a non-export file: the 400 message reaches the player
  server.use(http.post(`${API}/games/import`, () => HttpResponse.json({ detail: "not a gamentic export" }, { status: 400 })));
  await u.click(screen.getByRole("button", { name: /library/i }));
  const bad = new File([JSON.stringify({ nope: 1 })], "bad.json", { type: "application/json" });
  await u.upload(document.querySelector("#importFile"), bad);
  await waitFor(() => expect(document.querySelector(".toast")).toBeTruthy());
  expect(document.querySelector(".toast").textContent).toMatch(/not a gamentic export/i);
}, 10000);

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
  await u.type(cmpBox(), "open the lock");
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
  await u.type(cmpBox(), "read the wall");
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
  await u.type(cmpBox(), "look");
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

test("wipe all memory: the double confirm gates the call; success clears local traces and lands in the empty library", async () => {
  const u = user();
  let wipeUrl = null;
  let wiped = false;
  server.use(
    http.delete(`${API}/games`, ({ request }) => {
      wipeUrl = new URL(request.url);
      wiped = true;
      return HttpResponse.json({ wiped_games: 1, wiped_media_folders: 1 });
    }),
    http.get(`${API}/games`, () => HttpResponse.json({ games: wiped ? [] : [{ id: "g-test", title: "Test Adventure", status: "active", created_at: "x" }] })),
  );
  await mountApp();
  localStorage.setItem("gamentic.creator.session", "creator-old"); // a stored chat to be cleared
  await u.click(await screen.findByRole("button", { name: /settings/i }));
  await u.click(await screen.findByRole("button", { name: /wipe all memory/i }));

  // the dialog says exactly what it deletes; nothing has been called yet
  const modal = await screen.findByRole("dialog", { name: /wipe all memory/i });
  expect(within(modal).getByText(/deletes EVERY adventure.*no undo/is)).toBeTruthy();
  expect(wipeUrl).toBeNull();

  // first confirm click only ARMS it
  await u.click(within(modal).getByRole("button", { name: /erase everything/i }));
  expect(wipeUrl).toBeNull();
  expect(await screen.findByText(/last chance/i)).toBeTruthy();

  // the second click erases: DELETE /games?confirm=wipe
  await u.click(screen.getByRole("button", { name: /yes, erase everything/i }));
  await waitFor(() => expect(wipeUrl).not.toBeNull());
  expect(wipeUrl.pathname).toBe("/games");
  expect(wipeUrl.searchParams.get("confirm")).toBe("wipe");

  // post-wipe: the (now empty) library, and the creator session is gone from localStorage
  await waitFor(() => expect(screen.getByText(/no adventures yet/i)).toBeTruthy());
  expect(localStorage.getItem("gamentic.creator.session")).toBeNull();
});

test("cancelling the wipe dialog never calls the backend", async () => {
  const u = user();
  let called = false;
  server.use(http.delete(`${API}/games`, () => {
    called = true;
    return HttpResponse.json({ wiped_games: 0, wiped_media_folders: 0 });
  }));
  await mountApp();
  await u.click(await screen.findByRole("button", { name: /settings/i }));
  await u.click(await screen.findByRole("button", { name: /wipe all memory/i }));
  const modal = await screen.findByRole("dialog", { name: /wipe all memory/i });
  await u.click(within(modal).getByRole("button", { name: /^cancel$/i }));
  expect(document.querySelector(".holo-modal")).toBeNull();
  expect(called).toBe(false);
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
