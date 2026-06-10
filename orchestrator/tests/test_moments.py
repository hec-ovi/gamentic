"""Pivotal moments (owner spec): a character's memories of the player are CURATED
events - bonds, wounds, gifts, partings - never transcript, never whispers. Mechanical
pivots record themselves deterministically; the narrator notes narrative ones."""
from app import llm


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def _profile(client, gid, name="Mara"):
    cid = next(c["id"] for c in client.get(f"/games/{gid}/state").json()["characters"]
               if c["name"] == name)
    return client.get(f"/games/{gid}/characters/{cid}/profile").json()


def _texts(client, gid, name="Mara"):
    return [m["text"] for m in _profile(client, gid, name)["moments"]]


def test_disposition_change_is_a_moment(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("set_disposition", name="Mara", disposition="friendly"),
                             content="Something eases in her shoulders.")
    client.post(f"/games/{gid}/action", json={"action": "I hand her my waterskin."})
    assert "Turned friendly toward the player" in _texts(client, gid)
    # re-setting the SAME disposition is not a new moment
    fake_llm.narrator = _nar(T("set_disposition", name="Mara", disposition="friendly"),
                             content="She nods.")
    client.post(f"/games/{gid}/action", json={"action": "I nod back."})
    assert _texts(client, gid).count("Turned friendly toward the player") == 1


def test_following_gifts_and_wounds_are_moments(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("set_following", name="Mara", following=True),
                             T("add_item", name="rope"), content="She falls in beside you.")
    client.post(f"/games/{gid}/action", json={"action": "Walk with me, Mara."})
    client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "give", "item": "rope", "target": "Mara"}]})
    fake_llm.narrator = _nar(T("apply_damage", target="Mara", amount=2),
                             content="The blow clips her arm.")
    client.post(f"/games/{gid}/action", json={"segments": [{"type": "attack", "target": "Mara"}]})
    texts = _texts(client, gid)
    assert "Began traveling with the player" in texts
    assert "Received rope from the player" in texts
    assert any(t.startswith("Was wounded") for t in texts)


def test_note_moment_tool_records_silently(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("note_moment", name="Mara",
                               event="Stood beside the player against the Watch."),
                             content="She plants her feet next to yours.")
    d = client.post(f"/games/{gid}/action", json={"action": "I face them down."}).json()
    assert "Stood beside the player against the Watch" in _texts(client, gid)
    assert not any("Stood beside" in b["text"] for b in d["beats"]
                   if b["kind"] == "system")          # silent: the prose already told it


def test_characters_perform_their_past(client, fake_llm, world):
    """The origin guidance: hint early, open up with trust, full account when asked."""
    world = dict(world)
    world["characters"] = [dict(world["characters"][0],
                                origin="She ran the mountain passes for the old couriers guild.")]
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara glances over.")
    client.post(f"/games/{gid}/action", json={"action": "Who are you, really?"})
    system = fake_llm.character_calls()[-1]["system"]
    assert "perform it" in system and "plainly ask" in system
    assert "couriers guild" in system
