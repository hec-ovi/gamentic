"""End-to-end tests for the image-api adapter.

These drive the real FastAPI routes through Starlette's TestClient against the REAL
shipped Klein workflow, mocking ComfyUI at the network layer with respx (the httpx
analogue of MSW). No ComfyUI, no GPU, no internal-function mocking.
"""

import base64
import json

import httpx
import respx
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

COMFY = "http://comfy.test:8188"
PNG_BYTES = b"\x89PNG\r\n\x1a\n-fake-png-body-"


def _history_ok(prompt_id: str) -> dict:
    return {
        prompt_id: {
            "status": {"status_str": "success", "completed": True},
            "outputs": {
                "13": {
                    "images": [
                        {"filename": "gamentic_00001_.png", "subfolder": "", "type": "output"}
                    ]
                }
            },
        }
    }


def _mock_comfy(respx_mock, prompt_id: str = "pid-123") -> None:
    respx_mock.post(f"{COMFY}/prompt").mock(
        return_value=httpx.Response(200, json={"prompt_id": prompt_id})
    )
    respx_mock.get(f"{COMFY}/history/{prompt_id}").mock(
        return_value=httpx.Response(200, json=_history_ok(prompt_id))
    )
    respx_mock.get(f"{COMFY}/view").mock(
        return_value=httpx.Response(200, content=PNG_BYTES, headers={"content-type": "image/png"})
    )


def _node_by_title(graph: dict, title: str) -> dict:
    for node in graph.values():
        if node.get("_meta", {}).get("title") == title:
            return node
    raise AssertionError(f"no node titled {title!r} in sent graph")


@respx.mock
def test_generate_returns_image_url():
    _mock_comfy(respx.mock)
    resp = client.post("/image/generate", json={"prompt": "a neon dragon over a city"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["prompt_id"] == "pid-123"
    assert body["image_url"].startswith("/image/file?filename=gamentic_00001_.png")
    assert body["width"] == 1024 and body["height"] == 1024
    assert isinstance(body["seed"], int)
    assert body["image_b64"] is None


@respx.mock
def test_generate_patches_real_klein_graph():
    route = respx.post(f"{COMFY}/prompt").mock(
        return_value=httpx.Response(200, json={"prompt_id": "pid-9"})
    )
    respx.get(f"{COMFY}/history/pid-9").mock(
        return_value=httpx.Response(200, json=_history_ok("pid-9"))
    )

    resp = client.post(
        "/image/generate",
        json={"prompt": "haunted lighthouse", "width": 768, "height": 512, "seed": 42, "steps": 6},
    )
    assert resp.status_code == 200, resp.text

    sent = json.loads(route.calls.last.request.content)["prompt"]
    # Prompt lands on the positive encoder; seed on RandomNoise; steps + both
    # width/height carriers (latent + scheduler) are patched and agree.
    assert _node_by_title(sent, "Positive Prompt")["inputs"]["text"] == "haunted lighthouse"
    assert _node_by_title(sent, "Noise")["inputs"]["noise_seed"] == 42
    assert _node_by_title(sent, "Scheduler")["inputs"]["steps"] == 6
    assert _node_by_title(sent, "Latent Image")["inputs"]["width"] == 768
    assert _node_by_title(sent, "Latent Image")["inputs"]["height"] == 512
    assert _node_by_title(sent, "Scheduler")["inputs"]["width"] == 768
    assert _node_by_title(sent, "Scheduler")["inputs"]["height"] == 512


@respx.mock
def test_dimensions_clamped_and_snapped_to_multiple_of_16():
    route = respx.post(f"{COMFY}/prompt").mock(
        return_value=httpx.Response(200, json={"prompt_id": "pid-c"})
    )
    respx.get(f"{COMFY}/history/pid-c").mock(
        return_value=httpx.Response(200, json=_history_ok("pid-c"))
    )

    resp = client.post("/image/generate", json={"prompt": "x", "width": 99999, "height": 100})
    assert resp.status_code == 200
    body = resp.json()
    assert body["width"] == 1536  # clamped to MAX_DIM
    assert body["height"] == 256  # floored to 256
    sent = json.loads(route.calls.last.request.content)["prompt"]
    assert _node_by_title(sent, "Latent Image")["inputs"]["width"] == 1536


@respx.mock
def test_generate_b64_returns_decodable_png():
    _mock_comfy(respx.mock)
    resp = client.post("/image/generate", json={"prompt": "tiny golem", "response": "b64"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["image_url"] is None
    assert base64.b64decode(body["image_b64"]) == PNG_BYTES


@respx.mock
def test_image_file_proxies_png_bytes():
    respx.get(f"{COMFY}/view").mock(
        return_value=httpx.Response(200, content=PNG_BYTES, headers={"content-type": "image/png"})
    )
    resp = client.get("/image/file", params={"filename": "gamentic_00001_.png"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content == PNG_BYTES


@respx.mock
def test_comfy_rejection_surfaces_as_502():
    respx.post(f"{COMFY}/prompt").mock(
        return_value=httpx.Response(400, text="node validation failed")
    )
    resp = client.post("/image/generate", json={"prompt": "boom"})
    assert resp.status_code == 502
    assert "node validation failed" in resp.json()["detail"]


def test_missing_prompt_is_422():
    resp = client.post("/image/generate", json={})
    assert resp.status_code == 422


def test_health_reports_template_loaded():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["template_loaded"] is True


@respx.mock
def test_character_set_returns_three_views_with_shared_seed():
    route = respx.post(f"{COMFY}/prompt").mock(
        return_value=httpx.Response(200, json={"prompt_id": "pid-x"})
    )
    respx.get(f"{COMFY}/history/pid-x").mock(
        return_value=httpx.Response(200, json=_history_ok("pid-x"))
    )

    resp = client.post(
        "/image/character",
        json={"descriptor": "a grizzled dwarf with a braided red beard", "style": "oil painting", "seed": 7},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["seed"] == 7
    assert body["face_url"].startswith("/image/file?")
    assert body["body_front_url"].startswith("/image/file?")
    assert body["body_side_url"].startswith("/image/file?")

    # Three generations, one per view; all share the seed and the style+descriptor prefix,
    # differing only by the per-view framing suffix.
    prompts = []
    seeds = set()
    for call in route.calls:
        graph = json.loads(call.request.content)["prompt"]
        prompts.append(_node_by_title(graph, "Positive Prompt")["inputs"]["text"])
        seeds.add(_node_by_title(graph, "Noise")["inputs"]["noise_seed"])
    assert len(prompts) == 3
    assert seeds == {7}
    assert all(p.startswith("oil painting, a grizzled dwarf with a braided red beard") for p in prompts)
    assert any("front view" in p for p in prompts)
    assert any("side profile" in p for p in prompts)
    assert any("portrait" in p for p in prompts)


def test_character_requires_descriptor():
    resp = client.post("/image/character", json={"style": "noir"})
    assert resp.status_code == 422
