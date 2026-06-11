"""The whisper channel finally writes memory (live 2026-06-11): a whispered life
story left the profile untouched because whisper turns run no narrator pass and
characters held no memory tools. Characters now carry share_past / mark_moment /
admit_trait (self-only), profile memories attribute images by private_with and
whole-word name match (a whispered look at Layla once landed in Rust's gallery,
because "Rust" lives inside "trust"), and a private look always conditions on the
studied character's identity reference."""
from app import llm
from app.config import settings


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def _world(chars=None):
    return {
        "title": "T", "setting": "s", "tone": "t", "narrator_persona": "n",
        "opening_scenario": "o", "start_location": "the den", "player_life": 20,
        "characters": chars or [
            {"name": "Layla", "sex": "female", "persona": "A hacker. Sharp and wary."},
            {"name": "Rust", "sex": "male", "persona": "A fixer. Slow to trust."},
        ],
        "quests": [], "lore": [],
    }


def _profile(client, gid, name):
    st = client.get(f"/games/{gid}/state").json()
    cid = next(c["id"] for c in st["characters"] if c["name"] == name)
    return client.get(f"/games/{gid}/characters/{cid}/profile").json()


# ---------- the character's own memory tools, from a whisper ----------

def test_a_whispered_confession_reaches_past_moments_and_traits(client, fake_llm):
    gid = client.post("/games", json=_world()).json()["game_id"]
    fake_llm.character_replies["Layla"] = llm.LLMReply(
        content='[say]"I lost my brother to the sweeps."[/say]',
        tool_calls=[T("share_past", piece="Lost her brother to an automated sweep"),
                    T("mark_moment", event="Confided the loss of her brother"),
                    T("admit_trait", trait="haunted by the sweeps")])
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "text": "Tell me about your past.", "target": "Layla"}]}).json()
    prof = _profile(client, gid, "Layla")
    assert any("Lost her brother" in o["text"] for o in prof["origin"])
    assert any("Confided the loss" in m["text"] for m in prof["moments"])
    assert any("haunted by the sweeps" in t["text"] for t in prof["traits"])
    # the receipts stay in the private thread, stamped like the rest of the exchange
    receipts = [b for b in d["beats"] if b["kind"] == "system"]
    assert receipts and all(b["private_with"] for b in receipts)


def test_self_tools_never_touch_anyone_else(client, fake_llm):
    # the tools take no name on purpose: a character writes their OWN memory only
    gid = client.post("/games", json=_world()).json()["game_id"]
    fake_llm.character_replies["Layla"] = llm.LLMReply(
        content='[say]"Rust never talks about his scars."[/say]',
        tool_calls=[T("share_past", piece="Grew up in the lower stacks")])
    client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "text": "And Rust?", "target": "Layla"}]})
    assert any("lower stacks" in o["text"] for o in _profile(client, gid, "Layla")["origin"])
    assert _profile(client, gid, "Rust")["origin"] == []


def test_character_prompt_carries_the_memory_instructions():
    from app import prompts
    text = prompts.render("character.system.md", name="X", persona="p", knowledge="",
                          scene="s", tone="t", example_block="")
    assert "share_past" in text and "mark_moment" in text and "admit_trait" in text


# ---------- memories attribution (the Rust gallery bug) ----------

def test_private_look_images_belong_to_that_character_alone(client, fake_llm, world, monkeypatch):
    from app import media
    from app.integrate import jobs
    gid = client.post("/games", json=_world()).json()["game_id"]
    monkeypatch.setattr(media, "generate_scene_image",
                        lambda *a, **k: {"image_url": "data:image/png;base64,aGk="})
    st = client.get(f"/games/{gid}/state").json()
    layla = next(c["id"] for c in st["characters"] if c["name"] == "Layla")
    jobs.generate_view_snapshot(gid, "any picture of you and your brother?", private_with=layla)
    assert len(_profile(client, gid, "Layla")["memories"]) == 1
    assert _profile(client, gid, "Rust")["memories"] == []     # never a bystander's


def test_public_memories_match_whole_words_never_substrings(client, fake_llm, monkeypatch):
    from app import media
    from app.integrate import jobs
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)   # the route gates the render task
    gid = client.post("/games", json=_world()).json()["game_id"]
    monkeypatch.setattr(media, "generate_scene_image",
                        lambda *a, **k: {"image_url": "data:image/png;base64,aGk="})
    monkeypatch.setattr(jobs, "generate_images_for_game", lambda gid: None)   # no portrait churn
    monkeypatch.setattr(jobs, "generate_scene_image", lambda gid, sid: None)
    fake_llm.narrator = _nar(T("show_image", description="A rusted pipe drips with distrust near the trash heaps"),
                             content="The pipe drips.")
    client.post(f"/games/{gid}/action", json={"action": "I look at the pipe."})
    assert _profile(client, gid, "Rust")["memories"] == []     # "rusted"/"distrust" are not Rust
    fake_llm.narrator = _nar(T("show_image", description="Rust leans against the doorway, watching"),
                             content="He watches.")
    # a LOOK always earns its image (spontaneous narrator shots pace themselves out)
    client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "look", "text": "Rust by the doorway"}]})
    assert len(_profile(client, gid, "Rust")["memories"]) == 1


# ---------- a private look always carries the identity reference ----------

def test_private_look_defaults_its_reference_to_the_studied_character(client, fake_llm, monkeypatch):
    from app import media
    from app.integrate import jobs, storage
    gid = client.post("/games", json=_world()).json()["game_id"]
    st = client.get(f"/games/{gid}/state").json()
    layla = next(c["id"] for c in st["characters"] if c["name"] == "Layla")
    # give Layla a stored body view the reference must point at
    import sqlite3
    from app import db
    with db.get_conn() as conn:
        conn.execute("UPDATE characters SET body_front_url='/media/g/layla-front.png' WHERE id=?", (layla,))
    seen = {}
    monkeypatch.setattr(media, "generate_scene_image",
                        lambda prompt, **k: seen.update(k) or {"image_url": "data:image/png;base64,aGk="})
    jobs.generate_view_snapshot(gid, "any picture of you and your brother?", private_with=layla)
    assert seen.get("references"), "a private look must condition on the studied character"
    assert "layla-front" in seen["references"][0]


# ---------- memory marks written as text (the live 26B habit) ----------

def test_brace_marks_in_prose_apply_like_real_calls_and_never_display(client, fake_llm):
    """Live (first night): the character printed {piece: "..."} {trait: "haunted by
    silence"} inside a [do] block and made no real calls; the profile stayed empty."""
    gid = client.post("/games", json=_world()).json()["game_id"]
    fake_llm.character_replies["Otta" if False else "Layla"] = llm.LLMReply(content=(
        '[say]"The mountain took my brother."[/say]'
        '[do]She turns the float over in her hand. '
        '{piece: "The mountain took her brother"} {trait: "haunted by silence"}[/do]'))
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "text": "Tell me something true.", "target": "Layla"}]}).json()
    prof = _profile(client, gid, "Layla")
    assert any("took her brother" in o["text"] for o in prof["origin"])
    assert any("haunted by silence" in t["text"] for t in prof["traits"])
    for b in d["beats"]:               # the marks never reach the display text
        assert "{piece" not in b["text"] and "{trait" not in b["text"]
    assert any("You learn of Layla's past" in b["text"] for b in d["beats"]
               if b["kind"] == "system" and b["private_with"])


def test_unknown_brace_lines_still_die_in_character_segments(client, fake_llm):
    gid = client.post("/games", json=_world()).json()["game_id"]
    fake_llm.character_replies["Layla"] = llm.LLMReply(content=(
        '[say]"Fine."[/say]\n{mood: "wary", target: "player"}'))
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "text": "Talk to me.", "target": "Layla"}]}).json()
    assert not any("{mood" in b["text"] for b in d["beats"])


def test_bracket_toolname_marks_apply_like_real_calls_and_never_display(client, fake_llm):
    """Live (the gift turn, 2026-06-11 evening): the character wrote her memory calls as
    bracket text - '...cloak.[share_past, The compass was a gift of shared burdens.' and
    '...moving.[mark_moment, The gift deepened her trust.[admit_trait, burdened by the
    past.' - tool name first, comma payload, never terminated, chained mid-sentence.
    The content was lost AND the raw marks leaked into the visible prose."""
    gid = client.post("/games", json=_world()).json()["game_id"]
    fake_llm.character_replies["Layla"] = llm.LLMReply(content=(
        '[say]"You shouldn\'t have."[/say]'
        '[do]She tucks the compass away.[share_past, The compass was a gift of shared burdens.[/do]'
        '[do]She turns to the arch.[mark_moment, The gift deepened her trust.[admit_trait, burdened by the past.[/do]'))
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "text": "Take it.", "target": "Layla"}]}).json()
    prof = _profile(client, gid, "Layla")
    assert any("shared burdens" in o["text"] for o in prof["origin"])
    assert any("deepened her trust" in m["text"] for m in prof["moments"])
    assert any("burdened by the past" in t["text"] for t in prof["traits"])
    for b in d["beats"]:               # the marks never reach the display text
        assert "share_past" not in b["text"] and "mark_moment" not in b["text"]
        assert "admit_trait" not in b["text"]
    assert any("You learn of Layla's past" in b["text"] for b in d["beats"]
               if b["kind"] == "system" and b["private_with"])


def test_bare_and_closed_bracket_marks_strip_clean(client, fake_llm):
    """A bare '[mark_moment' mid-prose (the half-written twin of a real call) strips
    without applying anything; a closed '[admit_trait: x]' applies like a real call."""
    gid = client.post("/games", json=_world()).json()["game_id"]
    fake_llm.character_replies["Layla"] = llm.LLMReply(content=(
        '[do]She pulls her cloak tighter, as if shielding herself from a chill.[mark_moment[/do]'
        '[say]"Enough questions."[/say][admit_trait: quietly defiant]'))
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "text": "And then?", "target": "Layla"}]}).json()
    prof = _profile(client, gid, "Layla")
    assert any("quietly defiant" in t["text"] for t in prof["traits"])
    act = next(b for b in d["beats"] if b["kind"] == "action" and b["speaker_name"] == "Layla")
    assert act["text"].endswith("from a chill.")
    assert not any("mark_moment" in b["text"] or "admit_trait" in b["text"] for b in d["beats"])


def test_brace_marks_with_toolname_keys_apply_too():
    """{share_past: "..."} - the brace form keyed by the TOOL name instead of
    piece/trait/event - lands on the same tools."""
    from app.engine import parsing
    cleaned, marks = parsing.extract_memory_marks(
        'She nods. {share_past: "Ran the high passes alone"} {mark_moment: a quiet pact}')
    assert ("share_past", {"piece": "Ran the high passes alone"}) in marks
    assert ("mark_moment", {"event": "a quiet pact"}) in marks
    assert cleaned == "She nods."


def test_comment_debris_and_dangling_call_fragments_die(client, fake_llm):
    """Live (the very reply that proved the memory tools): the dialogue ended
    '...stone now.\\n*/\\n[admit_trait' - a real call AND its half-written text twin."""
    gid = client.post("/games", json=_world()).json()["game_id"]
    fake_llm.character_replies["Layla"] = llm.LLMReply(content=(
        '[say]"And the memory of a brother who is part of the stone now.\n'
        '*/\n[admit_trait[/say]'))
    d = client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "text": "Go on.", "target": "Layla"}]}).json()
    line = next(b for b in d["beats"] if b["kind"] == "dialogue")
    assert line["text"].endswith("part of the stone now.")
    assert "*/" not in line["text"] and "[admit_trait" not in line["text"]
