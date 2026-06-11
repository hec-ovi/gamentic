"""Tool-layer fixes from the 2026-06-11 live e2e audit + 24-agent static review:
negative add_item paid the player, article drift duplicated lanterns and exits,
add_item-as-take minted copies, remove_item near-misses leaked invalids to the screen,
no-op receipts spammed ('Tamsin turns hostile.' x6), the empty->stranger relation
staged a fake moment, absent characters got memories written, and amount=9999
one-shot a 10hp character off 'a flick on the ear'."""
from app import llm
from app.config import settings


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def _state(client, gid):
    return client.get(f"/games/{gid}/state").json()


def _systems(d):
    return [b["text"] for b in d["beats"] if b["kind"] == "system"]


def _mara(client, gid):
    return next(c for c in _state(client, gid)["characters"] if c["name"] == "Mara")


def _profile(client, gid):
    return client.get(f"/games/{gid}/characters/{_mara(client, gid)['id']}/profile").json()


# ---------- fix 1: add_item qty must be positive ----------

def test_negative_qty_add_item_is_invalid_and_feeds_back(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("add_item", name="copper coins", qty=-3),
                             content="You hand over three coppers.")
    d = client.post(f"/games/{gid}/action", json={"action": "I pay the toll."}).json()
    assert not any("Obtained" in t for t in _systems(d))     # live: 'Obtained: copper coins.'
    assert _state(client, gid)["player"]["inventory"] == []  # the player GAINED coins live
    # the reason rides the next narrator message so the retry loop can steer
    fake_llm.narrator = _nar(content="The tollkeeper waits.")
    client.post(f"/games/{gid}/action", json={"action": "I wait."})
    assert "qty must be positive; use remove_item" in fake_llm.narrator_calls()[1]["messages"][1]["content"]


def test_zero_qty_add_item_is_invalid(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("add_item", name="dust", qty=0))
    d = client.post(f"/games/{gid}/action", json={"action": "I grasp at nothing."}).json()
    assert not any(b["kind"] == "system" for b in d["beats"])
    assert _state(client, gid)["player"]["inventory"] == []


# ---------- fixes 2+3: article-blind matching, add_item as implicit take ----------

def test_add_item_matching_visible_scene_item_moves_it(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("place_item", target="scene", name="a rusted lantern",
                               description="metal flaking like dead skin"))
    client.post(f"/games/{gid}/action", json={"action": "I approach the door."})
    fake_llm.narrator = _nar(T("add_item", name="rusted lantern"))   # live: minted a copy
    d = client.post(f"/games/{gid}/action", json={"action": "I take the rusted lantern."}).json()
    assert "You take rusted lantern." in _systems(d)
    s = _state(client, gid)
    assert s["scene"]["items"] == []                          # the slot cleared
    assert [i["name"] for i in s["player"]["inventory"]] == ["a rusted lantern"]
    assert s["player"]["inventory"][0].get("qty", 1) == 1     # ONE lantern in the world


def test_add_item_respects_fixed_scenery(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("place_item", target="scene", name="an ancient altar", fixed=True))
    client.post(f"/games/{gid}/action", json={"action": "I look around."})
    fake_llm.narrator = _nar(T("add_item", name="ancient altar"))
    d = client.post(f"/games/{gid}/action", json={"action": "I pocket the altar."}).json()
    assert any("part of the place" in t for t in _systems(d))
    s = _state(client, gid)
    assert any(i["name"] == "an ancient altar" for i in s["scene"]["items"])  # stays put
    assert s["player"]["inventory"] == []


def test_add_item_merges_article_variants_in_the_pack(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("add_item", name="a brass key"))
    client.post(f"/games/{gid}/action", json={"action": "I find a key."})
    fake_llm.narrator = _nar(T("add_item", name="brass key"))
    client.post(f"/games/{gid}/action", json={"action": "I find another."})
    inv = _state(client, gid)["player"]["inventory"]
    assert len(inv) == 1                                      # merged, not a twin row
    assert inv[0]["name"] == "a brass key" and inv[0]["qty"] == 2


def test_give_item_lookup_is_article_blind(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("add_item", name="brass key"))
    client.post(f"/games/{gid}/action", json={"action": "I pick up the key."})
    fake_llm.narrator = _nar(T("give_item", item="the brass key", target="Mara"))
    d = client.post(f"/games/{gid}/action", json={"action": "I hand it over."}).json()
    assert "You give brass key to Mara." in _systems(d)
    assert _state(client, gid)["player"]["inventory"] == []
    assert any(i["name"] == "brass key" for i in _mara(client, gid)["inventory"])


def test_visible_item_index_keys_are_article_blind(client, fake_llm, world):
    """The unlock-card diff keys on item_key (live: 'a rusted lantern' in the scene and
    'rusted lantern' in the pack each rendered their own unlock card)."""
    from app import db, repo
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("place_item", target="scene", name="a rusted lantern"),
                             T("place_item", target="Mara", name="rusted lantern"))
    client.post(f"/games/{gid}/action", json={"action": "I look around."})
    with db.get_conn() as conn:
        idx = repo.visible_item_index(conn, gid)
    assert sum(1 for k in idx if "lantern" in k) == 1         # one key, one card


# ---------- fix 4: remove_item near-miss ----------

def test_remove_item_near_miss_takes_the_only_candidate(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("add_item", name="heavy iron key"))
    client.post(f"/games/{gid}/action", json={"action": "I take the key."})
    fake_llm.narrator = _nar(T("remove_item", name="room key"))   # live: both beats showed
    d = client.post(f"/games/{gid}/action", json={"action": "I trade it away."}).json()
    assert "Lost: heavy iron key." in _systems(d)
    assert not any("don't have" in t for t in _systems(d))
    assert _state(client, gid)["player"]["inventory"] == []


def test_remove_item_near_miss_stays_invalid_when_ambiguous(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("add_item", name="heavy iron key"),
                             T("add_item", name="small brass key"))
    client.post(f"/games/{gid}/action", json={"action": "I pocket both keys."})
    fake_llm.narrator = _nar(T("remove_item", name="room key"))
    d = client.post(f"/games/{gid}/action", json={"action": "I hand one over."}).json()
    assert not any(t.startswith("Lost:") for t in _systems(d))    # never guess between keys
    assert len(_state(client, gid)["player"]["inventory"]) == 2


def test_remove_item_is_article_blind(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("add_item", name="a brass key"))
    client.post(f"/games/{gid}/action", json={"action": "I take the key."})
    fake_llm.narrator = _nar(T("remove_item", name="the brass key"))
    d = client.post(f"/games/{gid}/action", json={"action": "I toss it."}).json()
    assert "Lost: a brass key." in _systems(d)
    assert _state(client, gid)["player"]["inventory"] == []


# ---------- fix 5: set_disposition no-op is silent ----------

def test_unchanged_disposition_prints_no_receipt(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("set_disposition", name="Mara", disposition="hostile"))
    d = client.post(f"/games/{gid}/action", json={"action": "I insult her."}).json()
    assert "Mara turns hostile." in _systems(d)               # the real shift announces
    fake_llm.narrator = _nar(T("set_disposition", name="Mara", disposition="hostile"))
    d = client.post(f"/games/{gid}/action", json={"action": "I insult her again."}).json()
    assert not any(b["kind"] == "system" for b in d["beats"])  # live: printed six times
    assert _mara(client, gid)["disposition"] == "hostile"


# ---------- fix 6: set_relation grammar + the empty->stranger non-event ----------

def test_empty_to_stranger_relation_is_a_silent_non_event(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("set_relation", name="Mara", relation="stranger"))
    d = client.post(f"/games/{gid}/action", json={"action": "I size her up."}).json()
    assert not any(b["kind"] == "system" for b in d["beats"])  # live: 'is now your stranger.'
    assert _mara(client, gid)["relation"] == "stranger"        # the label still lands
    assert _profile(client, gid)["moments"] == []              # and no fake pivotal moment


def test_relation_receipt_and_moment_are_article_aware(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("set_relation", name="Mara", relation="old friend"))
    d = client.post(f"/games/{gid}/action", json={"action": "We embrace."}).json()
    assert "Mara now sees you as an old friend." in _systems(d)
    assert "Came to see the player as an old friend" in [m["text"] for m in _profile(client, gid)["moments"]]
    fake_llm.narrator = _nar(T("set_relation", name="Mara", relation="sworn enemy"))
    d = client.post(f"/games/{gid}/action", json={"action": "I betray her."}).json()
    assert "Mara now sees you as a sworn enemy." in _systems(d)


# ---------- fix 7: note_moment / note_trait need the character here and alive ----------

def test_note_moment_rejects_a_character_in_another_scene(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("move_location", location="inner chamber"))
    client.post(f"/games/{gid}/action", json={"action": "I go deeper."})   # Mara stays behind
    fake_llm.narrator = _nar(T("note_moment", name="Mara", event="Watched the player descend"))
    client.post(f"/games/{gid}/action", json={"action": "I press on."})
    assert _profile(client, gid)["moments"] == []             # nothing written from afar
    fake_llm.narrator = _nar(content="Silence.")
    client.post(f"/games/{gid}/action", json={"action": "I listen."})
    assert "note_moment: Mara is not present" in fake_llm.narrator_calls()[-1]["messages"][1]["content"]


def test_note_trait_rejects_the_dead(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("kill_character", name="Mara"))
    client.post(f"/games/{gid}/action", json={"action": "The blade finds her."})
    fake_llm.narrator = _nar(T("note_trait", name="Mara", trait="brave to the end"))
    client.post(f"/games/{gid}/action", json={"action": "I mourn."})
    assert _profile(client, gid)["traits"] == []


def test_reveal_origin_stays_open_for_absent_characters(client, fake_llm, world):
    """Learning someone's past from a third party is legitimate; only memory writes guard."""
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("move_location", location="inner chamber"))
    client.post(f"/games/{gid}/action", json={"action": "I go deeper."})
    fake_llm.narrator = _nar(T("reveal_origin", name="Mara", fact="fled the mining colonies"))
    d = client.post(f"/games/{gid}/action", json={"action": "Who is Mara, really?"}).json()
    assert any("You learn of Mara's past" in t for t in _systems(d))


# ---------- fix 8: the damage cap ----------

def test_damage_amount_is_capped_at_the_tool_layer(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("apply_damage", target="Mara", amount=9999),
                             content="A flick on the ear.")
    d = client.post(f"/games/{gid}/action", json={"action": "I flick her ear."}).json()
    assert "Mara takes 6 damage (4 left)." in _systems(d)     # live: one-shot at 9999
    assert _mara(client, gid)["alive"] is True
    # narrator damage to the PLAYER is deliberately uncapped (a lethal fall must be able
    # to kill): see test_narrator_damage_to_the_player_is_uncapped_but_characters_are_protected


def test_damage_cap_is_a_live_setting(client, fake_llm, world, monkeypatch):
    monkeypatch.setattr(settings, "DAMAGE_CAP", 2)
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("apply_damage", target="Mara", amount=5))
    d = client.post(f"/games/{gid}/action", json={"action": "I strike."}).json()
    assert "Mara takes 2 damage (8 left)." in _systems(d)


# ---------- fix 9: add_exit dedupe is article-blind ----------

def test_second_exit_to_the_same_target_is_silent(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("add_exit", label="the salt-sprayed cliff path",
                               target="Lighthouse Path"))
    d = client.post(f"/games/{gid}/action", json={"action": "I scan the cliffs."}).json()
    assert "A way out opens: the salt-sprayed cliff path." in _systems(d)
    fake_llm.narrator = _nar(T("add_exit", label="the Lighthouse Path",
                               target="The Lighthouse Path"))   # live: a second button
    d = client.post(f"/games/{gid}/action", json={"action": "I look again."}).json()
    assert not any(b["kind"] == "system" for b in d["beats"])
    assert len(_state(client, gid)["scene"]["exits"]) == 1


# ---------- kill no-op + fix 10: describe_scene schema text ----------

def test_rekilling_the_dead_prints_no_second_receipt(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("kill_character", name="Mara"))
    d = client.post(f"/games/{gid}/action", json={"action": "It ends."}).json()
    assert "Mara is gone." in _systems(d)
    fake_llm.narrator = _nar(T("kill_character", name="Mara"))
    d = client.post(f"/games/{gid}/action", json={"action": "I make sure."}).json()
    assert not any(b["kind"] == "system" for b in d["beats"])


def test_describe_scene_schema_says_it_never_moves_anyone(client):
    from app.tools.base import SCHEMAS
    desc = SCHEMAS["describe_scene"]["function"]["description"]
    assert "REDECORATE" in desc and "CURRENT scene" in desc    # live: it 'expressed' travel
    assert "never moves" in desc and "move_location" in desc


# ---------- reveal_item authors discoveries (live: the most common invalid class) ----------

def test_reveal_item_creates_a_scene_item_when_nothing_was_planted(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("reveal_item", target="scene", name="broken clay jug"),
                             content="A jug lies in the silt.")
    d = client.post(f"/games/{gid}/action", json={"action": "I search the basin."}).json()
    assert any("You spot broken clay jug" in t for t in _systems(d))
    assert any(i["name"] == "broken clay jug" for i in d["state"]["scene"]["items"])


def test_reveal_item_still_flips_a_planted_hidden_item(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("place_item", target="scene", name="bloated satchel", hidden=True),
                             content="Something is buried here.")
    client.post(f"/games/{gid}/action", json={"action": "I look around."})
    fake_llm.narrator = _nar(T("reveal_item", target="scene", name="bloated satchel"),
                             content="There it is.")
    d = client.post(f"/games/{gid}/action", json={"action": "I dig."}).json()
    names = [i["name"] for i in d["state"]["scene"]["items"]]
    assert names.count("bloated satchel") == 1     # flipped, never duplicated


def test_reveal_item_to_player_lands_in_the_pack(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("reveal_item", target="player", name="water-damaged ledger"),
                             content="It was in your satchel all along.")
    d = client.post(f"/games/{gid}/action", json={"action": "I check my satchel."}).json()
    assert any("Obtained: water-damaged ledger" in t for t in _systems(d))
    assert any(i["name"] == "water-damaged ledger" for i in d["state"]["player"]["inventory"])


def test_take_item_miss_steers_the_retry_toward_add_item(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("take_item", name="storm lantern"),
                             content="You lift the lantern.")
    client.post(f"/games/{gid}/action", json={"action": "I take the lantern."})
    fake_llm.narrator = _nar(content="A quiet beat.")
    client.post(f"/games/{gid}/action", json={"action": "I wait."})
    # the steering text reaches the narrator via the failed-calls note next turn
    note = fake_llm.narrator_calls()[-1]
    blob = note["system"] + "".join(m.get("content", "") for m in note.get("messages", []) if isinstance(m, dict))
    assert "add_item it instead" in blob


def test_reveal_item_of_an_already_visible_item_is_silent(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("place_item", target="scene", name="a sleeping camel driver"),
                             T("reveal_item", target="scene", name="a sleeping camel driver"),
                             content="A man snores in the hay.")
    d = client.post(f"/games/{gid}/action", json={"action": "I enter the stables."}).json()
    receipts = [t for t in _systems(d) if "camel driver" in t]
    assert receipts == ["There is a sleeping camel driver here."]   # one receipt, not two


def test_spawn_absorbs_the_persons_scene_item_ghost(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("place_item", target="scene", name="a sleeping camel driver"),
                             content="A man snores in the hay.")
    client.post(f"/games/{gid}/action", json={"action": "I enter the stables."})
    fake_llm.narrator = _nar(T("spawn_character", name="the camel driver",
                               persona="a weary driver", sex="male"),
                             content="He wakes.")
    d = client.post(f"/games/{gid}/action", json={"action": "I wake him."}).json()
    assert any(c["name"] == "the camel driver" for c in d["state"]["characters"])
    assert not any("camel driver" in (i.get("name") or "")
                   for i in d["state"]["scene"]["items"] if i)   # the ghost slot is gone


def test_narrator_damage_to_the_player_is_uncapped_but_characters_are_protected(client, fake_llm, world):
    # the storyteller may stage a lethal fall (player death is a designed, recoverable
    # turn); nobody may one-shot a CHARACTER, and a character may not one-shot the player
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("apply_damage", target="player", amount=30),
                             content="The ground rushes up.")
    d = client.post(f"/games/{gid}/action", json={"action": "I step off the edge."}).json()
    assert d["state"]["player"]["life"] == 0
    assert d["state"]["status"] == "lost"
    fake_llm.narrator = _nar(T("heal", target="player", amount=30),
                             T("apply_damage", target="Mara", amount=30),
                             content="You wake; your hand lashes out.")
    d = client.post(f"/games/{gid}/action", json={"action": "I wake swinging."}).json()
    mara = next(c for c in d["state"]["characters"] if c["name"] == "Mara")
    assert mara["life"] == 10 - settings.DAMAGE_CAP            # capped, not one-shot
