"""Tiny persistent character -> voice registry.

The orchestrator is the real source of truth for game state, but the voice
service owns *voice assignment*: given a new character it picks a fitting, distinct
preset (and a default speed / emotion), remembers it, and can synthesize that
character's lines without the caller re-sending the voice each time. Backed by a
JSON file so it survives restarts; small enough to keep wholly in memory.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field

import config
import voices as voicelib


@dataclass
class Character:
    id: str
    name: str
    voice_id: str
    speed: float = 1.0
    base_emotion: str = "neutral"
    description: str = ""
    created_at: float = field(default_factory=lambda: 0.0)


class Registry:
    def __init__(self, path=config.CHARACTERS_FILE):
        self._path = path
        self._lock = threading.Lock()
        self._chars: dict[str, Character] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            raw = json.loads(self._path.read_text())
            self._chars = {k: Character(**v) for k, v in raw.items()}

    def _save(self) -> None:
        config.ensure_dirs()
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({k: asdict(v) for k, v in self._chars.items()}, indent=2))
        tmp.replace(self._path)

    def get(self, char_id: str) -> Character | None:
        return self._chars.get(char_id)

    def list(self) -> list[Character]:
        return list(self._chars.values())

    def used_voices(self) -> list[str]:
        return [c.voice_id for c in self._chars.values()]

    def upsert(
        self,
        *,
        available_voices: list[str],
        char_id: str,
        name: str,
        description: str = "",
        gender: str | None = None,
        accent: str | None = None,
        voice_id: str | None = None,
        speed: float | None = None,
        base_emotion: str = "neutral",
        now: float | None = None,
    ) -> Character:
        """Create or update a character. If ``voice_id`` is omitted, auto-assign a
        distinct preset from name/description on FIRST creation; a character that
        already exists keeps its voice (and speed) so re-creating an id is
        idempotent and never reshuffles an established voice."""
        with self._lock:
            existing = self._chars.get(char_id)
            assigned_speed = 1.0
            if voice_id is None:
                if existing is not None:
                    # idempotent: an existing character keeps its assigned voice/speed
                    voice_id, assigned_speed = existing.voice_id, existing.speed
                else:
                    voice_id, assigned_speed = voicelib.assign_voice(
                        available_voices,
                        key=char_id or name,
                        description=description,
                        gender=gender,
                        accent=accent,
                        exclude=[c.voice_id for cid, c in self._chars.items() if cid != char_id],
                    )
            char = Character(
                id=char_id,
                name=name,
                voice_id=voice_id,
                speed=speed if speed is not None else assigned_speed,
                base_emotion=base_emotion,
                description=description,
                created_at=self._chars[char_id].created_at if char_id in self._chars else (now or time.time()),
            )
            self._chars[char_id] = char
            self._save()
            return char

    def delete(self, char_id: str) -> bool:
        with self._lock:
            if char_id in self._chars:
                del self._chars[char_id]
                self._save()
                return True
            return False
