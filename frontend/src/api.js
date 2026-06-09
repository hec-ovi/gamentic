// Thin REST client for the Gamentic orchestrator (game API).
//
// The orchestrator lives at `backendUrl` (default http://localhost:8000) and
// sends CORS *. Media (image/voice/audio) is NOT here: it is served same-origin
// through the nginx proxy with RELATIVE urls (/image/, /voice/, /audio/) and is
// handled in voice.js / <img src>. Never hardcode :9001/:9002.

export class ApiError extends Error {
  constructor(message, { status = 0, body = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export function createApi(backendUrl) {
  const base = String(backendUrl || "http://localhost:8000").replace(/\/+$/, "");

  async function request(path, { method = "GET", body } = {}) {
    let response;
    try {
      response = await fetch(`${base}${path}`, {
        method,
        headers: {
          Accept: "application/json",
          ...(body ? { "Content-Type": "application/json" } : {}),
        },
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch (networkError) {
      // fetch rejects only on network failure / CORS / offline.
      throw new ApiError(networkError.message || "Backend unreachable", { status: 0 });
    }

    const payload = await readBody(response);
    if (!response.ok) {
      const detail =
        (payload && (payload.detail || payload.message)) || response.statusText || "Request failed";
      throw new ApiError(String(detail), { status: response.status, body: payload });
    }
    return payload;
  }

  return {
    base,
    health: () => request("/health"),
    listGames: () => request("/games"),
    createGame: (worldSheet) => request("/games", { method: "POST", body: worldSheet }),
    getState: (id) => request(`/games/${encodeURIComponent(id)}/state`),
    getBeats: (id, since = null) =>
      request(`/games/${encodeURIComponent(id)}/beats${Number.isInteger(since) ? `?since=${since}` : ""}`),
    // Take a turn. Accepts either a plain string (freeform) or an array of
    // tagged segments (what the action buttons compose). See frontend-api.md s2.
    takeAction: (id, input) => {
      const body = Array.isArray(input) ? { segments: input } : { action: input };
      return request(`/games/${encodeURIComponent(id)}/action`, { method: "POST", body });
    },
    deleteGame: (id) => request(`/games/${encodeURIComponent(id)}`, { method: "DELETE" }),
    clearBeats: (id) => request(`/games/${encodeURIComponent(id)}/beats`, { method: "DELETE" }),
    // "See" the scene: synchronous image of the current scene with the present
    // characters (5-10s). 409 = images disabled, 502 = image service down.
    viewScene: (id) => request(`/games/${encodeURIComponent(id)}/view`, { method: "POST" }),
    creatorMessage: (sessionId, message) =>
      request("/create/message", { method: "POST", body: { session_id: sessionId, message } }),
    creatorFinalize: (sessionId) =>
      request("/create/finalize", { method: "POST", body: { session_id: sessionId } }),
    // Restore an in-progress creator chat (sessions persist server-side).
    creatorSession: (sessionId) => request(`/create/${encodeURIComponent(sessionId)}`),
  };
}

async function readBody(response) {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
