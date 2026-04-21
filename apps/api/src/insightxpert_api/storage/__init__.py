"""Object storage abstraction. GCS in prod, local filesystem for dev/tests."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ..config import Settings


@runtime_checkable
class ObjectStore(Protocol):
    """Minimal object-store contract. All keys are POSIX-style slash-separated strings."""

    def put_bytes(self, key: str, data: bytes) -> None: ...
    def get_bytes(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def list(self, prefix: str) -> Iterable[str]: ...
    def delete(self, key: str) -> None: ...


def build_store(settings: "Settings") -> ObjectStore:
    """Factory: return GCS if a bucket is configured, else local-fs fallback."""
    if settings.gcs_bucket:
        from .gcs import GCSStorage

        return GCSStorage(settings.gcs_bucket)
    from .local import LocalStorage

    return LocalStorage(settings.local_storage_dir)


__all__ = ["ObjectStore", "build_store"]
