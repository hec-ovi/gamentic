"""Test config: drive the REAL adapter routes against a respx-faked Anna agent.

Set BEFORE app.main is imported (config reads these at import time)."""

import os

os.environ.setdefault("ANNA_AGENT_URL", "http://agent.test:19001")

import pytest
from fastapi.testclient import TestClient

AGENT = "http://agent.test:19001"


@pytest.fixture
def client():
    from app import main

    # the module-level singleton keeps session cookies across tests; reset it
    main.agent._cookies = {}
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def agent_volume(monkeypatch, tmp_path):
    """A fake agent state volume holding a signed-in profile's refresh token,
    the way the Web UI sign-in leaves it on anna-data."""
    from app import config

    profile = tmp_path / ".matrix" / "profiles" / "production" / "tester_0001"
    profile.mkdir(parents=True)
    (tmp_path / ".matrix" / "active_profile").write_text("production/tester_0001\n")
    (profile / "refresh_token").write_text("rt-volume-secret\n")
    monkeypatch.setattr(config, "AGENT_STATE_DIR", str(tmp_path / ".matrix"))
    yield profile


@pytest.fixture
def creds(monkeypatch):
    """Configure local-API credentials for the login/retry paths."""
    from app import config

    monkeypatch.setattr(config, "AGENT_USERNAME", "hec@example.com")
    monkeypatch.setattr(config, "AGENT_PASSWORD", "secret")
    yield


@pytest.fixture
def no_creds(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "AGENT_USERNAME", "")
    monkeypatch.setattr(config, "AGENT_PASSWORD", "")
    yield
