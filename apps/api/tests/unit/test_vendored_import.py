"""Smoke tests verifying the vendored pipeline imports cleanly."""

from __future__ import annotations


def test_single_prompt_linker_importable() -> None:
    from insightxpert_api.vendored.pipeline_core.linker.single_prompt_linker import (
        SinglePromptLinker,
    )

    assert SinglePromptLinker is not None


def test_database_profile_importable_and_has_model_validate() -> None:
    from insightxpert_api.vendored.pipeline_core.models.profile import DatabaseProfile

    assert DatabaseProfile is not None
    assert hasattr(DatabaseProfile, "model_validate")
