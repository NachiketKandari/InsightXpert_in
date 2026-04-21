"""DB-first prompt resolution with ``.j2`` file fallback.

Lookup order per ``name``:
  1. ``prompt_templates`` table — admin override. Must be ``is_active=1``.
  2. Vendored ``.j2`` file at ``vendored/agents_core/prompts/<name>.j2``.

Admin edits are live on the next turn (no hot-reload step).

The caller chooses the ``name``. Public's template files are named e.g.
``orchestrator_planner.j2`` and ``insight_quality_evaluator.j2``; the resolver
doesn't rewrite names — pass whatever you need.
"""

from __future__ import annotations

from pathlib import Path

import jinja2

from . import repository

_VENDORED_DIR = (
    Path(__file__).resolve().parents[1] / "vendored" / "agents_core" / "prompts"
)

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_VENDORED_DIR)),
    autoescape=False,
    keep_trailing_newline=True,
)


def render_prompt(name: str, **context: object) -> str:
    """Render the template ``name`` with ``context``.

    Raises ``jinja2.TemplateNotFound`` if neither a DB row nor a ``<name>.j2``
    file exists.
    """
    db_row = repository.get(name)
    if db_row is not None and db_row.is_active:
        return jinja2.Template(db_row.content).render(**context)
    return _env.get_template(f"{name}.j2").render(**context)
