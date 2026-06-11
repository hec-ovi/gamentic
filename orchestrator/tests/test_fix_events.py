"""The media-ready push (SSE): render jobs publish when media persists, and
GET /games/{gid}/events streams it out so the frontend re-fetches on signal
instead of polling blind (live 2026-06-11: the 40s poll ceiling lost a 47s
scene render and only F5 recovered it)."""
import asyncio
import json
import threading

from app import llm
from app.config import settings
from app.integrate import events


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


# ---------- the bus ----------

def test_a_thread_publish_reaches_an_async_subscriber():
    async def run():
        q = events.subscribe("g1")
        try:
            t = threading.Thread(target=events.publish, args=("g1", "scene"),
                                 kwargs={"scene_id": "s1"})
            t.start()
            t.join()
            evt = json.loads(await asyncio.wait_for(q.get(), timeout=2))
            assert evt == {"kind": "scene", "scene_id": "s1"}
        finally:
            events.unsubscribe("g1", q)
    asyncio.run(run())


def test_publish_to_a_game_with_no_subscribers_is_a_quiet_no_op():
    events.publish("nobody-listening", "item", name="x")   # must not raise


def test_unsubscribe_stops_delivery_and_other_games_never_cross():
    async def run():
        qa = events.subscribe("game-a")
        qb = events.subscribe("game-b")
        try:
            threading.Thread(target=events.publish, args=("game-a", "item"),
                             kwargs={"name": "lantern"}).start()
            evt = json.loads(await asyncio.wait_for(qa.get(), timeout=2))
            assert evt["name"] == "lantern"
            assert qb.empty()                      # game-b heard nothing
        finally:
            events.unsubscribe("game-a", qa)
            events.unsubscribe("game-b", qb)
        events.publish("game-a", "item", name="late")      # nobody left: no error
    asyncio.run(run())


# ---------- the jobs publish ----------

def test_item_render_publishes_after_persisting(client, fake_llm, world, monkeypatch):
    from app import integrate, media
    from app.integrate import jobs
    heard = []
    monkeypatch.setattr(events, "publish", lambda gid, kind, **d: heard.append((kind, d)))
    monkeypatch.setattr(media, "generate_scene_image",
                        lambda *a, **k: {"image_url": "data:image/png;base64,aGk="})
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("add_item", name="brass key"), content="A key.")
    client.post(f"/games/{gid}/action", json={"action": "I pick it up."})
    heard.clear()
    jobs.generate_item_image(gid, "brass key")
    assert ("item", {"name": "brass key"}) in heard


# ---------- the endpoint ----------

def test_events_endpoint_streams_a_published_event(client, fake_llm, world, monkeypatch):
    """Drives the real route handler's generator directly: an infinite SSE body never
    completes under TestClient's buffered streaming, so the wire shape is asserted on
    the StreamingResponse itself and the event flow on its body iterator."""
    from app import main as app_main
    monkeypatch.setattr(settings, "EVENTS_KEEPALIVE_S", 0.2)
    gid = client.post("/games", json=world).json()["game_id"]

    async def run():
        resp = await app_main.game_events_stream(gid)
        assert resp.media_type == "text/event-stream"
        it = resp.body_iterator
        try:
            assert (await it.__anext__()).startswith("retry:")   # subscribed
            events.publish(gid, "scene", scene_id="s1")
            evt = await asyncio.wait_for(it.__anext__(), timeout=2)
            assert json.loads(evt.removeprefix("data:").strip()) == \
                {"kind": "scene", "scene_id": "s1"}
            ping = await asyncio.wait_for(it.__anext__(), timeout=2)
            assert ping.startswith(": ping")                     # keepalive flows
        finally:
            await it.aclose()                                    # finally -> unsubscribe
        assert gid not in events._subscribers                    # cleanup proven
    asyncio.run(run())


def test_events_endpoint_404s_unknown_games(client):
    r = client.get("/games/nope/events")
    assert r.status_code == 404
