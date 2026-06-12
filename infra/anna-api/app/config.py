"""Adapter configuration, all overridable via environment variables."""

from __future__ import annotations

import os

# Where the Anna agent lives. On the gamentic docker network it is reachable by
# container name; the agent serves its local API (uvicorn) on 19001.
AGENT_URL: str = os.environ.get("ANNA_AGENT_URL", "http://gamentic-anna-agent:19001").rstrip("/")

# The agent's state directory (the anna-data volume, mounted read-only here).
# The copilot endpoints want a LOCAL session on top of the agent's cloud sign-in;
# the adapter mints one by exchanging the signed-in profile's stored refresh
# token at POST /refresh (verified live on 1.1.0-beta.17). active_profile names
# the profile dir; <profile>/refresh_token is the token file.
AGENT_STATE_DIR: str = os.environ.get("ANNA_AGENT_STATE_DIR", "/agent-data/.matrix")

# Optional local-API credentials, the FALLBACK when no usable refresh token is on
# the volume (e.g. a password account instead of OAuth). When set the adapter
# logs in via POST /login (form) and retries once on a credentials error.
AGENT_USERNAME: str = os.environ.get("ANNA_AGENT_USERNAME", "")
AGENT_PASSWORD: str = os.environ.get("ANNA_AGENT_PASSWORD", "")

# Model id advertised on /v1/models and echoed back in completions. The copilot
# API has no model parameter; whatever the orchestrator sends is accepted.
MODEL_ID: str = os.environ.get("ANNA_MODEL_ID", "anna-copilot")

# Hard ceiling on one copilot ask (seconds). Keep below the orchestrator's
# LLM_TIMEOUT (300s) so the adapter answers with a real error instead of both
# sides timing out blind.
ASK_TIMEOUT: float = float(os.environ.get("ANNA_ASK_TIMEOUT", "240"))

# EXPERIMENTAL image path: when true, /v1/images/generations asks the copilot to
# generate an image and extracts a URL from the reply. Off by default: the agent's
# local API has no image endpoint, and the orchestrator absorbs image failures by
# design (the game stays text-only playable). Flip on only after verifying live
# that the copilot can return images, and mind the credit spend.
IMAGE_VIA_COPILOT: bool = os.environ.get("ANNA_IMAGE_VIA_COPILOT", "false").strip().lower() not in ("", "0", "false", "no")
