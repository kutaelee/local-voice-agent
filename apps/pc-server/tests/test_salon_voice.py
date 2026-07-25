import asyncio
from uuid import uuid4

from local_voice_agent_server.application.salon_calls import SalonEvent
from local_voice_agent_server.application.salon_voice import SalonVoiceConversation


class FakeCoordinator:
    def __init__(self) -> None:
        self.calls = []

    async def handle(self, **kwargs):
        self.calls.append(kwargs)
        return [
            SalonEvent(
                "salon.assistant.message",
                {"text": "화요일 오전 열 시부터 가능해요. 어느 시간이 편하세요?"},
            ),
            SalonEvent(
                "salon.reservation.updated",
                {"change_type": "observed"},
            ),
            SalonEvent("assistant.state", {"state": "listening"}),
        ]


def test_voice_turn_uses_active_salon_conversation_and_forwards_domain_events() -> None:
    coordinator = FakeCoordinator()
    session_id = uuid4()
    conversation = SalonVoiceConversation(
        coordinator=coordinator,
        session_id=session_id,
    )

    reply = asyncio.run(
        conversation.respond(
            "다음 주 화요일 커트 가능한 시간이 언제예요?",
            language="ko",
        )
    )

    assert coordinator.calls == [
        {
            "session_id": session_id,
            "event_type": "salon.call.message",
            "text": "다음 주 화요일 커트 가능한 시간이 언제예요?",
        }
    ]
    assert reply.text == "화요일 오전 열 시부터 가능해요. 어느 시간이 편하세요?"
    assert [event.type for event in reply.events] == ["salon.reservation.updated"]
