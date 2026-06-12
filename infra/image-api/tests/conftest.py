"""Test config: drive the REAL shipped Klein workflow against a fake ComfyUI host.

Set BEFORE app.main is imported (config reads these at import time)."""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_PROD_WORKFLOW = (
    Path(__file__).resolve().parent.parent / "workflows" / "flux2_klein_api.json"
)

os.environ.setdefault("WORKFLOW_TEMPLATE", str(_PROD_WORKFLOW))
os.environ.setdefault("COMFY_URL", "http://comfy.test:8188")

# The DELETE endpoints unlink files in the staging (ComfyUI output) dir, so tests get a
# throwaway one - the default /comfy/output only exists inside the container.
_TEST_OUTPUT = Path(tempfile.mkdtemp(prefix="image-api-test-output-"))
os.environ.setdefault("COMFY_OUTPUT_DIR", str(_TEST_OUTPUT))


@pytest.fixture
def output_dir() -> Path:
    """A clean staging dir per test: created empty, emptied again afterwards so one
    test's leftovers can never make another test's purge count lie."""
    from app import config

    root = config.COMFY_OUTPUT_DIR
    root.mkdir(parents=True, exist_ok=True)
    for child in root.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    yield root
    for child in root.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
