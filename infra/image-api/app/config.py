"""Adapter configuration, all overridable via environment variables."""

from __future__ import annotations

import os
from pathlib import Path

# Where ComfyUI lives. On the gamentic docker network it is reachable by container name.
COMFY_URL: str = os.environ.get("COMFY_URL", "http://gamentic-image:8188")

# API-format workflow template to drive (FLUX.2 Klein distilled by default).
WORKFLOW_TEMPLATE: Path = Path(
    os.environ.get(
        "WORKFLOW_TEMPLATE",
        str(Path(__file__).resolve().parent.parent / "workflows" / "flux2_klein_api.json"),
    )
)

# Generation defaults. Small + few-step keeps a single image under ~60s on Strix Halo.
# Callers can override width/height/seed per request; steps is tuned for the distilled model.
DEFAULT_WIDTH: int = int(os.environ.get("IMAGE_DEFAULT_WIDTH", "1024"))
DEFAULT_HEIGHT: int = int(os.environ.get("IMAGE_DEFAULT_HEIGHT", "1024"))
DEFAULT_STEPS: int = int(os.environ.get("IMAGE_DEFAULT_STEPS", "4"))

# Hard ceiling on a single generation before we give up (seconds).
GENERATE_TIMEOUT: float = float(os.environ.get("IMAGE_GENERATE_TIMEOUT", "120"))

# Clamp requested dimensions so a caller can't ask for a 4k image that blows the budget.
MAX_DIM: int = int(os.environ.get("IMAGE_MAX_DIM", "1536"))
