"""image-api: a thin REST adapter in front of ComfyUI.

Implements the gamentic image contract (docs/SPECS.md section 3):

  POST /image/generate  {prompt, negative_prompt?, width?, height?, seed?, steps?}
                        -> {image_url, width, height, seed, prompt_id}
  GET  /image/file      proxies the rendered PNG back from ComfyUI

The orchestrator/frontend only ever talk to this origin; how images are produced
(ComfyUI graph, FLUX.2 Klein, LoRAs) stays behind this contract.
"""

from __future__ import annotations

import base64
import random
import uuid
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, Field

from . import config, workflow
from .comfy_client import ComfyClient, ComfyError, ImageRef

app = FastAPI(title="gamentic image-api", version="1.0.0")

_comfy = ComfyClient(config.COMFY_URL, timeout=config.GENERATE_TIMEOUT)

# Loaded once at import; if the template is missing the container fails fast and loud.
try:
    _template = workflow.load_template(config.WORKFLOW_TEMPLATE)
except FileNotFoundError:
    _template = None

# Per-view prompt suffixes for the character reference set. Same descriptor + same seed
# across the three keeps them reading as one person (shared-seed consistency); the views
# differ only by framing. See docs/image-service.md for the consistency method.
CHARACTER_VIEWS: dict[str, str] = {
    "face": "head-and-shoulders portrait, face clearly visible, looking at the camera, neutral background",
    "body_front": "full body, standing, front view, facing the camera, whole figure in frame, neutral background",
    "body_side": "full body, standing, side profile view, whole figure in frame, neutral background",
}


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    negative_prompt: str = ""
    width: int | None = None
    height: int | None = None
    seed: int | None = None
    steps: int | None = None
    response: Literal["url", "b64"] = "url"


class GenerateResponse(BaseModel):
    image_url: str | None = None
    image_b64: str | None = None
    width: int
    height: int
    seed: int
    prompt_id: str


class CharacterRequest(BaseModel):
    descriptor: str = Field(..., min_length=1)  # full appearance description
    style: str = ""  # world art style/theme, prepended to every view
    seed: int | None = None
    width: int | None = None
    height: int | None = None
    steps: int | None = None


class CharacterResponse(BaseModel):
    face_url: str
    body_front_url: str
    body_side_url: str
    seed: int


def _clamp_dim(value: int) -> int:
    # ComfyUI/FLUX want multiples of 16; round down and clamp to the budget ceiling.
    value = max(256, min(config.MAX_DIM, value))
    return value - (value % 16)


def _image_url(ref: ImageRef) -> str:
    return (
        f"/image/file?filename={ref.filename}"
        f"&subfolder={ref.subfolder}&type={ref.type}"
    )


def _compose(style: str, descriptor: str, view_suffix: str = "") -> str:
    parts = [p for p in (style.strip(), descriptor.strip(), view_suffix) if p]
    return ", ".join(parts)


async def _render(
    *, prompt: str, negative_prompt: str, width: int, height: int, seed: int, steps: int
) -> tuple[str, ImageRef]:
    """Build the graph, queue it on ComfyUI, wait for the image. Raises HTTPException.

    Returns (prompt_id, image_ref).
    """
    if _template is None:
        raise HTTPException(
            status_code=503,
            detail=f"workflow template not found at {config.WORKFLOW_TEMPLATE}",
        )
    try:
        graph = workflow.build_graph(
            _template,
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            seed=seed,
            steps=steps,
        )
    except workflow.WorkflowError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    try:
        client_id = uuid.uuid4().hex
        prompt_id = await _comfy.queue_prompt(graph, client_id)
        ref = await _comfy.wait_for_image(prompt_id)
        return prompt_id, ref
    except ComfyError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "comfy_url": config.COMFY_URL, "template_loaded": _template is not None}


@app.post("/image/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest) -> GenerateResponse:
    width = _clamp_dim(req.width or config.DEFAULT_WIDTH)
    height = _clamp_dim(req.height or config.DEFAULT_HEIGHT)
    seed = req.seed if req.seed is not None else random.randint(0, 2**32 - 1)
    steps = req.steps or config.DEFAULT_STEPS

    prompt_id, ref = await _render(
        prompt=req.prompt,
        negative_prompt=req.negative_prompt,
        width=width,
        height=height,
        seed=seed,
        steps=steps,
    )

    if req.response == "b64":
        data = await _comfy.fetch_image(ref)
        return GenerateResponse(
            image_b64=base64.b64encode(data).decode("ascii"),
            width=width,
            height=height,
            seed=seed,
            prompt_id=prompt_id,
        )

    return GenerateResponse(
        image_url=_image_url(ref), width=width, height=height, seed=seed, prompt_id=prompt_id
    )


@app.post("/image/character", response_model=CharacterResponse)
async def character(req: CharacterRequest) -> CharacterResponse:
    """Generate a character's 3-image reference set (face, body front, body side) as a
    coherent set. v1 consistency = shared seed + shared descriptor, per-view framing only.
    See docs/image-service.md for the method and the planned reference-conditioned upgrade.
    """
    width = _clamp_dim(req.width or config.DEFAULT_WIDTH)
    height = _clamp_dim(req.height or config.DEFAULT_HEIGHT)
    seed = req.seed if req.seed is not None else random.randint(0, 2**32 - 1)
    steps = req.steps or config.DEFAULT_STEPS

    urls: dict[str, str] = {}
    for view, suffix in CHARACTER_VIEWS.items():
        _, ref = await _render(
            prompt=_compose(req.style, req.descriptor, suffix),
            negative_prompt="",
            width=width,
            height=height,
            seed=seed,  # shared across views for same-person consistency
            steps=steps,
        )
        urls[view] = _image_url(ref)

    return CharacterResponse(
        face_url=urls["face"],
        body_front_url=urls["body_front"],
        body_side_url=urls["body_side"],
        seed=seed,
    )


@app.get("/image/file")
async def image_file(
    filename: str = Query(...),
    subfolder: str = Query(""),
    type: str = Query("output"),
) -> Response:
    try:
        data = await _comfy.fetch_image(
            ImageRef(filename=filename, subfolder=subfolder, type=type)
        )
    except ComfyError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=data, media_type="image/png")
