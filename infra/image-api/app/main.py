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
import hashlib
import logging
import random
import uuid
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, Field

from . import config, workflow
from .comfy_client import ComfyClient, ComfyError, ImageRef

log = logging.getLogger("image-api")

app = FastAPI(title="gamentic image-api", version="1.0.0")

_comfy = ComfyClient(config.COMFY_URL, timeout=config.GENERATE_TIMEOUT)

# Loaded once at import; if the template is missing the container fails fast and loud.
try:
    _template = workflow.load_template(config.WORKFLOW_TEMPLATE)
except FileNotFoundError:
    _template = None

# Per-view config for the character reference set. Same descriptor + same seed across the
# three keeps them reading as one person (shared-seed consistency); the views differ by
# framing AND aspect: the face is square (1:1 avatar), the bodies are tall full-body
# (stand-up cards, head-to-toe, no crop). Sizes come from config (image-api owns them, the
# orchestrator does not dictate them). See docs/image-service.md for the method.
#
# Body framing prompts push the whole figure into frame with headroom + foot space and a
# clean/black background, so the frontend can downscale into a tall card (and cut out later).
_BODY_FRAMING = (
    "full body shot, head to toe fully visible, entire figure in frame, "
    "centered with headroom above the head and space below the feet, "
    "natural standing pose, plain solid black background"
)


class _View:
    __slots__ = ("suffix", "width", "height")

    def __init__(self, suffix: str, width: int, height: int) -> None:
        self.suffix = suffix
        self.width = width
        self.height = height


def _character_views() -> dict[str, _View]:
    """Per-view framing + size, read from config at call time so env tuning needs no rebuild."""
    return {
        "face": _View(
            "head-and-shoulders portrait, face clearly visible, looking at the camera, "
            "plain neutral background",
            config.CHAR_FACE_WIDTH,
            config.CHAR_FACE_HEIGHT,
        ),
        "body_front": _View(
            f"{_BODY_FRAMING}, front view, facing the camera",
            config.CHAR_BODY_WIDTH,
            config.CHAR_BODY_HEIGHT,
        ),
        "body_side": _View(
            f"{_BODY_FRAMING}, side profile view",
            config.CHAR_BODY_WIDTH,
            config.CHAR_BODY_HEIGHT,
        ),
    }


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    negative_prompt: str = ""
    width: int | None = None
    height: int | None = None
    seed: int | None = None
    steps: int | None = None
    # Phase 2: optional identity references (fetchable image URLs, e.g. the orchestrator's
    # persisted character front ref). When present and fetchable, the render is conditioned
    # on them so an existing character stays recognizable. Absent/unfetchable -> text-only.
    references: list[str] = Field(default_factory=list)
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
    steps: int | None = None
    # NOTE: no width/height here on purpose. Per-view sizes are owned by image-api
    # (face square, body tall) and configured via env, so one request size can't fit
    # both framings. See _character_views() / config.CHAR_*.


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


async def _prepare_references(urls: list[str]) -> list[str]:
    """Fetch each reference URL and upload it into ComfyUI; return the input filenames.

    Graceful by contract: a URL that can't be fetched or uploaded is skipped (logged),
    never raised. So a render with bad refs degrades to text-only rather than failing.
    The input filename is content-derived so the same reference reuses one upload.
    """
    filenames: list[str] = []
    for url in urls[: config.MAX_REFERENCES]:
        try:
            data = await _comfy.download(url)
            name = f"ref_{hashlib.sha1(data).hexdigest()[:16]}.png"
            filenames.append(await _comfy.upload_image(data, name))
        except Exception as exc:  # noqa: BLE001 - any failure must not break the render
            log.warning("reference skipped (%s): %s", url, exc)
    return filenames


async def _render(
    *,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    seed: int,
    steps: int,
    reference_filenames: list[str] | None = None,
) -> tuple[str, ImageRef]:
    """Build the graph, queue it on ComfyUI, wait for the image. Raises HTTPException.

    With reference_filenames, conditions the render on those uploaded images (Phase 2);
    otherwise it is plain text-to-image. Returns (prompt_id, image_ref).
    """
    if _template is None:
        raise HTTPException(
            status_code=503,
            detail=f"workflow template not found at {config.WORKFLOW_TEMPLATE}",
        )
    try:
        if reference_filenames:
            graph = workflow.build_reference_graph(
                _template,
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                seed=seed,
                steps=steps,
                reference_filenames=reference_filenames,
            )
        else:
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

    reference_filenames = await _prepare_references(req.references) if req.references else []

    prompt_id, ref = await _render(
        prompt=req.prompt,
        negative_prompt=req.negative_prompt,
        width=width,
        height=height,
        seed=seed,
        steps=steps,
        reference_filenames=reference_filenames,
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
    coherent set. Per-view framing AND aspect: face square, bodies tall full-body, sizes
    owned by image-api (config.CHAR_*). v1 consistency = shared seed + shared descriptor.
    See docs/image-service.md for the method and the planned reference-conditioned upgrade.
    """
    seed = req.seed if req.seed is not None else random.randint(0, 2**32 - 1)
    steps = req.steps or config.DEFAULT_STEPS

    urls: dict[str, str] = {}
    for view, spec in _character_views().items():
        _, ref = await _render(
            prompt=_compose(req.style, req.descriptor, spec.suffix),
            negative_prompt="",
            width=_clamp_dim(spec.width),
            height=_clamp_dim(spec.height),
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
