"""Game -> wav ownership manifest (the deletion contract, 2026-06-11).

The owner killed the retention-timer idea: nothing in this stack deletes media
on a clock. Instead, every wav a game claims via ``game_id`` on a speak is
recorded here as ``filename -> [game_ids]`` (basenames only, deduped), stored
as JSON beside the wavs it describes. When an adventure is deleted, the
orchestrator calls ``DELETE /voice/games/{gid}``: solely-owned wavs die with
the game, a wav claimed by other games just loses the gid from its list.

A corrupt or missing manifest must never take down a speak - in the worst case
we forget ownership and the orphans wait for the purge-all sweep. Writes are
atomic (tmp + os.replace) so a crash mid-save leaves the previous manifest
intact, never a half-written one.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import config


def _safe_wav(name: str) -> Path | None:
    """Resolve a manifest entry strictly inside the audio dir, or refuse.

    Entries are basenames by construction, but the manifest is a file on disk
    and files on disk get hand-edited; a doctored entry like ``../characters.json``
    must never let a game delete anything outside the cache (the same rule
    ``GET /audio/{name}`` enforces when serving)."""
    if not name or "/" in name or "\\" in name or ".." in name:
        return None
    path = (config.AUDIO_DIR / name).resolve()
    if path.parent != config.AUDIO_DIR.resolve():
        return None
    return path


class Manifest:
    def __init__(self, path: Path = config.MANIFEST_FILE):
        self._path = path
        self._lock = threading.Lock()
        self._claims: dict[str, list[str]] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text())
            self._claims = {str(k): sorted({str(g) for g in v})
                            for k, v in raw.items() if isinstance(v, list)}
        except Exception:
            # missing file, truncated JSON, or a dict where a list should be:
            # start empty rather than refuse to speak
            self._claims = {}

    def _save(self) -> None:
        config.ensure_dirs()
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._claims, indent=2, sort_keys=True))
        os.replace(tmp, self._path)

    def claim(self, filename: str, game_id: str) -> None:
        """Record that ``game_id`` owns (a share of) this wav. Idempotent: a
        cache-hit re-speak from the same game does not even rewrite the file."""
        name = Path(filename).name  # basenames only, whatever the caller sent
        with self._lock:
            owners = self._claims.setdefault(name, [])
            if game_id not in owners:
                owners.append(game_id)
                self._save()

    def release_game(self, game_id: str) -> int:
        """Drop the gid from every entry; a wav owned by nobody else is deleted
        from disk. Returns the number of wavs actually unlinked (an unknown gid
        touches nothing and returns 0)."""
        deleted = 0
        with self._lock:
            touched = False
            for name in list(self._claims):
                owners = self._claims[name]
                if game_id not in owners:
                    continue
                owners.remove(game_id)
                touched = True
                if not owners:
                    del self._claims[name]
                    path = _safe_wav(name)
                    if path is not None:
                        try:
                            path.unlink()
                            deleted += 1
                        except FileNotFoundError:
                            pass  # already gone; the claim removal is what matters
            if touched:
                self._save()
        return deleted

    def purge_all(self) -> int:
        """Whole-cache wipe: every cached wav and the manifest itself die.
        Returns the number of wavs removed."""
        with self._lock:
            deleted = 0
            for path in config.AUDIO_DIR.glob("*.wav"):
                try:
                    path.unlink()
                    deleted += 1
                except FileNotFoundError:
                    pass
            self._claims = {}
            try:
                self._path.unlink()
            except FileNotFoundError:
                pass
        return deleted

    def owners(self, filename: str) -> list[str]:
        """Current claim list for a wav (read-only helper, used by tests)."""
        with self._lock:
            return list(self._claims.get(Path(filename).name, []))
