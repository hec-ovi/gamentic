"""Inference providers layer (docs/shared/inference-providers.md).

One interface per modality (text rides llm.chat; audio + image get dialect classes
here), plus the per-modality config spine. Pure JSON shaping over httpx, no SDKs.
Config resolves AT CALL TIME: admin DB override -> env -> default, so the admin
panel hot-swaps providers without a restart."""
from .base import (  # noqa: F401
    DIALECTS, MODALITIES, ProviderConfig, capability_notes, fal_queue_run, resolve,
)
