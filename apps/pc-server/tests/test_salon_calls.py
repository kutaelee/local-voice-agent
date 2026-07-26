import asyncio
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from local_voice_agent_server.application.salon_calls import (
    SalonCallCoordinator,
    SalonFaqDecision,
    SalonTurnDecision,
)
from local_voice_agent_server.domain.salon_booking import (
    ReservationRequest,
    SalonReservationService,
)
from local_voice_agent_server.infrastructure.file_reservations import (
    FileReservationStore,
)
from local_voice_agent_server.infrastructure.salon_config import load_salon_policy


REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = REPO_ROOT / "configs" / "salon-booking.json"


def _coordinator(
    tmp_path: Path,
    *,
    faq_responder=None,
    conversation_responder=None,
) -> SalonCallCoordinator:
    policy = load_salon_policy(POLICY_PATH)
    now = lambda: datetime(2026, 7, 25, 9, 0, tzinfo=policy.timezone)
    service = SalonReservationService(
        policy=policy,
        repository=FileReservationStore(
            data_path=tmp_path / "reservations.json",
            backup_root=tmp_path / "backup",
        ),
        now=now,
    )
    return SalonCallCoordinator(
        reservations=service,
        now=now,
        faq_responder=faq_responder,
        conversation_responder=conversation_responder,
    )


def _texts(events) -> list[str]:
    return [
        str(event.payload["text"])
        for event in events
        if event.type == "salon.assistant.message"
    ]


def test_call_starts_with_bounded_salon_persona(tmp_path: Path) -> None:
    async def scenario() -> None:
        coordinator = _coordinator(tmp_path)
        events = await coordinator.handle(
            session_id=uuid4(),
            event_type="salon.call.start",
        )
        assert [event.type for event in events] == [
            "salon.call.started",
            "salon.assistant.message",
            "assistant.state",
        ]
        assert _texts(events)[0] == (
            "안녕하세요, 윤슬 헤어 수아입니다."
        )

    asyncio.run(scenario())


def test_scope_guard_answers_salon_questions_and_refuses_unrelated_topics(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        coordinator = _coordinator(tmp_path)
        session_id = uuid4()
        await coordinator.handle(session_id=session_id, event_type="salon.call.start")
        price = await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text="커트 가격은 얼마예요?",
        )
        weather = await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text="오늘 서울 날씨 알려줘",
        )
        assert "커트 25,000원" in _texts(price)[0]
        assert "미용실 예약" in _texts(weather)[0]
        assert "날씨" not in _texts(weather)[0]

    asyncio.run(scenario())


def test_optional_model_answers_only_scoped_unknown_faq(tmp_path: Path) -> None:
    class FaqResponder:
        async def answer(self, question: str) -> SalonFaqDecision:
            if "두 명" in question:
                return SalonFaqDecision(
                    in_scope=True,
                    answer="동시간대 담당자 여유가 있으면 두 분 모두 예약할 수 있습니다.",
                )
            return SalonFaqDecision(in_scope=False, answer="")

    async def scenario() -> None:
        coordinator = _coordinator(tmp_path, faq_responder=FaqResponder())
        session_id = uuid4()
        await coordinator.handle(session_id=session_id, event_type="salon.call.start")
        party = await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text="친구와 두 명이 같이 받을 수 있나요?",
        )
        weather = await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text="내일 날씨는 어떤가요?",
        )

        assert "두 분 모두" in _texts(party)[0]
        assert "미용실 예약" in _texts(weather)[0]

    asyncio.run(scenario())


def test_conversation_model_drives_natural_reply_instead_of_echo(
    tmp_path: Path,
) -> None:
    class Harness:
        async def decide(self, **kwargs) -> SalonTurnDecision:
            assert kwargs["user_message"] == "커트하고 싶은데요"
            return SalonTurnDecision(
                in_scope=True,
                action="book",
                service_id="haircut",
                reply="좋아요. 언제 방문하시면 편하실까요?",
            )

        async def complete(self, **kwargs) -> str:
            raise AssertionError("no tool should run before details are complete")

    async def scenario() -> None:
        coordinator = _coordinator(
            tmp_path,
            conversation_responder=Harness(),
        )
        session_id = uuid4()
        await coordinator.handle(session_id=session_id, event_type="salon.call.start")
        events = await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text="커트하고 싶은데요",
        )
        assert _texts(events) == ["좋아요. 언제 방문하시면 편하실까요?"]

    asyncio.run(scenario())


def test_model_date_only_availability_returns_real_schedule_slots(
    tmp_path: Path,
) -> None:
    captured = {}

    class Harness:
        async def decide(self, **kwargs) -> SalonTurnDecision:
            return SalonTurnDecision(
                in_scope=True,
                action="availability",
                service_id="haircut",
                requested_date=date(2026, 7, 28),
                reply="다음 주 화요일 커트 가능한 시간을 확인해 볼게요.",
            )

        async def complete(self, **kwargs) -> str:
            captured.update(kwargs["tool_result"])
            return "화요일 오전 열 시와 열 시 삼십 분부터 가능해요. 어느 시간이 편하세요?"

    async def scenario() -> None:
        coordinator = _coordinator(
            tmp_path,
            conversation_responder=Harness(),
        )
        session_id = uuid4()
        await coordinator.handle(session_id=session_id, event_type="salon.call.start")
        events = await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text="다음 주 화요일 커트 가능한 시간이 언제예요?",
        )

        assert captured["operation"] == "availability_by_date"
        assert captured["requested_date"] == "2026-07-28"
        slots = captured["available_slots"]
        assert isinstance(slots, list)
        assert slots[0]["starts_at"].startswith("2026-07-28T10:00:00")
        assert _texts(events) == [
            "화요일 오전 열 시와 열 시 삼십 분부터 가능해요. 어느 시간이 편하세요?"
        ]

    asyncio.run(scenario())


def test_model_gate_searches_real_earliest_slot_without_asking_for_date(
    tmp_path: Path,
) -> None:
    observed = {}

    class Harness:
        turn = 0

        async def decide(self, **kwargs) -> SalonTurnDecision:
            self.turn += 1
            if self.turn == 1:
                return SalonTurnDecision(
                    in_scope=True,
                    action="book",
                    service_id="color",
                    reply="원하시는 날짜가 있으실까요?",
                )
            return SalonTurnDecision(
                in_scope=True,
                action="respond",
                reply="원하시는 날짜를 말씀해 주세요.",
            )

        async def complete(self, **kwargs) -> str:
            observed.update(kwargs["tool_result"])
            return "가장 빠른 시간은 오늘 오전 열 시예요. 이 시간으로 도와드릴까요?"

    async def scenario() -> None:
        coordinator = _coordinator(
            tmp_path,
            conversation_responder=Harness(),
        )
        session_id = uuid4()
        await coordinator.handle(session_id=session_id, event_type="salon.call.start")
        await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text="염색하고 싶어요.",
        )
        events = await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text="아니요, 제일 빠른 날짜요.",
        )

        assert observed["operation"] == "availability_search"
        assert observed["search_mode"] == "earliest"
        assert observed["available_slots"][0]["starts_at"].startswith(
            "2026-07-25T10:00:00"
        )
        assert "날짜를 말씀해" not in _texts(events)[0]

    asyncio.run(scenario())


def test_model_gate_finds_next_date_at_requested_time(
    tmp_path: Path,
) -> None:
    observed = {}

    class Harness:
        turn = 0

        async def decide(self, **kwargs) -> SalonTurnDecision:
            self.turn += 1
            if self.turn == 1:
                return SalonTurnDecision(
                    in_scope=True,
                    action="availability",
                    service_id="down_perm",
                    requested_date=date(2026, 7, 26),
                    reply="26일 가능한 시간을 확인해 볼게요.",
                )
            return SalonTurnDecision(
                in_scope=True,
                action="respond",
                reply="다른 날짜를 말씀해 주세요.",
            )

        async def complete(self, **kwargs) -> str:
            observed.clear()
            observed.update(kwargs["tool_result"])
            return "오전 열한 시는 28일 화요일에 가장 빨리 가능해요."

    async def scenario() -> None:
        coordinator = _coordinator(
            tmp_path,
            conversation_responder=Harness(),
        )
        session_id = uuid4()
        await coordinator.handle(session_id=session_id, event_type="salon.call.start")
        await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text="26일 다운펌 가능한가요?",
        )
        events = await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text="그날 말고 11시 되는 날짜가 언제예요?",
        )

        assert observed["operation"] == "availability_search"
        assert observed["search_mode"] == "next_at_time"
        assert observed["requested_time"] == "11:00"
        assert observed["available_slots"][0]["starts_at"].startswith(
            "2026-07-28T11:00:00"
        )
        assert "28일" in _texts(events)[0]

    asyncio.run(scenario())


def test_model_booking_checks_live_availability_before_confirmation(
    tmp_path: Path,
) -> None:
    observed = {}

    class Harness:
        async def decide(self, **kwargs) -> SalonTurnDecision:
            return SalonTurnDecision(
                in_scope=True,
                action="book",
                service_id="haircut",
                starts_at=datetime(
                    2026,
                    7,
                    26,
                    14,
                    0,
                    tzinfo=coordinator.policy.timezone,
                ),
                customer_name="김규태",
                phone="01012345678",
                reply="가능합니다. 바로 예약해 드릴게요.",
            )

        async def complete(self, **kwargs) -> str:
            observed.update(kwargs["tool_result"])
            return "해당 시간은 예약 가능합니다. 이 내용으로 예약을 진행할까요?"

    async def scenario() -> None:
        nonlocal coordinator
        coordinator = _coordinator(
            tmp_path,
            conversation_responder=Harness(),
        )
        session_id = uuid4()
        await coordinator.handle(session_id=session_id, event_type="salon.call.start")
        events = await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text="7월 26일 오후 2시에 커트 예약할게요. 김규태, 010-1234-5678입니다.",
        )

        assert observed["operation"] == "availability"
        assert observed["ok"] is True
        assert observed["next_step"] == "request_booking_confirmation"
        assert _texts(events) == [
            "해당 시간은 예약 가능합니다. 이 내용으로 예약을 진행할까요?"
        ]
        assert coordinator._reservations.list_reservations() == ()

    coordinator: SalonCallCoordinator
    asyncio.run(scenario())


def test_model_checks_requested_staff_before_collecting_contact(
    tmp_path: Path,
) -> None:
    observed = {}

    class Harness:
        async def decide(self, **kwargs) -> SalonTurnDecision:
            return SalonTurnDecision(
                in_scope=True,
                action="book",
                service_id="digital_perm",
                staff_id="minji",
                starts_at=datetime(
                    2026,
                    7,
                    29,
                    14,
                    0,
                    tzinfo=coordinator.policy.timezone,
                ),
                customer_name="이규태",
                reply="민지 선생님께 예약을 도와드릴게요. 연락처를 알려주시겠어요?",
            )

        async def complete(self, **kwargs) -> str:
            observed.update(kwargs["tool_result"])
            return "그 시간에는 민지 선생님 예약이 어렵고 준 선생님은 가능해요. 담당자를 변경해 드릴까요?"

    async def scenario() -> None:
        nonlocal coordinator
        coordinator = _coordinator(
            tmp_path,
            conversation_responder=Harness(),
        )
        coordinator._reservations.create(
            ReservationRequest(
                customer_name="기존 고객",
                phone="01011112222",
                service_id="digital_perm",
                staff_id="minji",
                starts_at=datetime(
                    2026,
                    7,
                    29,
                    14,
                    0,
                    tzinfo=coordinator.policy.timezone,
                ),
            )
        )
        session_id = uuid4()
        await coordinator.handle(session_id=session_id, event_type="salon.call.start")
        events = await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text="7월 29일 오후 2시에 민지 선생님 디지털 펌 예약할게요. 이규태입니다.",
        )

        assert observed["ok"] is False
        assert observed["requested_staff_name"] == "민지"
        assert observed["requested_staff_available"] is False
        assert observed["available_staff"] == ["준"]
        assert observed["next_step"] == "offer_an_available_alternative"
        assert "민지 선생님 예약이 어렵고" in _texts(events)[0]
        assert coordinator._reservations.list_reservations()[0].customer_name == "기존 고객"

    coordinator: SalonCallCoordinator
    asyncio.run(scenario())


def test_conversation_model_echo_is_rejected(tmp_path: Path) -> None:
    class Harness:
        async def decide(self, **kwargs) -> SalonTurnDecision:
            message = kwargs["user_message"]
            return SalonTurnDecision(
                in_scope=True,
                action="respond",
                reply=message,
            )

        async def complete(self, **kwargs) -> str:
            raise AssertionError

    async def scenario() -> None:
        coordinator = _coordinator(
            tmp_path,
            conversation_responder=Harness(),
        )
        session_id = uuid4()
        await coordinator.handle(session_id=session_id, event_type="salon.call.start")
        events = await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text="오늘 커트하고 싶어요",
        )
        assert _texts(events)[0] != "오늘 커트하고 싶어요"
        assert "정확히 처리하지 못했어요" in _texts(events)[0]
        assert events[0].payload["fallback"] == "model_decision_rejected"

    asyncio.run(scenario())


def test_multi_turn_booking_emits_owner_notification(tmp_path: Path) -> None:
    async def scenario() -> None:
        coordinator = _coordinator(tmp_path)
        session_id = uuid4()
        await coordinator.handle(session_id=session_id, event_type="salon.call.start")
        confirmation = await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text=(
                "7월 26일 오후 2시에 커트 예약할게요. "
                "이름은 김규태고 010-1234-5678입니다."
            ),
        )
        assert "예약할까요" in _texts(confirmation)[0]
        changed = await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text="네",
        )
        assert [event.type for event in changed] == [
            "salon.assistant.message",
            "salon.reservation.updated",
            "salon.owner.notification",
        ]
        assert "예약이 확정됐습니다" in _texts(changed)[0]
        assert changed[1].payload["change_type"] == "created"

    asyncio.run(scenario())


def test_availability_flows_into_booking_without_losing_slot(tmp_path: Path) -> None:
    async def scenario() -> None:
        coordinator = _coordinator(tmp_path)
        session_id = uuid4()
        await coordinator.handle(session_id=session_id, event_type="salon.call.start")
        available = await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text="7월 26일 오후 3시에 염색 가능해요?",
        )
        ask_name = await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text="예약해주세요",
        )
        assert "예약이 가능합니다" in _texts(available)[0]
        assert "예약자 이름" in _texts(ask_name)[0]

    asyncio.run(scenario())


def test_booking_confirmation_can_be_rejected_without_writing(tmp_path: Path) -> None:
    async def scenario() -> None:
        coordinator = _coordinator(tmp_path)
        session_id = uuid4()
        await coordinator.handle(session_id=session_id, event_type="salon.call.start")
        await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text=(
                "7월 26일 오후 2시에 커트 예약. "
                "이름은 김규태, 010-1234-5678"
            ),
        )
        rejected = await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text="아니요",
        )
        assert "반영하지 않았습니다" in _texts(rejected)[0]
        assert coordinator._reservations.list_reservations() == ()

    asyncio.run(scenario())


def test_confirmed_booking_can_be_modified_and_cancelled(tmp_path: Path) -> None:
    async def book(
        coordinator: SalonCallCoordinator,
        session_id,
    ) -> str:
        await coordinator.handle(session_id=session_id, event_type="salon.call.start")
        await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text=(
                "7월 26일 오후 2시에 커트 예약할게요. "
                "이름은 김규태, 010-1234-5678"
            ),
        )
        created = await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text="네",
        )
        reservation = created[1].payload["reservation"]
        assert isinstance(reservation, dict)
        return str(reservation["reservation_code"])

    async def scenario() -> None:
        coordinator = _coordinator(tmp_path)
        code = await book(coordinator, uuid4())

        modify_session = uuid4()
        await coordinator.handle(
            session_id=modify_session,
            event_type="salon.call.start",
        )
        confirmation = await coordinator.handle(
            session_id=modify_session,
            event_type="salon.call.message",
            text=(
                f"예약번호 {code}, 010-1234-5678이고 "
                "7월 28일 오후 3시 30분으로 변경할게요"
            ),
        )
        assert "변경할까요" in _texts(confirmation)[0]
        modified = await coordinator.handle(
            session_id=modify_session,
            event_type="salon.call.message",
            text="네",
        )
        assert modified[1].payload["change_type"] == "modified"

        cancel_session = uuid4()
        await coordinator.handle(
            session_id=cancel_session,
            event_type="salon.call.start",
        )
        confirmation = await coordinator.handle(
            session_id=cancel_session,
            event_type="salon.call.message",
            text=f"예약번호 {code}, 010-1234-5678 예약 취소할게요",
        )
        assert "취소할까요" in _texts(confirmation)[0]
        cancelled = await coordinator.handle(
            session_id=cancel_session,
            event_type="salon.call.message",
            text="네",
        )
        assert cancelled[1].payload["change_type"] == "cancelled"

    asyncio.run(scenario())


def test_duplicate_and_closed_day_errors_are_explained(tmp_path: Path) -> None:
    async def create(
        coordinator: SalonCallCoordinator,
        session_id,
        phone: str,
        text: str,
    ):
        await coordinator.handle(session_id=session_id, event_type="salon.call.start")
        await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text=f"{text} 이름은 김규태, {phone}",
        )
        return await coordinator.handle(
            session_id=session_id,
            event_type="salon.call.message",
            text="네",
        )

    async def scenario() -> None:
        coordinator = _coordinator(tmp_path)
        await create(
            coordinator,
            uuid4(),
            "010-1234-5678",
            "7월 26일 오후 2시에 커트 예약.",
        )
        duplicate = await create(
            coordinator,
            uuid4(),
            "010-1234-5678",
            "7월 26일 오후 2시에 염색 예약.",
        )
        assert duplicate[0].payload["error_code"] == "DUPLICATE_RESERVATION"

        closed_session = uuid4()
        await coordinator.handle(
            session_id=closed_session,
            event_type="salon.call.start",
        )
        await coordinator.handle(
            session_id=closed_session,
            event_type="salon.call.message",
            text=(
                "7월 27일 오후 2시에 커트 예약. "
                "이름은 김규태, 010-9999-9999"
            ),
        )
        closed = await coordinator.handle(
            session_id=closed_session,
            event_type="salon.call.message",
            text="네",
        )
        assert closed[0].payload["error_code"] == "SALON_CLOSED"

    asyncio.run(scenario())
