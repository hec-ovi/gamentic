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
    assert body["width"] == 768 and body["height"] == 768  # scene default
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


@respx.mock
def test_character_face_is_square_and_bodies_are_tall():
    """The contract's core ask: face comes back square (1:1), body views tall full-body."""
    from app import config

    route = respx.post(f"{COMFY}/prompt").mock(
        return_value=httpx.Response(200, json={"prompt_id": "pid-d"})
    )
    respx.get(f"{COMFY}/history/pid-d").mock(
        return_value=httpx.Response(200, json=_history_ok("pid-d"))
    )

    resp = client.post("/image/character", json={"descriptor": "an elf ranger", "seed": 1})
    assert resp.status_code == 200, resp.text

    # Map each sent graph to its view by the framing words in the positive prompt, then
    # assert the per-view aspect: face square, bodies tall (height > width).
    sizes_by_view = {}
    for call in route.calls:
        graph = json.loads(call.request.content)["prompt"]
        text = _node_by_title(graph, "Positive Prompt")["inputs"]["text"]
        latent = _node_by_title(graph, "Latent Image")["inputs"]
        sched = _node_by_title(graph, "Scheduler")["inputs"]
        # latent and scheduler must agree on the dimensions
        assert (latent["width"], latent["height"]) == (sched["width"], sched["height"])
        if "portrait" in text and "full body" not in text:
            sizes_by_view["face"] = (latent["width"], latent["height"])
        elif "front view" in text:
            sizes_by_view["body_front"] = (latent["width"], latent["height"])
        elif "side profile" in text:
            sizes_by_view["body_side"] = (latent["width"], latent["height"])

    assert sizes_by_view["face"] == (config.CHAR_FACE_WIDTH, config.CHAR_FACE_HEIGHT)
    fw, fh = sizes_by_view["face"]
    assert fw == fh, "face must be square"
    for key in ("body_front", "body_side"):
        bw, bh = sizes_by_view[key]
        assert (bw, bh) == (config.CHAR_BODY_WIDTH, config.CHAR_BODY_HEIGHT)
        assert bh > bw, f"{key} must be tall (height > width)"


@respx.mock
def test_character_body_prompts_request_full_figure_framing():
    route = respx.post(f"{COMFY}/prompt").mock(
        return_value=httpx.Response(200, json={"prompt_id": "pid-e"})
    )
    respx.get(f"{COMFY}/history/pid-e").mock(
        return_value=httpx.Response(200, json=_history_ok("pid-e"))
    )

    resp = client.post("/image/character", json={"descriptor": "a knight"})
    assert resp.status_code == 200, resp.text

    body_prompts = [
        _node_by_title(json.loads(c.request.content)["prompt"], "Positive Prompt")["inputs"]["text"]
        for c in route.calls
        if "full body" in _node_by_title(json.loads(c.request.content)["prompt"], "Positive Prompt")["inputs"]["text"]
    ]
    assert len(body_prompts) == 2  # front + side
    for p in body_prompts:
        assert "head to toe" in p
        assert "black background" in p


def test_character_requires_descriptor():
    resp = client.post("/image/character", json={"style": "noir"})
    assert resp.status_code == 422


# --- Phase 2: reference conditioning ---------------------------------------------------

REF_URL = "http://gamentic-orchestrator:8000/media/g1/char-7-front.png"
REF_BYTES = b"\x89PNG\r\n\x1a\n-reference-image-"


def _mock_upload(respx_mock, name: str = "ref_abc.png") -> None:
    respx_mock.post(f"{COMFY}/upload/image").mock(
        return_value=httpx.Response(200, json={"name": name, "subfolder": "", "type": "input"})
    )


@respx.mock
def test_generate_with_reference_conditions_the_graph():
    route = respx.post(f"{COMFY}/prompt").mock(
        return_value=httpx.Response(200, json={"prompt_id": "pid-r"})
    )
    respx.get(f"{COMFY}/history/pid-r").mock(
        return_value=httpx.Response(200, json=_history_ok("pid-r"))
    )
    respx.get(REF_URL).mock(return_value=httpx.Response(200, content=REF_BYTES))
    _mock_upload(respx.mock, name="ref_uploaded.png")

    resp = client.post(
        "/image/generate",
        json={"prompt": "the dwarf entering a tavern", "references": [REF_URL]},
    )
    assert resp.status_code == 200, resp.text

    sent = json.loads(route.calls.last.request.content)["prompt"]
    # The uploaded filename is loaded, encoded, and chained into the guider's positive.
    load = _node_by_title(sent, "Reference 0")
    assert load["class_type"] == "LoadImage"
    assert load["inputs"]["image"] == "ref_uploaded.png"
    guider = next(n for n in sent.values() if n["class_type"] == "CFGGuider")
    assert sent[guider["inputs"]["positive"][0]]["class_type"] == "ReferenceLatent"


@respx.mock
def test_unfetchable_reference_falls_back_to_text_only():
    route = respx.post(f"{COMFY}/prompt").mock(
        return_value=httpx.Response(200, json={"prompt_id": "pid-f"})
    )
    respx.get(f"{COMFY}/history/pid-f").mock(
        return_value=httpx.Response(200, json=_history_ok("pid-f"))
    )
    # The reference 404s; an upload mock exists but must never be reached.
    respx.get(REF_URL).mock(return_value=httpx.Response(404))
    upload = _mock_upload(respx.mock)

    resp = client.post(
        "/image/generate",
        json={"prompt": "a lonely tower", "references": [REF_URL]},
    )
    # Render still succeeds, just without conditioning.
    assert resp.status_code == 200, resp.text
    sent = json.loads(route.calls.last.request.content)["prompt"]
    assert not any(n["class_type"] == "ReferenceLatent" for n in sent.values())
    guider = next(n for n in sent.values() if n["class_type"] == "CFGGuider")
    assert sent[guider["inputs"]["positive"][0]]["_meta"]["title"] == "Positive Prompt"


@respx.mock
def test_reference_upload_uses_content_derived_name():
    respx.post(f"{COMFY}/prompt").mock(
        return_value=httpx.Response(200, json={"prompt_id": "pid-h"})
    )
    respx.get(f"{COMFY}/history/pid-h").mock(
        return_value=httpx.Response(200, json=_history_ok("pid-h"))
    )
    respx.get(REF_URL).mock(return_value=httpx.Response(200, content=REF_BYTES))
    upload = respx.post(f"{COMFY}/upload/image").mock(
        return_value=httpx.Response(200, json={"name": "x.png", "subfolder": "", "type": "input"})
    )

    resp = client.post("/image/generate", json={"prompt": "x", "references": [REF_URL]})
    assert resp.status_code == 200, resp.text
    # Uploaded under a stable sha1-derived name with overwrite, so re-sends reuse one file.
    body = upload.calls.last.request.content
    import hashlib

    digest = hashlib.sha1(REF_BYTES).hexdigest()[:16]
    assert f"ref_{digest}.png".encode() in body
    assert b"overwrite" in body
