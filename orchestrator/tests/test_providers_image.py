"""Image provider dialects: request shapes pinned to each provider's PUBLISHED schema
(comfy = the exact wire behavior media.py always had; openai generations/edits; gemini
generateContent parts; fal queue with its per-model parameter maps), documented-response
parsing, and deterministic capability degradation (no seed -> silently unused; no
references -> plain t2i in character_set). All over mocked HTTP."""
import base64
import json

from app import media
from app.providers import base as pbase
from app.providers import image as pimage


class _Resp:
    def __init__(self, payload=None, content=b""):
        self._payload = payload or {}
        self.content = content
        self.headers = {}
    def raise_for_status(self): pass
    def json(self): return self._payload


# ---------- comfy (the local default; request shapes byte-identical to before) ----------

def test_comfy_generate_request_shape(monkeypatch):
    captured = {}
    monkeypatch.setattr(pimage.httpx, "post",
                        lambda url, json=None, timeout=None:
                        captured.update(url=url, body=json, timeout=timeout)
                        or _Resp({"image_url": "/image/file?filename=x"}))
    p = pimage.get_provider(pbase.resolve("image"))
    out = p.generate("a cave mouth at dusk", (768, 768), seed=7,
                     references=["http://orch:8000/media/g/char-front.png"])
    assert captured["url"].endswith("/image/generate")
    assert captured["body"] == {"prompt": "a cave mouth at dusk", "width": 768, "height": 768,
                                "references": ["http://orch:8000/media/g/char-front.png"],
                                "seed": 7}
    assert out["image_url"] == "/image/file?filename=x"


def test_comfy_character_request_shape(monkeypatch):
    captured = {}
    monkeypatch.setattr(pimage.httpx, "post",
                        lambda url, json=None, timeout=None:
                        captured.update(url=url, body=json)
                        or _Resp({"face_url": "f", "body_front_url": "bf",
                                  "body_side_url": "bs", "seed": 1}))
    p = pimage.get_provider(pbase.resolve("image"))
    out = p.character_set("a scarred knight", "oil painting")
    assert captured["url"].endswith("/image/character")
    assert captured["body"] == {"descriptor": "a scarred knight", "style": "oil painting"}
    assert out["body_front_url"] == "bf"


def test_comfy_reference_capability_override_degrades_to_plain_t2i(monkeypatch):
    monkeypatch.setenv("IMAGE_SUPPORTS_REFERENCES", "false")
    captured = {}
    monkeypatch.setattr(pimage.httpx, "post",
                        lambda url, json=None, timeout=None:
                        captured.update(body=json) or _Resp({"image_url": "/x"}))
    p = pimage.get_provider(pbase.resolve("image"))
    p.generate("a cave", (512, 512), references=["http://r/1.png"])
    assert "references" not in captured["body"]      # silently dropped, nothing breaks


# ---------- openai ----------

def _openai_env(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("IMAGE_API_KEY", "sk-img")


def test_openai_generations_contract(monkeypatch):
    _openai_env(monkeypatch)
    captured = {}
    b64 = base64.b64encode(b"PNGBYTES").decode()
    monkeypatch.setattr(pimage.httpx, "post",
                        lambda url, json=None, headers=None, timeout=None:
                        captured.update(url=url, body=json, headers=headers)
                        or _Resp({"data": [{"b64_json": b64}]}))
    p = pimage.get_provider(pbase.resolve("image"))
    out = p.generate("a cave mouth at dusk", (768, 512))
    assert captured["url"] == "https://api.openai.com/v1/images/generations"
    assert captured["headers"] == {"Authorization": "Bearer sk-img"}
    assert captured["body"] == {"model": "gpt-image-2", "prompt": "a cave mouth at dusk",
                                "size": "1536x1024", "n": 1}      # landscape snaps to 1536x1024
    assert out["image_url"] == f"data:image/png;base64,{b64}"
    assert media.fetch_image_bytes(out["image_url"]) == b"PNGBYTES"  # persistable as-is


def test_openai_references_switch_to_edits_multipart(monkeypatch):
    _openai_env(monkeypatch)
    captured = {}
    monkeypatch.setattr(pimage.httpx, "get",
                        lambda url, timeout=None: _Resp(content=b"REFBYTES"))

    def _post(url, data=None, files=None, headers=None, timeout=None, json=None):
        captured.update(url=url, data=data, files=files, headers=headers)
        return _Resp({"data": [{"url": "https://oai/img.png"}]})
    monkeypatch.setattr(pimage.httpx, "post", _post)

    p = pimage.get_provider(pbase.resolve("image"))
    refs = [f"http://orch:8000/media/g/ref-{i}.png" for i in range(17)]
    out = p.generate("the same knight by a fire", (768, 768), references=refs)
    assert captured["url"] == "https://api.openai.com/v1/images/edits"
    assert captured["data"] == {"model": "gpt-image-2", "prompt": "the same knight by a fire",
                                "size": "1024x1024", "n": "1"}
    assert len(captured["files"]) == 16                       # documented reference cap
    name, (fname, blob, mime) = captured["files"][0]
    assert name == "image[]" and blob == b"REFBYTES" and mime == "image/png"
    assert out["image_url"] == "https://oai/img.png"          # documented url variant parsed


# ---------- gemini ----------

def test_gemini_generate_content_contract_and_seed_silently_unused(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    monkeypatch.setenv("IMAGE_API_KEY", "g-key")
    captured = {}
    monkeypatch.setattr(pimage.httpx, "get",
                        lambda url, timeout=None: _Resp(content=b"REF"))
    monkeypatch.setattr(pimage.httpx, "post",
                        lambda url, json=None, headers=None, timeout=None:
                        captured.update(url=url, body=json, headers=headers)
                        or _Resp({"candidates": [{"content": {"parts": [
                            {"text": "here you go"},
                            {"inlineData": {"mimeType": "image/png", "data": "QUJD"}}]}}]}))
    p = pimage.get_provider(pbase.resolve("image"))
    out = p.generate("a cave mouth at dusk", (768, 768), seed=42,
                     references=["http://orch:8000/media/g/ref.png"])
    assert captured["url"] == ("https://generativelanguage.googleapis.com"
                               "/v1beta/models/gemini-2.5-flash-image:generateContent")
    assert captured["headers"] == {"x-goog-api-key": "g-key"}
    assert captured["body"] == {"contents": [{"parts": [
        {"text": "a cave mouth at dusk"},
        {"inline_data": {"mime_type": "image/png",
                         "data": base64.b64encode(b"REF").decode()}}]}]}
    assert "seed" not in json.dumps(captured["body"])         # no seed: silently unused
    assert out["image_url"] == "data:image/png;base64,QUJD"   # inline blob parsed


# ---------- fal (queue dialect + per-model parameter maps) ----------

def _fal_queue(monkeypatch, captured, result):
    """Mock the queue flow: submit -> status (IN_PROGRESS then COMPLETED) -> response."""
    def _post(url, json=None, headers=None, timeout=None):
        captured.setdefault("posts", []).append({"url": url, "body": json, "headers": headers})
        rid = f"rq{len(captured['posts'])}"
        return _Resp({"request_id": rid, "status_url": f"{url}/requests/{rid}/status",
                      "response_url": f"{url}/requests/{rid}"})

    def _get(url, headers=None, timeout=None):
        captured.setdefault("gets", []).append({"url": url, "headers": headers})
        if url.endswith("/status"):
            seen = sum(1 for g in captured["gets"] if g["url"] == url)
            return _Resp({"status": "IN_PROGRESS" if seen == 1 else "COMPLETED"})
        return _Resp(result, content=b"BLOB")
    monkeypatch.setattr(pbase.httpx, "post", _post)
    monkeypatch.setattr(pbase.httpx, "get", _get)


def test_fal_nano_banana_2_queue_flow_and_param_map(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "fal")
    monkeypatch.setenv("IMAGE_API_KEY", "f-key")
    captured = {}
    _fal_queue(monkeypatch, captured, {"images": [{"url": "https://fal.media/x.png"}]})
    p = pimage.get_provider(pbase.resolve("image"))
    p.poll_interval = 0
    out = p.generate("a cave mouth at dusk", (768, 768), seed=5)

    submit = captured["posts"][0]
    assert submit["url"] == "https://queue.fal.run/fal-ai/nano-banana-2"
    assert submit["headers"] == {"Authorization": "Key f-key"}
    assert submit["body"] == {"prompt": "a cave mouth at dusk", "aspect_ratio": "1:1",
                              "resolution": "1K", "num_images": 1, "seed": 5}
    status_polls = [g for g in captured["gets"] if g["url"].endswith("/status")]
    assert len(status_polls) == 2                              # polled until COMPLETED
    assert status_polls[0]["headers"] == {"Authorization": "Key f-key"}
    assert out == {"image_url": "https://fal.media/x.png"}


def test_fal_gpt_image_2_param_map_has_no_seed(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "fal")
    monkeypatch.setenv("IMAGE_MODEL", "openai/gpt-image-2")
    captured = {}
    _fal_queue(monkeypatch, captured, {"images": [{"url": "https://fal.media/y.png"}]})
    p = pimage.get_provider(pbase.resolve("image"))
    p.poll_interval = 0
    p.generate("a cave", (768, 512), seed=5)                   # seed unsupported here
    assert captured["posts"][0]["url"] == "https://queue.fal.run/openai/gpt-image-2"
    assert captured["posts"][0]["body"] == {"prompt": "a cave",
                                            "image_size": {"width": 768, "height": 512},
                                            "quality": "high", "num_images": 1}


# ---------- character_set identity paths ----------

def test_character_set_reference_path_when_supported(monkeypatch):
    """Cloud provider WITH references (gemini): face first via t2i, then front/side
    conditioned on the face (reference-path identity)."""
    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    calls = []
    monkeypatch.setattr(pimage.httpx, "post",
                        lambda url, json=None, headers=None, timeout=None:
                        calls.append(json) or _Resp({"candidates": [{"content": {"parts": [
                            {"inlineData": {"mimeType": "image/png", "data": "QUJD"}}]}}]}))
    p = pimage.get_provider(pbase.resolve("image"))
    out = p.character_set("a scarred knight", "oil painting")
    assert len(calls) == 3
    face_parts = calls[0]["contents"][0]["parts"]
    assert len(face_parts) == 1 and "portrait" in face_parts[0]["text"]
    for body_call, view in ((calls[1], "front view"), (calls[2], "side profile")):
        parts = body_call["contents"][0]["parts"]
        assert view in parts[0]["text"] and "oil painting" in parts[0]["text"]
        assert parts[1]["inline_data"]["data"] == "QUJD"       # the face conditions the body
    assert out["face_url"] and out["body_front_url"] and out["body_side_url"]


def test_character_set_degrades_to_three_independent_t2i_without_references(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "fal")                # neither fal map takes refs
    captured = {}
    _fal_queue(monkeypatch, captured, {"images": [{"url": "https://fal.media/v.png"}]})
    p = pimage.get_provider(pbase.resolve("image"))
    p.poll_interval = 0
    out = p.character_set("a scarred knight", "oil painting")
    submits = captured["posts"]
    assert len(submits) == 3                                   # plain t2i per view
    assert all(set(s["body"]) == {"prompt", "aspect_ratio", "resolution", "num_images"}
               for s in submits)                               # no reference channel at all
    assert out == {"face_url": "https://fal.media/v.png",
                   "body_front_url": "https://fal.media/v.png",
                   "body_side_url": "https://fal.media/v.png", "seed": None}


def test_facade_dispatches_to_the_active_provider(monkeypatch):
    """media.generate_scene_image is the back-compat facade: same signature, but the
    active (env-resolved) provider serves the call."""
    from app.config import settings
    monkeypatch.setattr(settings, "IMAGE_ENABLED", True)
    monkeypatch.setenv("IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("IMAGE_API_KEY", "sk-img")
    captured = {}
    monkeypatch.setattr(pimage.httpx, "post",
                        lambda url, json=None, headers=None, timeout=None:
                        captured.update(url=url) or _Resp({"data": [{"url": "https://oai/i.png"}]}))
    out = media.generate_scene_image("a cave", width=512, height=512)
    assert captured["url"] == "https://api.openai.com/v1/images/generations"
    assert out == {"image_url": "https://oai/i.png"}
    # provider errors stay best-effort: the game never breaks over an image
    def _boom(*a, **k): raise RuntimeError("provider down")
    monkeypatch.setattr(pimage.httpx, "post", _boom)
    assert media.generate_scene_image("a cave") is None
