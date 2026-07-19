"""Late media beats vs in-flight turns: a turn_index is claimed exactly once.

A turn holds ONE write transaction for its whole run (LLM calls included) while
background image jobs persist on their own connections. Before the fix, a job that
landed mid-turn computed next_turn_index from the committed snapshot and claimed
the SAME index the running turn had already claimed: the client's incremental
beats?since=<last turn> poll (strict >) never delivered the job's beat live, and
reopening the game re-sorted it into the middle of the later exchange (the whisper
thread showed a study's image splitting a message from its reply).

run_turn and jobs._land_beat now both claim the write lock (BEGIN IMMEDIATE)
BEFORE reading the counter, so a late beat queues behind an in-flight turn and
lands strictly after it.
"""
import threading
import time

from app import db, media, repo
from app.integrate import jobs


WORLD = {
    "title": "Ordering", "setting": "a port town", "tone": "warm",
    "narrator_persona": "x", "opening_scenario": "Gulls wheel overhead.",
    "start_location": "harbor", "player_life": 20,
    "characters": [{"name": "Vex", "persona": "a scout",
                    "appearance": "tall, scarred, wears leather armor"}],
    "quests": [{"title": "x", "objectives": ["x"]}], "lore": [],
}


def _enable_images(monkeypatch, tmp_path):
    from app.config import settings
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(media, "generate_character_images",
                        lambda descriptor, style="", seed=None: None)
    monkeypatch.setattr(media, "generate_scene_image",
                        lambda prompt, seed=None, width=None, height=None,
                        references=None: {"image_url": "/image/file?filename=v"})
    monkeypatch.setattr(media, "fetch_image_bytes", lambda url: b"PNG")


def test_late_image_beat_lands_after_an_inflight_turn(client, fake_llm, monkeypatch, tmp_path):
    _enable_images(monkeypatch, tmp_path)
    gid = client.post("/games", json=WORLD).json()["game_id"]

    # simulate the in-flight turn exactly as run_turn does: claim the write lock,
    # read the counter, write a beat, and stay open across "the LLM call"
    turn_conn = db.connect()
    turn_conn.execute("BEGIN IMMEDIATE")
    claimed = repo.next_turn_index(turn_conn, gid)
    repo.add_beat(turn_conn, gid, "player", None, "action", "echo mid-flight",
                  "harbor", turn_index=claimed, seq=0)

    landed = {}
    job = threading.Thread(
        target=lambda: landed.update(beat=jobs.generate_view_snapshot(gid)))
    job.start()
    time.sleep(0.4)                    # the job reaches the lock and queues behind us
    assert "beat" not in landed        # it must NOT have landed while the turn runs
    turn_conn.commit()                 # the turn finishes
    turn_conn.close()
    job.join(timeout=30)
    assert not job.is_alive()

    beat = landed.get("beat")
    assert beat, "the late image beat must land once the turn commits"
    # strictly AFTER the turn that was in flight - never the same index
    assert beat["turn_index"] == claimed + 1

    # and the client's incremental poll (since = the turn it just saw) fetches it
    got = client.get(f"/games/{gid}/beats", params={"since": claimed}).json()["beats"]
    assert beat["id"] in [b["id"] for b in got]


def test_turn_after_late_image_advances_past_it(client, fake_llm, monkeypatch, tmp_path):
    """The other direction: once a late image landed, the next turn's beats sort
    after it - arrival order and (turn_index, seq) order stay the same story."""
    _enable_images(monkeypatch, tmp_path)
    gid = client.post("/games", json=WORLD).json()["game_id"]

    image = jobs.generate_view_snapshot(gid)
    assert image

    client.post(f"/games/{gid}/action", json={"action": "look at the gulls"})
    beats = client.get(f"/games/{gid}/beats").json()["beats"]
    idx = {b["id"]: i for i, b in enumerate(beats)}
    after_image = [b for b in beats if idx[b["id"]] > idx[image["id"]]]
    assert after_image, "the turn's beats come after the earlier image"
    assert all(b["turn_index"] > image["turn_index"] for b in after_image)
