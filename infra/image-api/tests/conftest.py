"""Test config: drive the REAL shipped Klein workflow against a fake ComfyUI host.

Set BEFORE app.main is imported (config reads these at import time)."""

import os
from pathlib import Path

_PROD_WORKFLOW = (
    Path(__file__).resolve().parent.parent / "workflows" / "flux2_klein_api.json"
)

os.environ.setdefault("WORKFLOW_TEMPLATE", str(_PROD_WORKFLOW))
os.environ.setdefault("COMFY_URL", "http://comfy.test:8188")
