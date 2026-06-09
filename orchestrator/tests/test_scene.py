"""Scene as an entity: exits (capped, dead-ends), scene/character inventories with
hidden/reveal/take, capped slots, and the action buttons (base + offered, capped)."""
from app import llm


def _world(chars=None, start="bar"):
    return {
        "title": "Sceneworld", "setting": "A dim bar.", "tone": "noir",
        "narrator_persona": "Terse.", "opening_scenario": "Smoke and neon.",
        "start_location": start, "player_life": 20,
        "characters": chars or [],
        "quests": [{"title": "Look", "description": "", "objectives": ["x"]}], "lore": [],
    }


def _new(client, chars=None, start="bar"):
    return client.post("/games", json=_world(chars, start)).json()["game_id"]


def _state(client, gid):
    return client.get(f"/games/{gid}/state").json()


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def test_scene_object_present(client, fake_llm):
    gid = _new(client)
    sc = _state(client, gid)["scene"]
    assert sc["name"] == "bar"
    assert sc["description"]                       # seeded from setting
    assert sc["exits"] == [] and sc["items"] == []
    labels = [a["label"] for a in sc["available_actions"]]
    assert "Look around" in labels and "Search" in labels   # base scene actions


def test_add_exit_and_cap_and_deadend(client, fake_llm):
    gid = _new(client)
    assert _state(client, gid)["scene"]["exits"] == []      # dead end / cell by default
    fake_llm.narrator = _nar(
        T("add_exit", label="the street", target="street"),
        T("add_exit", label="back room", target="backroom"),
        T("add_exit", label="cellar stairs", target="cellar"),
        T("add_exit", label="rooftop", target="roof"),       # 4th -> over cap, rejected
    )
    client.post(f"/games/{gid}/action", json={"action": "I look for a way out."})
    exits = _state(client, gid)["scene"]["exits"]
    assert len(exits) == 3                                    # capped at 3
    assert {e["target"] for e in exits} == {"street", "backroom", "cellar"}


def test_hidden_item_reveal_and_take(client, fake_llm):
    gid = _new(client)
    fake_llm.narrator = _nar(T("place_item", target="scene", name="brass key",
                               description="cold to the touch", hidden=True))
    client.post(f"/games/{gid}/action", json={"action": "I enter."})
    assert _state(client, gid)["scene"]["items"] == []       # hidden -> absent from state

    fake_llm.narrator = _nar(T("reveal_item", target="scene", name="brass key"))
    client.post(f"/games/{gid}/action", json={"action": "I search behind the bar."})
    items = _state(client, gid)["scene"]["items"]
    assert any(i["name"] == "brass key" for i in items)      # now visible

    fake_llm.narrator = _nar(T("take_item", name="brass key"))
    client.post(f"/games/{gid}/action", json={"action": "I pocket the key."})
    s = _state(client, gid)
    assert s["scene"]["items"] == []                          # gone from scene
    assert any(i["name"] == "brass key" for i in s["player"]["inventory"])


def test_scene_item_cap(client, fake_llm):
    gid = _new(client)
    fake_llm.narrator = _nar(*[T("place_item", target="scene", name=f"item{i}") for i in range(8)])
    client.post(f"/games/{gid}/action", json={"action": "I dump my bag out."})
    assert len(_state(client, gid)["scene"]["items"]) == 6   # capped at 6


def test_character_inventory_visible_and_capped(client, fake_llm):
    gid = _new(client, [{"name": "Mara", "persona": "a fence"}])
    fake_llm.narrator = _nar(*[T("place_item", target="Mara", name=f"trinket{i}") for i in range(5)])
    client.post(f"/games/{gid}/action", json={"action": "I watch Mara."})
    mara = next(c for c in _state(client, gid)["characters"] if c["name"] == "Mara")
    assert len(mara["inventory"]) == 3                        # character cap 3


def test_actions_base_set_and_offer(client, fake_llm):
    # an 'unknown' character has 2 base actions, so an offered one fits (-> 3)
    gid = _new(client, [{"name": "Mara", "persona": "a stranger", "disposition": "unknown"}])
    mara = next(c for c in _state(client, gid)["characters"] if c["name"] == "Mara")
    base = [a["label"] for a in mara["available_actions"]]
    assert base == ["Talk", "Observe"]
    fake_llm.narrator = _nar(T("offer_action", name="Mara", label="Bribe"))
    client.post(f"/games/{gid}/action", json={"action": "I slide her some cash."})
    mara = next(c for c in _state(client, gid)["characters"] if c["name"] == "Mara")
    labels = [a["label"] for a in mara["available_actions"]]
    assert "Bribe" in labels and len(labels) == 3            # capped at 3


def test_offer_scene_action(client, fake_llm):
    gid = _new(client)
    fake_llm.narrator = _nar(T("offer_scene_action", label="Pray at the shrine"))
    client.post(f"/games/{gid}/action", json={"action": "I notice a shrine."})
    labels = [a["label"] for a in _state(client, gid)["scene"]["available_actions"]]
    assert "Pray at the shrine" in labels and len(labels) <= 3


def test_describe_scene_and_character(client, fake_llm):
    gid = _new(client, [{"name": "Mara", "persona": "a guard"}])
    fake_llm.narrator = _nar(T("describe_scene", description="A flooded cellar, knee-deep in black water."),
                             T("describe_character", name="Mara", description="A grim, scarred sentinel."))
    client.post(f"/games/{gid}/action", json={"action": "I descend."})
    s = _state(client, gid)
    assert s["scene"]["description"] == "A flooded cellar, knee-deep in black water."
    assert next(c for c in s["characters"] if c["name"] == "Mara")["description"] == "A grim, scarred sentinel."


def test_move_creates_return_exit_so_you_cannot_get_stuck(client, fake_llm):
    gid = _new(client, [{"name": "Mara", "persona": "a guard"}], start="hall")
    fake_llm.narrator = _nar(T("move_location", location="cellar"))   # narrator adds NO exits
    client.post(f"/games/{gid}/action", json={"action": "I go down to the cellar."})
    sc = _state(client, gid)["scene"]
    assert sc["name"] == "cellar"
    assert any(e["target"] == "hall" for e in sc["exits"])            # a way back exists
    # the left-behind character is reachable again by going back (scene persistence)
    fake_llm.narrator = _nar(content="You climb back up.", )            # no move tool needed if exit used
    fake_llm.narrator = _nar(T("move_location", location="hall"))
    client.post(f"/games/{gid}/action", json={"action": "I go back up."})
    s = _state(client, gid)
    assert s["scene"]["name"] == "hall"
    assert any(c["name"] == "Mara" and c["location"] == "hall" for c in s["characters"])  # she's there


def test_scene_persistence_of_items(client, fake_llm):
    gid = _new(client, start="bar")
    fake_llm.narrator = _nar(T("place_item", target="scene", name="ledger"))
    client.post(f"/games/{gid}/action", json={"action": "I drop a ledger."})
    fake_llm.narrator = _nar(T("move_location", location="alley"))
    client.post(f"/games/{gid}/action", json={"action": "I step out to the alley."})
    assert _state(client, gid)["scene"]["name"] == "alley"
    assert _state(client, gid)["scene"]["items"] == []        # alley is its own scene
    fake_llm.narrator = _nar(T("move_location", location="bar"))
    client.post(f"/games/{gid}/action", json={"action": "I go back inside."})
    items = _state(client, gid)["scene"]["items"]
    assert any(i["name"] == "ledger" for i in items)          # the bar kept its ledger
