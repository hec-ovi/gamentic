// MSW server lifecycle + default handlers for the orchestrator API.
// Component tests mount the real app.js; all network goes through these handlers.
// Override per-test with `server.use(...)`.

import { afterAll, afterEach, beforeAll } from "vitest";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { GAMES, makeState, makeBeat } from "./fixtures.js";

const API = "http://localhost:8000";

export const defaultHandlers = [
  http.get(`${API}/health`, () => HttpResponse.json({ status: "ok" })),
  http.get(`${API}/games`, () => HttpResponse.json({ games: GAMES })),
  http.get(`${API}/games/:id/state`, () => HttpResponse.json(makeState())),
  http.get(`${API}/games/:id/beats`, () =>
    HttpResponse.json({ beats: [makeBeat({ id: "open", text: "Rain hammers the window of The Last Breath." })] }),
  ),
  http.post(`${API}/games/:id/action`, () =>
    HttpResponse.json({ beats: [makeBeat({ text: "Nothing happens." })], state: makeState() }),
  ),
  http.post(`${API}/voice/speak`, () => HttpResponse.json({ audio_url: "/audio/x.wav" })),
  // swallow anything else (media etc.) so a stray request never hard-fails a test
  http.all("*", () => new HttpResponse(null, { status: 404 })),
];

export const server = setupServer(...defaultHandlers);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// Mount the app fresh against a given DOM root. Resets module state so each test
// gets its own controller instance.
export async function mountApp() {
  document.body.innerHTML = '<div id="app" class="app-shell"></div>';
  localStorage.clear();
  const { vi } = await import("vitest");
  vi.resetModules();
  const mod = await import("../src/app.js");
  return mod.init({ root: document.querySelector("#app") });
}
