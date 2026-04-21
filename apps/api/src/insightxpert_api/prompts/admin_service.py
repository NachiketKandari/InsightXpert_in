"""Admin-facing prompt management service.

Combines the set of bundled ``.j2`` template files (authoritative fallback)
with DB override rows in ``prompt_templates``. The resolver's lookup order
(DB first, file fallback) is mirrored here so the admin FE can show a
unified list plus preview both the override and the baked-in default.
"""

from __future__ import annotations

from pathlib import Path
from time import time as _now
from typing import Any

from sqlalchemy import select

from ..db.engine import get_engine
from ..orchestration.table import prompt_templates
from . import repository

_VENDORED_DIR = (
    Path(__file__).resolve().parents[1] / "vendored" / "agents_core" / "prompts"
)


def _file_names() -> set[str]:
    """All prompt names available on disk (stripped of ``.j2``)."""
    if not _VENDORED_DIR.is_dir():
        return set()
    return {p.stem for p in _VENDORED_DIR.glob("*.j2")}


def _file_content(name: str) -> str | None:
    path = _VENDORED_DIR / f"{name}.j2"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def list_all() -> list[dict[str, Any]]:
    """Union of disk prompts + DB overrides. See module docstring."""
    with get_engine().connect() as conn:
        rows = conn.execute(select(prompt_templates)).all()
    db_by_name = {r.name: r for r in rows}
    names = _file_names() | set(db_by_name.keys())
    out: list[dict[str, Any]] = []
    for name in sorted(names):
        db_row = db_by_name.get(name)
        has_override = db_row is not None
        is_active = bool(db_row.is_active) if db_row else False
        source = "db" if (db_row is not None and is_active) else "file"
        out.append(
            {
                "name": name,
                "has_override": has_override,
                "is_active": is_active,
                "description": db_row.description if db_row else None,
                "updated_at": int(db_row.updated_at) if db_row else None,
                "source": source,
            }
        )
    return out


def get_detail(name: str) -> dict[str, Any] | None:
    """Return combined DB + file details for one prompt, or ``None`` if neither exists."""
    db_row = repository.get(name)
    file_content = _file_content(name)
    if db_row is None and file_content is None:
        return None
    # DB override wins (when active) for the primary `content`, matching the resolver.
    if db_row is not None and db_row.is_active:
        content = db_row.content
        source = "db"
    elif file_content is not None:
        content = file_content
        source = "file"
    else:
        # DB row exists but inactive, file missing → fall back to DB content.
        assert db_row is not None
        content = db_row.content
        source = "db"

    # Look up updated_at from DB row directly (repository.get strips it).
    updated_at: int | None = None
    if db_row is not None:
        with get_engine().connect() as conn:
            row = conn.execute(
                select(prompt_templates.c.updated_at).where(
                    prompt_templates.c.name == name
                )
            ).first()
        if row is not None:
            updated_at = int(row.updated_at)

    return {
        "name": name,
        "content": content,
        "source": source,
        "description": db_row.description if db_row else None,
        "is_active": bool(db_row.is_active) if db_row else False,
        "updated_at": updated_at,
        "file_content": file_content,
    }


def upsert(name: str, content: str, description: str | None = None) -> dict[str, Any]:
    repository.upsert(name, content, description=description, is_active=True)
    detail = get_detail(name)
    assert detail is not None
    return detail


def delete(name: str) -> bool:
    """Delete a DB override. Returns ``True`` if a row existed."""
    with get_engine().begin() as conn:
        res = conn.execute(
            prompt_templates.delete().where(prompt_templates.c.name == name)
        )
    return res.rowcount > 0


def reset(name: str) -> None:
    """Idempotent delete — no-op if the row doesn't exist."""
    delete(name)


# Keep the `_now` import used for symmetry with repository.upsert signatures,
# even though we don't compute timestamps here directly.
_ = _now
