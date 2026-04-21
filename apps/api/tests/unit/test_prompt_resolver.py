"""Prompt resolver: DB override wins over vendored .j2 file."""

from __future__ import annotations

import pytest

from insightxpert_api.prompts import render_prompt
from insightxpert_api.prompts import repository as prompt_repo


def test_file_fallback_renders_vendored_j2(fresh_db):
    # orchestrator_planner.j2 lives in vendored/agents_core/prompts.
    # We just assert rendering succeeds and produces a non-empty string.
    out = render_prompt("orchestrator_planner")
    assert isinstance(out, str)
    assert out.strip()


def test_db_row_overrides_file(fresh_db):
    # Insert an active DB row under the same name as a vendored file — it wins.
    prompt_repo.upsert(
        "orchestrator_planner",
        "DB override says hello {{ who }}",
        description="test override",
        is_active=True,
    )
    out = render_prompt("orchestrator_planner", who="world")
    assert out == "DB override says hello world"


def test_inactive_db_row_falls_back_to_file(fresh_db):
    prompt_repo.upsert(
        "orchestrator_planner",
        "inactive override",
        is_active=False,
    )
    out = render_prompt("orchestrator_planner")
    assert "inactive override" not in out
    assert out.strip()


def test_missing_name_raises(fresh_db):
    import jinja2

    with pytest.raises(jinja2.TemplateNotFound):
        render_prompt("definitely_not_a_real_template_name")
