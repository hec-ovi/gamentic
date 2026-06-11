// Creator session persistence: chats survive refreshes via the stored
// session_id + GET /create/{session_id} (docs/frontend-api.md s0 item 7).

import { test, expect } from "vitest";
import { screen, waitFor } from "@testing-library/dom";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server, mountApp } from "./setup.js";

const API = "http://localhost:8000";
const SESSION_KEY = "gamentic.creator.session";
const user = () => userEvent.setup({ delay: null });

test("an in-progress creation is restored after a refresh; Start over discards it", async () => {
  const u = user();
  server.use(
    http.get(`${API}/create/creator-abc`, () =>
      HttpResponse.json({
        session_id: "creator-abc",
        history: [
          { role: "user", content: "A haunted lighthouse." },
          { role: "assistant", content: "Storm-lashed rocks it is. Who joins you?" },
        ],
      }),
    ),
  );
  await mountApp(); // clears localStorage...
  localStorage.setItem(SESSION_KEY, "creator-abc"); // ...then simulate a pre-refresh session
  await u.click(screen.getByRole("button", { name: /forge a world/i }));

  expect(await screen.findByText(/picked up where you left off/i)).toBeTruthy();
  expect(screen.getByText("A haunted lighthouse.")).toBeTruthy();
  expect(screen.getByText(/storm-lashed rocks/i)).toBeTruthy();

  await u.click(screen.getByRole("button", { name: /start over/i }));
  expect(localStorage.getItem(SESSION_KEY)).toBeNull();
  await waitFor(() => expect(screen.queryByText("A haunted lighthouse.")).toBeNull());
});

test("an expired/unknown stored session starts clean and clears the stored id", async () => {
  const u = user();
  // no handler for GET /create/:id -> the catch-all 404s it
  await mountApp();
  localStorage.setItem(SESSION_KEY, "creator-gone");
  await u.click(screen.getByRole("button", { name: /forge a world/i }));

  expect(await screen.findByText(/tell me about the world you want to play/i)).toBeTruthy();
  expect(screen.queryByText(/picked up where you left off/i)).toBeNull();
  await waitFor(() => expect(localStorage.getItem(SESSION_KEY)).toBeNull());
});

test("sending a creator message stores the session id for a later restore", async () => {
  const u = user();
  server.use(http.post(`${API}/create/message`, () => HttpResponse.json({ reply: "Tell me more." })));
  await mountApp();
  await u.click(screen.getByRole("button", { name: /forge a world/i }));
  await u.type(screen.getByPlaceholderText(/describe your world/i), "A haunted lighthouse");
  await u.click(screen.getByRole("button", { name: /^send$/i }));

  expect(await screen.findByText("Tell me more.")).toBeTruthy();
  expect(localStorage.getItem(SESSION_KEY)).toMatch(/^creator-/);
});

test("focus returns to the creator chat box when the reply lands", async () => {
  server.use(http.post(`${API}/create/message`, () => HttpResponse.json({ reply: "A lighthouse. Good. What haunts it?" })));
  const u = user();
  await mountApp();
  await u.click(await screen.findByRole("button", { name: /forge a world/i }));
  const box = await screen.findByPlaceholderText(/describe your world/i);
  await u.type(box, "a haunted lighthouse");
  await u.click(screen.getByRole("button", { name: /^send$/i })); // focus lands on the button
  await screen.findByText(/what haunts it/i);
  // the reply landed: the keyboard comes back to the chat box on its own
  await waitFor(() => expect(document.activeElement).toBe(screen.getByPlaceholderText(/describe your world/i)));
});
