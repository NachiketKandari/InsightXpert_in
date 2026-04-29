"""Runtime model-config route — what the chat input toolbar reads.

The FE settings store hits these endpoints to render the model picker and
optimistically switch the active chat model. Provider switching is a v1
non-goal (only Gemini is wired up), so `provider` is validated as a single
allowed value and `/switch` mutates `settings.gemini_chat_model` in-process
only — there is no persistent override. A process restart returns to the
env-pinned default.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth.dependencies import get_current_user
from ..config import Settings, get_settings
from ..metrics.pricing import PRICING

router = APIRouter(prefix="/api/v1/config", tags=["config"])


_ALLOWED_PROVIDER = "gemini"

# Chat-capable Gemini models. Embeddings model is excluded — it's not a
# valid chat model and would 400 if selected from the picker.
_CHAT_MODELS: list[str] = sorted(
    name for name in PRICING if not name.endswith("-embedding-001")
)


class ProviderModels(BaseModel):
    provider: str
    models: list[str]


class ConfigResponse(BaseModel):
    current_provider: str
    current_model: str
    providers: list[ProviderModels]


class SwitchRequest(BaseModel):
    provider: str
    model: str


@router.get("", response_model=ConfigResponse)
async def get_config(
    _user: object = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> ConfigResponse:
    return ConfigResponse(
        current_provider=settings.llm_provider,
        current_model=settings.gemini_chat_model,
        providers=[ProviderModels(provider=_ALLOWED_PROVIDER, models=_CHAT_MODELS)],
    )


@router.post("/switch", response_model=ConfigResponse)
async def switch_model(
    body: SwitchRequest,
    _user: object = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> ConfigResponse:
    if body.provider != _ALLOWED_PROVIDER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported provider '{body.provider}'. Only '{_ALLOWED_PROVIDER}' is wired up.",
        )
    if body.model not in _CHAT_MODELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown model '{body.model}'. Allowed: {', '.join(_CHAT_MODELS)}.",
        )

    # In-process override only — Settings is the cached singleton from
    # get_settings(); mutating the field here flips every site that reads
    # settings.gemini_chat_model on next access. Lost on restart by design.
    settings.gemini_chat_model = body.model
    settings.llm_provider = body.provider

    return ConfigResponse(
        current_provider=settings.llm_provider,
        current_model=settings.gemini_chat_model,
        providers=[ProviderModels(provider=_ALLOWED_PROVIDER, models=_CHAT_MODELS)],
    )
