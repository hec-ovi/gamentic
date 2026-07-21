"""Test harness. Real FastAPI routes + real SQLite; the LLM is faked at the
app.llm.chat boundary (the one external dependency), so the turn loop, tool
dispatch, and DB writes are all exercised for real.
"""
import os
import re
import tempfile

import pytest

# Point the DB at a temp file BEFORE importing the app (config reads env at import).
_TMP = tempfile.mkdtemp(prefix="gamentic-test-")
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")
# Media services are off by default in tests (they are best-effort accessories);
# the integration test enables them and mocks the network layer.
os.environ.setdefault("IMAGE_ENABLED", "false")
os.environ.setdefault("VOICE_ENABLED", "false")
# Hermetic suite: any test that enables media without stubbing it must hit a DEAD
# port, never the live services (live 2026-06-11: a suite run rendered 14 REAL
# images through localhost:9001 into the just-purged staging dir - each one a
# ~6s GPU render - while the inert cleanup stubs kept the deletes from firing).
os.environ["IMAGE_API_URL"] = "http://127.0.0.1:9"
os.environ["VOICE_API_URL"] = "http://127.0.0.1:9"

from fastapi.testclient import TestClient  # noqa: E402
from app import db, llm, main, media  # noqa: E402


class FakeLLM:
    """Scriptable stand-in for the model. Branches on the call shape:
    narrator (tools present, not save_world), character (no tools),
    creator-finalize (save_world tool present)."""

    def __init__(self):
        self.narrator = llm.LLMReply(content="You step forward into the dark.")
        self.narrator_script = []          # queue of LLMReply consumed per narrator call
        self.resolve = llm.LLMReply(content="The moment settles around you.")  # follow-up narration pass
        self.character = llm.LLMReply(content="\"Stay close,\" she whispers.")
        self.character_replies = {}        # name -> LLMReply
        self.finalize = llm.LLMReply(content="", tool_calls=[])
        self.creator_text = llm.LLMReply(content="What kind of world do you imagine?")
        # per-image art director: default empty -> _artdirected_prompt falls back to the
        # template prompt, so render tests keep their deterministic pre-director
        # behavior unless they script a directed prompt explicitly
        self.image_prompt = llm.LLMReply(content="")
        # art director: default empty -> art_direction returns None and the templates
        # carry the renders, so creation tests keep their pre-director behavior unless
        # they script a direction explicitly
        self.artdirector = llm.LLMReply(content="")
        # default: interpreter yields nothing -> engine falls back to the raw action text,
        # so existing free-text tests behave exactly as before
        self.interpret = llm.LLMReply(content="", tool_calls=[])
        self.explain = llm.LLMReply(content="A thing of note, by the look of it.")
        self.summary = llm.LLMReply(content="- The player arrived and met the locals.")
        self.charsummary = llm.LLMReply(content="- You remember the player arriving.")
        # default EMPTY: enrichment skips the write, so fixture origins stay untouched
        # in every test that does not opt in by setting fake.origin to a biography
        self.origin = llm.LLMReply(content="")
        self.calls = []

    def __call__(self, messages, tools=None, tool_choice="auto", temperature=0.8,
                 max_tokens=0, stop=None, thinking=None, on_delta=None, cancel=None):
        sys = messages[0]["content"] if messages else ""
        names = [t["function"]["name"] for t in (tools or [])]
        self.calls.append({"messages": messages, "tools": tools, "system": sys, "names": names,
                           "max_tokens": max_tokens, "stop": stop, "thinking": thinking})
        reply = self._dispatch(sys, names)
        # Mirror the real streaming transport: content arrives as a few fragments, and a
        # set cancel flag aborts the call mid-delivery exactly like a closed stream.
        if cancel is not None and cancel.is_set():
            raise llm.LLMCancelled()
        if on_delta is not None and reply.content:
            text = reply.content
            step = max(1, len(text) // 3)
            for i in range(0, len(text), step):
                if cancel is not None and cancel.is_set():
                    raise llm.LLMCancelled()
                on_delta(text[i:i + step])
        return reply

    def _dispatch(self, sys, names):
        if "save_world" in names:
            return self.finalize
        if "submit_segments" in names:               # input interpreter
            return self.interpret
        if "cue_character" in names:                 # narrator toolset
            if self.narrator_script:
                return self.narrator_script.pop(0)
            return self.narrator
        if sys.startswith("You narrate the immediate outcome"):  # resolve narration pass
            return self.resolve
        if sys.startswith("You write a single image-generation prompt"):  # agentic image prompt
            return self.image_prompt
        if sys.startswith("You are the art director"):       # creation art direction
            return self.artdirector
        if sys.startswith("You answer the player's tap"):    # tap-to-explain
            return self.explain
        if sys.startswith("You maintain the story recap"):   # rolling summary fold
            return self.summary
        if sys.startswith("You maintain the private memory"):  # per-character recap fold
            return self.charsummary
        if sys.startswith("You deepen the private backstory"):  # origin enrichment
            if isinstance(self.origin, Exception):
                raise self.origin
            return self.origin
        if sys.startswith("You are a warm"):         # story-creator chat
            return self.creator_text
        # otherwise a character call (may carry CHARACTER_TOOLS attack/give, or none)
        m = re.match(r"You are (.+?),", sys)          # "You are <Name>, a character..."
        nm = m.group(1) if m else ""
        rep = self.character_replies.get(nm, self.character)
        if isinstance(rep, list):                     # a queue: consumed call by call
            rep = rep.pop(0) if len(rep) > 1 else rep[0]
        return rep

    def narrator_calls(self):
        return [c for c in self.calls if "cue_character" in c["names"]]

    def character_calls(self):
        return [c for c in self.calls if c["system"].startswith("You are ")
                and "cue_character" not in c["names"]
                and not c["system"].startswith("You are a warm")]


@pytest.fixture(autouse=True)
def fresh_db():
    if os.path.exists(os.environ["DB_PATH"]):
        os.remove(os.environ["DB_PATH"])
    db.init_db()
    yield


@pytest.fixture(autouse=True)
def inert_media_cleanup(monkeypatch):
    """The ownership-cleanup calls are DESTRUCTIVE against live services: the dev box
    usually has the real image-api/voice-api up on 9001/9002, and a wipe test that
    flips IMAGE_ENABLED on would otherwise EMPTY THE REAL STAGING FOLDER. Inert by
    default; tests that assert these calls re-patch them with recorders, and the
    wire-shape tests reach the real functions via direct module imports."""
    monkeypatch.setattr(media, "delete_staging_image", lambda url: None)
    monkeypatch.setattr(media, "purge_all_staging_images", lambda: None)
    monkeypatch.setattr(media, "purge_game_audio", lambda gid: None)
    monkeypatch.setattr(media, "purge_all_audio", lambda: None)


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(llm, "chat", fake)
    return fake


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def world():
    return {
        "title": "The Sunken Crypt",
        "setting": "a flooded dwarven crypt",
        "tone": "grim, tense",
        "narrator_persona": "A solemn, vivid dungeon master.",
        "opening_scenario": "Cold water laps at your boots as the crypt door groans shut behind you.",
        "start_location": "crypt entrance",
        "player_life": 20,
        "characters": [
            {"name": "Mara", "persona": "A wary dwarven scout, loyal but blunt.",
             "knowledge": "Knows a secret tunnel behind the altar."}
        ],
        "quests": [
            {"title": "Escape the Crypt", "description": "Find a way out.",
             "objectives": ["Find the altar", "Open the tunnel"]}
        ],
        "lore": [
            {"keys": ["altar"], "content": "The altar bleeds black water when touched.", "constant": False}
        ],
    }
