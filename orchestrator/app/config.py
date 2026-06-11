"""Runtime configuration. Everything overridable by env; sane local defaults."""
import os


class Settings:
    # llama.cpp OpenAI-compatible endpoint. In compose this is the container name.
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8080/v1")
    LLM_MODEL = os.getenv("LLM_MODEL", "gemma-4-12b-heretic")
    # Generous by owner decision: turns of 3-4 minutes are an accepted trade for story
    # depth, and an uncapped narrator generation at deep context can pass 180s (live:
    # a hard-mode continue at 10k ctx timed out at exactly 180s and lost the turn).
    LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "300"))
    # The model's context window, for the context-usage meter (used/max shown in the UI).
    LLM_CONTEXT_SIZE = int(os.getenv("LLM_CONTEXT_SIZE", "131072"))

    # Sampling
    NARRATOR_TEMPERATURE = float(os.getenv("NARRATOR_TEMPERATURE", "0.8"))
    # A/B knob for the 26B hybrid model: request-level enable_thinking on the NARRATOR
    # call only (llama.cpp merges it over the server's global chat-template kwargs).
    # Utility and character calls never think. Default off.
    NARRATOR_THINKING = os.getenv("NARRATOR_THINKING", "true").lower() == "true"
    CHARACTER_TEMPERATURE = float(os.getenv("CHARACTER_TEMPERATURE", "0.9"))
    NARRATOR_MAX_TOKENS = int(os.getenv("NARRATOR_MAX_TOKENS", "0"))    # 0 = uncapped (prompt governs length)
    # Follow-up "resolve" narration pass: when the narrator changed state via tools but wrote
    # no prose, a short second pass voices the outcome so no turn is dead air.
    NARRATOR_RESOLVE_MAX_TOKENS = int(os.getenv("NARRATOR_RESOLVE_MAX_TOKENS", "180"))
    # Agentic input interpreter: freeform typed actions are parsed into structured
    # say/do/attack/give/whisper segments by one small LLM call before the turn runs,
    # so typing freely gets directed routing + adjudication like the buttons do.
    # Falls back to the raw text on any failure. One extra call (~1-2s) per typed turn.
    INTERPRET_FREE_TEXT = os.getenv("INTERPRET_FREE_TEXT", "true").lower() == "true"
    INTERPRET_MAX_TOKENS = int(os.getenv("INTERPRET_MAX_TOKENS", "300"))
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
    SUMMARY_MAX_TOKENS = int(os.getenv("SUMMARY_MAX_TOKENS", "640"))
    SCENE_BEATS = int(os.getenv("SCENE_BEATS", "14"))       # legacy location window (scene_beats_for_character)
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
    CHAR_SUMMARY_MAX_TOKENS = int(os.getenv("CHAR_SUMMARY_MAX_TOKENS", "320"))
    LORE_BUDGET = int(os.getenv("LORE_BUDGET", "8"))        # max lore entries injected
    # Turn economy (owner direction 2026-06-10: a turn is a beat, not a chapter; he saw
    # three stacked conversations in one turn): at most two voices per narrator reply,
    # each speaking once, with a tight cascade budget. All live-tunable by env.
    MAX_CHARACTER_REACTIONS = int(os.getenv("MAX_CHARACTER_REACTIONS", "2"))
    TURN_MAX_ACTOR_STEPS = int(os.getenv("TURN_MAX_ACTOR_STEPS", "4"))   # total character beats per turn
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
    CHAR_ACTION_CAP = int(os.getenv("CHAR_ACTION_CAP", "3"))
    CHAR_TRAIT_CAP = int(os.getenv("CHAR_TRAIT_CAP", "12"))   # unlocked traits per character
    SCENE_ACTION_CAP = int(os.getenv("SCENE_ACTION_CAP", "3"))

    DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "gamentic.db"))
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
    # Agentic image prompts: the text model writes the scene/view image prompt from live
    # context (poses and the just-happened action included) instead of the code template.
    # Adds one LLM call per image (a few seconds, and it shares the single llama.cpp
    # server with turns). Deterministic guards + template fallback still apply. A/B this.
    IMAGE_AGENTIC_PROMPTS = os.getenv("IMAGE_AGENTIC_PROMPTS", "false").lower() == "true"
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

    # --- Voice integration (orchestrator -> voice-api, server to server) ---
    VOICE_API_URL = os.getenv("VOICE_API_URL", "http://localhost:9002")
    VOICE_ENABLED = os.getenv("VOICE_ENABLED", "true").lower() == "true"

    # --- Admin panel (/admin) ---
    # When set, the panel page and its /admin/providers API require
    # 'Authorization: Bearer <token>'. Empty = open (keep the stack off public nets).
    ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")


settings = Settings()
