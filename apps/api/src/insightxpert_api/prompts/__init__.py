"""Prompt resolution layer.

DB-first: admin edits in ``prompt_templates`` win; ``.j2`` files in the
vendored ``agents_core/prompts/`` directory are the fallback.
"""

from .resolver import render_prompt

__all__ = ["render_prompt"]
