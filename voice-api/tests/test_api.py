"""End-to-end tests through the real HTTP routes to the audio side effects.

These drive the actual FastAPI app (model loaded) and assert on decoded WAV
output, the SPECS contract shape, emotion handling, the character flow, and
error paths. Skipped automatically when the Kokoro model assets are absent."""
from __future__ import annotations

import io

import soundfile as sf

import config


def _decode(client, audio_url: str):
    r = client.get(audio_url)
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    data, sr = sf.read(io.BytesIO(r.content), dtype="float32")
    return data, sr


def test_health_reports_voices(client):
    j = client.get("/health").json()
    assert j["status"] == "ok"
    assert j["voices"] > 0
    assert j["sample_rate"] == config.SAMPLE_RATE


def test_voices_catalog_is_english_by_default(client):
    voices = client.get("/voices").json()["voices"]
    assert voices
    assert all(v["voice_id"][:3] in ("af_", "am_", "bf_", "bm_") for v in voices)
    assert len(client.get("/voices?all=true").json()["voices"]) >= len(voices)


def test_speak_contract_returns_audio_url_and_real_audio(client):
    # The SPECS contract: POST /voice/speak {text, voice_id} -> {audio_url}
    j = client.post("/voice/speak", json={"text": "You shall not pass!", "voice_id": "af_heart"}).json()
    assert "audio_url" in j and j["audio_url"].startswith("/audio/")
    data, sr = _decode(client, j["audio_url"])
    assert sr == config.SAMPLE_RATE
    assert len(data) > sr * 0.3  # at least ~0.3s of audio


def test_speak_base64_format(client):
    j = client.post("/voice/speak", json={"text": "Base64 please.", "voice_id": "am_adam", "format": "base64"}).json()
    assert "audio_base64" in j and "audio_url" not in j
    import base64
    raw = base64.b64decode(j["audio_base64"])
    data, sr = sf.read(io.BytesIO(raw), dtype="float32")
    assert sr == config.SAMPLE_RATE and len(data) > 0


def test_emotion_tags_change_output_length(client):
    plain = client.post("/voice/speak", json={"text": "You think you can win?", "voice_id": "bm_george"}).json()
    tagged = client.post("/voice/speak", json={
        "text": "[angry] You think you can win? [laugh] Pathetic.", "voice_id": "bm_george"}).json()
    d_plain, _ = _decode(client, plain["audio_url"])
    d_tagged, _ = _decode(client, tagged["audio_url"])
    # the tagged line has an extra clause + a spliced laugh, so it must be longer
    assert len(d_tagged) > len(d_plain)


def test_blended_voice_synthesizes(client):
    j = client.post("/voice/speak", json={"text": "A blended voice.", "voice_id": "af_heart:0.6,am_adam:0.4"}).json()
    data, sr = _decode(client, j["audio_url"])
    assert len(data) > 0


def test_identical_request_is_cached_to_same_url(client):
    body = {"text": "Cache me.", "voice_id": "af_sarah"}
    a = client.post("/voice/speak", json=body).json()["audio_url"]
    b = client.post("/voice/speak", json=body).json()["audio_url"]
    assert a == b


def test_assign_voice_endpoint(client):
    j = client.post("/voice/assign", json={"name": "Old Wizard", "description": "an old gravelly wizard"}).json()
    assert j["voice_id"][:3] in ("af_", "am_", "bf_", "bm_")
    assert j["speed"] <= 1.0


def test_character_flow_create_retrieve_speak(client):
    created = client.post("/characters", json={
        "id": "npc-grim", "name": "Grimgar", "description": "a deep-voiced ogre warrior"}).json()
    assert created["id"] == "npc-grim"
    assert created["voice_id"]
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
        "id": "npc-fixed", "name": "Lady", "voice_id": "bf_emma", "base_emotion": "calm"}).json()
    assert created["voice_id"] == "bf_emma"
    client.delete("/characters/npc-fixed")


def test_streaming_endpoint_yields_wav(client):
    with client.stream("POST", "/voice/stream", json={"text": "Streaming hello there.", "voice_id": "af_heart"}) as s:
        assert s.status_code == 200
        chunks = list(s.iter_bytes())
    body = b"".join(chunks)
    assert body[:4] == b"RIFF" and b"WAVE" in body[:16]
    assert len(body) > 44  # header + some PCM


def test_voice_consistent_under_alternating_speakers(client):
    # Two characters speaking in turns (the real turn-loop pattern). Each one's audio
    # must be byte-identical on every turn regardless of who spoke in between, and the
    # two must differ. base64 forces a real re-render (no file cache) each call.
    import base64, hashlib
    client.post("/characters", json={"id": "alt-a", "name": "Aria", "description": "a young female bard"})
    client.post("/characters", json={"id": "alt-b", "name": "Borin", "description": "a gruff old male dwarf"})
    lines = {"alt-a": "[happy] Onward, friend! [laugh]", "alt-b": "[angry] Bah! [sigh] Fine."}

    def render(cid):
        r = client.post(f"/characters/{cid}/speak", json={"text": lines[cid], "format": "base64"}).json()
        return hashlib.sha256(base64.b64decode(r["audio_base64"])).hexdigest()

    seq = ["alt-a", "alt-b", "alt-a", "alt-b", "alt-b", "alt-a"]
    seen: dict[str, set] = {"alt-a": set(), "alt-b": set()}
    for cid in seq:
        seen[cid].add(render(cid))
    assert len(seen["alt-a"]) == 1  # stable across alternation
    assert len(seen["alt-b"]) == 1
    assert seen["alt-a"] != seen["alt-b"]  # distinct voices
    client.delete("/characters/alt-a")
    client.delete("/characters/alt-b")


def test_recreating_character_keeps_voice(client):
    # Idempotency through the real API: re-POSTing an existing id (even with a changed
    # description) must not reshuffle the established voice.
    first = client.post("/characters", json={"id": "idem", "name": "X", "description": "a young female rogue"}).json()
    again = client.post("/characters", json={"id": "idem", "name": "X", "description": "now an old male wizard"}).json()
    assert again["voice_id"] == first["voice_id"]
    client.delete("/characters/idem")


def test_errors(client):
    assert client.post("/voice/speak", json={"text": "hi", "voice_id": "zz_nope"}).status_code == 400
    assert client.post("/voice/speak", json={"text": "", "voice_id": "af_heart"}).status_code == 422
    assert client.post("/characters/ghost/speak", json={"text": "boo"}).status_code == 404
    assert client.get("/characters/ghost").status_code == 404
    assert client.get("/audio/../etc/passwd").status_code in (400, 404)
