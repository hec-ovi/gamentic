"""Inference providers layer (docs/shared/inference-providers.md).

One interface per modality (text rides llm.chat; audio + image get dialect classes
here), plus the per-modality config spine. Pure JSON shaping over httpx, no SDKs.
Config resolves AT CALL TIME: env -> default; .env (written by the setup faces)
is the single config layer, applied on the next compose up."""
from .base import (  # noqa: F401
    DIALECTS, MODALITIES, AnnaConfig, ProviderConfig, anna_config,
    anna_enabled, fal_queue_run, resolve, voice_enabled,
)
