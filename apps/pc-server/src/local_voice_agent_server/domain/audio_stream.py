"""Bounded, ordered audio-input aggregate with explicit terminal states."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


class AudioStreamError(ValueError):
    """A sanitized audio stream contract violation."""


class AudioStreamState(StrEnum):
    IDLE = "idle"
    CAPTURING = "capturing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class AudioStream:
    max_bytes: int = 8 * 1024 * 1024
    state: AudioStreamState = AudioStreamState.IDLE
    stream_id: UUID | None = None
    encoding: str | None = None
    sample_rate_hz: int | None = None
    channels: int | None = None
    next_chunk_index: int = 0
    duration_ms: int = 0
    _chunks: list[bytes] = field(default_factory=list, repr=False)
    _size_bytes: int = 0

    def start(
        self,
        *,
        stream_id: UUID,
        encoding: str,
        sample_rate_hz: int,
        channels: int,
    ) -> None:
        if self.state is AudioStreamState.CAPTURING:
            raise AudioStreamError("an audio stream is already active")
        if encoding != "pcm_s16le":
            raise AudioStreamError("only pcm_s16le is enabled")
        if sample_rate_hz not in {16_000, 24_000, 48_000}:
            raise AudioStreamError("sample rate is unsupported")
        if channels not in {1, 2}:
            raise AudioStreamError("channel count is unsupported")
        self.state = AudioStreamState.CAPTURING
        self.stream_id = stream_id
        self.encoding = encoding
        self.sample_rate_hz = sample_rate_hz
        self.channels = channels
        self.next_chunk_index = 0
        self.duration_ms = 0
        self._chunks.clear()
        self._size_bytes = 0

    def append(
        self,
        *,
        stream_id: UUID,
        chunk_index: int,
        data: bytes,
        duration_ms: int,
    ) -> None:
        self._require_active(stream_id)
        if chunk_index != self.next_chunk_index:
            raise AudioStreamError("audio chunk is out of order")
        if not data:
            raise AudioStreamError("audio chunk is empty")
        if duration_ms < 1 or duration_ms > 1_000:
            raise AudioStreamError("audio chunk duration is invalid")
        projected = self._size_bytes + len(data)
        if projected > self.max_bytes:
            raise AudioStreamError("audio stream exceeds the byte limit")
        self._chunks.append(bytes(data))
        self._size_bytes = projected
        self.duration_ms += duration_ms
        self.next_chunk_index += 1

    def finish(self, *, stream_id: UUID) -> bytes:
        self._require_active(stream_id)
        if not self._chunks:
            raise AudioStreamError("audio stream has no chunks")
        self.state = AudioStreamState.COMPLETED
        return b"".join(self._chunks)

    def cancel(self, *, stream_id: UUID) -> None:
        self._require_active(stream_id)
        self.state = AudioStreamState.CANCELLED
        self._chunks.clear()
        self._size_bytes = 0

    @property
    def size_bytes(self) -> int:
        return self._size_bytes

    def _require_active(self, stream_id: UUID) -> None:
        if self.state is not AudioStreamState.CAPTURING:
            raise AudioStreamError("no audio stream is active")
        if self.stream_id != stream_id:
            raise AudioStreamError("audio stream id does not match")
