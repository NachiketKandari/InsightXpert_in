"""Server-Sent Events primitives: chunk taxonomy + async emitter."""

from .chunks import ChatChunk, ChunkType
from .emitter import EventEmitter

__all__ = ["ChatChunk", "ChunkType", "EventEmitter"]
