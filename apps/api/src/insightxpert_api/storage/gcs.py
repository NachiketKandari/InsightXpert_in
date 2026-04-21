"""Google Cloud Storage backend for ``ObjectStore``."""

from __future__ import annotations

from collections.abc import Iterable

from google.cloud import storage


class GCSStorage:
    def __init__(self, bucket_name: str) -> None:
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket_name)

    def put_bytes(self, key: str, data: bytes) -> None:
        self._bucket.blob(key).upload_from_string(data)

    def get_bytes(self, key: str) -> bytes:
        return self._bucket.blob(key).download_as_bytes()

    def exists(self, key: str) -> bool:
        return self._bucket.blob(key).exists()

    def delete(self, key: str) -> None:
        self._bucket.blob(key).delete()

    def list(self, prefix: str) -> Iterable[str]:
        return [blob.name for blob in self._bucket.list_blobs(prefix=prefix)]
