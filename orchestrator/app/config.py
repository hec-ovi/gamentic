"""Runtime configuration. Everything overridable by env; sane local defaults."""
import os


class Settings:
    # llama.cpp OpenAI-compatible endpoint. In compose this is the container name.
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8080/v1")
    LLM_MODEL = os.getenv("LLM_MODEL", "gemma-4-12b-heretic")
    LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "180"))
    # The model's context window, for the context-usage meter (used/max shown in the UI).
    LLM_CONTEXT_SIZE = int(os.getenv("LLM_CONTEXT_SIZE", "131072"))

    # Sampling
    NARRATOR_TEMPERATURE = float(os.getenv("NARRATOR_TEMPERATURE", "0.8"))
    CHARACTER_TEMPERATURE = float(os.getenv("CHARACTER_TEMPERATURE", "0.9"))
    NARRATOR_MAX_TOKENS = int(os.getenv("NARRATOR_MAX_TOKENS", "400"))
    # Follow-up "resolve" narration pass: when the narrator changed state via tools but wrote
    # no prose, a short second pass voices the outcome so no turn is dead air.
    NARRATOR_RESOLVE_MAX_TOKENS = int(os.getenv("NARRATOR_RESOLVE_MAX_TOKENS", "180"))
    # Agentic input interpreter: freeform typed actions are parsed into structured
    # say/do/attack/give/whisper segments by one small LLM call before the turn runs,
    # so typing freely gets directed routing + adjudication like the buttons do.
    # Falls back to the raw text on any failure. One extra call (~1-2s) per typed turn.
    INTERPRET_FREE_TEXT = os.getenv("INTERPRET_FREE_TEXT", "true").lower() == "true"
    INTERPRET_MAX_TOKENS = int(os.getenv("INTERPRET_MAX_TOKENS", "300"))
    # Roomy enough for a character to actually tell something (owner feedback: replies
    # felt clipped); the prompt still says to stop when the point is made.
    CHARACTER_MAX_TOKENS = int(os.getenv("CHARACTER_MAX_TOKENS", "420"))

    # Context budgeting
    HISTORY_BEATS = int(os.getenv("HISTORY_BEATS", "24"))   # raw recent beats fed to narrator
    SCENE_BEATS = int(os.getenv("SCENE_BEATS", "14"))       # recent beats a character perceives
    LORE_BUDGET = int(os.getenv("LORE_BUDGET", "8"))        # max lore entries injected
    MAX_CHARACTER_REACTIONS = int(os.getenv("MAX_CHARACTER_REACTIONS", "3"))
    # Multi-actor cascade caps (pacing + runaway-loop guard; research: cap cascade depth)
    TURN_MAX_ACTOR_STEPS = int(os.getenv("TURN_MAX_ACTOR_STEPS", "6"))   # total character beats per turn
    TURN_MAX_PER_CHARACTER = int(os.getenv("TURN_MAX_PER_CHARACTER", "2"))  # times one char can act per turn

    # FICTIONAL story time (hybrid): every turn auto-ticks a few minutes so the clock never
    # freezes, and the narrator jumps it with advance_time (hours/days). Never wall clock.
    TURN_TIME_MINUTES = int(os.getenv("TURN_TIME_MINUTES", "5"))
    DAY_START_HOUR = int(os.getenv("DAY_START_HOUR", "8"))     # in-fiction hour at story start
    TIME_ADVANCE_CAP_DAYS = int(os.getenv("TIME_ADVANCE_CAP_DAYS", "30"))  # max one advance_time jump

    # Scene/inventory/action caps (the fixed slot counts; single source of truth for the UI grids)
    SCENE_EXIT_CAP = int(os.getenv("SCENE_EXIT_CAP", "3"))
    SCENE_INVENTORY_CAP = int(os.getenv("SCENE_INVENTORY_CAP", "6"))
    CHAR_INVENTORY_CAP = int(os.getenv("CHAR_INVENTORY_CAP", "3"))
    CHAR_ACTION_CAP = int(os.getenv("CHAR_ACTION_CAP", "3"))
    SCENE_ACTION_CAP = int(os.getenv("SCENE_ACTION_CAP", "3"))

    DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "gamentic.db"))
    # Per-game image store (downloaded from image-api, served by us, deleted on wipe).
    GAMES_DATA_DIR = os.getenv("GAMES_DATA_DIR",
                               os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "games"))

    # --- Image integration (orchestrator -> image-api, server to server) ---
    IMAGE_API_URL = os.getenv("IMAGE_API_URL", "http://localhost:9001")
    IMAGE_ENABLED = os.getenv("IMAGE_ENABLED", "true").lower() == "true"
    # Scene size is orchestrator-owned (sent to /image/generate). Character per-view sizing
    # (square face vs tall body) is image-api-owned; see docs/image-agent-contract.md.
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
    # Spontaneous narrator images (the show_image tool fired WITHOUT the player looking)
    # are allowed only every N turns, so they stay a dramatic beat, not wallpaper.
    # A player look always renders if the narrator calls the tool.
    IMAGE_NARRATOR_COOLDOWN_TURNS = int(os.getenv("IMAGE_NARRATOR_COOLDOWN_TURNS", "4"))
    # Per-turn VISUAL budget so the screen does not get noisy. These cap how many images
    # are shown in a single turn, not how many exist. Character references are generated
    # ONCE at creation and reused; this only limits display.
    IMAGE_MAX_ARTIFACTS_PER_TURN = int(os.getenv("IMAGE_MAX_ARTIFACTS_PER_TURN", "4"))
    IMAGE_MAX_SCENE_PER_TURN = int(os.getenv("IMAGE_MAX_SCENE_PER_TURN", "1"))
    IMAGE_MAX_CHARACTERS_PER_TURN = int(os.getenv("IMAGE_MAX_CHARACTERS_PER_TURN", "2"))

    # --- Voice integration (orchestrator -> voice-api, server to server) ---
    VOICE_API_URL = os.getenv("VOICE_API_URL", "http://localhost:9002")
    VOICE_ENABLED = os.getenv("VOICE_ENABLED", "true").lower() == "true"


settings = Settings()
