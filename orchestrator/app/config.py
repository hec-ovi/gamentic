"""Runtime configuration. Everything overridable by env; sane local defaults."""
import os


def _optional_float(name: str) -> float | None:
    """A sampling knob: unset or empty means the field is never sent, so the server's
    own default (and the model's own recommended value) stands."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _seconds_or_none(name: str, default: str) -> float | None:
    """A wall-clock ceiling in seconds, where 0 (or anything unparseable) means
    NO ceiling. httpx reads None as 'never time out', so the value goes straight
    through to the transport."""
    try:
        v = float(os.getenv(name, default) or 0)
    except ValueError:
        v = 0.0
    return v if v > 0 else None


class Settings:
    # llama.cpp OpenAI-compatible endpoint. In compose this is the container name.
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8080/v1")
    LLM_MODEL = os.getenv("LLM_MODEL", "gemma-4-12b-heretic")
    # NO ceiling by owner decision (2026-07-25): a thinking model at deep context
    # blew the old 300s transport timeout, the ReadTimeout escaped as a bare 500,
    # and the whole turn was lost. Waiting is always better than losing the turn.
    # Set LLM_TIMEOUT to a positive number of seconds to put a ceiling back.
    LLM_TIMEOUT = _seconds_or_none("LLM_TIMEOUT", "0")
    # Kill-switch for the streaming transport. When false, calls that ask for live
    # deltas (on_delta/cancel) fall back to the blocking request: deltas arrive once,
    # whole, at the end; cancel is honored between calls only. Turn results are
    # identical either way; this only trades liveness for the old wire behavior.
    LLM_STREAM = os.getenv("LLM_STREAM", "true").lower() == "true"
    # The model's context window, for the context-usage meter (used/max shown in the UI).
    LLM_CONTEXT_SIZE = int(os.getenv("LLM_CONTEXT_SIZE", "131072"))

    # Sampling belongs to the SERVER (owner 2026-07-25: "leave all default", "i dont like
    # toy with those values at all"). The nine per-call temperatures that used to live
    # here and at each call site are gone: they were guesses, they differed per call for
    # no measured reason, and they overrode both the model's own recommended values and
    # llama.cpp's defaults. Empty = the field is never sent, which is the default and the
    # intended state; set one in .env and it applies to every call, for an experiment.
    # One switch, then the values. Off = the app sends no sampling field at all. On =
    # every field you filled in below rides on every call; the ones left empty still are
    # not sent, so turning the switch on does not silently invent numbers.
    LLM_SAMPLING = os.getenv("LLM_SAMPLING", "false").lower() == "true"
    LLM_TEMPERATURE = _optional_float("LLM_TEMPERATURE")
    LLM_TOP_P = _optional_float("LLM_TOP_P")
    LLM_TOP_K = _optional_float("LLM_TOP_K")
    LLM_MIN_P = _optional_float("LLM_MIN_P")

    def sampling(self) -> dict:
        """What to merge into a request payload: empty unless the switch is on. Read off
        the instance, like every other setting, so a runtime override lands."""
        if not self.LLM_SAMPLING:
            return {}
        fields = {"temperature": self.LLM_TEMPERATURE, "top_p": self.LLM_TOP_P,
                  "top_k": self.LLM_TOP_K, "min_p": self.LLM_MIN_P}
        return {k: v for k, v in fields.items() if v is not None}
    # A/B knob for a hybrid thinking model: request-level enable_thinking on the NARRATOR
    # call only (llama.cpp merges it over the server's global chat-template kwargs).
    # Utility and character calls never think.
    NARRATOR_THINKING = os.getenv("NARRATOR_THINKING", "true").lower() == "true"
    NARRATOR_MAX_TOKENS = int(os.getenv("NARRATOR_MAX_TOKENS", "0"))    # 0 = the global guard below
    # A RUNAWAY guard, not a length dial (owner 2026-07-25, after a degenerate loop ran
    # 61,805 tokens over 42 minutes from a 938-token prompt, with the transport ceiling
    # gone and nothing to stop it before the context wall). 4096 tokens is around 3000
    # words: past any narration, character line, recap or interpreter payload, so nothing
    # real is ever cut. It ends generations that have stopped being output. Length is
    # still shaped by the prompt asking for content, never by this number.
    LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))
    # The one call that legitimately writes more: save_world carries an entire world
    # bible as tool-call JSON, and JSON cut mid-object is unparseable, not merely short
    # (creator.py). Same guard, room to finish.
    WORLD_MAX_TOKENS = int(os.getenv("WORLD_MAX_TOKENS", "16384"))
    # Follow-up "resolve" narration pass: when the narrator changed state via tools but wrote
    # no prose, a short second pass voices the outcome so no turn is dead air.
    # Uncapped like every other call (see INTERPRET_MAX_TOKENS): the prompt asks for a
    # short outcome, a ceiling only cut it mid-sentence.
    NARRATOR_RESOLVE_MAX_TOKENS = int(os.getenv("NARRATOR_RESOLVE_MAX_TOKENS", "0"))
    # Agentic input interpreter: freeform typed actions are parsed into structured
    # say/do/attack/give/whisper segments by one small LLM call before the turn runs,
    # so typing freely gets directed routing + adjudication like the buttons do.
    # Falls back to the raw text on any failure. One extra call (~1-2s) per typed turn.
    INTERPRET_FREE_TEXT = os.getenv("INTERPRET_FREE_TEXT", "true").lower() == "true"
    # 0 = uncapped, and it MUST stay that way: this call answers with a tool call whose
    # arguments are JSON, and a ceiling truncates that JSON mid-object. The parse then
    # fails, the arguments read as {}, and the turn silently falls back to the raw text -
    # live 2026-07-25: 'fill the form ... and give it to Chinesa' produced
    # submit_segments({}), so no give attempt was ever built and the form never moved.
    # creator.py documents the identical failure for save_world. Shape output with the
    # prompt, never with a token ceiling.
    INTERPRET_MAX_TOKENS = int(os.getenv("INTERPRET_MAX_TOKENS", "0"))
    CHARACTER_MAX_TOKENS = int(os.getenv("CHARACTER_MAX_TOKENS", "0"))  # 0 = uncapped (prompt governs length)

    # Context budgeting. The verbatim window is GENEROUS by owner decision (slower turns
    # are an accepted trade for a richer story); it is also a per-game live setting
    # (PATCH /settings {history_beats}). Prefill on the box runs ~600 tok/s: every ~600
    # tokens of window costs ~1s per narrator call.
    HISTORY_BEATS = int(os.getenv("HISTORY_BEATS", "80"))   # raw recent beats fed to narrator
    # Rolling story recap: everything OLDER than the recent turns gets folded into a
    # compact facts-only summary (one background LLM call), so the narrator knows the
    # WHOLE story at a bounded token cost. Characters fold separately (CHAR_SUMMARY_*
    # below) from witnessed beats only.
    SUMMARY_ENABLED = os.getenv("SUMMARY_ENABLED", "true").lower() == "true"
    SUMMARY_EVERY_TURNS = int(os.getenv("SUMMARY_EVERY_TURNS", "10"))  # fold cadence
    SUMMARY_KEEP_TURNS = int(os.getenv("SUMMARY_KEEP_TURNS", "8"))     # newest turns never folded
    # Uncapped: a recap is re-fed to every prompt, so a ceiling that cuts it mid-fact
    # poisons memory permanently. The prompt asks for facts-only lines; that is the
    # length control.
    SUMMARY_MAX_TOKENS = int(os.getenv("SUMMARY_MAX_TOKENS", "0"))
    # Character memory (each character agent has its OWN whole context, bounded):
    # verbatim window = the newest beats THEY witnessed (stamped per beat, follows them
    # across scenes); everything older folds into their private recap below.
    CHAR_HISTORY_BEATS = int(os.getenv("CHAR_HISTORY_BEATS", "30"))
    # Per-character rolling recap: when a character has accumulated CHAR_SUMMARY_EVERY
    # unfolded witnessed BEATS (the cadence unit is beats; the fold cursor is a beats
    # turn_index like the game recap), one background LLM call folds them into their
    # memory_summary. Only story-central characters ever cross the threshold, so this
    # never adds a per-turn call for the whole cast.
    CHAR_SUMMARY_ENABLED = os.getenv("CHAR_SUMMARY_ENABLED", "true").lower() == "true"
    CHAR_SUMMARY_EVERY = int(os.getenv("CHAR_SUMMARY_EVERY", "12"))      # cadence, in witnessed beats
    CHAR_SUMMARY_KEEP_TURNS = int(os.getenv("CHAR_SUMMARY_KEEP_TURNS", "8"))  # newest turns never folded
    CHAR_SUMMARY_MAX_TOKENS = int(os.getenv("CHAR_SUMMARY_MAX_TOKENS", "0"))  # see SUMMARY_MAX_TOKENS
    LORE_BUDGET = int(os.getenv("LORE_BUDGET", "8"))        # max lore entries injected
    # Turn economy (owner direction 2026-06-10 + 2026-07-20: a turn is a beat, not a
    # chapter, and not a lecture - he wants an AGILE exchange, not stacked conversations
    # and long reaction chains). One or two voices per narrator reply, each once, with a
    # tight cascade budget. All live-tunable by env.
    MAX_CHARACTER_REACTIONS = int(os.getenv("MAX_CHARACTER_REACTIONS", "2"))
    TURN_MAX_ACTOR_STEPS = int(os.getenv("TURN_MAX_ACTOR_STEPS", "3"))   # total character beats per turn
    TURN_MAX_PER_CHARACTER = int(os.getenv("TURN_MAX_PER_CHARACTER", "1"))  # times one char can act per turn

    # FICTIONAL story time (hybrid): every turn auto-ticks a few minutes so the clock never
    # freezes, and the narrator jumps it with advance_time (hours/days). Never wall clock.
    TURN_TIME_MINUTES = int(os.getenv("TURN_TIME_MINUTES", "5"))
    DAY_START_HOUR = int(os.getenv("DAY_START_HOUR", "8"))     # in-fiction hour at story start
    TIME_ADVANCE_CAP_DAYS = int(os.getenv("TIME_ADVANCE_CAP_DAYS", "30"))  # max one advance_time jump

    # SSE keepalive: a comment ping every N seconds keeps proxies from idling the
    # /games/{gid}/events stream out (small in tests, 20s live).
    EVENTS_KEEPALIVE_S = float(os.getenv("EVENTS_KEEPALIVE_S", "20"))

    # Hard ceiling on ONE apply_damage/attack call, whoever calls it. The engine clamps
    # client-supplied attack amounts separately; this is defense in depth at the tool
    # layer (live: a player segment rode amount=9999 through adjudication and one-shot
    # a 10hp character off "a flick on the ear").
    DAMAGE_CAP = int(os.getenv("DAMAGE_CAP", "6"))

    # Scene/inventory/action caps (the fixed slot counts; single source of truth for the UI grids)
    SCENE_EXIT_CAP = int(os.getenv("SCENE_EXIT_CAP", "3"))
    SCENE_INVENTORY_CAP = int(os.getenv("SCENE_INVENTORY_CAP", "6"))
    CHAR_INVENTORY_CAP = int(os.getenv("CHAR_INVENTORY_CAP", "3"))
    CHAR_ACTION_CAP = int(os.getenv("CHAR_ACTION_CAP", "4"))   # 3 base + a rotating contextual offer (owner call 2026-06-11)
    CHAR_TRAIT_CAP = int(os.getenv("CHAR_TRAIT_CAP", "12"))   # unlocked traits per character
    SCENE_ACTION_CAP = int(os.getenv("SCENE_ACTION_CAP", "3"))

    DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "gamentic.db"))
    # A turn holds its write transaction across every LLM call it makes, so this busy
    # timeout has to outlast a worst-case turn or a background writer (image/portrait
    # persist) raises "database is locked" and loses its work. With LLM_TIMEOUT off,
    # a worst case is however long the model thinks: an hour of patience, not 330s.
    DB_TIMEOUT = float(os.getenv("DB_TIMEOUT", "3600"))
    # Per-game image store (downloaded from image-api, served by us, deleted on wipe).
    GAMES_DATA_DIR = os.getenv("GAMES_DATA_DIR",
                               os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "games"))

    # --- Image integration (orchestrator -> image-api, server to server) ---
    IMAGE_API_URL = os.getenv("IMAGE_API_URL", "http://localhost:9001")
    IMAGE_ENABLED = os.getenv("IMAGE_ENABLED", "true").lower() == "true"
    # Scene size is orchestrator-owned (sent to /image/generate). Character per-view sizing
    # (square face vs tall body) is image-api-owned; see docs/image/image-service.md.
    # Benchmarked on the box: 768x768 renders in ~5.6s, so scenes default to real quality.
    IMAGE_SCENE_W = int(os.getenv("IMAGE_SCENE_W", "768"))
    IMAGE_SCENE_H = int(os.getenv("IMAGE_SCENE_H", "768"))
    # The 'See' snapshot (scene WITH present characters) is a wide landscape shot so full
    # figures fit side by side. 1152x768 benchmarks like the tall body size (~7.6s).
    IMAGE_VIEW_W = int(os.getenv("IMAGE_VIEW_W", "1152"))
    IMAGE_VIEW_H = int(os.getenv("IMAGE_VIEW_H", "768"))
    # Where the image-api can fetch OUR persisted /media files from (compose-internal
    # hostname). Used to absolutize character reference URLs for identity conditioning.
    MEDIA_INTERNAL_BASE = os.getenv("MEDIA_INTERNAL_BASE", "http://gamentic-orchestrator:8000")
    # The art director (owner direction 2026-07-21: EVERY image gets one). At creation,
    # one call reads the whole world bible and writes every character descriptor + the
    # main opening image prompt. After that, every render (scene art, See/look snapshots,
    # narrator shots, item cards) spins up a per-image art-director call that writes the
    # prompt from the whole live context. Adds one LLM call per image (it shares the
    # single llama.cpp server with turns). Deterministic guards + template fallback
    # still apply on any failure.
    IMAGE_ART_DIRECTOR = os.getenv("IMAGE_ART_DIRECTOR", "true").lower() == "true"
    # Item unlock images: a small square card rendered when an item first becomes visible
    # (obtained, revealed, placed in view), shown as a system image beat and attached to
    # the item. Capped per turn so a loot shower doesn't queue a render storm.
    IMAGE_ITEMS = os.getenv("IMAGE_ITEMS", "true").lower() == "true"
    IMAGE_ITEM_SIZE = int(os.getenv("IMAGE_ITEM_SIZE", "320"))
    IMAGE_MAX_ITEMS_PER_TURN = int(os.getenv("IMAGE_MAX_ITEMS_PER_TURN", "2"))
    # Spontaneous narrator images (the show_image tool fired WITHOUT the player looking)
    # are allowed only every N turns, so they stay a dramatic beat, not wallpaper.
    # A player look always renders if the narrator calls the tool.
    IMAGE_NARRATOR_COOLDOWN_TURNS = int(os.getenv("IMAGE_NARRATOR_COOLDOWN_TURNS", "4"))
    # A character showing what THEY are doing, asked for by the character itself rather
    # than by the narrator. Three levels the player picks per game; the number is the
    # minimum turns between two character shots, counted against the same cursor the
    # narrator's pacing uses, so images stay spaced however they were asked for.
    IMAGE_CHARACTER_LEVELS = {"off": 0, "sometimes": 6, "often": 2}
    IMAGE_CHARACTER_FREQUENCY = os.getenv("IMAGE_CHARACTER_FREQUENCY", "sometimes")

    # --- Voice integration (orchestrator -> voice-api, server to server) ---
    VOICE_API_URL = os.getenv("VOICE_API_URL", "http://localhost:9002")
    VOICE_ENABLED = os.getenv("VOICE_ENABLED", "true").lower() == "true"


settings = Settings()
