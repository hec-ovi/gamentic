"""Item unlock images: when an item first becomes VISIBLE (obtained, revealed, placed in
view), a small square card renders in the background, attaches to the item wherever it
lives, and lands as a SYSTEM image beat in the chat."""
from app import llm, media, db, repo
from app.config import settings


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def _enable_images(monkeypatch, tmp_path, captured):
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(media, "generate_character_images", lambda d, style="", seed=None: None)

    def _gen(prompt, seed=None, width=None, height=None, references=None):
        captured.append({"prompt": prompt, "width": width, "height": height})
        return {"image_url": "/image/file?filename=item"}
    monkeypatch.setattr(media, "generate_scene_image", _gen)
    monkeypatch.setattr(media, "fetch_image_bytes", lambda url: b"PNG")


def _item_beats(client, gid):
    return [b for b in client.get(f"/games/{gid}/beats").json()["beats"]
            if b["kind"] == "image" and b["speaker"] == "system"]


def test_obtained_item_gets_a_small_card_and_a_system_image_beat(client, fake_llm, world,
                                                                 monkeypatch, tmp_path):
    captured = []
    _enable_images(monkeypatch, tmp_path, captured)
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("add_item", name="brass key",
                               description="a small tarnished key"),
                             content="A key glints in the silt.")
    client.post(f"/games/{gid}/action", json={"action": "I search the silt."})

    beats = _item_beats(client, gid)
    assert len(beats) == 1 and beats[0]["text"].startswith("brass key.")
    assert "tarnished key" in beats[0]["text"]             # the concept rides along
    assert beats[0]["image_url"].startswith(f"/media/{gid}/item-")
    shot = next(c for c in captured if "brass key" in c["prompt"])
    assert "Close-up of a single brass key" in shot["prompt"]
    assert "a small tarnished key" in shot["prompt"]
    assert "plain unmarked surfaces, no signage" in shot["prompt"]
    assert shot["width"] == shot["height"] == settings.IMAGE_ITEM_SIZE
    # the image is attached to the pack item too
    inv = client.get(f"/games/{gid}/state").json()["player"]["inventory"]
    assert inv[0]["name"] == "brass key" and inv[0]["image_url"] == beats[0]["image_url"]


def test_hidden_items_get_no_card_until_revealed(client, fake_llm, world,
                                                 monkeypatch, tmp_path):
    captured = []
    _enable_images(monkeypatch, tmp_path, captured)
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("place_item", target="scene", name="buried strongbox",
                               description="an iron strongbox", hidden=True),
                             content="Nothing seems out of place.")
    client.post(f"/games/{gid}/action", json={"action": "I look casually."})
    assert not _item_beats(client, gid)                       # hidden = not unlocked

    fake_llm.narrator = _nar(T("reveal_item", target="scene", name="buried strongbox"),
                             content="Your boot strikes metal.")
    client.post(f"/games/{gid}/action", json={"action": "I dig."})
    beats = _item_beats(client, gid)
    assert len(beats) == 1 and beats[0]["text"].startswith("buried strongbox.")
    assert "iron strongbox" in beats[0]["text"]            # the concept rides along


def test_item_card_renders_only_once(client, fake_llm, world, monkeypatch, tmp_path):
    """Re-entering a scene (or re-listing the item) never re-renders or re-posts the card."""
    captured = []
    _enable_images(monkeypatch, tmp_path, captured)
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("place_item", target="scene", name="old lantern"),
                             content="A lantern hangs by the door.")
    client.post(f"/games/{gid}/action", json={"action": "I enter."})
    assert len(_item_beats(client, gid)) == 1
    fake_llm.narrator = _nar(content="You pace the room.")
    client.post(f"/games/{gid}/action", json={"action": "I pace."})
    assert len(_item_beats(client, gid)) == 1                  # still just the one card


def test_item_cards_are_capped_per_turn(client, fake_llm, world, monkeypatch, tmp_path):
    captured = []
    _enable_images(monkeypatch, tmp_path, captured)
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("add_item", name="rope"), T("add_item", name="flint"),
                             T("add_item", name="dried fish"),
                             content="The chest holds supplies.")
    client.post(f"/games/{gid}/action", json={"action": "I open the chest."})
    assert len(_item_beats(client, gid)) == settings.IMAGE_MAX_ITEMS_PER_TURN == 2


def test_taken_item_carries_its_image_into_the_pack(client, fake_llm, world,
                                                    monkeypatch, tmp_path):
    captured = []
    _enable_images(monkeypatch, tmp_path, captured)
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("place_item", target="scene", name="old lantern"),
                             content="A lantern hangs by the door.")
    client.post(f"/games/{gid}/action", json={"action": "I enter."})
    url = _item_beats(client, gid)[0]["image_url"]
    fake_llm.narrator = _nar(T("take_item", name="old lantern"), content="You unhook it.")
    client.post(f"/games/{gid}/action", json={"action": "I take the lantern."})
    inv = client.get(f"/games/{gid}/state").json()["player"]["inventory"]
    lantern = next(i for i in inv if i["name"] == "old lantern")
    assert lantern["image_url"] == url
    assert len(_item_beats(client, gid)) == 1                  # taking is not a new unlock


def test_item_cards_do_not_consume_the_narrator_image_pacing(client, fake_llm, world,
                                                             monkeypatch, tmp_path):
    """A system item card must not block the narrator's own show_image cooldown."""
    captured = []
    _enable_images(monkeypatch, tmp_path, captured)
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("add_item", name="brass key"), content="A key in the dust.")
    client.post(f"/games/{gid}/action", json={"action": "I search."})
    assert len(_item_beats(client, gid)) == 1
    fake_llm.narrator = _nar(T("show_image", description="A vast drowned hall opens ahead."),
                             content="The hall opens out.")
    client.post(f"/games/{gid}/action", json={"action": "I push the door."})
    narrator_images = [b for b in client.get(f"/games/{gid}/beats").json()["beats"]
                       if b["kind"] == "image" and b["speaker"] == "narrator"]
    assert len(narrator_images) == 1                           # item card didn't block it
