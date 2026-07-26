"""Salon call persona with a model-led conversation and guarded booking tools."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
import logging
import re
from typing import Callable, Literal, Protocol
from uuid import UUID, uuid4

from ..domain.salon_booking import (
    Reservation,
    ReservationRequest,
    SalonBookingError,
    SalonPolicy,
    SalonReservationService,
    local_datetime,
)


SalonAction = Literal["availability", "book", "cancel", "modify"]
SalonModelAction = Literal["respond", "availability", "book", "cancel", "modify"]
logger = logging.getLogger(__name__)


class SalonFaqResponderError(RuntimeError):
    """A bounded language adapter could not return a validated FAQ decision."""


@dataclass(frozen=True, slots=True)
class SalonFaqDecision:
    in_scope: bool
    answer: str


class SalonFaqResponder(Protocol):
    async def answer(self, question: str) -> SalonFaqDecision: ...


@dataclass(frozen=True, slots=True)
class SalonTurnDecision:
    """Validated model output; it is a proposal, never authority to mutate data."""

    in_scope: bool
    action: SalonModelAction
    reply: str
    service_id: str | None = None
    staff_id: str | None = None
    starts_at: datetime | None = None
    requested_date: date | None = None
    customer_name: str | None = None
    phone: str | None = None
    reservation_code: str | None = None
    confirmed: bool = False


class SalonConversationResponder(Protocol):
    async def decide(
        self,
        *,
        user_message: str,
        state: dict[str, object],
        history: tuple[dict[str, str], ...],
        now: datetime,
    ) -> SalonTurnDecision: ...

    async def complete(
        self,
        *,
        user_message: str,
        state: dict[str, object],
        history: tuple[dict[str, str], ...],
        tool_result: dict[str, object],
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class SalonEvent:
    type: str
    payload: dict[str, object]


@dataclass(slots=True)
class SalonCallState:
    call_id: UUID
    started_at: datetime
    action: SalonAction | None = None
    service_id: str | None = None
    staff_id: str | None = None
    starts_at: datetime | None = None
    requested_date: date | None = None
    customer_name: str | None = None
    phone: str | None = None
    reservation_code: str | None = None
    awaiting_confirmation: bool = False
    history: list[dict[str, str]] = field(default_factory=list)

    def clear_transaction(self) -> None:
        self.action = None
        self.service_id = None
        self.staff_id = None
        self.starts_at = None
        self.requested_date = None
        self.customer_name = None
        self.phone = None
        self.reservation_code = None
        self.awaiting_confirmation = False


class SalonCallCoordinator:
    def __init__(
        self,
        *,
        reservations: SalonReservationService,
        now: Callable[[], datetime] | None = None,
        faq_responder: SalonFaqResponder | None = None,
        conversation_responder: SalonConversationResponder | None = None,
    ) -> None:
        self._reservations = reservations
        self.policy = reservations.policy
        self._now = now or (lambda: datetime.now(self.policy.timezone))
        self._faq_responder = faq_responder
        self._conversation_responder = conversation_responder
        self._calls: dict[UUID, SalonCallState] = {}
        self._lock = asyncio.Lock()

    async def handle(
        self,
        *,
        session_id: UUID,
        event_type: str,
        text: str | None = None,
    ) -> list[SalonEvent]:
        async with self._lock:
            if event_type == "salon.call.start":
                return self._start(session_id)
            if event_type == "salon.call.message":
                if text is None:
                    raise ValueError("salon call text is required")
                return await self._message(session_id, text)
            if event_type == "salon.call.end":
                return self._end(session_id)
            raise ValueError("unsupported salon call event")

    async def disconnect(self, session_id: UUID) -> None:
        async with self._lock:
            self._calls.pop(session_id, None)

    def is_active(self, session_id: UUID) -> bool:
        """Return whether this authenticated session owns an active salon call."""

        return session_id in self._calls

    def reservation_snapshot(self) -> list[dict[str, object]]:
        return [
            self._reservation_view(item)
            for item in self._reservations.list_reservations()
        ]

    def menu_snapshot(self) -> list[dict[str, object]]:
        return [
            {
                "service_id": service.service_id,
                "category": service.category,
                "name": service.name,
                "duration_minutes": service.duration_minutes,
                "price_won": service.price_won,
                "staff": [
                    member.name
                    for member in self.policy.staff
                    if service.service_id in member.service_ids
                ],
            }
            for service in self.policy.services
        ]

    def _start(self, session_id: UUID) -> list[SalonEvent]:
        existing = self._calls.get(session_id)
        if existing is not None:
            return [
                SalonEvent(
                    "salon.call.started",
                    {
                        "call_id": str(existing.call_id),
                        "status": "already_active",
                    },
                )
            ]
        state = SalonCallState(call_id=uuid4(), started_at=self._normalized_now())
        self._calls[session_id] = state
        greeting = (
            f"안녕하세요, {self.policy.salon_name} "
            f"{self.policy.receptionist_name}입니다."
        )
        self._append_history(state, "assistant", greeting)
        return [
            SalonEvent(
                "salon.call.started",
                {
                    "call_id": str(state.call_id),
                    "status": "active",
                    "persona": self.policy.receptionist_name,
                    "salon_name": self.policy.salon_name,
                },
            ),
            SalonEvent("salon.assistant.message", {"text": greeting}),
            SalonEvent(
                "assistant.state",
                {"state": "listening", "detail": "salon_call_active"},
            ),
        ]

    async def _message(self, session_id: UUID, text: str) -> list[SalonEvent]:
        state = self._calls.get(session_id)
        if state is None:
            raise ValueError("salon call is not active")
        normalized = " ".join(text.strip().split())
        if not normalized or len(normalized) > 2_000:
            raise ValueError("salon call message is invalid")
        if self._conversation_responder is not None:
            return await self._model_message(state, normalized)
        if _is_negative_confirmation(normalized) and state.awaiting_confirmation:
            state.clear_transaction()
            return self._reply("알겠습니다. 요청은 반영하지 않았습니다. 다른 예약을 도와드릴까요?")

        informational = self._informational_answer(normalized)
        if informational is not None and not state.awaiting_confirmation:
            return self._reply(informational)

        self._capture_details(state, normalized)
        explicit_action = _detect_action(normalized)
        if explicit_action is not None:
            if state.action != explicit_action:
                state.awaiting_confirmation = False
            state.action = explicit_action
        if state.action is None:
            if _is_greeting(normalized):
                return self._reply("네, 편하게 말씀해 주세요. 어떤 예약을 도와드릴까요?")
            if self._faq_responder is not None:
                try:
                    decision = await self._faq_responder.answer(normalized)
                except SalonFaqResponderError:
                    return [
                        SalonEvent(
                            "salon.assistant.message",
                            {
                                "text": (
                                    "지금은 추가 상담 답변을 준비하지 못했습니다. "
                                    "예약, 변경, 취소, 가격과 영업시간은 바로 도와드릴 수 있어요."
                                ),
                                "fallback": "faq_model_unavailable",
                            },
                        )
                    ]
                if decision.in_scope:
                    return self._reply(decision.answer)
            return self._reply(
                "저는 미용실 예약, 변경, 취소와 시술·가격·영업시간 안내만 도와드릴 수 있어요."
            )
        try:
            if state.action == "availability":
                return self._availability(state)
            if state.action == "book":
                return self._book(state, normalized)
            if state.action == "cancel":
                return self._cancel(state, normalized)
            return self._modify(state, normalized)
        except SalonBookingError as error:
            state.awaiting_confirmation = False
            return [
                SalonEvent(
                    "salon.assistant.message",
                    {"text": str(error), "error_code": error.code},
                )
            ]

    async def _model_message(
        self,
        state: SalonCallState,
        text: str,
    ) -> list[SalonEvent]:
        assert self._conversation_responder is not None
        history = tuple(state.history[-12:])
        availability_search = _availability_search_request(text)
        excluded_date = (
            state.requested_date
            if availability_search is not False and "말고" in text
            else None
        )
        try:
            decision = await self._conversation_responder.decide(
                user_message=text,
                state=self._model_state(state),
                history=history,
                now=self._normalized_now(),
            )
            reply = _safe_model_reply(text, decision.reply)
            self._apply_model_slots(state, decision)
        except (SalonFaqResponderError, SalonBookingError) as error:
            logger.warning(
                "salon conversation decision rejected",
                extra={
                    "salon_call_id": str(state.call_id),
                    "salon_error_type": type(error).__name__,
                    "salon_error_code": getattr(error, "code", None),
                },
            )
            self._append_history(state, "user", text)
            fallback = self._model_recovery_reply(state)
            self._append_history(state, "assistant", fallback)
            return [
                SalonEvent(
                    "salon.assistant.message",
                    {
                        "text": fallback,
                        "fallback": "model_decision_rejected",
                        "error_code": getattr(
                            error,
                            "code",
                            "MODEL_DECISION_INVALID",
                        ),
                    },
                )
            ]

        self._append_history(state, "user", text)

        if not decision.in_scope:
            state.clear_transaction()
            return self._model_reply(state, reply)
        if availability_search is not False and state.service_id is not None:
            state.action = "availability"
            state.starts_at = None
            tool_result = self._model_availability_search_result(
                state,
                requested_time=availability_search,
                excluded_date=excluded_date,
            )
            return await self._complete_model_tool(
                state,
                text,
                history,
                tool_result,
            )
        if decision.action == "respond":
            return self._model_reply(state, reply)

        state.action = decision.action
        try:
            if decision.action == "availability":
                tool_result = self._model_availability_result(state)
                return await self._complete_model_tool(state, text, history, tool_result)
            if decision.action == "book":
                return await self._model_book(state, text, history, decision, reply)
            if decision.action == "modify":
                return await self._model_modify(state, text, history, decision, reply)
            return await self._model_cancel(state, text, history, decision, reply)
        except SalonBookingError as error:
            state.awaiting_confirmation = False
            tool_result = {
                "ok": False,
                "operation": decision.action,
                "error_code": error.code,
                "message": str(error),
            }
            events = await self._complete_model_tool(state, text, history, tool_result)
            events[0].payload["error_code"] = error.code
            return events

    async def _model_book(
        self,
        state: SalonCallState,
        text: str,
        history: tuple[dict[str, str], ...],
        decision: SalonTurnDecision,
        reply: str,
    ) -> list[SalonEvent]:
        if state.service_id is None or state.starts_at is None:
            return self._model_reply(state, reply)

        # Never let the language model promise a slot before the authoritative
        # file-backed schedule has been checked. This intentionally happens
        # before collecting customer identity or contact details.
        if not state.awaiting_confirmation:
            availability = self._model_availability_result(state)
            missing = self._missing_model_booking_field(state)
            if not availability["ok"]:
                availability["next_step"] = "offer_an_available_alternative"
            elif missing == "customer_name":
                availability["next_step"] = "request_customer_name"
            elif missing == "phone":
                availability["next_step"] = "request_phone"
            else:
                availability["next_step"] = "request_booking_confirmation"
            if missing is not None or not availability["ok"]:
                return await self._complete_model_tool(
                    state,
                    text,
                    history,
                    availability,
                )
            state.awaiting_confirmation = True
            return await self._complete_model_tool(
                state,
                text,
                history,
                availability,
            )
        if not decision.confirmed or not _is_positive_confirmation(text):
            if _is_negative_confirmation(text):
                state.clear_transaction()
            return self._model_reply(state, reply)
        assert state.service_id is not None
        assert state.starts_at is not None
        assert state.customer_name is not None
        assert state.phone is not None
        reservation = self._reservations.create(
            ReservationRequest(
                customer_name=state.customer_name,
                phone=state.phone,
                service_id=state.service_id,
                starts_at=state.starts_at,
                staff_id=state.staff_id,
            )
        )
        state.clear_transaction()
        return await self._model_changed(
            state, text, history, "created", reservation
        )

    async def _model_modify(
        self,
        state: SalonCallState,
        text: str,
        history: tuple[dict[str, str], ...],
        decision: SalonTurnDecision,
        reply: str,
    ) -> list[SalonEvent]:
        if (
            state.reservation_code is None
            or state.phone is None
            or state.starts_at is None
        ):
            return self._model_reply(state, reply)
        if not state.awaiting_confirmation:
            state.awaiting_confirmation = True
            return self._model_reply(state, reply)
        if not decision.confirmed or not _is_positive_confirmation(text):
            if _is_negative_confirmation(text):
                state.clear_transaction()
            return self._model_reply(state, reply)
        reservation = self._reservations.modify(
            reservation_code=state.reservation_code,
            phone=state.phone,
            starts_at=state.starts_at,
            service_id=state.service_id,
            staff_id=state.staff_id,
        )
        state.clear_transaction()
        return await self._model_changed(
            state, text, history, "modified", reservation
        )

    async def _model_cancel(
        self,
        state: SalonCallState,
        text: str,
        history: tuple[dict[str, str], ...],
        decision: SalonTurnDecision,
        reply: str,
    ) -> list[SalonEvent]:
        if state.reservation_code is None or state.phone is None:
            return self._model_reply(state, reply)
        if not state.awaiting_confirmation:
            state.awaiting_confirmation = True
            return self._model_reply(state, reply)
        if not decision.confirmed or not _is_positive_confirmation(text):
            if _is_negative_confirmation(text):
                state.clear_transaction()
            return self._model_reply(state, reply)
        reservation = self._reservations.cancel(
            reservation_code=state.reservation_code,
            phone=state.phone,
        )
        state.clear_transaction()
        return await self._model_changed(
            state, text, history, "cancelled", reservation
        )

    def _model_availability_result(
        self,
        state: SalonCallState,
    ) -> dict[str, object]:
        if state.service_id is None:
            return {
                "ok": False,
                "operation": "availability",
                "error_code": "MISSING_FIELDS",
                "message": "확인할 세부 시술이 더 필요합니다.",
            }
        service = self.policy.service(state.service_id)
        if state.starts_at is None:
            if state.requested_date is None:
                return {
                    "ok": False,
                    "operation": "availability",
                    "error_code": "MISSING_FIELDS",
                    "message": "확인할 날짜가 더 필요합니다.",
                }
            return self._model_daily_availability_result(
                service_id=state.service_id,
                requested_date=state.requested_date,
            )
        staff = self._reservations.available_staff(
            service_id=state.service_id,
            starts_at=state.starts_at,
        )
        requested_staff = (
            self.policy.staff_member(state.staff_id)
            if state.staff_id is not None
            else None
        )
        requested_staff_available = (
            requested_staff is None
            or any(member.staff_id == requested_staff.staff_id for member in staff)
        )
        return {
            "ok": bool(staff) and requested_staff_available,
            "operation": "availability",
            "service_name": service.name,
            "starts_at": state.starts_at.isoformat(),
            "available_staff": [member.name for member in staff],
            "requested_staff_name": (
                requested_staff.name if requested_staff is not None else None
            ),
            "requested_staff_available": requested_staff_available,
            "message": (
                "요청한 담당자와 시간으로 예약할 수 있습니다."
                if requested_staff is not None and requested_staff_available
                else (
                    "요청한 담당자는 해당 시간에 예약이 어렵습니다."
                    if requested_staff is not None
                    else (
                        "예약 가능한 담당자가 있습니다."
                        if staff
                        else "해당 시간에는 예약 가능한 담당자가 없습니다."
                    )
                )
            ),
        }

    def _model_daily_availability_result(
        self,
        *,
        service_id: str,
        requested_date: date,
    ) -> dict[str, object]:
        service = self.policy.service(service_id)
        hours = self.policy.business_hours[requested_date.weekday()]
        if hours is None:
            return {
                "ok": False,
                "operation": "availability_by_date",
                "service_name": service.name,
                "requested_date": requested_date.isoformat(),
                "error_code": "SALON_CLOSED",
                "available_slots": [],
                "message": "선택한 날짜는 정기 휴무일입니다.",
            }
        candidate = local_datetime(
            requested_date,
            hours.opens_at,
            self.policy.timezone_name,
        )
        closes_at = local_datetime(
            requested_date,
            hours.closes_at,
            self.policy.timezone_name,
        )
        slots: list[dict[str, object]] = []
        while candidate + timedelta(minutes=service.duration_minutes) <= closes_at:
            try:
                staff = self._reservations.available_staff(
                    service_id=service_id,
                    starts_at=candidate,
                )
            except SalonBookingError as error:
                if error.code in {
                    "RESERVATION_IN_PAST",
                    "BOOKING_HORIZON_EXCEEDED",
                }:
                    candidate += timedelta(minutes=self.policy.slot_minutes)
                    continue
                raise
            if staff:
                slots.append(
                    {
                        "starts_at": candidate.isoformat(),
                        "available_staff": [member.name for member in staff],
                    }
                )
            candidate += timedelta(minutes=self.policy.slot_minutes)
        return {
            "ok": bool(slots),
            "operation": "availability_by_date",
            "service_name": service.name,
            "requested_date": requested_date.isoformat(),
            "available_slots": slots,
            "message": (
                "예약 가능한 시간이 있습니다."
                if slots
                else "선택한 날짜에는 예약 가능한 시간이 없습니다."
            ),
        }

    def _model_availability_search_result(
        self,
        state: SalonCallState,
        *,
        requested_time: time | None,
        excluded_date: date | None,
    ) -> dict[str, object]:
        if state.service_id is None:
            return {
                "ok": False,
                "operation": "availability_search",
                "error_code": "MISSING_FIELDS",
                "available_slots": [],
                "message": "확인할 세부 시술이 더 필요합니다.",
            }
        service = self.policy.service(state.service_id)
        requested_staff = (
            self.policy.staff_member(state.staff_id)
            if state.staff_id is not None
            else None
        )
        slots: list[dict[str, object]] = []
        first_date = self._normalized_now().date()
        if excluded_date is not None and excluded_date >= first_date:
            first_date = excluded_date + timedelta(days=1)
        for offset in range(self.policy.booking_horizon_days + 1):
            candidate_date = first_date + timedelta(days=offset)
            hours = self.policy.business_hours[candidate_date.weekday()]
            if hours is None:
                continue
            if requested_time is not None:
                candidate = local_datetime(
                    candidate_date,
                    requested_time,
                    self.policy.timezone_name,
                )
                closes_at = local_datetime(
                    candidate_date,
                    hours.closes_at,
                    self.policy.timezone_name,
                )
                if (
                    requested_time < hours.opens_at
                    or candidate + timedelta(minutes=service.duration_minutes)
                    > closes_at
                ):
                    continue
                candidates = (candidate,)
            else:
                daily = self._model_daily_availability_result(
                    service_id=state.service_id,
                    requested_date=candidate_date,
                )
                candidates = tuple(
                    datetime.fromisoformat(str(item["starts_at"]))
                    for item in daily["available_slots"]
                )
            for candidate in candidates:
                try:
                    available_staff = self._reservations.available_staff(
                        service_id=state.service_id,
                        starts_at=candidate,
                    )
                except SalonBookingError as error:
                    if error.code in {
                        "RESERVATION_IN_PAST",
                        "BOOKING_HORIZON_EXCEEDED",
                    }:
                        continue
                    raise
                if requested_staff is not None:
                    available_staff = tuple(
                        member
                        for member in available_staff
                        if member.staff_id == requested_staff.staff_id
                    )
                if available_staff:
                    slots.append(
                        {
                            "starts_at": candidate.isoformat(),
                            "available_staff": [
                                member.name for member in available_staff
                            ],
                        }
                    )
                if len(slots) >= 3:
                    break
            if len(slots) >= 3:
                break
        return {
            "ok": bool(slots),
            "operation": "availability_search",
            "search_mode": (
                "next_at_time" if requested_time is not None else "earliest"
            ),
            "service_name": service.name,
            "requested_time": (
                requested_time.isoformat(timespec="minutes")
                if requested_time is not None
                else None
            ),
            "requested_staff_name": (
                requested_staff.name if requested_staff is not None else None
            ),
            "available_slots": slots,
            "message": (
                "조건에 맞는 가장 빠른 예약 가능 시간을 찾았습니다."
                if slots
                else "조건에 맞는 예약 가능 시간을 찾지 못했습니다."
            ),
        }

    async def _model_changed(
        self,
        state: SalonCallState,
        text: str,
        history: tuple[dict[str, str], ...],
        change_type: str,
        reservation: Reservation,
    ) -> list[SalonEvent]:
        service = self.policy.service(reservation.service_id)
        staff = self.policy.staff_member(reservation.staff_id)
        payload = self._reservation_view(reservation)
        tool_result = {
            "ok": True,
            "operation": change_type,
            "reservation_code": reservation.short_code,
            "service_name": service.name,
            "staff_name": staff.name,
            "starts_at": reservation.starts_at.isoformat(),
        }
        message_events = await self._complete_model_tool(
            state, text, history, tool_result
        )
        summary = str(message_events[0].payload["text"])
        return [
            *message_events,
            SalonEvent(
                "salon.reservation.updated",
                {"change_type": change_type, "reservation": payload},
            ),
            SalonEvent(
                "salon.owner.notification",
                {
                    "title": f"{self.policy.salon_name} 예약 알림",
                    "body": summary,
                    "change_type": change_type,
                    "reservation_id": str(reservation.reservation_id),
                },
            ),
        ]

    async def _complete_model_tool(
        self,
        state: SalonCallState,
        text: str,
        history: tuple[dict[str, str], ...],
        tool_result: dict[str, object],
    ) -> list[SalonEvent]:
        assert self._conversation_responder is not None
        try:
            reply = await self._conversation_responder.complete(
                user_message=text,
                state=self._model_state(state),
                history=history,
                tool_result=tool_result,
            )
            reply = _safe_model_reply(text, reply)
        except SalonFaqResponderError:
            reply = str(tool_result.get("message", "처리 결과를 확인해 주세요."))
        return self._model_reply(state, reply)

    def _apply_model_slots(
        self,
        state: SalonCallState,
        decision: SalonTurnDecision,
    ) -> None:
        if decision.service_id is not None:
            self.policy.service(decision.service_id)
            state.service_id = decision.service_id
        if decision.staff_id is not None:
            self.policy.staff_member(decision.staff_id)
            state.staff_id = decision.staff_id
        if decision.starts_at is not None:
            state.starts_at = decision.starts_at.astimezone(self.policy.timezone)
            state.requested_date = state.starts_at.date()
        elif decision.requested_date is not None:
            state.requested_date = decision.requested_date
            state.starts_at = None
        if decision.customer_name is not None:
            state.customer_name = decision.customer_name
        if decision.phone is not None:
            state.phone = decision.phone
        if decision.reservation_code is not None:
            state.reservation_code = decision.reservation_code

    def _model_state(self, state: SalonCallState) -> dict[str, object]:
        return {
            "action": state.action,
            "service_id": state.service_id,
            "staff_id": state.staff_id,
            "starts_at": (
                state.starts_at.isoformat() if state.starts_at is not None else None
            ),
            "requested_date": (
                state.requested_date.isoformat()
                if state.requested_date is not None
                else None
            ),
            "customer_name": state.customer_name,
            "phone": state.phone,
            "reservation_code": state.reservation_code,
            "awaiting_confirmation": state.awaiting_confirmation,
        }

    def _model_recovery_reply(self, state: SalonCallState) -> str:
        """Preserve the current call context when a bounded model turn fails."""

        if state.action == "book":
            if state.service_id is None:
                return "원하시는 세부 시술을 한 번만 더 말씀해 주시겠어요?"
            if state.starts_at is None:
                return "원하시는 날짜와 시간을 한 번만 더 말씀해 주시겠어요?"
            if state.customer_name is None:
                return "예약자 성함을 알려주시겠어요?"
            if state.phone is None:
                return (
                    "예약 확정에는 연락 가능한 휴대전화 번호가 필요해요. "
                    "번호 없이 예약 가능 여부까지만 안내해 드릴까요?"
                )
        if state.awaiting_confirmation:
            return "말씀드린 내용으로 진행할지 다시 한번 확인해 주시겠어요?"
        return "제가 방금 말씀을 정확히 처리하지 못했어요. 마지막 요청을 한 번만 다시 말씀해 주시겠어요?"

    @staticmethod
    def _missing_model_booking_field(state: SalonCallState) -> str | None:
        if state.service_id is None:
            return "service_id"
        if state.starts_at is None:
            return "starts_at"
        if state.customer_name is None:
            return "customer_name"
        if state.phone is None:
            return "phone"
        return None

    @staticmethod
    def _append_history(
        state: SalonCallState,
        role: str,
        content: str,
    ) -> None:
        state.history.append({"role": role, "content": content})
        del state.history[:-12]

    def _model_reply(
        self,
        state: SalonCallState,
        text: str,
    ) -> list[SalonEvent]:
        self._append_history(state, "assistant", text)
        return self._reply(text)

    def _availability(self, state: SalonCallState) -> list[SalonEvent]:
        if state.service_id is None:
            return self._reply("원하시는 시술을 알려주세요. 커트, 염색, 펌, 클리닉이 가능합니다.")
        if state.starts_at is None:
            return self._reply("원하시는 날짜와 시간을 알려주세요.")
        staff = self._reservations.available_staff(
            service_id=state.service_id,
            starts_at=state.starts_at,
        )
        service = self.policy.service(state.service_id)
        if not staff:
            return self._reply(
                f"{_format_datetime(state.starts_at)}에는 {service.name} 예약이 어렵습니다. "
                "다른 시간을 말씀해 주세요."
            )
        names = ", ".join(member.name for member in staff)
        state.action = "book"
        return self._reply(
            f"{_format_datetime(state.starts_at)} {service.name} 예약이 가능합니다. "
            f"가능한 담당자는 {names}입니다. 예약을 원하시면 이름과 휴대전화 번호를 알려주세요."
        )

    def _book(self, state: SalonCallState, text: str) -> list[SalonEvent]:
        missing = self._missing_booking_field(state)
        if missing is not None:
            return self._reply(missing)
        assert state.service_id is not None
        assert state.starts_at is not None
        assert state.customer_name is not None
        assert state.phone is not None
        if not state.awaiting_confirmation:
            state.awaiting_confirmation = True
            service = self.policy.service(state.service_id)
            staff = (
                self.policy.staff_member(state.staff_id).name
                if state.staff_id is not None
                else "가능한 담당자"
            )
            return self._reply(
                f"{state.customer_name} 고객님, {_format_datetime(state.starts_at)} "
                f"{service.name}, {staff}로 예약할까요?"
            )
        if not _is_positive_confirmation(text):
            return self._reply("예약 진행 여부를 네 또는 아니요로 말씀해 주세요.")
        reservation = self._reservations.create(
            ReservationRequest(
                customer_name=state.customer_name,
                phone=state.phone,
                service_id=state.service_id,
                starts_at=state.starts_at,
                staff_id=state.staff_id,
            )
        )
        state.clear_transaction()
        return self._changed("created", reservation)

    def _cancel(self, state: SalonCallState, text: str) -> list[SalonEvent]:
        if state.reservation_code is None:
            return self._reply("취소할 예약번호 8자리를 알려주세요.")
        if state.phone is None:
            return self._reply("예약 확인을 위해 휴대전화 번호를 알려주세요.")
        if not state.awaiting_confirmation:
            state.awaiting_confirmation = True
            return self._reply(
                f"예약번호 {state.reservation_code} 예약을 취소할까요?"
            )
        if not _is_positive_confirmation(text):
            return self._reply("취소 진행 여부를 네 또는 아니요로 말씀해 주세요.")
        reservation = self._reservations.cancel(
            reservation_code=state.reservation_code,
            phone=state.phone,
        )
        state.clear_transaction()
        return self._changed("cancelled", reservation)

    def _modify(self, state: SalonCallState, text: str) -> list[SalonEvent]:
        if state.reservation_code is None:
            return self._reply("변경할 예약번호 8자리를 알려주세요.")
        if state.phone is None:
            return self._reply("예약 확인을 위해 휴대전화 번호를 알려주세요.")
        if state.starts_at is None:
            return self._reply("변경할 새 날짜와 시간을 알려주세요.")
        if not state.awaiting_confirmation:
            state.awaiting_confirmation = True
            return self._reply(
                f"예약번호 {state.reservation_code} 예약을 "
                f"{_format_datetime(state.starts_at)}로 변경할까요?"
            )
        if not _is_positive_confirmation(text):
            return self._reply("변경 진행 여부를 네 또는 아니요로 말씀해 주세요.")
        reservation = self._reservations.modify(
            reservation_code=state.reservation_code,
            phone=state.phone,
            starts_at=state.starts_at,
            service_id=state.service_id,
            staff_id=state.staff_id,
        )
        state.clear_transaction()
        return self._changed("modified", reservation)

    def _capture_details(self, state: SalonCallState, text: str) -> None:
        service = self.policy.service_by_text(text)
        if service is not None:
            state.service_id = service.service_id
        staff = self.policy.staff_by_text(text)
        if staff is not None:
            state.staff_id = staff.staff_id
        parsed_datetime = _parse_datetime(
            text,
            now=self._normalized_now(),
            timezone_name=self.policy.timezone_name,
        )
        if parsed_datetime is not None:
            state.starts_at = parsed_datetime
        phone = _parse_phone(text)
        if phone is not None:
            state.phone = phone
        name = _parse_name(text)
        if name is not None:
            state.customer_name = name
        code = _parse_reservation_code(text)
        if code is not None:
            state.reservation_code = code

    def _informational_answer(self, text: str) -> str | None:
        if any(word in text for word in ("영업시간", "몇 시", "휴무", "문 여")):
            lines = []
            for weekday, label in enumerate(("월", "화", "수", "목", "금", "토", "일")):
                hours = self.policy.business_hours[weekday]
                value = (
                    "휴무"
                    if hours is None
                    else f"{hours.opens_at:%H:%M}~{hours.closes_at:%H:%M}"
                )
                lines.append(f"{label} {value}")
            return "영업시간은 " + ", ".join(lines) + "입니다."
        if any(word in text for word in ("가격", "얼마", "요금", "메뉴")):
            return "시술 가격은 " + ", ".join(
                f"{item.name} {item.price_won:,}원" for item in self.policy.services
            ) + "입니다."
        if any(word in text for word in ("위치", "주소", "어디")):
            return f"주소는 {self.policy.address}입니다."
        if "주차" in text:
            return self.policy.parking
        if any(word in text for word in ("취소 규정", "취소 수수료", "변경 규정")):
            return self.policy.cancellation_policy
        if any(word in text for word in ("시술", "서비스", "뭐 해")):
            return "가능한 시술은 " + ", ".join(
                f"{item.name} 약 {item.duration_minutes}분"
                for item in self.policy.services
            ) + "입니다."
        return None

    def _missing_booking_field(self, state: SalonCallState) -> str | None:
        if state.service_id is None:
            return "원하시는 시술을 알려주세요."
        if state.starts_at is None:
            return "원하시는 날짜와 시간을 알려주세요."
        if state.customer_name is None:
            return "예약자 이름을 알려주세요."
        if state.phone is None:
            return "연락받을 휴대전화 번호를 알려주세요."
        return None

    def _changed(
        self,
        change_type: str,
        reservation: Reservation,
    ) -> list[SalonEvent]:
        action = {
            "created": "예약이 확정됐습니다",
            "modified": "예약이 변경됐습니다",
            "cancelled": "예약이 취소됐습니다",
        }[change_type]
        service = self.policy.service(reservation.service_id)
        staff = self.policy.staff_member(reservation.staff_id)
        summary = (
            f"{action}. 예약번호는 {reservation.short_code}, "
            f"{_format_datetime(reservation.starts_at)} {service.name}, "
            f"담당 {staff.name}입니다."
        )
        event_payload = self._reservation_view(reservation)
        return [
            SalonEvent("salon.assistant.message", {"text": summary}),
            SalonEvent(
                "salon.reservation.updated",
                {"change_type": change_type, "reservation": event_payload},
            ),
            SalonEvent(
                "salon.owner.notification",
                {
                    "title": f"{self.policy.salon_name} 예약 {action[4:6]}",
                    "body": summary,
                    "change_type": change_type,
                    "reservation_id": str(reservation.reservation_id),
                },
            ),
        ]

    def _end(self, session_id: UUID) -> list[SalonEvent]:
        state = self._calls.pop(session_id, None)
        if state is None:
            raise ValueError("salon call is not active")
        return [
            SalonEvent(
                "salon.assistant.message",
                {"text": f"{self.policy.salon_name}이었습니다. 감사합니다."},
            ),
            SalonEvent(
                "salon.call.ended",
                {"call_id": str(state.call_id), "status": "completed"},
            ),
            SalonEvent("assistant.state", {"state": "idle"}),
        ]

    @staticmethod
    def _reply(text: str) -> list[SalonEvent]:
        return [SalonEvent("salon.assistant.message", {"text": text})]

    def _normalized_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            return value.replace(tzinfo=self.policy.timezone)
        return value.astimezone(self.policy.timezone)

    def _reservation_view(self, item: Reservation) -> dict[str, object]:
        payload = _reservation_payload(item)
        payload["service_name"] = self.policy.service(item.service_id).name
        payload["staff_name"] = self.policy.staff_member(item.staff_id).name
        return payload


def _detect_action(text: str) -> SalonAction | None:
    if "취소" in text and "취소 규정" not in text and "취소 수수료" not in text:
        return "cancel"
    if any(word in text for word in ("변경", "옮기", "바꾸")):
        return "modify"
    if any(word in text for word in ("가능", "빈 시간", "자리 있", "비어")):
        return "availability"
    if "예약" in text:
        return "book"
    return None


def _availability_search_request(text: str) -> time | None | Literal[False]:
    normalized = " ".join(text.split())
    searches_earliest = any(
        phrase in normalized
        for phrase in (
            "가장 빠른",
            "제일 빠른",
            "빠른 날짜",
            "빠른 시간",
            "되는 날짜",
            "가능한 날짜",
        )
    )
    if not searches_earliest:
        return False
    match = re.search(
        r"(?:(오전|오후)\s*)?(\d{1,2})\s*시(?:\s*(\d{1,2})\s*분)?",
        normalized,
    )
    if match is None:
        return None
    meridiem, hour_value, minute_value = match.groups()
    hour = int(hour_value)
    minute = int(minute_value or "0")
    if not 0 <= minute <= 59 or not 1 <= hour <= 12:
        return None
    if meridiem == "오후" and hour != 12:
        hour += 12
    elif meridiem == "오전" and hour == 12:
        hour = 0
    return time(hour, minute)


def _is_greeting(text: str) -> bool:
    return any(word in text for word in ("안녕", "여보세요", "문의", "질문"))


def _is_positive_confirmation(text: str) -> bool:
    normalized = text.replace(" ", "")
    return normalized in {
        "네",
        "네.",
        "예",
        "예.",
        "맞아요",
        "맞습니다",
        "진행해주세요",
        "예약해주세요",
        "취소해주세요",
        "변경해주세요",
        "그렇게해주세요",
    }


def _is_negative_confirmation(text: str) -> bool:
    return any(word in text for word in ("아니요", "아니", "취소할게", "그만"))


def _parse_phone(text: str) -> str | None:
    match = re.search(r"(?<!\d)(01[016789])[- ]?(\d{3,4})[- ]?(\d{4})(?!\d)", text)
    return "".join(match.groups()) if match is not None else None


def _parse_name(text: str) -> str | None:
    match = re.search(
        r"(?:이름|예약자)(?:은|는|이|가)?\s*[:：]?\s*([가-힣A-Za-z]{2,30})",
        text,
    )
    return match.group(1) if match is not None else None


def _parse_reservation_code(text: str) -> str | None:
    match = re.search(r"예약\s*번호(?:는|가)?\s*[:：]?\s*([A-Fa-f0-9-]{8,36})", text)
    return match.group(1).replace("-", "").upper() if match is not None else None


def _parse_datetime(
    text: str,
    *,
    now: datetime,
    timezone_name: str,
) -> datetime | None:
    selected_date: date | None = None
    iso = re.search(r"\b(20\d{2})[-./](\d{1,2})[-./](\d{1,2})\b", text)
    korean = re.search(r"(?:(20\d{2})년\s*)?(\d{1,2})월\s*(\d{1,2})일", text)
    try:
        if iso is not None:
            selected_date = date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        elif korean is not None:
            year = int(korean.group(1)) if korean.group(1) else now.year
            selected_date = date(year, int(korean.group(2)), int(korean.group(3)))
            if korean.group(1) is None and selected_date < now.date():
                selected_date = selected_date.replace(year=year + 1)
        elif "모레" in text:
            selected_date = now.date() + timedelta(days=2)
        elif "내일" in text:
            selected_date = now.date() + timedelta(days=1)
        elif "오늘" in text:
            selected_date = now.date()
    except ValueError as error:
        raise SalonBookingError("DATE_INVALID", "날짜를 확인해 주세요.") from error

    clock = re.search(
        r"(?:(오전|오후)\s*)?(\d{1,2})시(?:\s*(\d{1,2})분)?",
        text,
    )
    colon = re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", text)
    if clock is None and colon is None:
        return None
    if selected_date is None:
        selected_date = now.date()
    if colon is not None:
        hour = int(colon.group(1))
        minute = int(colon.group(2))
    else:
        assert clock is not None
        period = clock.group(1)
        hour = int(clock.group(2))
        minute = int(clock.group(3) or 0)
        if not 1 <= hour <= 12 and period is not None:
            raise SalonBookingError("TIME_INVALID", "시간을 확인해 주세요.")
        if period == "오후" and hour < 12:
            hour += 12
        if period == "오전" and hour == 12:
            hour = 0
    try:
        selected_time = time(hour, minute)
    except ValueError as error:
        raise SalonBookingError("TIME_INVALID", "시간을 확인해 주세요.") from error
    return local_datetime(selected_date, selected_time, timezone_name)


def _format_datetime(value: datetime) -> str:
    weekday = "월화수목금토일"[value.weekday()]
    return f"{value:%Y년 %-m월 %-d일}({weekday}) {value:%H시 %M분}"


def _reservation_payload(item: Reservation) -> dict[str, object]:
    return {
        "reservation_id": str(item.reservation_id),
        "reservation_code": item.short_code,
        "customer_name": item.customer_name,
        "phone_masked": item.phone[:3] + "****" + item.phone[-4:],
        "service_id": item.service_id,
        "staff_id": item.staff_id,
        "starts_at": item.starts_at.isoformat(),
        "ends_at": item.ends_at.isoformat(),
        "status": item.status,
        "version": item.version,
    }


def _safe_model_reply(user_message: str, reply: str) -> str:
    normalized = " ".join(reply.strip().split())
    if not normalized or len(normalized) > 600:
        raise SalonFaqResponderError("salon model reply is invalid")
    user_key = re.sub(r"[\W_]+", "", user_message).casefold()
    reply_key = re.sub(r"[\W_]+", "", normalized).casefold()
    if len(user_key) >= 4 and reply_key == user_key:
        raise SalonFaqResponderError("salon model echoed the caller")
    return normalized
