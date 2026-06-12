"""Inference providers layer (docs/shared/inference-providers.md).

One interface per modality (text rides llm.chat; audio + image get dialect classes
here), plus the per-modality config spine. Pure JSON shaping over httpx, no SDKs.
Config resolves AT CALL TIME: admin DB override -> env -> default, so the admin
panel hot-swaps providers without a restart."""
from .base import (  # noqa: F401
    ANNA_FIELDS, DIALECTS, MODALITIES, AnnaConfig, ProviderConfig, anna_config,
    anna_enabled, capability_notes, fal_queue_run, resolve, voice_enabled,
)
