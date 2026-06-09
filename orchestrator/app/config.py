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
    CHARACTER_MAX_TOKENS = int(os.getenv("CHARACTER_MAX_TOKENS", "220"))

    # Context budgeting
    HISTORY_BEATS = int(os.getenv("HISTORY_BEATS", "24"))   # raw recent beats fed to narrator
    SCENE_BEATS = int(os.getenv("SCENE_BEATS", "14"))       # recent beats a character perceives
    LORE_BUDGET = int(os.getenv("LORE_BUDGET", "8"))        # max lore entries injected
    MAX_CHARACTER_REACTIONS = int(os.getenv("MAX_CHARACTER_REACTIONS", "3"))
    # Multi-actor cascade caps (pacing + runaway-loop guard; research: cap cascade depth)
    TURN_MAX_ACTOR_STEPS = int(os.getenv("TURN_MAX_ACTOR_STEPS", "6"))   # total character beats per turn
    TURN_MAX_PER_CHARACTER = int(os.getenv("TURN_MAX_PER_CHARACTER", "2"))  # times one char can act per turn

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
