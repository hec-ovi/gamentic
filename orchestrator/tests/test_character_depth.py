"""Character depth: traits unlock VISIBLY through play (note_trait receipts), feed back
into the character's own agent, and power the full-screen profile endpoint (traits +
shared moments + image memories), which stays spoiler-safe."""
from app import llm
from app.config import settings


def T(_tool, **args):
    return llm.ToolCall(_tool, args)


def _nar(*calls, content="..."):
    return llm.LLMReply(content=content, tool_calls=list(calls))


def _cid(client, gid, name="Mara"):
    st = client.get(f"/games/{gid}/state").json()
    return next(c["id"] for c in st["characters"] if c["name"] == name)


def test_trait_unlock_is_a_visible_receipt_and_lands_on_the_card(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("note_trait", name="Mara", trait="distrusts authority"),
                             content="Mara spits at the mention of the guard.")
    d = client.post(f"/games/{gid}/action", json={"action": "I mention the guards."}).json()
    assert any(b["kind"] == "system" and b["text"] == "Trait unlocked: Mara - distrusts authority."
               for b in d["beats"])
    mara = next(c for c in d["state"]["characters"] if c["name"] == "Mara")
    assert [t["text"] for t in mara["traits"]] == ["distrusts authority"]
    assert mara["traits"][0]["unlocked"].startswith("Day ")    # story-clock stamp


def test_legacy_snake_case_traits_read_clean(client, fake_llm, world):
    """Rows recorded before the write-side cleaner keep raw snake_case in the DB
    (live: Mirele had 'detached_seer_like_calm'); reads normalize them anyway."""
    import json
    from app import db, repo
    gid = client.post("/games", json=world).json()["game_id"]
    cid = _cid(client, gid)
    with db.get_conn() as conn:
        legacy = json.dumps([{"id": "t0", "text": "detached_seer_like_calm", "minutes": 0}])
        conn.execute("UPDATE characters SET traits=?, moments=?, origin_revealed=? WHERE id=?",
                     (legacy, legacy, legacy, cid))
    prof = client.get(f"/games/{gid}/characters/{cid}/profile").json()
    assert prof["traits"][0]["text"] == "detached seer like calm"
    assert prof["moments"][0]["text"] == "detached seer like calm"
    assert prof["origin"][0]["text"] == "detached seer like calm"
    assert "detached seer like calm" in client.get(f"/games/{gid}/state").json()["characters"][0]["traits"][0]["text"]


def test_duplicate_traits_unlock_silently_once(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("note_trait", name="Mara", trait="Distrusts authority."),
                             content="...")
    client.post(f"/games/{gid}/action", json={"action": "x"})
    fake_llm.narrator = _nar(T("note_trait", name="Mara", trait="distrusts authority"),
                             content="...")
    d = client.post(f"/games/{gid}/action", json={"action": "y"}).json()
    assert not any("Trait unlocked" in b["text"] for b in d["beats"] if b["kind"] == "system")
    mara = next(c for c in d["state"]["characters"] if c["name"] == "Mara")
    assert len(mara["traits"]) == 1                            # normalized dedupe


def test_unlocked_traits_feed_the_character_agent(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    fake_llm.narrator = _nar(T("note_trait", name="Mara", trait="sentimental about her ship"),
                             content="...")
    client.post(f"/games/{gid}/action", json={"action": "x"})
    fake_llm.narrator = _nar(T("cue_character", name="Mara"), content="Mara looks over.")
    client.post(f"/games/{gid}/action", json={"action": "Mara, you ok?"})
    system = fake_llm.character_calls()[-1]["system"]
    assert "WHAT THE STORY HAS REVEALED ABOUT YOU" in system
    assert "sentimental about her ship" in system


def test_profile_collects_traits_pivotal_moments_and_stays_spoiler_safe(client, fake_llm, world):
    # an explicit public description: with none given, the persona's FIRST sentence now
    # intentionally becomes the public line (the live blank-card fix), which would make
    # this fixture's one-sentence persona public by design
    world = dict(world)
    world["characters"] = [dict(world["characters"][0], description="A dwarven scout.")]
    gid = client.post("/games", json=world).json()["game_id"]
    cid = _cid(client, gid)
    # a trait, a pivotal moment (narrator-noted), and a whisper that must NOT appear
    fake_llm.narrator = _nar(T("note_trait", name="Mara", trait="blunt"),
                             T("note_moment", name="Mara", event="Chose to trust the player with the route"),
                             T("cue_character", name="Mara"), content="Mara shrugs.")
    fake_llm.character_replies = {"Mara": llm.LLMReply(content='[say]"Out with it."[/say]')}
    client.post(f"/games/{gid}/action", json={"action": "Mara, can I trust you?"})
    client.post(f"/games/{gid}/action", json={"segments": [
        {"type": "whisper", "text": "The tunnel. Tonight.", "target": "Mara"}]})

    prof = client.get(f"/games/{gid}/characters/{cid}/profile").json()
    assert [t["text"] for t in prof["traits"]] == ["blunt"]
    texts = [m["text"] for m in prof["moments"]]
    assert texts == ["Chose to trust the player with the route"]   # curated pivots only
    assert prof["moments"][0]["when"].startswith("Day ")
    blob = str(prof)
    assert "The tunnel. Tonight." not in blob                  # whispers NEVER surface
    assert "Out with it." not in blob                          # transcript never surfaces
    assert "loyal but blunt" not in blob                       # persona text stays hidden
    assert "secret tunnel behind the altar" not in blob        # knowledge stays hidden


def test_profile_memories_only_include_images_that_name_them(client, fake_llm, world,
                                                             monkeypatch, tmp_path):
    """Owner spec: a memory belongs to a character only when they are a MAIN PART of
    that moment - merely being in the same place gave everyone identical galleries."""
    from app import media
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setattr(settings, "GAMES_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "IMAGE_ITEMS", False)
    monkeypatch.setattr(media, "generate_character_images", lambda d, style="", seed=None: None)
    monkeypatch.setattr(media, "generate_scene_image",
                        lambda prompt, seed=None, width=None, height=None, references=None:
                        {"image_url": "/image/file?filename=m"})
    monkeypatch.setattr(media, "fetch_image_bytes", lambda url: b"PNG")
    gid = client.post("/games", json=world).json()["game_id"]
    cid = _cid(client, gid)
    client.post(f"/games/{gid}/view", json={"focus": ""})          # anonymous scene shot
    client.post(f"/games/{gid}/view", json={"focus": "at Mara"})   # HER moment
    prof = client.get(f"/games/{gid}/characters/{cid}/profile").json()
    assert len(prof["memories"]) == 1                              # only the one naming her
    assert "mara" in prof["memories"][0]["caption"].lower()
    assert prof["memories"][0]["caption"].count(".") >= 2          # a real concept, not a label


def test_profile_404s(client, fake_llm, world):
    gid = client.post("/games", json=world).json()["game_id"]
    assert client.get(f"/games/{gid}/characters/nope/profile").status_code == 404
    assert client.get("/games/nope/characters/x/profile").status_code == 404
