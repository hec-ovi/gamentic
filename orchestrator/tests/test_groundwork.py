"""M0 groundwork repairs (evolve branch): the art director's dead placeholders, the
LLM output caps in the creation/art path, the write-lock-vs-persist timeout, two tool
guards (negative remove_item, heal on the dead), template export fidelity, and the
checkpoint import path guard."""
import os

import pytest

from app import creator, db, llm, prompts, repo, transfer
from app.config import settings


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def _state(client, gid):
    return client.get(f"/games/{gid}/state").json()


# ---------- the art director actually receives the world ----------

def test_artdirector_user_prompt_is_fully_substituted(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    with db.get_conn() as conn:
        g = repo.get_game(conn, gid)
        chars = repo.get_characters(conn, gid)
        msgs = prompts.build_artdirector_messages(g, chars, time_of_day="morning",
                                                  start_location="crypt entrance")
    user = msgs[1]["content"]
    assert "The Sunken Crypt" in user               # the world data is IN the prompt
    assert "Mara" in user
    assert "flooded dwarven crypt" in user
    assert "{" not in user                          # no unsubstituted placeholder survives


# ---------- no LLM output caps in the creation/art path ----------

def test_creation_and_art_calls_are_uncapped(client, fake_llm, world):
    from app import llm as llmmod
    fake_llm.artdirector = llmmod.LLMReply(content="{}")
    gid = client.post("/games", json=world).json()["game_id"]

    # creator chat + finalize
    client.post("/create/message", json={"session_id": "s1", "message": "a moody port town"})
    fake_llm.finalize = llmmod.LLMReply(content="", tool_calls=[T("save_world", **world)])
    client.post("/create/finalize", json={"session_id": "s1"})
    # tap-to-explain
    client.post(f"/games/{gid}/explain", json={"kind": "quest", "key": "Escape the Crypt"})
    # art director + agentic image prompt (direct: media stays disabled in tests)
    from app.integrate import image_prompts, jobs
    jobs.art_direction(gid)
    image_prompts._artdirected_prompt("PLACE: crypt", fallback="crypt")

    shapes = {
        "finalize": lambda c: "save_world" in c["names"],
        "creator chat": lambda c: c["system"].startswith("You are a warm"),
        "explain": lambda c: c["system"].startswith("You answer the player's tap"),
        "art director": lambda c: c["system"].startswith("You are the art director"),
        "image prompt": lambda c: c["system"].startswith("You write a single image-generation prompt"),
        "origin enrichment": lambda c: c["system"].startswith("You deepen the private backstory"),
    }
    for label, match in shapes.items():
        calls = [c for c in fake_llm.calls if match(c)]
        assert calls, f"no {label} call was made"
        assert all(c["max_tokens"] == 0 for c in calls), f"{label} call is capped"


def test_llm_chat_omits_max_tokens_when_uncapped(monkeypatch):
    sent = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}

    def fake_post(url, **kwargs):
        sent.update(kwargs["json"])
        return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    llm.chat([{"role": "user", "content": "hi"}])
    assert "max_tokens" not in sent                 # the default is uncapped


# ---------- background persists survive a long turn's write lock ----------

def test_connections_queue_behind_a_turn_length_lock():
    with db.get_conn() as conn:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 330000


def test_dead_symbols_are_gone():
    assert not hasattr(settings, "SCENE_BEATS")
    assert not hasattr(repo, "scene_beats_for_character")


# ---------- tool guards ----------

def test_negative_qty_remove_item_is_invalid(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("add_item", name="copper coins", qty=3))
    client.post(f"/games/{gid}/action", json={"action": "search the floor"})
    fake_llm.narrator = _nar(T("remove_item", name="copper coins", qty=-3),
                             content="A tax collector empties your purse.")
    client.post(f"/games/{gid}/action", json={"action": "pay the toll"})
    inv = _state(client, gid)["player"]["inventory"]
    coins = next(i for i in inv if i["name"] == "copper coins")
    assert coins.get("qty", 1) == 3                 # the negative qty changed NOTHING
    # the reason rides the next narrator message so the retry loop can steer
    fake_llm.narrator = _nar(content="The collector shrugs.")
    client.post(f"/games/{gid}/action", json={"action": "I wait."})
    assert "qty must be positive; use add_item" in fake_llm.narrator_calls()[-1]["messages"][1]["content"]


def test_heal_refuses_the_dead(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("kill_character", name="Mara"))
    client.post(f"/games/{gid}/action", json={"action": "strike her down"})
    fake_llm.narrator = _nar(T("heal", amount=5, target="Mara"),
                             content="You press a potion to her lips.")
    client.post(f"/games/{gid}/action", json={"action": "revive her"})
    mara = next(c for c in _state(client, gid)["characters"] if c["name"] == "Mara")
    assert not mara["alive"]                        # no half-resurrection
    assert not mara["present"]


# ---------- template export fidelity ----------

def test_template_carries_designed_characters_and_opening_state(client, fake_llm, world):
    world = dict(world)
    world["characters"] = [dict(world["characters"][0],
                                gender="female", origin="Raised in the deep halls.",
                                relation="guide")]
    world["player_items"] = [{"name": "a sealed ledger", "description": "Wax unbroken."}]
    world["start_time_of_day"] = "evening"
    gid = client.post("/games", json=world).json()["game_id"]

    exported = client.get(f"/games/{gid}/export?kind=template").json()
    w = exported["world"]
    mara = next(c for c in w["characters"] if c["name"] == "Mara")
    assert mara["gender"] == "female"
    assert mara["origin"] == "Raised in the deep halls."
    assert mara["relation"] == "guide"
    assert {"name": "a sealed ledger", "description": "Wax unbroken."} in w["player_items"]
    assert w["start_time_of_day"] == "evening"

    # and a fresh import of that template seeds the same opening state
    gid2 = client.post("/games/import", json=exported).json()["game_id"]
    s2 = _state(client, gid2)
    assert any(i["name"] == "a sealed ledger" for i in s2["player"]["inventory"])
    assert "evening" in s2["time"]["label"].lower()
    mara2 = next(c for c in s2["characters"] if c["name"] == "Mara")
    assert mara2["gender"] == "female"
    assert mara2["relation"] == "guide"


# ---------- checkpoint import path guard ----------

@pytest.mark.parametrize("evil", ["../../../../home", "/etc", "a/../b", "x" * 12])
def test_checkpoint_with_malformed_game_id_is_rejected(client, fake_llm, world, evil,
                                                       tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    gid = client.post("/games", json=world).json()["game_id"]
    ckpt = client.get(f"/games/{gid}/export?kind=checkpoint").json()
    ckpt["game"]["id"] = evil
    r = client.post("/games/import", json=ckpt)
    assert r.status_code == 400
    assert "malformed game id" in r.json()["detail"]
    # nothing was copied anywhere
    assert os.listdir(tmp_path) == []


def test_media_route_rejects_non_game_ids(client, fake_llm, world, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    trap = tmp_path / "not-a-game-id" / "images"
    trap.mkdir(parents=True)
    (trap / "secret.png").write_bytes(b"png")
    assert client.get("/media/not-a-game-id/secret.png").status_code == 404
