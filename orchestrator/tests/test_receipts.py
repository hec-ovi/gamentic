"""System-beat receipts (live-found polish): duplicate tool calls in one narrator reply
are suppressed, model-invented snake_case never reaches the player, and quest/objective
receipts say WHAT changed, not just that something did."""
from app import llm


WORLD = {
    "title": "Receipts", "setting": "a town", "tone": "calm",
    "narrator_persona": "Plain.", "opening_scenario": "A quiet square.",
    "start_location": "square", "player_life": 20, "characters": [],
    "quests": [{"title": "Secure the zone", "description": "",
                "objectives": ["Establish a perimeter"]}], "lore": [],
}


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def test_duplicate_tool_calls_in_one_reply_apply_once(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    fake_llm.narrator = _nar(T("add_item", name="scanner_device"),
                             T("add_item", name="scanner_device"))
    d = client.post(f"/games/{gid}/action", json={"action": "I grab the scanner."}).json()
    obtained = [b for b in d["beats"] if b["kind"] == "system" and "Obtained" in b["text"]]
    assert len(obtained) == 1                                  # one receipt, not two
    inv = client.get(f"/games/{gid}/state").json()["player"]["inventory"]
    item = next(i for i in inv if "scanner" in i["name"])
    assert item.get("qty", 1) == 1                             # and ONE item, not qty 2


def test_snake_case_names_are_humanized_everywhere(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    fake_llm.narrator = _nar(T("add_item", name="scanner_device"),
                             T("place_item", target="scene", name="sensor_node"),
                             T("move_location", location="landing_zone_exterior"))
    d = client.post(f"/games/{gid}/action", json={"action": "I move out."}).json()
    texts = [b["text"] for b in d["beats"] if b["kind"] == "system"]
    assert "Obtained: scanner device." in texts
    assert "You move to landing zone exterior." in texts
    assert not any("_" in t for t in texts)                    # no snake_case for the player
    st = client.get(f"/games/{gid}/state").json()
    assert all("_" not in i["name"] for i in st["player"]["inventory"])

    # and lookups still work when the model later uses the snake_case name
    fake_llm.narrator = _nar(T("give_item", item="scanner_device", target="player"))
    # (player->player is invalid; use remove_item to prove the matcher instead)
    fake_llm.narrator = _nar(T("remove_item", name="scanner_device"))
    d = client.post(f"/games/{gid}/action", json={"action": "I drop it."}).json()
    assert any("Lost: scanner device." == b["text"] for b in d["beats"] if b["kind"] == "system")


def test_quest_and_objective_receipts_name_what_changed(client, fake_llm):
    gid = client.post("/games", json=WORLD).json()["game_id"]
    st = client.get(f"/games/{gid}/state").json()
    quest = st["quests"][0]
    oid = quest["objectives"][0]["id"]
    fake_llm.narrator = _nar(T("update_objective", objective_id=oid, done=True),
                             T("complete_quest", quest_id=quest["id"]))
    d = client.post(f"/games/{gid}/action", json={"action": "The perimeter holds."}).json()
    texts = [b["text"] for b in d["beats"] if b["kind"] == "system"]
    assert "Objective complete: Establish a perimeter." in texts
    assert "Quest complete: Secure the zone." in texts
