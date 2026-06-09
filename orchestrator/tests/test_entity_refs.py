"""Entity references: the UI's chips send real IDs (character.id, item.id) instead of
names. The brain resolves targets and items by ID first, then by name, so chips can
never misroute and a give-by-id still moves the properly named item."""
from app import llm


def _world(chars=None):
    return {
        "title": "Chipworld", "setting": "a keep", "tone": "grim",
        "narrator_persona": "Plain.", "opening_scenario": "A cold hall.",
        "start_location": "hall", "player_life": 20, "characters": chars or [],
        "quests": [{"title": "Get out", "objectives": ["Find the gate"]}], "lore": [],
    }


def _new(client, chars=None):
    return client.post("/games", json=_world(chars)).json()["game_id"]


def _state(client, gid):
    return client.get(f"/games/{gid}/state").json()


def _char(state, name):
    return next(c for c in state["characters"] if c["name"] == name)


def test_directed_say_routes_by_character_id(client, fake_llm):
    gid = _new(client, [{"name": "Mara", "persona": "a guard"}])
    cid = _char(_state(client, gid), "Mara")["id"]
    fake_llm.character = llm.LLMReply(content='[say]"Speak quickly."[/say]')
    out = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "say", "text": "Mara, open the gate.", "target": cid}]}).json()
    assert any(b["kind"] == "dialogue" and b["speaker_name"] == "Mara" for b in out["beats"])


def test_attack_segment_by_character_id(client, fake_llm):
    gid = _new(client, [{"name": "Brute", "persona": "a thug", "life": 10, "max_life": 10}])
    cid = _char(_state(client, gid), "Brute")["id"]
    out = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "attack", "target": cid, "amount": 4}]}).json()
    brute = _char(out["state"], "Brute")
    assert brute["life"] == 6
    # the system beat names the character, never the raw id
    assert any("Brute" in b["text"] for b in out["beats"] if b["kind"] == "system")


def test_give_by_item_id_and_target_id_moves_named_item(client, fake_llm):
    gid = _new(client, [{"name": "Mara", "persona": "a guard"}])
    # seed an item into the player's inventory via a narrator tool
    fake_llm.narrator = llm.LLMReply(content="...", tool_calls=[
        llm.ToolCall("add_item", {"name": "brass key", "description": "cold to the touch"})])
    client.post(f"/games/{gid}/action", json={"action": "I pick up the key."})
    s = _state(client, gid)
    item_id = s["player"]["inventory"][0]["id"]
    assert item_id  # player items now carry ids for the chips
    cid = _char(s, "Mara")["id"]

    fake_llm.narrator = llm.LLMReply(content="The exchange happens.")  # stop re-granting the key
    out = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "give", "item": item_id, "target": cid}]}).json()
    s2 = out["state"]
    assert all(i["name"] != "brass key" for i in s2["player"]["inventory"])
    mara = _char(s2, "Mara")
    assert any(i["name"] == "brass key" for i in mara["inventory"])   # real name, not the id
    assert any("brass key" in b["text"] and "Mara" in b["text"]
               for b in out["beats"] if b["kind"] == "system")


def test_character_chip_in_say_text_directs_the_line(client, fake_llm):
    # say "hello [Mara] how are you?" - the chip itself is the addressing, no explicit target
    gid = _new(client, [{"name": "Mara", "persona": "a guard"}])
    cid = _char(_state(client, gid), "Mara")["id"]
    fake_llm.character = llm.LLMReply(content='[say]"Well met."[/say]')
    out = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "say", "text": "hello Mara, how are you?",
         "refs": [{"kind": "character", "id": cid, "name": "Mara"}]}]}).json()
    assert any(b["kind"] == "dialogue" and b["speaker_name"] == "Mara" for b in out["beats"])
    # the player's echoed action shows the name, not the raw id
    echo = next(b for b in out["beats"] if b["speaker"] == "player")
    assert "Mara" in echo["text"] and cid not in echo["text"]


def test_give_echo_uses_chip_names_not_ids(client, fake_llm):
    gid = _new(client, [{"name": "Mara", "persona": "a guard"}])
    fake_llm.narrator = llm.LLMReply(content="...", tool_calls=[
        llm.ToolCall("add_item", {"name": "brass key"})])
    client.post(f"/games/{gid}/action", json={"action": "I pick up the key."})
    s = _state(client, gid)
    item_id = s["player"]["inventory"][0]["id"]
    cid = _char(s, "Mara")["id"]
    fake_llm.narrator = llm.LLMReply(content="Done.")
    out = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "give", "item": item_id, "target": cid,
         "refs": [{"kind": "item", "id": item_id, "name": "brass key"},
                  {"kind": "character", "id": cid, "name": "Mara"}]}]}).json()
    echo = next(b for b in out["beats"] if b["speaker"] == "player")
    assert "brass key" in echo["text"] and "Mara" in echo["text"]
    assert item_id not in echo["text"] and cid not in echo["text"]


def test_name_resolution_still_works(client, fake_llm):
    # the model (and free text) keeps using names; nothing regressed
    gid = _new(client, [{"name": "Mara", "persona": "a guard", "life": 8, "max_life": 8}])
    out = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "attack", "target": "Mara", "amount": 3}]}).json()
    assert _char(out["state"], "Mara")["life"] == 5
