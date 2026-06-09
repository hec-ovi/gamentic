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
# These are the /image/generate (scene) fallbacks; the orchestrator owns scene size and
# normally passes width/height explicitly. Scene is roughly square.
DEFAULT_WIDTH: int = int(os.environ.get("IMAGE_DEFAULT_WIDTH", "768"))
DEFAULT_HEIGHT: int = int(os.environ.get("IMAGE_DEFAULT_HEIGHT", "768"))
DEFAULT_STEPS: int = int(os.environ.get("IMAGE_DEFAULT_STEPS", "4"))

# Per-view sizes for /image/character. The image-api OWNS these (the orchestrator sends
# only descriptor/style/seed): face comes back square, body views come back tall full-body
# so the vertical character cards are not cropped. All env-tunable, no rebuild to change.
# Ratios preserved (face 1:1, body 9:16). Body MUST stay elongated 9:16: a wider 2:3 frame
# makes klein fill the width and crop the feet (verified). Defaults are at the big end of the
# measured curve; klein is fast enough on this box that ~3-8s/image is acceptable for detail.
CHAR_FACE_WIDTH: int = int(os.environ.get("IMAGE_CHAR_FACE_WIDTH", "512"))
CHAR_FACE_HEIGHT: int = int(os.environ.get("IMAGE_CHAR_FACE_HEIGHT", "512"))
CHAR_BODY_WIDTH: int = int(os.environ.get("IMAGE_CHAR_BODY_WIDTH", "640"))
CHAR_BODY_HEIGHT: int = int(os.environ.get("IMAGE_CHAR_BODY_HEIGHT", "1152"))

# Hard ceiling on a single generation before we give up (seconds).
GENERATE_TIMEOUT: float = float(os.environ.get("IMAGE_GENERATE_TIMEOUT", "120"))

# Clamp requested dimensions so a caller can't ask for a 4k image that blows the budget.
MAX_DIM: int = int(os.environ.get("IMAGE_MAX_DIM", "1536"))
