"""Runtime model-config route — what the chat input toolbar reads.

The FE settings store hits these endpoints to render the model picker and
optimistically switch the active chat model. ``/switch`` mutates the in-process
``Settings`` singleton — there is no persistent override. A process restart
returns to the env-pinned default.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from ..auth.dependencies import get_current_user, require_admin
from ..config import Settings, get_settings
from ..metrics.pricing import PRICING
from .client_config import _FEATURES  # in-process feature flags, shared with client-config

router = APIRouter(prefix="/api/v1/config", tags=["config"])

# Chat-capable models by provider. Embeddings models are excluded — they're
# not valid chat models and would 400 if selected from the picker.
_CHAT_MODELS: dict[str, list[str]] = {}
for _name in sorted(PRICING):
    if "embedding" in _name:
        continue
    # Group by provider prefix: gemini-* or deepseek-*
    if _name.startswith("gemini"):
        _CHAT_MODELS.setdefault("gemini", []).append(_name)
    elif _name.startswith("deepseek"):
        _CHAT_MODELS.setdefault("deepseek", []).append(_name)
# Ensure both providers have at least an empty list so the picker doesn't 500.
_CHAT_MODELS.setdefault("gemini", [])
_CHAT_MODELS.setdefault("deepseek", [])


def _current_model(settings: Settings) -> str:
    """Active chat model for the configured provider."""
    if settings.llm_provider == "deepseek":
        return settings.deepseek_chat_model
    return settings.gemini_chat_model


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
    response: Response,
    _user: object = Depends(get_current_user),
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> ConfigResponse:
    response.headers["Cache-Control"] = "private, max-age=60"
    return ConfigResponse(
        current_provider=settings.llm_provider,
        current_model=_current_model(settings),
        providers=[
            ProviderModels(provider=p, models=m)
            for p, m in sorted(_CHAT_MODELS.items())
        ],
    )


@router.post("/switch", response_model=ConfigResponse)
async def switch_model(
    body: SwitchRequest,
    _user: object = Depends(get_current_user),
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> ConfigResponse:
    allowed = _CHAT_MODELS.get(body.provider)
    if allowed is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported provider '{body.provider}'. Allowed: {', '.join(sorted(_CHAT_MODELS))}.",
        )
    if body.model not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown model '{body.model}' for provider '{body.provider}'. Allowed: {', '.join(sorted(allowed))}.",
        )

    # In-process override only — Settings is the cached singleton from
    # get_settings(); mutating the field here flips every site that reads
    # settings.{gemini,deepseek}_chat_model on next access. Lost on restart
    # by design.
    if body.provider == "deepseek":
        settings.deepseek_chat_model = body.model
    else:
        settings.gemini_chat_model = body.model
    settings.llm_provider = body.provider

    return ConfigResponse(
        current_provider=settings.llm_provider,
        current_model=_current_model(settings),
        providers=[
            ProviderModels(provider=p, models=m)
            for p, m in sorted(_CHAT_MODELS.items())
        ],
    )


class FeatureToggleUpdate(BaseModel):
    feature: str
    enabled: bool


@router.get("/features")
async def get_features(
    response: Response,
    _user: object = Depends(get_current_user),
) -> dict[str, object]:
    """Return current feature flags (authenticated, read by admin panel)."""
    response.headers["Cache-Control"] = "private, max-age=300"
    return {"features": dict(_FEATURES)}


@router.post("/features")
async def update_feature(
    body: FeatureToggleUpdate,
    _admin: object = Depends(require_admin),
) -> dict[str, object]:
    """Toggle a single feature flag in-process (admin only)."""
    if body.feature not in _FEATURES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown feature '{body.feature}'.",
        )
    _FEATURES[body.feature] = body.enabled
    return {"features": dict(_FEATURES)}


class ThresholdRequest(BaseModel):
    threshold: int


@router.get("/threshold")
async def get_threshold(
    _user: object = Depends(get_current_user),
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> dict[str, int]:
    """Return the column threshold for single-prompt schema linking."""
    return {"threshold": settings.single_sql_column_threshold}


@router.post("/threshold")
async def update_threshold(
    body: ThresholdRequest,
    _admin: object = Depends(require_admin),
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> dict[str, int]:
    """Update the column threshold for single-prompt schema linking (admin only)."""
    if body.threshold < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Threshold must be a non-negative integer.",
        )
    settings.single_sql_column_threshold = body.threshold
    return {"threshold": settings.single_sql_column_threshold}

