"""The gift turn and the character whisper (live 2026-06-11 evening):

1. The give picker sends {item:'<inventory id>', target:'<name>'} with NO entity
   chips, so the raw item id reached the public echo - the owner saw "you give
   408f0801a83d to Sera". Echoes show NAMES, never ids; the compose path now resolves
   a bare id against the DB.
2. A gift's reply is owed to the player alone (owner: "when i give item a private
   whisper comes from that character... that must be forced"): the receiver answers in
   the private thread, GUARANTEED, even when the narrator cued nobody. The public
   receipt stays public (a mechanical fact); other characters' reactions stay public.
3. Characters can initiate whispers (owner: "characters should be able to also
   whisper"): a [whisper]...[/whisper] span in ANY reply becomes a private dialogue
   beat with the whisper tone, even on a public turn.
"""
from app import llm


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def _world(chars=None, player_items=None):
    return {
        "title": "Giftworld", "setting": "A quiet hall.", "tone": "warm",
        "narrator_persona": "Gentle.", "opening_scenario": "Lanterns burn low.",
        "start_location": "the hall", "player_life": 20,
        "characters": chars or [{"name": "Sera", "persona": "a watchful guard"}],
        "player_items": player_items or [{"name": "compass", "description": "a brass compass"}],
        "quests": [], "lore": [],
    }


def _new(client, chars=None, player_items=None):
    return client.post("/games", json=_world(chars, player_items)).json()["game_id"]


def _state(client, gid):
    return client.get(f"/games/{gid}/state").json()


def _item_id(client, gid, name):
    inv = _state(client, gid)["player"]["inventory"]
    return next(i["id"] for i in inv if i["name"] == name)


# ---------- TASK 1: the id leak in the public echo ----------

def test_give_by_inventory_id_echoes_the_item_name_not_the_id(client, fake_llm):
    """Live: the give picker sends the raw inventory item id with no entity chip, so
    'you give 408f0801a83d to Sera' reached the player echo. The compose path resolves
    the bare id against the pack; the public beat carries the item NAME, never the id."""
    gid = _new(client)
    iid = _item_id(client, gid, "compass")
    fake_llm.narrator = _nar(T("give_item", item="compass", target="Sera"),
                             content="Sera accepts the compass with a nod.")
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "give", "item": iid, "target": "Sera"}]}).json()
    echo = next(b for b in d["beats"] if b["speaker"] == "player")
    assert "compass" in echo["text"]                 # the name landed
    assert iid not in echo["text"]                   # the raw id never did
    assert echo["text"] == "you give compass to Sera"


def test_attack_by_character_id_echoes_the_name_not_the_id(client, fake_llm):
    """The same bare-id leak guards every directed family: an attack segment carrying a
    character ID (no chip) must echo the character's NAME, not the id."""
    gid = _new(client)
    cid = next(c["id"] for c in _state(client, gid)["characters"] if c["name"] == "Sera")
    fake_llm.narrator = _nar(content="Your fist swings wide.")
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "attack", "target": cid, "text": "I throw a punch"}]}).json()
    echo = next(b for b in d["beats"] if b["speaker"] == "player")
    assert "Sera" in echo["text"] and cid not in echo["text"]


# ---------- TASK 2: a gift's reply is a forced private whisper ----------

def test_accepted_give_forces_a_private_reply_from_the_receiver(client, fake_llm):
    """Owner: the gift's reply must come from that character, privately, ALWAYS - even
    when the narrator's reply cues nobody to speak. The receiver's beats all carry
    private_with=their id, and at least one dialogue beat exists."""
    gid = _new(client)
    sera = next(c["id"] for c in _state(client, gid)["characters"] if c["name"] == "Sera")
    iid = _item_id(client, gid, "compass")
    # the narrator accepts the give but cues NO reply - the engine forces one anyway
    fake_llm.narrator = _nar(T("give_item", item="compass", target="Sera"),
                             content="The compass changes hands.")
    fake_llm.character_replies["Sera"] = llm.LLMReply(
        content='[say]"You honour me with this."[/say][do]She turns it over.[/do]')
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "give", "item": iid, "target": "Sera"}]}).json()
    sera_beats = [b for b in d["beats"] if b["speaker"] == sera]
    assert sera_beats, "the receiver must answer the gift"
    assert all(b["private_with"] == sera for b in sera_beats)   # every beat private to them
    dlg = [b for b in sera_beats if b["kind"] == "dialogue"]
    assert dlg and dlg[0]["emotion"] == ""                     # private, but a natural voice
    # the public receipt stays public (a mechanical fact, not a confidence)
    receipt = next(b for b in d["beats"] if b["kind"] == "system" and "compass" in b["text"])
    assert receipt["private_with"] is None


def test_a_cued_receiver_still_answers_a_gift_once_and_privately(client, fake_llm):
    """When the narrator DOES cue the receiver, their gift reply still lands in the
    private thread (never publicly, never twice): the receiver is pulled out of the open
    cascade and answered once by the forced private pass."""
    gid = _new(client)
    sera = next(c["id"] for c in _state(client, gid)["characters"] if c["name"] == "Sera")
    iid = _item_id(client, gid, "compass")
    fake_llm.narrator = _nar(T("give_item", item="compass", target="Sera"),
                             T("cue_character", name="Sera"),
                             content="Sera receives the compass.")
    fake_llm.character_replies["Sera"] = llm.LLMReply(content='[say]"I will keep it close."[/say]')
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "give", "item": iid, "target": "Sera"}]}).json()
    dlg = [b for b in d["beats"] if b["speaker"] == sera and b["kind"] == "dialogue"]
    assert len(dlg) == 1                                  # answered once, not doubled
    assert dlg[0]["private_with"] == sera                 # and in private


def test_a_refused_give_forces_no_private_reply(client, fake_llm):
    """A give whose target is ABSENT bounces deterministically before adjudication - it
    never becomes a pending attempt, so no gift reply is forced (no private beats, no
    receipt of a transfer that never happened)."""
    gid = _new(client, chars=[{"name": "Sera", "persona": "a guard"}])
    iid = _item_id(client, gid, "compass")
    fake_llm.narrator = _nar(content="The hall is empty of the one you sought.")
    fake_llm.character_replies["Sera"] = llm.LLMReply(content='[say]"Here."[/say]')
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "give", "item": iid, "target": "Ghost"}]}).json()
    assert not any(b["private_with"] for b in d["beats"])       # nothing private was forced
    assert not any(b["kind"] == "dialogue" for b in d["beats"])  # no one received it


def test_another_present_characters_reaction_to_a_gift_stays_public(client, fake_llm):
    """Only the receiver's reply goes private. A bystander cued by the narrator in the
    same turn reacts in the open, where everyone present can hear them."""
    gid = _new(client, chars=[{"name": "Sera", "persona": "a guard"},
                              {"name": "Otto", "persona": "a nosy clerk"}])
    sera = next(c["id"] for c in _state(client, gid)["characters"] if c["name"] == "Sera")
    otto = next(c["id"] for c in _state(client, gid)["characters"] if c["name"] == "Otto")
    iid = _item_id(client, gid, "compass")
    fake_llm.narrator = _nar(T("give_item", item="compass", target="Sera"),
                             T("cue_character", name="Otto"),
                             content="Otto cranes his neck to see.")
    fake_llm.character_replies["Sera"] = llm.LLMReply(content='[say]"My thanks."[/say]')
    fake_llm.character_replies["Otto"] = llm.LLMReply(content='[say]"What is that, then?"[/say]')
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "give", "item": iid, "target": "Sera"}]}).json()
    sera_beats = [b for b in d["beats"] if b["speaker"] == sera]
    otto_beats = [b for b in d["beats"] if b["speaker"] == otto]
    assert sera_beats and all(b["private_with"] == sera for b in sera_beats)   # receiver: private
    assert otto_beats and all(b["private_with"] is None for b in otto_beats)   # bystander: public


def test_two_gifts_to_different_characters_each_reply_privately(client, fake_llm):
    """Multiple gives in one stack: each receiver answers in their OWN private thread."""
    gid = _new(client, chars=[{"name": "Sera", "persona": "a guard"},
                              {"name": "Otto", "persona": "a clerk"}],
               player_items=[{"name": "compass", "description": ""},
                             {"name": "coin", "description": ""}])
    sera = next(c["id"] for c in _state(client, gid)["characters"] if c["name"] == "Sera")
    otto = next(c["id"] for c in _state(client, gid)["characters"] if c["name"] == "Otto")
    comp = _item_id(client, gid, "compass")
    coin = _item_id(client, gid, "coin")
    fake_llm.narrator = _nar(T("give_item", item="compass", target="Sera"),
                             T("give_item", item="coin", target="Otto"),
                             content="Two gifts pass at once.")
    fake_llm.character_replies["Sera"] = llm.LLMReply(content='[say]"For me?"[/say]')
    fake_llm.character_replies["Otto"] = llm.LLMReply(content='[say]"A coin!"[/say]')
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "give", "item": comp, "target": "Sera"},
        {"type": "give", "item": coin, "target": "Otto"}]}).json()
    assert all(b["private_with"] == sera for b in d["beats"] if b["speaker"] == sera)
    assert all(b["private_with"] == otto for b in d["beats"] if b["speaker"] == otto)
    assert any(b["speaker"] == sera for b in d["beats"])   # both answered
    assert any(b["speaker"] == otto for b in d["beats"])


# ---------- TASK 3: characters can initiate whispers ----------

def test_a_character_whisper_span_lands_privately_on_a_public_turn(client, fake_llm):
    """Owner: 'characters should be able to also whisper.' A [say]+[whisper] reply on a
    PUBLIC directed-say turn emits the say publicly and the whisper privately; the private
    line keeps a natural voice (private is about who hears it, not a forced hush)."""
    gid = _new(client)
    sera = next(c["id"] for c in _state(client, gid)["characters"] if c["name"] == "Sera")
    fake_llm.narrator = _nar(T("cue_character", name="Sera"), content="Sera turns to you.")
    fake_llm.character_replies["Sera"] = llm.LLMReply(content=(
        '[say]"All is well here."[/say][whisper]They are listening. Say nothing.[/whisper]'))
    d = client.post(f"/games/{gid}/action", json={
        "action": "Is everything alright?"}).json()
    dialogue = [b for b in d["beats"] if b["speaker"] == sera and b["kind"] == "dialogue"]
    public = [b for b in dialogue if b["private_with"] is None]
    private = [b for b in dialogue if b["private_with"] == sera]
    assert any("All is well" in b["text"] for b in public)        # the say is public
    assert private, "the whisper must be private"
    assert "They are listening" in private[0]["text"]
    assert private[0]["emotion"] == ""                            # private routing, natural voice


def test_a_character_whisper_never_appears_in_any_public_beat(client, fake_llm):
    """The secret stays out of the open thread: the whispered words appear in NO public
    beat (the bystander-leak guard, mirrored from the player whisper channel)."""
    gid = _new(client)
    sera = next(c["id"] for c in _state(client, gid)["characters"] if c["name"] == "Sera")
    fake_llm.narrator = _nar(T("cue_character", name="Sera"), content="Sera nods.")
    fake_llm.character_replies["Sera"] = llm.LLMReply(content=(
        '[say]"Welcome, traveller."[/say][whisper]The bridge is a trap.[/whisper]'))
    d = client.post(f"/games/{gid}/action", json={"action": "Hello."}).json()
    for b in d["beats"]:
        if b["private_with"] is None:
            assert "The bridge is a trap" not in b["text"]
            assert "bridge" not in b["text"]


def test_character_prompt_teaches_the_whisper_tag():
    """The character grammar must teach [whisper] (pinned like the memory instructions)."""
    from app import prompts
    text = prompts.render("character.system.md", name="X", persona="p", knowledge="",
                          scene="s", tone="t", example_block="")
    assert "[whisper]" in text and "[/whisper]" in text
