"""The character-to-world channel.

Owner 2026-07-25: "sometimes i ask a character about revealing a new exit ... and this
doesn't work and they state it in the private message but world is not affected". The
character was right to say it and powerless to make it true: world authority is the
narrator's, and there was no way to hand a claim across.

propose_change is that way. The character says what should now be true, the narrator
rules on it in the SAME turn with the world's own tools, and a refusal costs nothing
because the words were already spoken. What a proposal may never become: damage,
healing, moving or robbing the player. Those are never a character's to arrange.
"""
from app import llm, repo, db, tools
from app.config import settings


def _is_referee(call):
    """The referee pass carries the world subset: exits yes, cue_character never."""
    return "add_exit" in call["names"] and "cue_character" not in call["names"]


def _referee_call(fake_llm):
    return next(c for c in fake_llm.calls if _is_referee(c))


def _cue(fake_llm, name="Mara", content="Mara looks toward the dark."):
    fake_llm.narrator = llm.LLMReply(
        content=content,
        tool_calls=[llm.ToolCall("cue_character", {"name": name, "impulse": "answer"})])


def _proposes(fake_llm, change, said='[say]"There is a way out back there."[/say]'):
    fake_llm.character = llm.LLMReply(
        content=said, tool_calls=[llm.ToolCall("propose_change", {"change": change})])


# ---------- the tool exists and belongs to characters ----------

def test_characters_carry_it_always():
    names = [t["function"]["name"] for t in tools.character_tools(images=False)]
    assert "propose_change" in names


def test_the_narrator_does_not_carry_it():
    """The narrator changes the world directly; proposing to itself is noise."""
    names = [t["function"]["name"] for t in tools.narrator_tools(adjudicating=True, images=True)]
    assert "propose_change" not in names


def test_a_proposal_can_only_become_a_world_change():
    """Never the player's body, possessions or position."""
    names = [t["function"]["name"] for t in tools.PROPOSAL_TOOLS]
    for forbidden in ("apply_damage", "heal", "kill_character", "move_location",
                      "add_item", "remove_item", "take_item", "give_item",
                      "set_game_status"):
        assert forbidden not in names, f"{forbidden} must not be reachable from a proposal"
    assert "add_exit" in names and "place_item" in names and "spawn_character" in names


# ---------- the round trip: a claim becomes state ----------

def test_a_promised_way_out_becomes_a_real_exit(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    _cue(fake_llm)
    _proposes(fake_llm, "a drain behind the altar leads out to the cistern")
    fake_llm.proposal = llm.LLMReply(content="", tool_calls=[
        llm.ToolCall("add_exit", {"label": "the drain behind the altar",
                                  "target": "the cistern"})])
    d = client.post(f"/games/{gid}/action",
                    json={"action": "Mara, is there another way out of here?"}).json()
    exits = [(e.get("label") or "").lower() for e in d["state"]["scene"]["exits"]]
    assert any("drain" in e for e in exits), f"the exit never landed: {exits}"


def test_the_referee_sees_the_claim_and_the_state(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    _cue(fake_llm)
    _proposes(fake_llm, "a drain behind the altar leads out to the cistern")
    client.post(f"/games/{gid}/action", json={"action": "Any way out, Mara?"})
    call = _referee_call(fake_llm)
    assert "drain behind the altar" in call["user"]      # the claim, verbatim
    assert "Mara" in call["user"] or "Mara" in call["system"]
    assert "CURRENT STATE" in call["system"]             # ruled against the real world


def test_a_refusal_changes_nothing_and_the_turn_still_lands(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    before = client.get(f"/games/{gid}/state").json()["scene"]["exits"]
    _cue(fake_llm)
    _proposes(fake_llm, "a dragon is waiting outside to carry us home")
    fake_llm.proposal = llm.LLMReply(content="", tool_calls=[])   # the narrator says no
    r = client.post(f"/games/{gid}/action", json={"action": "Any way out?"})
    assert r.status_code == 200
    assert r.json()["state"]["scene"]["exits"] == before
    assert any(b["kind"] == "dialogue" for b in r.json()["beats"]), "she still spoke"


def test_no_proposal_means_no_extra_call(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    _cue(fake_llm)
    fake_llm.character = llm.LLMReply(content='[say]"Nothing that way."[/say]')
    before = len(fake_llm.calls)
    client.post(f"/games/{gid}/action", json={"action": "Any way out?"})
    after = [c for c in fake_llm.calls[before:] if _is_referee(c)]
    assert not after, "a referee pass ran with nothing to rule on"


def test_the_claim_list_is_bounded(client, fake_llm, world, monkeypatch):
    monkeypatch.setattr(settings, "MAX_PROPOSALS_PER_TURN", 2)
    gid = client.post("/games", json=world).json()["game_id"]
    _cue(fake_llm)
    fake_llm.character = llm.LLMReply(content='[say]"Several things."[/say]', tool_calls=[
        llm.ToolCall("propose_change", {"change": "first claim"}),
        llm.ToolCall("propose_change", {"change": "second claim"}),
        llm.ToolCall("propose_change", {"change": "third claim"})])
    client.post(f"/games/{gid}/action", json={"action": "Tell me everything."})
    call = _referee_call(fake_llm)
    assert "first claim" in call["user"] and "second claim" in call["user"]
    assert "third claim" not in call["user"]


def test_an_empty_claim_is_refused_before_it_reaches_the_narrator(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    _cue(fake_llm)
    fake_llm.character = llm.LLMReply(content='[say]"..."[/say]', tool_calls=[
        llm.ToolCall("propose_change", {"change": "   "})])
    client.post(f"/games/{gid}/action", json={"action": "Any way out?"})
    assert not [c for c in fake_llm.calls if _is_referee(c)]


def test_a_change_the_referee_makes_is_announced_to_the_player(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    _cue(fake_llm)
    _proposes(fake_llm, "a drain behind the altar leads out")
    fake_llm.proposal = llm.LLMReply(content="", tool_calls=[
        llm.ToolCall("add_exit", {"label": "the drain", "target": "the cistern"})])
    d = client.post(f"/games/{gid}/action", json={"action": "Any way out?"}).json()
    assert any(b["kind"] == "system" and "drain" in b["text"].lower() for b in d["beats"]), \
        "the world changed with nothing on screen to say so"


def test_a_private_conversation_can_change_the_world_too(client, fake_llm, world):
    """The exact live shape: asked privately, answered privately, world still moves."""
    gid = client.post("/games", json=world).json()["game_id"]
    with db.get_conn() as conn:
        mara = repo.find_character_by_name(conn, gid, "Mara")
    fake_llm.character_replies["Mara"] = llm.LLMReply(
        content='[private]"There is a drain behind the altar."[/private]',
        tool_calls=[llm.ToolCall("propose_change",
                                 {"change": "a drain behind the altar leads to the cistern"})])
    fake_llm.proposal = llm.LLMReply(content="", tool_calls=[
        llm.ToolCall("add_exit", {"label": "the drain behind the altar",
                                  "target": "the cistern"})])
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "conversation", "text": "Is there another way out?", "target": mara["id"]}]}).json()
    exits = [(e.get("label") or "").lower() for e in d["state"]["scene"]["exits"]]
    assert any("drain" in e for e in exits), f"the private promise stayed talk: {exits}"


def test_a_referee_failure_never_costs_the_turn(client, fake_llm, world, monkeypatch):
    gid = client.post("/games", json=world).json()["game_id"]
    _cue(fake_llm)
    _proposes(fake_llm, "a drain behind the altar leads out")
    original = fake_llm.__call__

    def _boom(messages, **kw):
        if any("CURRENT STATE" in m["content"] and "referee" in m["content"] for m in messages):
            raise RuntimeError("the referee call died")
        return original(messages, **kw)
    monkeypatch.setattr(fake_llm, "__call__", _boom)
    monkeypatch.setattr("app.llm.chat", _boom)
    r = client.post(f"/games/{gid}/action", json={"action": "Any way out?"})
    assert r.status_code == 200, "a failed referee pass must not lose the turn"
