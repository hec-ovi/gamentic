"""The live turn feed: the running turn reporting its progress over the per-game SSE
bus, plus the per-game stop flag that lets the player interrupt a generation.

Everything here is DISPLAY-plane only. The stored story is still written exclusively
by run_turn's emit() -> repo.add_beat inside the turn's transaction, byte-identical
with the feed off; these events are a live mirror of that work, fire-and-forget, for
clients that want to show the turn as it happens instead of waiting for the POST to
return. A client that misses events (reconnect, no EventSource) loses nothing: the
POST response and /beats?since= are the reconciliation of record, and the frontend
treats live content as provisional until they confirm it.

Event kinds added to the bus (the media hints scene|portrait|item|beat are untouched;
clients ignore kinds they don't know):
  phase          {phase: interpret|narrator|character, name?}   "who is working now"
  live_beat      {beat: {...}}          a beat the instant emit() stored it (uncommitted!)
  live_text      {sid, op: append|replace, text, speaker, name, beat_kind, private_with}
                 provisional streaming text for a beat still being generated
  live_text_done {sid}                  that provisional stream ended (real beats follow)
  turn_done      {turn_index, stopped}  the turn COMMITTED; everything above is now durable
  turn_stopped   {}                     a stop request was honored mid-turn

Stop semantics: request_stop() sets a threading.Event that every LLM call of the
running turn carries as its cancel handle (llm.chat closes the stream; llama.cpp
aborts the slot). The cancel PROPAGATES out of run_turn and the route lets the
transaction roll back: a stopped turn never happened - no beats, no player echo, no
clock tick (owner 2026-07-20: stop must take the player's own action back too). The
flag is cleared at the START of the next turn (begin_turn), never at the end of the
stopped one, so a stop that lands between two LLM calls still cancels the turn.
"""
import threading
import uuid

from ..integrate import events
from . import streamscrub

_BEAT_FIELDS = ("id", "turn_index", "seq", "speaker", "speaker_name", "kind",
                "text", "location", "image_url", "audio_url", "private_with", "emotion")

_stops: dict[str, threading.Event] = {}
_lock = threading.Lock()


def stop_event(gid: str) -> threading.Event:
    with _lock:
        ev = _stops.get(gid)
        if ev is None:
            ev = _stops[gid] = threading.Event()
        return ev


def begin_turn(gid: str) -> threading.Event:
    """Called once per player request, BEFORE the interpreter runs: a stale stop from
    the previous turn must never kill the new one."""
    ev = stop_event(gid)
    ev.clear()
    return ev


def request_stop(gid: str) -> None:
    stop_event(gid).set()


def stopping(gid: str) -> bool:
    return stop_event(gid).is_set()


def phase(gid: str, name: str, actor: str | None = None) -> None:
    events.publish(gid, "phase", phase=name, **({"name": actor} if actor else {}))


def publish_beat(gid: str, beat: dict) -> None:
    events.publish(gid, "live_beat", beat={k: beat.get(k) for k in _BEAT_FIELDS})


def publish_text(gid: str, sid: str, op: str, text: str, speaker: str,
                 name: str | None, beat_kind: str, private_with: str | None = None) -> None:
    events.publish(gid, "live_text", sid=sid, op=op, text=text, speaker=speaker,
                   name=name, beat_kind=beat_kind, private_with=private_with)


def publish_text_done(gid: str, sid: str) -> None:
    events.publish(gid, "live_text_done", sid=sid)


def publish_done(gid: str, turn_index: int | None, stopped: bool) -> None:
    if stopped:
        events.publish(gid, "turn_stopped")
    events.publish(gid, "turn_done", turn_index=turn_index, stopped=stopped)


class LiveNarration:
    """on_delta adapter for a narrator (or resolve) call: raw fragments in, stable
    scrubbed prose out to the live view under one stream id."""

    def __init__(self, gid: str):
        self.gid = gid
        self.sid = uuid.uuid4().hex[:12]
        self.ps = streamscrub.ProseStream()
        self.opened = False

    def on_delta(self, fragment: str) -> None:
        for op, text in self.ps.feed(fragment):
            self.opened = True
            publish_text(self.gid, self.sid, op, text, "narrator", "Narrator", "narration")

    def done(self) -> None:
        if self.opened:
            publish_text_done(self.gid, self.sid)


class LiveCharacter:
    """on_delta adapter for one character call: streams the interior of the say/whisper
    span being written (one stream id per segment), routed exactly like the final beat
    will be (a whisper span, or a forced-private reply, goes to the private thread)."""

    def __init__(self, gid: str, ch: dict, private_with: str | None):
        self.gid = gid
        self.ch = ch
        self.private = private_with
        self.cs = streamscrub.CharacterStream()
        self.sids: dict[int, str] = {}
        self.shown: dict[str, str] = {}
        self.donetexts: dict[int, str] = {}

    def _push(self, idx: int, kind: str, text: str) -> None:
        if not text:
            return
        sid = self.sids.setdefault(idx, uuid.uuid4().hex[:12])
        prev = self.shown.get(sid, "")
        if text == prev:
            return
        private = self.private or (self.ch["id"] if kind == "whisper" else None)
        op = "append" if text.startswith(prev) else "replace"
        frag = text[len(prev):] if op == "append" else text
        publish_text(self.gid, sid, op, frag, self.ch["id"], self.ch["name"],
                     "dialogue", private_with=private)
        self.shown[sid] = text

    def on_delta(self, fragment: str) -> None:
        done, tail = self.cs.feed(fragment)
        # a segment that just closed completes its bubble with the canonical batch text
        for idx, seg in enumerate(done):
            kind, text, _ = seg
            if idx in self.sids and self.donetexts.get(idx) != text:
                self._push(idx, kind, text)
                self.donetexts[idx] = text
        if tail:
            kind, text = tail
            if kind in ("say", "whisper"):
                self._push(len(done), kind, text)

    def done(self) -> None:
        for sid in self.sids.values():
            publish_text_done(self.gid, sid)
