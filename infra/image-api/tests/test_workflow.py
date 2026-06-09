"""Unit tests for the title-driven graph patcher (build_graph)."""

import pytest

from app import workflow


def test_ksampler_style_template_patches_seed_and_steps_on_one_node():
    template = {
        "1": {"class_type": "CLIPTextEncode", "_meta": {"title": "Positive Prompt"}, "inputs": {"text": "x"}},
        "2": {"class_type": "CLIPTextEncode", "_meta": {"title": "Negative Prompt"}, "inputs": {"text": ""}},
        "3": {"class_type": "EmptySD3LatentImage", "_meta": {"title": "Latent Image"}, "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "4": {"class_type": "KSampler", "_meta": {"title": "Sampler"}, "inputs": {"seed": 0, "steps": 20}},
    }
    g = workflow.build_graph(
        template, prompt="hi", negative_prompt="blurry", width=640, height=384, seed=7, steps=4
    )
    assert g["1"]["inputs"]["text"] == "hi"
    assert g["2"]["inputs"]["text"] == "blurry"
    assert g["3"]["inputs"]["width"] == 640 and g["3"]["inputs"]["height"] == 384
    assert g["4"]["inputs"]["seed"] == 7
    assert g["4"]["inputs"]["steps"] == 4


def test_distilled_style_seed_goes_to_noise_and_steps_to_scheduler():
    template = {
        "a": {"class_type": "CLIPTextEncode", "_meta": {"title": "Positive Prompt"}, "inputs": {"text": ""}},
        "b": {"class_type": "EmptyFlux2LatentImage", "_meta": {"title": "Latent Image"}, "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "c": {"class_type": "Flux2Scheduler", "_meta": {"title": "Scheduler"}, "inputs": {"steps": 4, "width": 1024, "height": 1024}},
        "d": {"class_type": "RandomNoise", "_meta": {"title": "Noise"}, "inputs": {"noise_seed": 0}},
    }
    g = workflow.build_graph(
        template, prompt="p", negative_prompt="ignored", width=512, height=512, seed=99, steps=5
    )
    assert g["d"]["inputs"]["noise_seed"] == 99
    assert g["c"]["inputs"]["steps"] == 5
    # Both width/height carriers stay in sync.
    assert g["b"]["inputs"]["width"] == 512 and g["c"]["inputs"]["width"] == 512


def test_input_does_not_mutate_template():
    template = {
        "a": {"class_type": "CLIPTextEncode", "_meta": {"title": "Positive Prompt"}, "inputs": {"text": "orig"}},
        "b": {"class_type": "EmptyFlux2LatentImage", "_meta": {"title": "Latent Image"}, "inputs": {"width": 1024, "height": 1024}},
    }
    workflow.build_graph(template, prompt="new", negative_prompt="", width=512, height=512, seed=1, steps=4)
    assert template["a"]["inputs"]["text"] == "orig"


def test_missing_positive_node_raises():
    with pytest.raises(workflow.WorkflowError):
        workflow.build_graph(
            {"1": {"class_type": "KSampler", "_meta": {"title": "Sampler"}, "inputs": {}}},
            prompt="x", negative_prompt="", width=512, height=512, seed=1, steps=4,
        )


def test_missing_dimension_node_raises():
    with pytest.raises(workflow.WorkflowError):
        workflow.build_graph(
            {"1": {"class_type": "CLIPTextEncode", "_meta": {"title": "Positive Prompt"}, "inputs": {"text": ""}}},
            prompt="x", negative_prompt="", width=512, height=512, seed=1, steps=4,
        )


def test_real_shipped_workflow_parses_and_patches():
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "workflows" / "flux2_klein_api.json"
    template = workflow.load_template(path)
    g = workflow.build_graph(
        template, prompt="a castle", negative_prompt="", width=768, height=768, seed=5, steps=4
    )
    # Sanity: the Klein graph wires CLIPLoader as type 'flux2' and uses the distilled model.
    clip = next(n for n in g.values() if n["class_type"] == "CLIPLoader")
    assert clip["inputs"]["type"] == "flux2"
    unet = next(n for n in g.values() if n["class_type"] == "UNETLoader")
    assert unet["inputs"]["unet_name"] == "flux-2-klein-4b.safetensors"
