"""A tiny per-game event bus for 'your media is ready' pushes (SSE).

The render jobs run minutes behind their turn (origins first, then portraits, then
scene art), and the frontend used to poll blind: /state every 2.5s with a 16-try
ceiling that the live scene art beat by seven seconds (2026-06-11: F5 was the only
way to see it). Now every job that persists media PUBLISHES here, and
GET /games/{gid}/events streams the events out; the browser's EventSource replaces
both polling timers.

In-process by design: one uvicorn worker owns the whole game (plain REST,
sequential turns), so a module-level registry is the entire infrastructure. Jobs
run in worker threads while the SSE generator lives on the event loop, hence the
call_soon_threadsafe hop.
"""
import asyncio
import json
import threading

_subscribers: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}
_lock = threading.Lock()


def subscribe(gid: str) -> asyncio.Queue:
    """Register the CALLING loop's queue for a game's events (SSE endpoint only)."""
    q: asyncio.Queue = asyncio.Queue()
    with _lock:
        _subscribers.setdefault(gid, []).append((asyncio.get_running_loop(), q))
    return q


def unsubscribe(gid: str, q: asyncio.Queue) -> None:
    with _lock:
        subs = _subscribers.get(gid, [])
        _subscribers[gid] = [(lo, qq) for lo, qq in subs if qq is not q]
        if not _subscribers[gid]:
            del _subscribers[gid]


def publish(gid: str, kind: str, **data) -> None:
    """Fire-and-forget from any thread: a render job announcing persisted media.
    kind: scene | portrait | item | beat (what just became fetchable). Subscribers
    re-fetch /state or /beats?since= on receipt; the event itself carries only hints."""
    evt = json.dumps({"kind": kind, **data})
    with _lock:
        subs = list(_subscribers.get(gid, []))
    for loop, q in subs:
        try:
            loop.call_soon_threadsafe(q.put_nowait, evt)
        except RuntimeError:
            pass   # a closed loop is a dead subscriber; unsubscribe cleans it up
