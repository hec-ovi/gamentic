"""Relation (owner spec): what a character IS to the player is a FREE label the
narrator/creator chooses (sister, boss, sworn rival...), a separate axis from the
4-value mechanical disposition, which stays fixed."""
from app import llm


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def _mara(client, gid):
    return next(c for c in client.get(f"/games/{gid}/state").json()["characters"]
                if c["name"] == "Mara")


def test_creator_sets_relation_and_everyone_sees_it(client, fake_llm, world):
    world = dict(world)
    world["characters"] = [dict(world["characters"][0], relation="older sister")]
    gid = client.post("/games", json=world).json()["game_id"]
    assert _mara(client, gid)["relation"] == "older sister"
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara looks up.")
    client.post(f"/games/{gid}/action", json={"action": "Sis, we need to talk."})
    assert "the player's older sister" in fake_llm.narrator_calls()[-1]["system"]
    # the CHARACTER's side never says "the player" (live: the meta-term leaked into beats)
    assert "To the one you are with, you are their older sister." \
        in fake_llm.character_calls()[-1]["system"]


def test_narrator_can_evolve_the_relation_freely(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("set_relation", name="Mara", relation="sworn ally"),
                             content="Something is settled between you.")
    d = client.post(f"/games/{gid}/action", json={"action": "I offer her my hand."}).json()
    # article-aware wording (live: 'Tamsin is now your stranger.' read broken)
    assert any(b["text"] == "Mara now sees you as a sworn ally." for b in d["beats"]
               if b["kind"] == "system")
    mara = _mara(client, gid)
    assert mara["relation"] == "sworn ally"
    assert mara["disposition"] in ("friendly", "neutral", "hostile", "unknown")  # axis intact
    # the change is itself a pivotal moment
    prof = client.get(f"/games/{gid}/characters/{mara['id']}/profile").json()
    assert "Came to see the player as a sworn ally" in [m["text"] for m in prof["moments"]]
    # re-setting the same relation is silent
    fake_llm.narrator = _nar(T("set_relation", name="Mara", relation="Sworn Ally"),
                             content="Nothing changes.")
    d = client.post(f"/games/{gid}/action", json={"action": "I nod."}).json()
    assert not any("sworn ally" in b["text"].lower() for b in d["beats"] if b["kind"] == "system")


def test_spawn_carries_a_relation(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("spawn_character", name="Ferro", persona="a debt collector",
                               sex="male", relation="debt collector"),
                             content="A heavy knock.")
    d = client.post(f"/games/{gid}/action", json={"action": "I open the door."}).json()
    ferro = next(c for c in d["state"]["characters"] if c["name"] == "Ferro")
    assert ferro["relation"] == "debt collector"
