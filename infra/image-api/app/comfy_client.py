"""Thin async client for ComfyUI's HTTP API.

ComfyUI is headless (started with --listen, no browser). We drive it through three
stable endpoints:

  POST /prompt              queue an API-format prompt graph -> {"prompt_id": ...}
  GET  /history/{id}        poll until the graph finished -> outputs with image refs
  GET  /view?filename=...   fetch the rendered PNG bytes

The adapter never imports ComfyUI code; the only coupling is this HTTP contract.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx


class ComfyError(RuntimeError):
    """ComfyUI rejected the prompt or failed to produce an image in time."""


@dataclass
class ImageRef:
    """A rendered image as ComfyUI addresses it in its output folder."""

    filename: str
    subfolder: str
    type: str  # "output" | "temp"


class ComfyClient:
    def __init__(self, base_url: str, *, timeout: float = 300.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def queue_prompt(self, graph: dict, client_id: str) -> str:
        """Submit an API-format graph; return the prompt_id."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base_url}/prompt",
                json={"prompt": graph, "client_id": client_id},
            )
            if resp.status_code != 200:
                # ComfyUI returns a JSON body describing the node validation error.
                raise ComfyError(
                    f"ComfyUI rejected prompt ({resp.status_code}): {resp.text[:1000]}"
                )
            prompt_id = resp.json().get("prompt_id")
            if not prompt_id:
                raise ComfyError(f"ComfyUI returned no prompt_id: {resp.text[:500]}")
            return prompt_id

    async def wait_for_image(
        self, prompt_id: str, *, poll_interval: float = 0.5
    ) -> ImageRef:
        """Poll /history until the prompt completes, then return the first image ref."""
        deadline = time.monotonic() + self._timeout
        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                resp = await client.get(f"{self._base_url}/history/{prompt_id}")
                resp.raise_for_status()
                history = resp.json()
                entry = history.get(prompt_id)
                if entry is not None:
                    status = entry.get("status", {})
                    if status.get("status_str") == "error":
                        raise ComfyError(f"ComfyUI workflow errored: {status}")
                    ref = _first_image(entry.get("outputs", {}))
                    if ref is not None:
                        return ref
                    # Present in history with no images and not errored -> still finishing.
                if time.monotonic() > deadline:
                    raise ComfyError(
                        f"Timed out after {self._timeout:.0f}s waiting for prompt {prompt_id}"
                    )
                await asyncio.sleep(poll_interval)

    async def upload_image(self, data: bytes, filename: str) -> str:
        """Upload image bytes to ComfyUI's input dir; return the name LoadImage should use.

        We pass overwrite=true with a caller-chosen (content-derived) filename so repeated
        uploads of the same reference reuse one input file instead of accumulating copies.
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self._base_url}/upload/image",
                data={"type": "input", "overwrite": "true"},
                files={"image": (filename, data, "image/png")},
            )
            if resp.status_code != 200:
                raise ComfyError(
                    f"ComfyUI rejected image upload ({resp.status_code}): {resp.text[:500]}"
                )
            body = resp.json()
            name = body.get("name")
            if not name:
                raise ComfyError(f"ComfyUI upload returned no name: {resp.text[:300]}")
            subfolder = body.get("subfolder", "")
            return f"{subfolder}/{name}" if subfolder else name

    async def download(self, url: str) -> bytes:
        """GET arbitrary (e.g. orchestrator /media) URL bytes. Raises on any failure."""
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content

    async def fetch_image(self, ref: ImageRef) -> bytes:
        """Download the rendered PNG bytes from ComfyUI's /view."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(
                f"{self._base_url}/view",
                params={
                    "filename": ref.filename,
                    "subfolder": ref.subfolder,
                    "type": ref.type,
                },
            )
            resp.raise_for_status()
            return resp.content


def _first_image(outputs: dict) -> ImageRef | None:
    """Pull the first image reference out of a /history outputs block."""
    for node_output in outputs.values():
        for image in node_output.get("images", []) or []:
            if image.get("type") == "temp":
                # Skip preview/temp images; we want the saved output.
                continue
            return ImageRef(
                filename=image["filename"],
                subfolder=image.get("subfolder", ""),
                type=image.get("type", "output"),
            )
    return None
