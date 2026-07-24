"""End-to-end: the model set named in .env is the one ComfyUI is asked to render with.

Each test boots a fresh copy of the app with different environment (the way compose hands
it in), drives the real /image/generate route, and reads the graph that actually went to
ComfyUI. Nothing internal is mocked; ComfyUI is faked at the network layer with respx.
"""

import importlib
import json
import sys

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

COMFY = "http://comfy.test:8188"
PNG_BYTES = b"\x89PNG\r\n\x1a\n-fake-png-body-"


def _forget(package):
    """Drop the cached modules AND the parent package's attributes: `from . import config`
    would otherwise hand the freshly executed main.py the previous run's config."""
    for name in ("main", "config"):
        sys.modules.pop(f"{package.__name__}.{name}", None)
        if hasattr(package, name):
            delattr(package, name)


@pytest.fixture
def boot(monkeypatch):
    """Import app.main fresh under the given environment; drop it again afterwards so the
    next importer gets a module built from clean env."""
    import app

    def _boot(**env):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        _forget(app)
        return importlib.import_module("app.main")

    yield _boot
    _forget(app)


def _mock_comfy(respx_mock, prompt_id="pid-cfg"):
    queue = respx_mock.post(f"{COMFY}/prompt").mock(
        return_value=httpx.Response(200, json={"prompt_id": prompt_id})
    )
    respx_mock.get(f"{COMFY}/history/{prompt_id}").mock(
        return_value=httpx.Response(
            200,
            json={
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
            },
        )
    )
    respx_mock.get(f"{COMFY}/view").mock(
        return_value=httpx.Response(200, content=PNG_BYTES, headers={"content-type": "image/png"})
    )
    return queue


def _sent_graph(queue):
    return json.loads(queue.calls.last.request.content)["prompt"]


def _node_by_class(graph, class_type):
    return next(n for n in graph.values() if n["class_type"] == class_type)


def test_env_model_names_are_what_comfyui_is_asked_to_load(boot):
    main = boot(
        COMFY_UNET_NAME="some-other-4b.safetensors",
        COMFY_CLIP_NAME="some-other-encoder.safetensors",
        COMFY_CLIP_TYPE="flux2",
        COMFY_VAE_NAME="some-other-vae.safetensors",
    )
    with respx.mock(assert_all_called=False) as router:
        queue = _mock_comfy(router)
        resp = TestClient(main.app).post("/image/generate", json={"prompt": "a lantern-lit alley"})
    assert resp.status_code == 200, resp.text

    graph = _sent_graph(queue)
    assert _node_by_class(graph, "UNETLoader")["inputs"]["unet_name"] == "some-other-4b.safetensors"
    assert _node_by_class(graph, "CLIPLoader")["inputs"]["clip_name"] == "some-other-encoder.safetensors"
    assert _node_by_class(graph, "VAELoader")["inputs"]["vae_name"] == "some-other-vae.safetensors"


def test_without_model_env_the_shipped_klein_set_is_used(boot):
    main = boot(COMFY_UNET_NAME="", COMFY_CLIP_NAME="", COMFY_CLIP_TYPE="", COMFY_VAE_NAME="")
    with respx.mock(assert_all_called=False) as router:
        queue = _mock_comfy(router)
        resp = TestClient(main.app).post("/image/generate", json={"prompt": "a quiet chapel"})
    assert resp.status_code == 200, resp.text

    graph = _sent_graph(queue)
    assert _node_by_class(graph, "UNETLoader")["inputs"]["unet_name"] == "flux-2-klein-4b.safetensors"
    assert _node_by_class(graph, "CLIPLoader")["inputs"]["clip_name"] == "qwen_3_4b.safetensors"
    assert _node_by_class(graph, "VAELoader")["inputs"]["vae_name"] == "flux2-vae.safetensors"


def test_a_model_setting_with_no_loader_refuses_to_render(boot, tmp_path):
    """A template that cannot take the configured model would render with the wrong one.
    The service stays up and says why, instead of quietly painting the wrong picture."""
    template = tmp_path / "no_unet.json"
    template.write_text(
        json.dumps(
            {
                "1": {"class_type": "CheckpointLoaderSimple", "_meta": {"title": "Model"},
                      "inputs": {"ckpt_name": "whatever.safetensors"}},
                "2": {"class_type": "CLIPTextEncode", "_meta": {"title": "Positive Prompt"},
                      "inputs": {"text": ""}},
                "3": {"class_type": "EmptySD3LatentImage", "_meta": {"title": "Latent Image"},
                      "inputs": {"width": 1024, "height": 1024}},
            }
        )
    )
    main = boot(WORKFLOW_TEMPLATE=str(template), COMFY_UNET_NAME="klein.safetensors")
    with respx.mock(assert_all_called=False) as router:
        _mock_comfy(router)
        client = TestClient(main.app)

        health = client.get("/health").json()
        assert health["template_loaded"] is False
        assert "UNETLoader" in health["template_error"]

        resp = client.post("/image/generate", json={"prompt": "anything"})
    assert resp.status_code == 503
    assert "UNETLoader" in resp.json()["detail"]
