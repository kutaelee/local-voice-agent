from __future__ import annotations

import asyncio
import base64
from uuid import uuid4

import pytest

from local_voice_agent_server.application.model_switch import (
    ModelActivityBarrier,
)
from local_voice_agent_server.application.session_events import (
    VoiceSessionEventHandler,
)
from local_voice_agent_server.application.voice_turn import (
    ConversationReply,
    SynthesizedAudio,
    Transcript,
    VoiceEvent,
    VoiceTurnService,
)
from local_voice_agent_server.protocol.client_events import (
    validate_client_payload,
)


class FakeStt:
    async def transcribe(self, audio: bytes, **_: object) -> Transcript:
        assert audio == b"\x00\x01" * 160
        return Transcript("테스트입니다.", "ko", 0.9)


class FakeConversation:
    async def respond(self, text: str, **_: object) -> str:
        assert text == "테스트입니다."
        return "확인했습니다."


class FakeTts:
    async def synthesize(self, text: str, **_: object) -> SynthesizedAudio:
        assert text == "확인했습니다."
        return SynthesizedAudio(b"\x00\x00" * 120, 24_000)


def factory(*_: object) -> VoiceTurnService:
    return VoiceTurnService(
        stt=FakeStt(),
        conversation=FakeConversation(),
        tts=FakeTts(),
    )


def test_voice_session_routes_complete_turn_and_releases_session() -> None:
    async def scenario() -> None:
        barrier = ModelActivityBarrier()
        handler = VoiceSessionEventHandler(
            factory,
            model_activity_barrier=barrier,
        )
        session_id = uuid4()
        request_id = uuid4()
        stream_id = uuid4()
        started = await handler.handle(
            session_id=session_id,
            request_id=request_id,
            event_type="audio.input.start",
            payload=validate_client_payload(
                "audio.input.start",
                {
                    "audio_stream_id": str(stream_id),
                    "encoding": "pcm_s16le",
                    "sample_rate_hz": 16000,
                    "channels": 1,
                },
            ),
        )
        assert [event.type for event in started] == ["assistant.state"]
        chunked = await handler.handle(
            session_id=session_id,
            request_id=request_id,
            event_type="audio.input.chunk",
            payload=validate_client_payload(
                "audio.input.chunk",
                {
                    "audio_stream_id": str(stream_id),
                    "chunk_index": 0,
                    "encoding": "pcm_s16le",
                    "duration_ms": 20,
                    "data_base64": base64.b64encode(b"\x00\x01" * 160).decode(),
                },
            ),
        )
        assert chunked == []
        completed = await handler.handle(
            session_id=session_id,
            request_id=request_id,
            event_type="audio.input.end",
            payload=validate_client_payload(
                "audio.input.end",
                {
                    "audio_stream_id": str(stream_id),
                    "reason": "vad_end",
                },
            ),
        )
        assert completed[-1].type == "audio.output.end"
        assert barrier.active_users == 0

        restarted = await handler.handle(
            session_id=session_id,
            request_id=uuid4(),
            event_type="audio.input.start",
            payload=validate_client_payload(
                "audio.input.start",
                {
                    "audio_stream_id": str(uuid4()),
                    "encoding": "pcm_s16le",
                    "sample_rate_hz": 16000,
                    "channels": 1,
                },
            ),
        )
        assert restarted[0].payload["state"] == "listening"

    asyncio.run(scenario())


def test_voice_session_blocks_model_switch_until_response_finishes() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        class BlockingConversation:
            async def respond(self, text: str, **_: object) -> str:
                assert text
                entered.set()
                await release.wait()
                return "확인했습니다."

        def blocking_factory(*_: object) -> VoiceTurnService:
            return VoiceTurnService(
                stt=FakeStt(),
                conversation=BlockingConversation(),
                tts=FakeTts(),
            )

        barrier = ModelActivityBarrier(drain_timeout_seconds=1)
        handler = VoiceSessionEventHandler(
            blocking_factory,
            model_activity_barrier=barrier,
        )
        session_id = uuid4()
        stream_id = uuid4()
        await handler.handle(
            session_id=session_id,
            request_id=uuid4(),
            event_type="audio.input.start",
            payload=validate_client_payload(
                "audio.input.start",
                {
                    "audio_stream_id": str(stream_id),
                    "encoding": "pcm_s16le",
                    "sample_rate_hz": 16_000,
                    "channels": 1,
                },
            ),
        )
        await handler.handle(
            session_id=session_id,
            request_id=uuid4(),
            event_type="audio.input.chunk",
            payload=validate_client_payload(
                "audio.input.chunk",
                {
                    "audio_stream_id": str(stream_id),
                    "chunk_index": 0,
                    "encoding": "pcm_s16le",
                    "duration_ms": 20,
                    "data_base64": base64.b64encode(b"\x00\x01" * 160).decode(),
                },
            ),
        )
        processing = asyncio.create_task(
            handler.handle(
                session_id=session_id,
                request_id=uuid4(),
                event_type="audio.input.end",
                payload=validate_client_payload(
                    "audio.input.end",
                    {
                        "audio_stream_id": str(stream_id),
                        "reason": "vad_end",
                    },
                ),
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=1)
        switching = asyncio.create_task(barrier.begin_switch())
        await asyncio.sleep(0)
        assert switching.done() is False

        release.set()
        await asyncio.wait_for(processing, timeout=1)
        await asyncio.wait_for(switching, timeout=1)
        assert barrier.active_users == 0
        await barrier.end_switch()

    asyncio.run(scenario())


def test_barge_in_cancels_active_capture() -> None:
    async def scenario() -> None:
        handler = VoiceSessionEventHandler(factory)
        session_id = uuid4()
        stream_id = uuid4()
        await handler.handle(
            session_id=session_id,
            request_id=uuid4(),
            event_type="audio.input.start",
            payload=validate_client_payload(
                "audio.input.start",
                {
                    "audio_stream_id": str(stream_id),
                    "encoding": "pcm_s16le",
                    "sample_rate_hz": 16000,
                    "channels": 1,
                },
            ),
        )
        result = await handler.handle(
            session_id=session_id,
            request_id=uuid4(),
            event_type="audio.input.end",
            payload=validate_client_payload(
                "audio.input.end",
                {
                    "audio_stream_id": str(stream_id),
                    "reason": "barge_in",
                },
            ),
        )
        assert result[0].payload["state"] == "interrupted"

    asyncio.run(scenario())


def test_cancel_interrupts_processing_and_allows_next_turn() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        class BlockingConversation:
            async def respond(self, text: str, **_: object) -> str:
                assert text
                entered.set()
                await release.wait()
                return "?뺤씤?덉뒿?덈떎."

        def blocking_factory(*_: object) -> VoiceTurnService:
            return VoiceTurnService(
                stt=FakeStt(),
                conversation=BlockingConversation(),
                tts=FakeTts(),
            )

        handler = VoiceSessionEventHandler(blocking_factory)
        session_id = uuid4()
        response_request_id = uuid4()
        stream_id = uuid4()
        await handler.handle(
            session_id=session_id,
            request_id=uuid4(),
            event_type="audio.input.start",
            payload=validate_client_payload(
                "audio.input.start",
                {
                    "audio_stream_id": str(stream_id),
                    "encoding": "pcm_s16le",
                    "sample_rate_hz": 16000,
                    "channels": 1,
                },
            ),
        )
        await handler.handle(
            session_id=session_id,
            request_id=uuid4(),
            event_type="audio.input.chunk",
            payload=validate_client_payload(
                "audio.input.chunk",
                {
                    "audio_stream_id": str(stream_id),
                    "chunk_index": 0,
                    "encoding": "pcm_s16le",
                    "duration_ms": 20,
                    "data_base64": base64.b64encode(b"\x00\x01" * 160).decode(),
                },
            ),
        )
        processing = asyncio.create_task(
            handler.handle(
                session_id=session_id,
                request_id=response_request_id,
                event_type="audio.input.end",
                payload=validate_client_payload(
                    "audio.input.end",
                    {
                        "audio_stream_id": str(stream_id),
                        "reason": "vad_end",
                    },
                ),
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=1)

        cancel_payload = validate_client_payload(
            "operation.cancel.requested",
            {
                "target_kind": "assistant_response",
                "target_id": str(response_request_id),
                "reason": "barge_in",
                "idempotency_key": str(uuid4()),
            },
        )
        cancelled = await handler.handle(
            session_id=session_id,
            request_id=uuid4(),
            event_type="operation.cancel.requested",
            payload=cancel_payload,
        )
        duplicate = await handler.handle(
            session_id=session_id,
            request_id=uuid4(),
            event_type="operation.cancel.requested",
            payload=cancel_payload,
        )
        assert [event.type for event in cancelled] == [
            "operation.cancel.result",
            "assistant.state",
        ]
        assert cancelled[0].payload["status"] == "cancellation_requested"
        assert duplicate == cancelled
        with pytest.raises(asyncio.CancelledError):
            await processing

        restarted = await handler.handle(
            session_id=session_id,
            request_id=uuid4(),
            event_type="audio.input.start",
            payload=validate_client_payload(
                "audio.input.start",
                {
                    "audio_stream_id": str(uuid4()),
                    "encoding": "pcm_s16le",
                    "sample_rate_hz": 16000,
                    "channels": 1,
                },
            ),
        )
        assert restarted[0].payload["state"] == "listening"

    asyncio.run(scenario())


def test_pending_tool_approval_resumes_same_voice_turn() -> None:
    async def scenario() -> None:
        expected_approval_id = uuid4()
        digest = "a" * 64

        class ApprovalConversation:
            async def respond(self, text: str, **_: object) -> ConversationReply:
                assert text
                return ConversationReply(
                    text=None,
                    events=(
                        VoiceEvent(
                            "assistant.state",
                            {"state": "waiting_approval"},
                        ),
                    ),
                    pending_approval_id=expected_approval_id,
                )

            async def decide_approval(
                self,
                *,
                approval_id: object,
                approved: bool,
                arguments_digest: str,
                **_: object,
            ) -> ConversationReply:
                assert approval_id == expected_approval_id
                assert approved is True
                assert arguments_digest == digest
                return ConversationReply(text="승인된 작업을 완료했습니다.")

        class ApprovalTts:
            async def synthesize(
                self,
                text: str,
                **_: object,
            ) -> SynthesizedAudio:
                assert text == "승인된 작업을 완료했습니다."
                return SynthesizedAudio(b"\x00\x00" * 120, 24_000)

        def approval_factory(*_: object) -> VoiceTurnService:
            return VoiceTurnService(
                stt=FakeStt(),
                conversation=ApprovalConversation(),
                tts=ApprovalTts(),
            )

        barrier = ModelActivityBarrier()
        handler = VoiceSessionEventHandler(
            approval_factory,
            model_activity_barrier=barrier,
        )
        session_id = uuid4()
        stream_id = uuid4()
        response_request_id = uuid4()
        await handler.handle(
            session_id=session_id,
            request_id=uuid4(),
            event_type="audio.input.start",
            payload=validate_client_payload(
                "audio.input.start",
                {
                    "audio_stream_id": str(stream_id),
                    "encoding": "pcm_s16le",
                    "sample_rate_hz": 16_000,
                    "channels": 1,
                },
            ),
        )
        await handler.handle(
            session_id=session_id,
            request_id=uuid4(),
            event_type="audio.input.chunk",
            payload=validate_client_payload(
                "audio.input.chunk",
                {
                    "audio_stream_id": str(stream_id),
                    "chunk_index": 0,
                    "encoding": "pcm_s16le",
                    "duration_ms": 20,
                    "data_base64": base64.b64encode(b"\x00\x01" * 160).decode(),
                },
            ),
        )
        pending = await handler.handle(
            session_id=session_id,
            request_id=response_request_id,
            event_type="audio.input.end",
            payload=validate_client_payload(
                "audio.input.end",
                {
                    "audio_stream_id": str(stream_id),
                    "reason": "vad_end",
                },
            ),
        )
        assert pending[-1].payload["state"] == "waiting_approval"
        assert barrier.active_users == 1
        await handler.disconnect(
            session_id=session_id,
            preserve_pending_approval=True,
        )
        assert barrier.active_users == 1

        resumed = await handler.handle(
            session_id=session_id,
            request_id=uuid4(),
            event_type="tool.approval.response",
            payload=validate_client_payload(
                "tool.approval.response",
                {
                    "approval_id": str(expected_approval_id),
                    "decision": "approve",
                    "arguments_digest": digest,
                },
            ),
        )
        assert resumed[-1].type == "audio.output.end"
        assert barrier.active_users == 0

    asyncio.run(scenario())
