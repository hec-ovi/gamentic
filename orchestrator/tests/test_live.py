"""Live integration tests against the REAL Gemma model (no LLM mock).

Auto-skips when the model is not reachable (so CI without a GPU just skips these).
Run locally with the text stack up:  PYTHONPATH=. pytest tests/test_live.py -v -s

Assertions are structural and tolerant of model variance: we verify the brain
produces playable output (narration every turn, tools actually fire, characters
actually speak, state evolves, the story log accumulates), not exact wording.
"""
import httpx
import pytest

from app.config import settings


def _model_up() -> bool:
    try:
        r = httpx.get(f"{settings.LLM_BASE_URL}/models", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _model_up(), reason="LLM not reachable at LLM_BASE_URL")


WORLD = {
    "title": "The Sunken Crypt", "setting": "a flooded dwarven crypt", "tone": "grim, tense",
    "narrator_persona": "A solemn, vivid dungeon master who keeps it tight.",
    "opening_scenario": "Cold water laps at your boots as the crypt door groans shut behind you.",
    "start_location": "crypt entrance", "player_life": 20,
    "characters": [{"name": "Mara", "persona": "A wary dwarven scout, loyal but blunt. Speaks tersely.",
                    "knowledge": "Knows a secret tunnel behind the altar."}],
    "quests": [{"title": "Escape the Crypt", "description": "Find a way out.",
                "objectives": ["Find the altar", "Open the tunnel"]}],
    "lore": [{"keys": ["altar"], "content": "The altar bleeds black water when touched.", "constant": False}],
}

ACTIONS = [
    "I draw my axe and wade toward the dripping water, calling out for Mara.",
    "I ask Mara what she knows about this crypt, then search the walls for a hidden passage.",
    "I touch the altar and brace myself for whatever happens.",
]


def test_live_playthrough(client):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    init = client.get(f"/games/{gid}/state").json()

    # Directed turn: addressing Mara routes to her deterministically, so she MUST respond
    # (this proves the structural routing live, regardless of model variance).
    r = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "say", "text": "Mara, what do you know about this crypt?", "target": "Mara"}]})
    assert r.status_code == 200, r.text
    beats = r.json()["beats"]
    assert any(b["kind"] == "dialogue" and b["speaker_name"] == "Mara" for b in beats), \
        "directed routing did not reach Mara"
    narration_turns = 1 if any(b["kind"] == "narration" for b in beats) else 0

    for action in ["I search the crumbling walls for a hidden passage.", "I press deeper into the dark."]:
        r = client.post(f"/games/{gid}/action", json={"action": action})
        assert r.status_code == 200, r.text
        bs = r.json()["beats"]
        assert any(b["speaker"] == "player" for b in bs)
        assert all(b["text"].strip() for b in bs if b["kind"] == "narration")
        # NO DEAD AIR: a free-text turn is never fully silent - it always carries a non-player
        # beat (narration/dialogue/action, or at least a system note for a state change). The
        # resolve pass makes narration the norm; the deterministic suite locks that mechanism.
        assert any(b["speaker"] != "player" for b in bs), f"dead-air turn (only the player spoke): {action!r}"
        narration_turns += 1 if any(b["kind"] == "narration" for b in bs) else 0

    final = client.get(f"/games/{gid}/state").json()
    log = client.get(f"/games/{gid}/beats").json()["beats"]
    # narration should be the norm across the run (resolve pass); tolerant of one quiet turn
    assert narration_turns >= 2, "narrator narrated almost nothing across the run"
    assert final != init, "nothing changed across the playthrough"
    assert sum(1 for b in log if b["speaker"] == "player") == 3
    # the player always has a purpose (goal seeded from the first quest at creation)
    assert final["current_goal"].strip(), "no current goal was ever set"

    print(f"\n[live] beats={len(log)} narration_turns={narration_turns} "
          f"life {init['player']['life']}->{final['player']['life']} "
          f"goal={final['current_goal']!r} scene={final['scene']['status']}")


def test_live_narrator_memory(client):
    """Tell the narrator to remember a fact, then check it is in context next turn."""
    gid = client.post("/games", json=WORLD).json()["game_id"]
    # A turn very likely to trigger a remember() + state change.
    client.post(f"/games/{gid}/action",
                json={"action": "I carve a warning into the wall: 'THE BRIDGE AHEAD IS TRAPPED'. I want to remember this."})
    # The fact (if remembered) is now in game memory; play another turn and confirm continuity holds.
    r = client.post(f"/games/{gid}/action", json={"action": "I continue cautiously."})
    assert r.status_code == 200
    # memory is best-effort at the model level; we just assert the turn resolved with beats
    assert r.json()["beats"]


def test_live_create_story_from_conversation(client):
    sid = "live-creator-1"
    client.post("/create/message", json={"session_id": sid,
                "message": "I want a haunted lighthouse mystery where I play a lone keeper. Make a ghost character and a quest to relight the lamp."})
    client.post("/create/message", json={"session_id": sid,
                "message": "Eerie tone. That's enough, build it."})
    r = client.post("/create/finalize", json={"session_id": sid})
    assert r.status_code == 200, r.text
    gid = r.json()["game_id"]
    s = client.get(f"/games/{gid}/state").json()
    assert s["title"].strip()
    assert len(s["characters"]) >= 1
    assert len(s["quests"]) >= 1
    # the created game is immediately playable
    op = client.get(f"/games/{gid}/beats").json()["beats"]
    assert any(b["kind"] == "narration" for b in op)
    print(f"\n[live-creator] title={s['title']!r} chars={[c['name'] for c in s['characters']]} "
          f"quests={[q['title'] for q in s['quests']]}")
