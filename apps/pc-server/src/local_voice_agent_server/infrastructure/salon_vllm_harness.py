"""Model-led salon conversation harness with a closed structured-output boundary."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, tzinfo
from difflib import SequenceMatcher
import json
import re
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..application.salon_calls import (
    SalonFaqResponderError,
    SalonTurnDecision,
)
from ..domain.salon_booking import SalonPolicy


Transport = Callable[[dict[str, object]], object]


class SalonVllmConversationHarness:
    """Lets the model conduct the call while keeping mutations behind domain gates."""

    def __init__(
        self,
        *,
        policy: SalonPolicy,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float = 30,
        transport: Transport | None = None,
    ) -> None:
        parsed = urlparse(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("salon conversation vLLM URL must be loopback HTTP")
        if not model or len(model) > 512:
            raise ValueError("salon conversation model name is invalid")
        if len(api_key) < 32:
            raise ValueError("salon conversation API key must contain at least 32 characters")
        if not 1 <= timeout_seconds <= 120:
            raise ValueError("salon conversation timeout is invalid")
        self._endpoint = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._transport = transport or self._request
        self._timezone = policy.timezone
        self._persona_prompt = _persona_prompt(policy)

    async def decide(
        self,
        *,
        user_message: str,
        state: dict[str, object],
        history: tuple[dict[str, str], ...],
        now: datetime,
    ) -> SalonTurnDecision:
        normalized = " ".join(user_message.strip().split())
        if not normalized or len(normalized) > 2_000:
            raise ValueError("salon conversation message is invalid")
        context = {
            "now": now.isoformat(),
            "relative_date_reference": _relative_date_reference(now),
            "conversation_state": state,
            "recent_dialogue": history[-12:],
            "latest_user_message": normalized,
        }
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._persona_prompt},
            {
                "role": "system",
                "content": "CURRENT_CONTEXT="
                + json.dumps(context, ensure_ascii=False, separators=(",", ":")),
            },
        ]
        messages.append({"role": "user", "content": normalized})
        raw = await self._call(
            messages=messages,
            schema_name="salon_turn",
            schema=_TURN_SCHEMA,
            max_tokens=384,
        )
        decision = _parse_turn(raw, timezone=self._timezone)
        if _repeats_recent_reply(decision.reply, history) or _reply_leaks_internal_state(
            decision.reply
        ):
            messages.insert(
                -1,
                {
                    "role": "system",
                    "content": (
                        "방금 만든 답은 최근 답변과 표현이나 내용이 너무 비슷해 최신 고객 "
                        "질문에 답하지 못했다. 가장 최근 user 메시지를 다시 읽고 그 질문의 "
                        "의도와 필요한 action을 새로 판단한다. 안전 범위는 그대로 지키되 "
                        "이전 답을 요약하거나 반복하지 않는다. 거절이라면 정형적인 사과나 "
                        "'예약 관련 안내만'이라는 문구도 반복하지 않는다. reply에는 고객에게 "
                        "직접 말할 자연스러운 한국어만 쓰고 action, 슬롯, JSON, Note, 판단 "
                        "과정을 절대 노출하지 않는다."
                    ),
                },
            )
            raw = await self._call(
                messages=messages,
                schema_name="salon_turn_retry",
                schema=_TURN_SCHEMA,
                max_tokens=384,
            )
            decision = _parse_turn(raw, timezone=self._timezone)
        return decision

    async def complete(
        self,
        *,
        user_message: str,
        state: dict[str, object],
        history: tuple[dict[str, str], ...],
        tool_result: dict[str, object],
    ) -> str:
        context = {
            "conversation_state": state,
            "recent_dialogue": history[-12:],
            "tool_result": tool_result,
            "latest_user_message": user_message,
        }
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._persona_prompt},
            {
                "role": "system",
                "content": (
                    "도구 실행 결과를 고객에게 자연스럽게 전달한다. "
                    "성공이나 실패를 도구 결과와 다르게 말하지 않는다. "
                    "고객 문장을 따라 하지 말고 한두 문장으로 말한다. availability 결과면 "
                    "확인된 시술, 날짜와 시간, available_staff를 구체적으로 알려 주고 예약을 "
                    "진행할지 자연스럽게 묻는다. 이미 받은 시술이나 시간을 다시 확인하거나 "
                    "묻지 않는다. 내부 필드명, JSON, 판단 과정은 말하지 않는다.\nRESULT_CONTEXT="
                    + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
                ),
            },
        ]
        raw = await self._call(
            messages=messages,
            schema_name="salon_tool_reply",
            schema=_REPLY_SCHEMA,
            max_tokens=192,
        )
        value = _content_object(raw)
        if set(value) != {"reply"} or not isinstance(value["reply"], str):
            raise SalonFaqResponderError("salon tool reply is invalid")
        reply = " ".join(value["reply"].strip().split())
        if not reply or len(reply) > 600:
            raise SalonFaqResponderError("salon tool reply is invalid")
        return reply

    async def _call(
        self,
        *,
        messages: list[dict[str, str]],
        schema_name: str,
        schema: dict[str, object],
        max_tokens: int,
    ) -> object:
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.35,
            "top_p": 0.9,
            "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        try:
            return await asyncio.to_thread(self._transport, payload)
        except SalonFaqResponderError:
            raise
        except Exception as error:
            raise SalonFaqResponderError(
                "salon conversation model request failed"
            ) from error

    def _request(self, payload: dict[str, object]) -> object:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = Request(
            self._endpoint,
            data=encoded,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read(256 * 1024 + 1)
        except (HTTPError, URLError, TimeoutError) as error:
            raise SalonFaqResponderError(
                "salon conversation vLLM request failed"
            ) from error
        if len(raw) > 256 * 1024:
            raise SalonFaqResponderError("salon conversation response is too large")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise SalonFaqResponderError(
                "salon conversation response is not JSON"
            ) from error


_NULLABLE_STRING: dict[str, object] = {"type": ["string", "null"]}
_TURN_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "in_scope": {"type": "boolean"},
        "action": {
            "type": "string",
            "enum": ["respond", "availability", "book", "modify", "cancel"],
        },
        "reply": {"type": "string", "maxLength": 600},
        "service_id": _NULLABLE_STRING,
        "staff_id": _NULLABLE_STRING,
        "starts_at": _NULLABLE_STRING,
        "customer_name": _NULLABLE_STRING,
        "phone": _NULLABLE_STRING,
        "reservation_code": _NULLABLE_STRING,
        "confirmed": {"type": "boolean"},
    },
    "required": [
        "in_scope",
        "action",
        "reply",
        "service_id",
        "staff_id",
        "starts_at",
        "customer_name",
        "phone",
        "reservation_code",
        "confirmed",
    ],
    "additionalProperties": False,
}
_REPLY_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"reply": {"type": "string", "maxLength": 600}},
    "required": ["reply"],
    "additionalProperties": False,
}


def _parse_turn(raw: object, *, timezone: tzinfo) -> SalonTurnDecision:
    value = _content_object(raw)
    if set(value) != set(_TURN_SCHEMA["required"]):
        raise SalonFaqResponderError("salon turn fields are invalid")
    try:
        in_scope = value["in_scope"]
        action = value["action"]
        reply = " ".join(value["reply"].strip().split())
        confirmed = value["confirmed"]
        if (
            not isinstance(in_scope, bool)
            or action not in {"respond", "availability", "book", "modify", "cancel"}
            or not isinstance(value["reply"], str)
            or not reply
            or len(reply) > 600
            or not isinstance(confirmed, bool)
        ):
            raise TypeError
        strings = {}
        for key in (
            "service_id",
            "staff_id",
            "customer_name",
            "phone",
            "reservation_code",
        ):
            item = value[key]
            if item is not None and not isinstance(item, str):
                raise TypeError
            normalized = item.strip() if isinstance(item, str) else None
            strings[key] = normalized or None
        starts_at_value = value["starts_at"]
        if starts_at_value is not None and not isinstance(starts_at_value, str):
            raise TypeError
        if isinstance(starts_at_value, str):
            starts_at_value = starts_at_value.strip() or None
        starts_at = (
            datetime.fromisoformat(starts_at_value)
            if isinstance(starts_at_value, str)
            else None
        )
        if starts_at is not None and starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=timezone)
        phone = strings["phone"]
        if phone is not None:
            phone = re.sub(r"\D", "", phone)
            if not re.fullmatch(r"01[016789]\d{7,8}", phone):
                raise ValueError
        code = strings["reservation_code"]
        if code is not None:
            code = code.replace("-", "").upper()
            if not re.fullmatch(r"[A-F0-9]{8,32}", code):
                raise ValueError
    except (AttributeError, TypeError, ValueError) as error:
        raise SalonFaqResponderError("salon turn values are invalid") from error
    return SalonTurnDecision(
        in_scope=in_scope,
        action=action,
        reply=reply,
        service_id=strings["service_id"],
        staff_id=strings["staff_id"],
        starts_at=starts_at,
        customer_name=strings["customer_name"],
        phone=phone,
        reservation_code=code,
        confirmed=confirmed,
    )


def _content_object(raw: object) -> dict[str, object]:
    try:
        if not isinstance(raw, dict):
            raise TypeError
        choices = raw["choices"]
        if not isinstance(choices, list) or len(choices) != 1:
            raise TypeError
        content = choices[0]["message"]["content"]
        if not isinstance(content, str):
            raise TypeError
        value = json.loads(content)
        if not isinstance(value, dict):
            raise TypeError
        return value
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise SalonFaqResponderError("salon model response is invalid") from error


def _persona_prompt(policy: SalonPolicy) -> str:
    facts = {
        "salon_name": policy.salon_name,
        "receptionist_name": policy.receptionist_name,
        "timezone": policy.timezone_name,
        "address": policy.address,
        "phone": policy.phone,
        "parking": policy.parking,
        "cancellation_policy": policy.cancellation_policy,
        "booking_horizon_days": policy.booking_horizon_days,
        "business_hours": {
            str(day): (
                None
                if hours is None
                else {
                    "opens_at": hours.opens_at.isoformat(timespec="minutes"),
                    "closes_at": hours.closes_at.isoformat(timespec="minutes"),
                }
            )
            for day, hours in policy.business_hours.items()
        },
        "services": [
            {
                "service_id": item.service_id,
                "category": item.category,
                "name": item.name,
                "aliases": list(item.aliases),
                "duration_minutes": item.duration_minutes,
                "price_won": item.price_won,
            }
            for item in policy.services
        ],
        "staff": [
            {
                "staff_id": item.staff_id,
                "name": item.name,
                "service_ids": sorted(item.service_ids),
            }
            for item in policy.staff
        ],
    }
    return (
        f"당신은 {policy.salon_name}의 예약 담당자 {policy.receptionist_name}다. "
        "전화 응대처럼 따뜻하고 자연스러운 한국어 존댓말로 대화한다. "
        "고객 문장을 그대로 되풀이하거나 단순히 바꿔 말하지 않는다. "
        "이미 받은 정보를 다시 묻지 않고, 한 번에 질문 하나만 한다. "
        "미용실 예약·변경·취소와 제공된 매장 정보만 답한다. 범위 밖 질문은 짧게 선을 긋고 "
        "예약 관련 도움으로 돌아온다. 이때 최근에 사용한 거절 문구와 문장 구조를 반복하지 "
        "않는다. 매번 '죄송합니다'로 시작하거나 같은 기능 제한을 낭독하지 말고, 고객 말의 "
        "의도나 감정을 짧게 받아 준 뒤 현재 통화 흐름에 어울리는 질문으로 자연스럽게 "
        "전환한다. 공격적인 표현에는 맞받아치거나 훈계하지 말고 차분하게 경계를 세운다. "
        "범위 밖 주제의 실제 답은 제공하지 않으며 사실을 만들지 않는다.\n"
        "action은 현재 턴의 목적이다. 단순 대화나 안내는 respond, 예약 가능 시간 조회는 "
        "availability, 신규 예약은 book, 변경은 modify, 취소는 cancel이다. "
        "'가능해요', '자리 있어요', '시간 돼요'처럼 가능 여부를 묻는 발화는 반드시 "
        "availability다. 실제로 예약해 달라는 의사가 있을 때만 book이다. "
        "현재 대화에서 명확히 얻은 슬롯만 채우며 추측하지 않는다. 날짜는 반드시 시간대가 포함된 "
        "ISO 8601로 바꾼다. 날짜만 있고 시간이 없으면 starts_at을 채우지 않는다. "
        "CURRENT_CONTEXT의 relative_date_reference가 상대 날짜 표현의 유일한 기준이다. "
        "요일과 날짜를 직접 계산하지 말고 그 표의 날짜를 그대로 사용한다. "
        "CURRENT_CONTEXT의 recent_dialogue는 참고 문맥이고 latest_user_message가 반드시 "
        "이번에 답해야 하는 유일한 최신 발화다. 이전 질문에 다시 답하지 않는다. "
        "신규 예약의 필수 정보는 시술, 정확한 날짜와 시간, 이름, 전화번호이며 이 순서로 "
        "부족한 정보를 한 번에 하나씩 묻는다. 담당자 선택은 선택사항이므로 필수 정보보다 먼저 "
        "묻지 않고, 고객이 지정하지 않으면 가능한 담당자로 배정된다고 안내한다. "
        "상태에 이미 있는 슬롯은 null로 보내도 된다. "
        "신규 예약·변경·취소의 첫 요청에는 confirmed=false로 하고, 모든 정보를 요약한 뒤 "
        "진행해도 되는지 묻는다. 이전 턴이 확인 대기 중이고 고객이 명시적으로 동의한 경우에만 "
        "confirmed=true로 한다. 인사에 인사를 답하되 자기소개만 반복하지 않는다. "
        "정해진 JSON 스키마 외 텍스트는 출력하지 않는다.\nFACTS="
        + json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
    )


def _relative_date_reference(now: datetime) -> dict[str, str]:
    local_date = now.date()
    weekdays = ("월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일")
    start_of_week = local_date - timedelta(days=local_date.weekday())
    next_week = start_of_week + timedelta(days=7)
    reference = {
        "오늘": local_date.isoformat(),
        "내일": (local_date + timedelta(days=1)).isoformat(),
        "모레": (local_date + timedelta(days=2)).isoformat(),
    }
    for index, label in enumerate(weekdays):
        next_occurrence = local_date + timedelta(
            days=((index - local_date.weekday()) % 7 or 7)
        )
        reference[f"다음 {label}"] = next_occurrence.isoformat()
        reference[f"다음주 {label}"] = (next_week + timedelta(days=index)).isoformat()
    return reference


def _repeats_recent_reply(
    reply: str,
    history: tuple[dict[str, str], ...],
) -> bool:
    candidate = _comparison_text(reply)
    if len(candidate) < 20:
        return False
    recent_assistant = (
        item.get("content", "")
        for item in reversed(history)
        if item.get("role") == "assistant"
    )
    for previous in recent_assistant:
        normalized = _comparison_text(previous)
        if len(normalized) < 20:
            continue
        if candidate == normalized:
            return True
        if SequenceMatcher(None, candidate, normalized).ratio() >= 0.78:
            return True
    return False


def _comparison_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", value).casefold()


def _reply_leaks_internal_state(reply: str) -> bool:
    lowered = reply.casefold()
    return any(
        marker in lowered
        for marker in (
            "(action:",
            "service_id:",
            "starts_at:",
            "confirmed:",
            "[note:",
            "json schema",
        )
    )
