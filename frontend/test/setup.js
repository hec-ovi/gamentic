// MSW server lifecycle + default handlers for the orchestrator API.
// Component tests mount the real app.js; all network goes through these handlers.
// Override per-test with `server.use(...)`.

import { afterAll, afterEach, beforeAll } from "vitest";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { GAMES, makeState, makeBeat, makeProfile } from "./fixtures.js";

const API = "http://localhost:8000";

export const defaultHandlers = [
  http.get(`${API}/health`, () => HttpResponse.json({ status: "ok" })),
  http.get(`${API}/games`, () => HttpResponse.json({ games: GAMES })),
  http.get(`${API}/games/:id/state`, () => HttpResponse.json(makeState())),
  // ?since=<turn_index> is the post-turn late-image poll: nothing new by default
  http.get(`${API}/games/:id/beats`, ({ request }) =>
    new URL(request.url).searchParams.has("since")
      ? HttpResponse.json({ beats: [] })
      : HttpResponse.json({ beats: [makeBeat({ id: "open", text: "Rain hammers the window of The Last Breath." })] }),
  ),
  http.post(`${API}/games/:id/action`, () =>
    HttpResponse.json({ beats: [makeBeat({ text: "Nothing happens." })], state: makeState() }),
  ),
  http.post(`${API}/games/:id/continue`, () =>
    HttpResponse.json({ beats: [makeBeat({ text: "The story drifts forward." })], state: makeState() }),
  ),
  // echo the request body merged over the full live-settings shape, like the
  // real orchestrator (a partial echo would silently zero the other settings)
  http.patch(`${API}/games/:id/settings`, async ({ request }) => {
    const body = await request.json().catch(() => ({}));
    return HttpResponse.json({
      settings: {
        narrator_gender: "",
        difficulty: "normal",
        history_beats: 80,
        summary_every: 10,
        context_tokens: 0,
        turn_voices: 2,
        turn_acts: 1,
        ...body,
      },
      narrator_voice_id: "af_alloy",
    });
  }),
  http.get(`${API}/games/:id/characters/:cid/profile`, () => HttpResponse.json(makeProfile())),
  http.post(`${API}/voice/speak`, () => HttpResponse.json({ audio_url: "/audio/x.wav" })),
  // swallow anything else (media etc.) so a stray request never hard-fails a test
  http.all("*", () => new HttpResponse(null, { status: 404 })),
];

export const server = setupServer(...defaultHandlers);

// jsdom ships createObjectURL but not revokeObjectURL; the export download helper
// revokes its blob URL in a delayed timer that otherwise explodes after the test.
if (typeof URL.revokeObjectURL !== "function") URL.revokeObjectURL = () => {};

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// Mount the app fresh against a given DOM root. Resets module state so each test
// gets its own controller instance. The PREVIOUS instance's pollers are stopped
// first: vi.resetModules() alone leaves their intervals firing into later tests.
let lastApp = null;

export async function mountApp() {
  if (lastApp && typeof lastApp.destroy === "function") lastApp.destroy();
  document.body.innerHTML = '<div id="app" class="app-shell"></div>';
  localStorage.clear();
  const { vi } = await import("vitest");
  vi.resetModules();
  const mod = await import("../src/app.js");
  lastApp = mod.init({ root: document.querySelector("#app") });
  return lastApp;
}

afterEach(() => {
  if (lastApp && typeof lastApp.destroy === "function") lastApp.destroy();
  lastApp = null;
});
