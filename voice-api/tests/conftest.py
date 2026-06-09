"""Test fixtures. Redirects the writable data dir to a tmp path before the app
imports config, and provides a TestClient that runs the real startup (loads the
Kokoro model). If the model files are absent (e.g. a CI box without the assets),
the whole suite skips with a clear reason rather than failing spuriously."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Redirect data dir BEFORE app/config import so generated audio + registry land in tmp.
_TMP = tempfile.mkdtemp(prefix="voiceapi-test-")
os.environ.setdefault("VOICE_DATA_DIR", _TMP)

import config  # noqa: E402

MODEL_PRESENT = Path(config.KOKORO_MODEL).exists() and Path(config.KOKORO_VOICES).exists()


@pytest.fixture(scope="session")
def client():
    """Integration client. Skips (not fails) when the model assets are absent, so
    pure-unit tests still run anywhere while synthesis tests run on the box."""
    if not MODEL_PRESENT:
        pytest.skip(f"Kokoro model not present at {config.KOKORO_MODEL}")
    from fastapi.testclient import TestClient
    import app as appmod
    with TestClient(appmod.app) as c:  # runs lifespan startup -> loads model
        yield c
