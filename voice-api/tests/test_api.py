"""End-to-end tests through the real HTTP routes to the audio side effects.

These drive the actual FastAPI app (real SNAC decoder) against the fake
llama.cpp upstream from conftest, and assert on decoded WAV output, the SPECS
contract shape, tag translation as actually sent upstream, the character flow,
and error paths."""
from __future__ import annotations

import base64
import io

import soundfile as sf

import config
from conftest import tokenized_contents


def _decode(client, audio_url: str):
    r = client.get(audio_url)
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    data, sr = sf.read(io.BytesIO(r.content), dtype="float32")
    return data, sr


def test_health_reports_upstream_and_voices(client):
    j = client.get("/health").json()
    assert j["status"] == "ok"
    assert j["upstream"] is True
    assert j["voices"] > 0
    assert j["sample_rate"] == config.SAMPLE_RATE


def test_voices_catalog_lists_presets(client):
    voices = client.get("/voices").json()["voices"]
    ids = {v["voice_id"] for v in voices}
    assert {"narrator", "elder_male", "young_female", "villain_male"} <= ids
    assert all(v["gender"] in ("male", "female") and v["description"] for v in voices)


def test_speak_contract_returns_audio_url_and_real_audio(client):
    # The SPECS contract: POST /voice/speak {text, voice_id} -> {audio_url}
    j = client.post("/voice/speak", json={"text": "You shall not pass!", "voice_id": "narrator"}).json()
    assert "audio_url" in j and j["audio_url"].startswith("/audio/")
    data, sr = _decode(client, j["audio_url"])
    assert sr == config.SAMPLE_RATE
    assert len(data) > sr * 0.3  # at least ~0.3s of audio


def test_speak_base64_format(client):
    j = client.post("/voice/speak", json={"text": "Base64 please.", "voice_id": "adult_male", "format": "base64"}).json()
    assert "audio_base64" in j and "audio_url" not in j
    raw = base64.b64decode(j["audio_base64"])
    data, sr = sf.read(io.BytesIO(raw), dtype="float32")
    assert sr == config.SAMPLE_RATE and len(data) > 0


def test_emotion_tags_translate_to_maya_tags_upstream(client, upstream):
    client.post("/voice/speak", json={
        "text": "[angry] You think you can win? [laugh] Pathetic.", "voice_id": "villain_male"})
    sent = tokenized_contents(upstream)[-1]
    assert "<angry>" in sent and "<laugh>" in sent
    assert "[" not in sent          # no game-format tags leak to the model
    assert "</" not in sent         # closing tags would be spoken as words


def test_alias_and_unknown_tags(client, upstream):
    client.post("/voice/speak", json={
        "text": "[shout] Charge! [sob] We lost. [flibber] Onward.", "voice_id": "narrator"})
    sent = tokenized_contents(upstream)[-1]
    assert "<scream>" in sent and "<cry>" in sent
    assert "flibber" not in sent    # unknown tags are dropped, never spoken


def test_base_emotion_leads_the_line(client, upstream):
    client.post("/voice/speak", json={
        "text": "Stay close to me.", "voice_id": "adult_female", "emotion": "whisper"})
    sent = tokenized_contents(upstream)[-1]
    assert "<whisper>" in sent.split("Stay")[0]


def test_preset_voice_resolves_to_description(client, upstream):
    client.post("/voice/speak", json={"text": "Hmph.", "voice_id": "elder_male"})
    sent = tokenized_contents(upstream)[-1]
    assert 'description="Male voice, 70 years old' in sent


def test_freeform_voice_description_passes_through(client, upstream):
    desc = "Female voice, 30s, soft breathy timbre, calm and secretive"
    client.post("/voice/speak", json={"text": "Quiet now.", "voice_id": desc})
    assert f'description="{desc}"' in tokenized_contents(upstream)[-1]


def test_speed_folds_into_pacing_words(client, upstream):
    client.post("/voice/speak", json={"text": "So slow.", "voice_id": "narrator", "speed": 0.5})
    client.post("/voice/speak", json={"text": "So fast.", "voice_id": "narrator", "speed": 1.5})
    slow, fast = tokenized_contents(upstream)[-2:]
    assert "slow unhurried pacing" in slow
    assert "fast urgent pacing" in fast


def test_identical_request_is_cached_to_same_url(client):
    body = {"text": "Cache me.", "voice_id": "narrator"}
    a = client.post("/voice/speak", json=body).json()["audio_url"]
    b = client.post("/voice/speak", json=body).json()["audio_url"]
    assert a == b


def test_assign_voice_endpoint(client):
    j = client.post("/voice/assign", json={"name": "Old Wizard", "description": "an old gravelly wizard"}).json()
    assert j["voice_id"].startswith("Male voice, 70 years old")
    assert "pitch" in j["voice_id"] and "tone" in j["voice_id"]


def test_character_flow_create_retrieve_speak(client):
    created = client.post("/characters", json={
        "id": "npc-grim", "name": "Grimgar", "description": "a deep-voiced ogre warrior"}).json()
    assert created["id"] == "npc-grim"
    assert created["voice_id"].startswith("Male voice")
    voice = created["voice_id"]

    got = client.get("/characters/npc-grim").json()
    assert got["voice_id"] == voice  # retrieve the assigned voice

    spoken = client.post("/characters/npc-grim/speak", json={"text": "[shout] Who dares enter?"}).json()
    data, sr = _decode(client, spoken["audio_url"])
    assert sr == config.SAMPLE_RATE and len(data) > 0

    assert "npc-grim" in [c["id"] for c in client.get("/characters").json()["characters"]]
    assert client.delete("/characters/npc-grim").json()["deleted"] == "npc-grim"
    assert client.get("/characters/npc-grim").status_code == 404


def test_character_with_explicit_voice(client):
    created = client.post("/characters", json={
        "id": "npc-fixed", "name": "Lady", "voice_id": "elder_female", "base_emotion": "calm"}).json()
    assert created["voice_id"] == "elder_female"
    client.delete("/characters/npc-fixed")


def test_streaming_endpoint_yields_wav(client):
    with client.stream("POST", "/voice/stream", json={"text": "Streaming hello there.", "voice_id": "narrator"}) as s:
        assert s.status_code == 200
        chunks = list(s.iter_bytes())
    body = b"".join(chunks)
    assert body[:4] == b"RIFF" and b"WAVE" in body[:16]
    # header + PCM for all frames after the warmup frame (fake upstream: >= 12 frames)
    assert len(body) > 44 + 10 * 2048 * 2


def test_voice_consistent_under_alternating_speakers(client, upstream):
    # Two characters speaking in turns (the real turn-loop pattern). Each one's line
    # must go upstream with its own stable voice description regardless of who spoke
    # in between, and the two descriptions must differ. Audio bytes are NOT stable
    # (the SNAC vocoder injects noise; Maya1 samples), so the stable-prompt
    # invariant is the guarantee that a character keeps "their voice".
    client.post("/characters", json={"id": "alt-a", "name": "Aria", "description": "a young female bard"})
    client.post("/characters", json={"id": "alt-b", "name": "Borin", "description": "a gruff old male dwarf"})
    lines = {"alt-a": "[happy] Onward, friend! [laugh]", "alt-b": "[angry] Bah! [sigh] Fine."}

    seq = ["alt-a", "alt-b", "alt-a", "alt-b", "alt-b", "alt-a"]
    sent: dict[str, set] = {"alt-a": set(), "alt-b": set()}
    for cid in seq:
        before = len(tokenized_contents(upstream))
        r = client.post(f"/characters/{cid}/speak", json={"text": lines[cid], "format": "base64"})
        assert r.status_code == 200 and r.json()["audio_base64"]
        sent[cid].add(tokenized_contents(upstream)[before])

    assert len(sent["alt-a"]) == 1  # stable voice+line prompt across alternation
    assert len(sent["alt-b"]) == 1
    assert sent["alt-a"] != sent["alt-b"]  # distinct voice descriptions
    client.delete("/characters/alt-a")
    client.delete("/characters/alt-b")


def test_recreating_character_keeps_voice(client):
    # Idempotency through the real API: re-POSTing an existing id (even with a changed
    # description) must not reshuffle the established voice.
    first = client.post("/characters", json={"id": "idem", "name": "X", "description": "a young female rogue"}).json()
    again = client.post("/characters", json={"id": "idem", "name": "X", "description": "now an old male wizard"}).json()
    assert again["voice_id"] == first["voice_id"]
    client.delete("/characters/idem")


def test_upstream_down_returns_502(client, monkeypatch):
    import app as appmod
    monkeypatch.setattr(appmod.engine(), "_base", "http://127.0.0.1:9")  # dead port
    r = client.post("/voice/speak", json={"text": "anyone there?", "voice_id": "narrator"})
    assert r.status_code == 502


def test_errors(client):
    assert client.post("/voice/speak", json={"text": "hi", "voice_id": "zz_nope"}).status_code == 400
    assert client.post("/voice/speak", json={"text": "", "voice_id": "narrator"}).status_code == 422
    assert client.post("/voice/speak", json={"text": "[flibber]", "voice_id": "narrator"}).status_code == 400
    assert client.post("/characters/ghost/speak", json={"text": "boo"}).status_code == 404
    assert client.get("/characters/ghost").status_code == 404
    assert client.get("/audio/../etc/passwd").status_code in (400, 404)
