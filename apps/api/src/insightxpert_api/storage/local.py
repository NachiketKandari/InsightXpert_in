"""Local-filesystem backend for ``ObjectStore``. Used in tests and dev."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


class LocalStorage:
    def __init__(self, root: str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        """Resolve ``key`` under root, rejecting path-traversal attempts."""
        candidate = (self._root / key).resolve()
        root_resolved = self._root.resolve()
        try:
            candidate.relative_to(root_resolved)
        except ValueError as e:
            raise ValueError(f"path traversal rejected: {key!r}") from e
        return candidate

    def put_bytes(self, key: str, data: bytes) -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get_bytes(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.exists():
            path.unlink()

    def list(self, prefix: str) -> Iterable[str]:
        root_resolved = self._root.resolve()
        base = self._resolve(prefix) if prefix else root_resolved
        start = base if base.is_dir() else base.parent
        if not start.exists():
            return []
        keys: list[str] = []
        for path in start.rglob("*"):
            if path.is_file():
                rel = path.resolve().relative_to(root_resolved).as_posix()
                if rel.startswith(prefix):
                    keys.append(rel)
        return sorted(keys)
