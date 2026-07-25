"""Route speech turns through an active salon call instead of the generic assistant."""

from __future__ import annotations

from uuid import UUID

from .salon_calls import SalonCallCoordinator
from .voice_turn import ConversationReply, VoiceEvent


class SalonVoiceConversation:
    """Conversation port backed by the same model-led salon call aggregate."""

    def __init__(
        self,
        *,
        coordinator: SalonCallCoordinator,
        session_id: UUID,
    ) -> None:
        self._coordinator = coordinator
        self._session_id = session_id

    async def respond(
        self,
        text: str,
        *,
        language: str,
    ) -> ConversationReply:
        if language not in {"ko", "kor", "ko-KR"}:
            raise ValueError("salon voice conversation currently requires Korean")
        events = await self._coordinator.handle(
            session_id=self._session_id,
            event_type="salon.call.message",
            text=text,
        )
        replies = [
            str(event.payload["text"])
            for event in events
            if event.type == "salon.assistant.message"
        ]
        if len(replies) != 1:
            raise ValueError("salon voice turn did not produce one reply")
        forwarded = tuple(
            VoiceEvent(event.type, dict(event.payload))
            for event in events
            if event.type not in {"salon.assistant.message", "assistant.state"}
        )
        return ConversationReply(text=replies[0], events=forwarded)

    async def decide_approval(
        self,
        *,
        approval_id: UUID,
        approved: bool,
        arguments_digest: str,
        reason: str | None,
    ) -> ConversationReply:
        del approval_id, approved, arguments_digest, reason
        raise ValueError("salon reservation confirmation uses the next caller turn")
