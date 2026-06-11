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

// A hung socket must become an error, never an eternal busy-lock. LLM-bound
// calls legitimately run minutes (the brain's own transport ceiling is 300s);
// plain reads should fail fast.
export const READ_TIMEOUT_MS = 20000;
export const LLM_TIMEOUT_MS = 330000;
export const IMPORT_TIMEOUT_MS = 60000;

export function createApi(backendUrl) {
  const base = String(backendUrl || "http://localhost:8000").replace(/\/+$/, "");

  async function request(path, { method = "GET", body, timeout = READ_TIMEOUT_MS } = {}) {
    let response;
    let timer = null;
    try {
      // Promise.race, not AbortSignal.timeout: the signal must come from the
      // same realm as fetch (jsdom's is rejected by node's fetch), and a race
      // converts the hang into an error everywhere the same way.
      const attempt = fetch(`${base}${path}`, {
        method,
        headers: {
          Accept: "application/json",
          ...(body ? { "Content-Type": "application/json" } : {}),
        },
        body: body ? JSON.stringify(body) : undefined,
      });
      attempt.catch(() => {}); // losing the race must never surface as unhandled
      const hang = new Promise((_, reject) => {
        timer = setTimeout(
          () => reject(new ApiError("The backend is taking too long to answer. Try again.", { status: 0 })),
          timeout,
        );
      });
      response = await Promise.race([attempt, hang]);
    } catch (networkError) {
      if (networkError instanceof ApiError) throw networkError;
      // fetch rejects only on network failure / CORS / offline.
      throw new ApiError(networkError.message || "Backend unreachable", { status: 0 });
    } finally {
      if (timer) clearTimeout(timer);
    }

    const payload = await readBody(response);
    if (!response.ok) {
      throw new ApiError(errorDetail(payload, response), { status: response.status, body: payload });
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
    // An optional `wish` rides along: a hope whispered to the storyteller, never
    // echoed as a player beat.
    takeAction: (id, input, wish) => {
      const body = Array.isArray(input) ? { segments: input } : { action: input };
      if (wish) body.wish = wish;
      return request(`/games/${encodeURIComponent(id)}/action`, { method: "POST", body, timeout: LLM_TIMEOUT_MS });
    },
    // "Continue": the narrator advances the story with NO player input. Same
    // response shape as /action; no player beat comes back.
    continueStory: (id, wish) =>
      request(`/games/${encodeURIComponent(id)}/continue`, { method: "POST", body: wish ? { wish } : {}, timeout: LLM_TIMEOUT_MS }),
    // Live game settings: any subset of { difficulty, narrator_gender }.
    patchSettings: (id, payload) =>
      request(`/games/${encodeURIComponent(id)}/settings`, { method: "PATCH", body: payload }),
    // The full-screen character view (traits, moments, memories). Cheap; refetch
    // when opening and after each turn while open.
    characterProfile: (id, cid) =>
      request(`/games/${encodeURIComponent(id)}/characters/${encodeURIComponent(cid)}/profile`),
    // Adventure portability: template = the world as designed, checkpoint = the
    // full save. Returns the export JSON (the caller turns it into a download).
    exportGame: (id, kind) => request(`/games/${encodeURIComponent(id)}/export?kind=${encodeURIComponent(kind)}`),
    // Import a previously exported JSON -> { game_id } (always a NEW game).
    importGame: (payload) => request("/games/import", { method: "POST", body: payload, timeout: IMPORT_TIMEOUT_MS }),
    deleteGame: (id) => request(`/games/${encodeURIComponent(id)}`, { method: "DELETE" }),
    // The settings "wipe all memory" button: every game, creator session,
    // voice entry and media folder. NEVER call without the confirm param.
    wipeAll: () => request("/games?confirm=wipe", { method: "DELETE" }),
    clearBeats: (id) => request(`/games/${encodeURIComponent(id)}/beats`, { method: "DELETE" }),
    // Tap-to-explain: an in-world, spoiler-safe aside about a visible thing.
    // payload: { kind: item|character|scene|quest|goal|beat, key } or
    // { kind: "beat", beat_id }. 404 = nothing visible matches.
    explain: (id, payload) =>
      request(`/games/${encodeURIComponent(id)}/explain`, { method: "POST", body: payload, timeout: LLM_TIMEOUT_MS }),
    creatorMessage: (sessionId, message) =>
      request("/create/message", { method: "POST", body: { session_id: sessionId, message }, timeout: LLM_TIMEOUT_MS }),
    creatorFinalize: (sessionId) =>
      request("/create/finalize", { method: "POST", body: { session_id: sessionId }, timeout: LLM_TIMEOUT_MS }),
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

// FastAPI's 422 detail is an ARRAY of {loc,msg,type}; a plain String() of it
// reads "[object Object]" in a toast. Flatten to the human messages.
function errorDetail(payload, response) {
  const d = payload && typeof payload === "object" ? (payload.detail ?? payload.message) : payload;
  if (Array.isArray(d)) {
    const msgs = d.map((x) => (x && typeof x === "object" ? x.msg || x.message : x)).filter(Boolean);
    if (msgs.length) return msgs.join("; ");
  } else if (d && typeof d === "object") {
    return d.msg || d.message || JSON.stringify(d);
  } else if (d != null && String(d).trim()) {
    return String(d);
  }
  return response.statusText || "Request failed";
}
