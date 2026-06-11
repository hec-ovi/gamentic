"""Origin enrichment: a character with a thin backstory gets a real biography at
creation, one focused LLM call each (the finalize pass writes the whole world in one
shot and under-delivers here; live finding 2026-06-10: origins still too short)."""
from app import db, llm, repo


BIO = ("Born in the flooded quarter of a port city, she learned early that debts "
       "outlive the people who owe them. A salvage accident took her mentor and left "
       "her with his ledger and his enemies. She spent four years running cargo nobody "
       "asked about, building a name for discretion. A betrayal by a partner cost her "
       "everything but the boat. She wants one clean score and a door that locks from "
       "the inside.")


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def _world(origin):
    return {
        "title": "T", "setting": "a port city", "tone": "noir",
        "narrator_persona": "Terse.", "opening_scenario": "Rain.",
        "start_location": "bar", "player_life": 20,
        "characters": [{"name": "Mara", "persona": "a fixer", "description": "Sharp.",
                        "origin": origin}],
        "quests": [], "lore": [],
    }


def _origin(client, gid):
    st = client.get(f"/games/{gid}/state").json()
    cid = st["characters"][0]["id"]
    with db.get_conn() as conn:
        return repo.get_character(conn, cid)["origin"]


def test_thin_origins_get_a_real_biography_at_creation(client, fake_llm):
    fake_llm.origin = llm.LLMReply(content=BIO)
    gid = client.post("/games", json=_world("Came from the docks.")).json()["game_id"]
    o = _origin(client, gid)
    assert "flooded quarter" in o
    assert len(o) > 220


def test_rich_origins_are_left_alone(client, fake_llm):
    fake_llm.origin = llm.LLMReply(content=BIO)
    rich = ("Born in the smelter slums of Karsk, she ran contraband through the canal "
            "gates before the levy wars took her brother and left her holding his "
            "debts. She came east owing money to people who do not forget, and she has "
            "spent every year since buying back her own name one favor at a time, "
            "which is why she reads every contract twice and trusts no one young.")
    gid = client.post("/games", json=_world(rich)).json()["game_id"]
    o = _origin(client, gid)
    assert o.startswith("Born in the smelter slums")
    assert "flooded quarter" not in o


def test_enriched_origin_reaches_narrator_and_character(client, fake_llm):
    fake_llm.origin = llm.LLMReply(content=BIO)
    gid = client.post("/games", json=_world("Short.")).json()["game_id"]
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="She looks up.")
    client.post(f"/games/{gid}/action", json={"action": "I nod at Mara."})
    nar = [c for c in fake_llm.calls if "cue_character" in c["names"]][-1]["system"]
    assert "flooded quarter" in nar          # the narrator's secrets block carries PAST
    ch = [c for c in fake_llm.calls if c["system"].startswith("You are Mara")][-1]["system"]
    assert "flooded quarter" in ch           # the character's own YOUR PAST carries it


def test_enrichment_failure_never_breaks_creation(client, fake_llm):
    fake_llm.origin = RuntimeError("model down")
    gid = client.post("/games", json=_world("Came from the docks.")).json()["game_id"]
    assert gid
    assert _origin(client, gid) == "Came from the docks."
