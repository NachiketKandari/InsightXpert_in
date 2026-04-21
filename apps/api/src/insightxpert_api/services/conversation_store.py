"""In-memory conversation store for v1.

Per-session list of conversations; each conversation is an ordered list of messages + the
replay buffer of SSE chunks seen since the conversation was opened (so the UI can re-render
on refresh while the Cloud Run instance is alive).

v1 accepts the tradeoff that state is lost on instance recycle. Slice 2+ will swap this out
for a GCS snapshot or Neon Postgres — the ``ConversationStore`` contract stays the same.
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from time import time
from typing import Any


@dataclass
class Message:
    message_id: str
    role: str  # "user" | "assistant"
    content: str
    created_at: float = field(default_factory=time)


@dataclass
class Conversation:
    conversation_id: str
    session_id: str
    title: str | None = None
    starred: bool = False
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)
    messages: list[Message] = field(default_factory=list)
    chunks: list[dict[str, Any]] = field(default_factory=list)  # SSE replay buffer

    def touch(self) -> None:
        self.updated_at = time()


class ConversationNotFoundError(KeyError):
    """Raised on lookups/mutations for missing (session_id, conversation_id)."""


class ConversationStore:
    """Thread-safe in-memory store. One instance per Cloud Run process.

    Keys: ``(session_id, conversation_id) -> Conversation``.
    """

    def __init__(self) -> None:
        # OrderedDict preserves insertion order for list() endpoints.
        self._convos: dict[tuple[str, str], Conversation] = OrderedDict()
        self._lock = threading.RLock()

    # ---- Creation & lookup ------------------------------------------------

    def create(self, session_id: str, title: str | None = None) -> Conversation:
        with self._lock:
            cid = str(uuid.uuid4())
            convo = Conversation(conversation_id=cid, session_id=session_id, title=title)
            self._convos[(session_id, cid)] = convo
            return convo

    def get(self, session_id: str, conversation_id: str) -> Conversation:
        with self._lock:
            try:
                return self._convos[(session_id, conversation_id)]
            except KeyError as e:
                raise ConversationNotFoundError(conversation_id) from e

    def get_or_create(self, session_id: str, conversation_id: str | None) -> Conversation:
        if conversation_id is None:
            return self.create(session_id)
        with self._lock:
            existing = self._convos.get((session_id, conversation_id))
            if existing is not None:
                return existing
            # Caller supplied an unknown id — materialize it so chunks have a home.
            convo = Conversation(conversation_id=conversation_id, session_id=session_id)
            self._convos[(session_id, conversation_id)] = convo
            return convo

    def list(self, session_id: str) -> list[Conversation]:
        with self._lock:
            return [
                c
                for (s, _), c in self._convos.items()
                if s == session_id
            ]

    # ---- Mutations --------------------------------------------------------

    def append_message(
        self,
        session_id: str,
        conversation_id: str,
        *,
        role: str,
        content: str,
    ) -> Message:
        with self._lock:
            convo = self.get(session_id, conversation_id)
            msg = Message(message_id=str(uuid.uuid4()), role=role, content=content)
            convo.messages.append(msg)
            convo.touch()
            return msg

    def append_chunk(
        self,
        session_id: str,
        conversation_id: str,
        chunk: dict[str, Any],
    ) -> None:
        """Append a serialized SSE chunk to the replay buffer."""
        with self._lock:
            convo = self.get(session_id, conversation_id)
            convo.chunks.append(chunk)
            convo.touch()

    def rename(self, session_id: str, conversation_id: str, title: str | None) -> Conversation:
        with self._lock:
            convo = self.get(session_id, conversation_id)
            convo.title = title
            convo.touch()
            return convo

    def set_starred(
        self, session_id: str, conversation_id: str, starred: bool
    ) -> Conversation:
        with self._lock:
            convo = self.get(session_id, conversation_id)
            convo.starred = starred
            convo.touch()
            return convo

    def delete(self, session_id: str, conversation_id: str) -> None:
        with self._lock:
            key = (session_id, conversation_id)
            if key not in self._convos:
                raise ConversationNotFoundError(conversation_id)
            del self._convos[key]

    # ---- Serialization helpers -------------------------------------------

    @staticmethod
    def to_dict(convo: Conversation) -> dict[str, Any]:
        return asdict(convo)


# Module-level singleton for the FastAPI process. Tests can construct their own instance.
_store = ConversationStore()


def get_conversation_store() -> ConversationStore:
    """FastAPI dependency."""
    return _store
