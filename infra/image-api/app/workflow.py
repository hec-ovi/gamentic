"""Build a ComfyUI API-format prompt graph from a template + request parameters.

We keep one API-format workflow JSON on disk and patch a handful of values into it
per request. To stay robust against node-id churn when the template is re-exported,
we locate nodes by their ``_meta.title`` rather than by numeric id. The shipped
template (FLUX.2 Klein 4B distilled) uses these titles; the patching is tolerant so a
KSampler-style template (seed + steps on one "Sampler" node) also works.

Klein distilled is a SamplerCustomAdvanced pipeline:
  - prompt   -> CLIPTextEncode titled "Positive Prompt"
  - width/h  -> EmptyFlux2LatentImage "Latent Image" AND Flux2Scheduler "Scheduler"
  - steps    -> Flux2Scheduler "Scheduler"
  - seed     -> RandomNoise "Noise"
It is guidance-free (negative is a ConditioningZeroOut), so a negative prompt has no
node to land on and is ignored.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

TITLE_POSITIVE = "Positive Prompt"
TITLE_NEGATIVE = "Negative Prompt"
TITLE_LATENT = "Latent Image"
TITLE_SCHEDULER = "Scheduler"
TITLE_NOISE = "Noise"
TITLE_SAMPLER = "Sampler"  # KSampler-style fallback: carries both seed and steps


class WorkflowError(RuntimeError):
    """The template is missing a node the adapter needs to patch."""


def load_template(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


def _index_by_title(graph: dict) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for node in graph.values():
        title = node.get("_meta", {}).get("title")
        if title and title not in index:
            index[title] = node
    return index


def build_graph(
    template: dict,
    *,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    seed: int,
    steps: int,
) -> dict:
    """Return a deep copy of the template with request values patched in."""
    graph = copy.deepcopy(template)
    by_title = _index_by_title(graph)

    positive = by_title.get(TITLE_POSITIVE)
    if positive is None:
        raise WorkflowError(
            f"workflow template has no node titled {TITLE_POSITIVE!r}; "
            f"title the positive CLIPTextEncode {TITLE_POSITIVE!r} and re-export in API format"
        )
    positive["inputs"]["text"] = prompt

    # Negative is optional: distilled Klein has no negative node (guidance-free).
    negative = by_title.get(TITLE_NEGATIVE)
    if negative is not None:
        negative["inputs"]["text"] = negative_prompt

    # Width/height live on the latent node and, for Klein, also on the scheduler.
    # Both must agree, so patch every node that carries width+height.
    sized_any = False
    for title in (TITLE_LATENT, TITLE_SCHEDULER):
        node = by_title.get(title)
        if node and "width" in node["inputs"] and "height" in node["inputs"]:
            node["inputs"]["width"] = width
            node["inputs"]["height"] = height
            sized_any = True
    if not sized_any:
        raise WorkflowError(
            "workflow template has no node with width/height to size the image "
            f"(expected a node titled {TITLE_LATENT!r} or {TITLE_SCHEDULER!r})"
        )

    # Steps: scheduler (Klein) or the KSampler fallback.
    for title in (TITLE_SCHEDULER, TITLE_SAMPLER):
        node = by_title.get(title)
        if node and "steps" in node["inputs"]:
            node["inputs"]["steps"] = steps
            break

    # Seed: dedicated RandomNoise (noise_seed) or the KSampler fallback (seed).
    noise = by_title.get(TITLE_NOISE)
    if noise and "noise_seed" in noise["inputs"]:
        noise["inputs"]["noise_seed"] = seed
    else:
        sampler = by_title.get(TITLE_SAMPLER)
        if sampler and "seed" in sampler["inputs"]:
            sampler["inputs"]["seed"] = seed

    return graph
