"""Gamentic voice service (workstream E).

Kokoro-82M on CPU. Honors the SPECS contract ``POST /voice/speak {text, voice_id}
-> {audio_url}`` and adds a thin character layer (assign a voice at creation,
retrieve it, speak as that character) plus a low-latency streaming endpoint.

Emotion is approximated from inline ``[tag]`` markers (see emotion.py); the engine
runs faster-than-realtime on CPU so the iGPU stays free for the LLM and images.
"""
from __future__ import annotations

import base64
import struct
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

import config
import synth
import voices as voicelib
from characters import Registry

_engine: synth.KokoroEngine | None = None
_registry: Registry | None = None


def engine() -> synth.KokoroEngine:
    assert _engine is not None, "engine not initialised"
    return _engine


def registry() -> Registry:
    assert _registry is not None, "registry not initialised"
    return _registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine, _registry
    config.ensure_dirs()
    _engine = synth.KokoroEngine()
    _registry = Registry()
    yield


app = FastAPI(title="Gamentic Voice API", version="1.0", lifespan=lifespan)


# --- schemas --------------------------------------------------------------

class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1)
    voice_id: str = config.DEFAULT_VOICE
    speed: float = Field(1.0, gt=0.1, le=3.0)
    emotion: str = "neutral"  # base tone; inline [tags] override per-span
    format: str = "url"        # "url" -> {audio_url} | "base64" -> {audio_base64}


class AssignRequest(BaseModel):
    name: str = ""
    seed: str = ""
    description: str = ""
    gender: str | None = None
    accent: str | None = None
    exclude: list[str] = []


class CharacterRequest(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""
    gender: str | None = None
    accent: str | None = None
    voice_id: str | None = None
    speed: float | None = Field(None, gt=0.1, le=3.0)
    base_emotion: str = "neutral"


class CharacterSpeakRequest(BaseModel):
    text: str = Field(..., min_length=1)
    emotion: str | None = None  # override the character's base emotion for this line
    speed: float | None = Field(None, gt=0.1, le=3.0)
    format: str = "url"


# --- core synth + serving -------------------------------------------------

def _synth_to_payload(text: str, voice_id: str, speed: float, base_emotion: str, fmt: str) -> dict:
    try:
        wav = engine().render(text, voice_id, speed=speed, base_emotion=base_emotion)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if wav.size == 0:
        raise HTTPException(status_code=400, detail="nothing to speak after tag parsing")
    dur = synth.duration_s(wav)
    if fmt == "base64":
        return {"audio_base64": base64.b64encode(synth.wav_bytes(wav)).decode("ascii"),
                "duration_s": dur, "sample_rate": config.SAMPLE_RATE}
    name = synth.content_hash(text, voice_id, f"{speed:.3f}", base_emotion) + ".wav"
    path = config.AUDIO_DIR / name
    if not path.exists():
        synth.write_wav(wav, name)
    return {"audio_url": f"/audio/{name}", "duration_s": dur, "sample_rate": config.SAMPLE_RATE}


@app.get("/health")
def health() -> dict:
    ok = _engine is not None
    return {"status": "ok" if ok else "loading",
            "voices": len(engine().available_voices()) if ok else 0,
            "sample_rate": config.SAMPLE_RATE}


@app.get("/voices")
def list_voices(all: bool = False) -> dict:
    infos = voicelib.catalog(engine().available_voices(), english_only=not all)
    return {"voices": [vi.__dict__ for vi in infos]}


@app.post("/voice/assign")
def assign(req: AssignRequest) -> dict:
    key = req.seed or req.name
    if not key:
        raise HTTPException(status_code=400, detail="name or seed required")
    voice_id, speed = voicelib.assign_voice(
        engine().available_voices(), key=key, description=req.description,
        gender=req.gender, accent=req.accent, exclude=req.exclude)
    return {"voice_id": voice_id, "speed": speed}


@app.post("/voice/speak")
def speak(req: SpeakRequest) -> dict:
    return _synth_to_payload(req.text, req.voice_id, req.speed, req.emotion, req.format)


@app.post("/voice/stream")
async def stream(req: SpeakRequest):
    try:
        voicelib.parse_voice_id(req.voice_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    async def gen():
        yield _wav_header(config.SAMPLE_RATE)
        async for chunk in engine().render_stream(
            req.text, req.voice_id, speed=req.speed, base_emotion=req.emotion):
            if chunk.size:
                yield _pcm16(chunk)

    return StreamingResponse(gen(), media_type="audio/wav")


@app.get("/audio/{name}")
def get_audio(name: str):
    if "/" in name or ".." in name:
        raise HTTPException(status_code=400, detail="bad name")
    path = config.AUDIO_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(str(path), media_type="audio/wav")


# --- character layer ------------------------------------------------------

@app.post("/characters")
def create_character(req: CharacterRequest) -> dict:
    try:
        if req.voice_id is not None:
            voicelib.parse_voice_id(req.voice_id)
        char = registry().upsert(
            available_voices=engine().available_voices(),
            char_id=req.id, name=req.name, description=req.description,
            gender=req.gender, accent=req.accent, voice_id=req.voice_id,
            speed=req.speed, base_emotion=req.base_emotion)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return char.__dict__


@app.get("/characters")
def list_characters() -> dict:
    return {"characters": [c.__dict__ for c in registry().list()]}


@app.get("/characters/{char_id}")
def get_character(char_id: str) -> dict:
    char = registry().get(char_id)
    if not char:
        raise HTTPException(status_code=404, detail="unknown character")
    return char.__dict__


@app.delete("/characters/{char_id}")
def delete_character(char_id: str) -> dict:
    if not registry().delete(char_id):
        raise HTTPException(status_code=404, detail="unknown character")
    return {"deleted": char_id}


@app.post("/characters/{char_id}/speak")
def character_speak(char_id: str, req: CharacterSpeakRequest) -> dict:
    char = registry().get(char_id)
    if not char:
        raise HTTPException(status_code=404, detail="unknown character")
    return _synth_to_payload(
        req.text, char.voice_id,
        req.speed if req.speed is not None else char.speed,
        req.emotion or char.base_emotion, req.format)


# --- streaming WAV helpers ------------------------------------------------

def _wav_header(sr: int, channels: int = 1, bits: int = 16) -> bytes:
    """RIFF/WAVE header with streaming-convention placeholder sizes (0xFFFFFFFF)."""
    byte_rate = sr * channels * bits // 8
    block_align = channels * bits // 8
    return (b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, sr, byte_rate, block_align, bits)
            + b"data" + struct.pack("<I", 0xFFFFFFFF))


def _pcm16(wav: np.ndarray) -> bytes:
    return (np.clip(wav, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
