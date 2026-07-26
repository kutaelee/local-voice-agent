import asyncio
from datetime import date, datetime
import json
from pathlib import Path

import pytest

from local_voice_agent_server.application.salon_calls import SalonFaqResponderError
from local_voice_agent_server.infrastructure.salon_config import load_salon_policy
from local_voice_agent_server.infrastructure.salon_vllm_harness import (
    SalonVllmConversationHarness,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = REPO_ROOT / "configs" / "salon-booking.json"
API_KEY = "h" * 32


def _response(value: dict[str, object]) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(value, ensure_ascii=False),
                }
            }
        ]
    }


def test_model_drives_turn_with_persona_context_and_closed_schema() -> None:
    captured = {}

    def transport(payload):
        captured.update(payload)
        return _response(
            {
                "in_scope": True,
                "action": "book",
                "reply": "좋아요. 원하시는 날짜와 시간을 알려주시겠어요?",
                "service_id": "haircut",
                "staff_id": "",
                "starts_at": "",
                "requested_date": "",
                "customer_name": "",
                "phone": "",
                "reservation_code": "",
                "confirmed": False,
            }
        )

    adapter = SalonVllmConversationHarness(
        policy=load_salon_policy(POLICY_PATH),
        base_url="http://127.0.0.1:46322/v1",
        model="gemma4-12b",
        api_key=API_KEY,
        transport=transport,
    )
    decision = asyncio.run(
        adapter.decide(
            user_message="커트 예약하고 싶어요",
            state={"awaiting_confirmation": False},
            history=(),
            now=datetime.fromisoformat("2026-07-25T12:00:00+09:00"),
        )
    )

    assert decision.action == "book"
    assert decision.service_id == "haircut"
    assert decision.starts_at is None
    assert decision.phone is None
    assert decision.reply != "커트 예약하고 싶어요"
    assert captured["temperature"] == 0.35
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert "고객 문장을 그대로 되풀이" in captured["messages"][0]["content"]
    assert '"다음주 수요일":"2026-07-29"' in captured["messages"][1]["content"]
    assert '"action_hint":"book"' in captured["messages"][1]["content"]
    assert captured["chat_template_kwargs"] == {"enable_thinking": False}


def test_tool_result_is_narrated_by_model_without_code_authored_sentence() -> None:
    captured = {}

    def transport(payload):
        captured.update(payload)
        return _response(
            {"reply": "토요일 오후 두 시에는 민지 디자이너로 예약하실 수 있어요."}
        )

    adapter = SalonVllmConversationHarness(
        policy=load_salon_policy(POLICY_PATH),
        base_url="http://localhost:46322/v1",
        model="gemma4-12b",
        api_key=API_KEY,
        transport=transport,
    )
    reply = asyncio.run(
        adapter.complete(
            user_message="그때 자리 있어요?",
            state={"action": "availability"},
            history=(),
            tool_result={
                "ok": True,
                "operation": "availability",
                "available_staff": ["민지"],
            },
        )
    )

    assert "민지 디자이너" in reply
    assert "RESULT_CONTEXT=" in captured["messages"][1]["content"]


def test_verbose_availability_reply_is_regenerated_for_phone() -> None:
    replies = iter(
        [
            {
                "reply": (
                    "7월 28일 화요일에는 오전 열 시부터 열한 시 삼십 분까지 가능합니다. "
                    "담당자는 가능한 분으로 배정해 드릴 수 있습니다. "
                    "성함과 전화번호도 함께 말씀해 주세요."
                )
            },
            {
                "reply": (
                    "화요일은 오전 열 시와 열 시 삼십 분부터 가능해요. "
                    "어느 시간이 편하실까요?"
                )
            },
        ]
    )
    calls = []

    def transport(payload):
        calls.append(payload)
        return _response(next(replies))

    adapter = SalonVllmConversationHarness(
        policy=load_salon_policy(POLICY_PATH),
        base_url="http://127.0.0.1:46322/v1",
        model="gemma4-12b",
        api_key=API_KEY,
        transport=transport,
    )
    reply = asyncio.run(
        adapter.complete(
            user_message="화요일 커트 가능한 시간이 언제예요?",
            state={"action": "availability"},
            history=(),
            tool_result={
                "ok": True,
                "operation": "availability_by_date",
                "service_name": "기본 커트",
                "requested_date": "2026-07-28",
                "available_slots": [
                    {
                        "starts_at": "2026-07-28T10:00:00+09:00",
                        "available_staff": ["민지"],
                    }
                ],
            },
        )
    )

    assert len(calls) == 2
    assert calls[1]["response_format"]["json_schema"]["name"] == (
        "salon_tool_reply_retry"
    )
    assert "성함" not in reply
    assert reply.endswith("어느 시간이 편하실까요?")


def test_repetitive_scope_refusal_is_regenerated_by_model() -> None:
    replies = iter(
        [
            "그 내용은 안내해 드리기 어렵고, 미용실 예약 관련 도움만 드릴 수 있어요.",
            "날씨는 제가 확인할 수 없네요. 방문하실 날짜를 정하는 건 같이 도와드릴까요?",
        ]
    )
    calls = []

    def transport(payload):
        calls.append(payload)
        return _response(
            {
                "in_scope": False,
                "action": "respond",
                "reply": next(replies),
                "service_id": None,
                "staff_id": None,
                "starts_at": None,
                "requested_date": None,
                "customer_name": None,
                "phone": None,
                "reservation_code": None,
                "confirmed": False,
            }
        )

    adapter = SalonVllmConversationHarness(
        policy=load_salon_policy(POLICY_PATH),
        base_url="http://127.0.0.1:46322/v1",
        model="gemma4-12b",
        api_key=API_KEY,
        transport=transport,
    )
    decision = asyncio.run(
        adapter.decide(
            user_message="내일 비 와요?",
            state={"awaiting_confirmation": False},
            history=(
                {
                    "role": "assistant",
                    "content": (
                        "그 내용은 안내해 드리기 어렵고, "
                        "미용실 예약 관련 도움만 드릴 수 있어요."
                    ),
                },
            ),
            now=datetime.fromisoformat("2026-07-25T12:00:00+09:00"),
        )
    )

    assert len(calls) == 2
    assert "날씨는 제가 확인할 수 없네요" in decision.reply
    assert calls[1]["response_format"]["json_schema"]["name"] == "salon_turn_retry"


def test_stale_in_scope_reply_is_regenerated_for_latest_question() -> None:
    values = iter(
        [
            {
                "in_scope": True,
                "action": "respond",
                "reply": "커트, 염색, 펌의 세부 메뉴를 차례로 안내해 드릴게요.",
                "service_id": None,
                "staff_id": None,
                "starts_at": None,
                "requested_date": None,
                "customer_name": None,
                "phone": None,
                "reservation_code": None,
                "confirmed": False,
            },
            {
                "in_scope": True,
                "action": "availability",
                "reply": "7월 29일 오후 두 시 디지털 펌 가능 여부를 확인해 볼게요.",
                "service_id": "digital_perm",
                "staff_id": None,
                "starts_at": "2026-07-29T14:00:00+09:00",
                "requested_date": None,
                "customer_name": None,
                "phone": None,
                "reservation_code": None,
                "confirmed": False,
            },
        ]
    )
    calls = []

    def transport(payload):
        calls.append(payload)
        return _response(next(values))

    adapter = SalonVllmConversationHarness(
        policy=load_salon_policy(POLICY_PATH),
        base_url="http://127.0.0.1:46322/v1",
        model="gemma4-12b",
        api_key=API_KEY,
        transport=transport,
    )
    decision = asyncio.run(
        adapter.decide(
            user_message="7월 29일 오후 2시에 디지털 펌 가능해요?",
            state={"awaiting_confirmation": False},
            history=(
                {
                    "role": "assistant",
                    "content": "커트, 염색, 펌의 세부 메뉴를 차례로 안내해 드릴게요.",
                },
            ),
            now=datetime.fromisoformat("2026-07-25T12:00:00+09:00"),
        )
    )

    assert len(calls) == 2
    assert decision.action == "availability"
    assert decision.service_id == "digital_perm"


def test_internal_planning_text_is_not_exposed_to_customer() -> None:
    values = iter(
        [
            {
                "in_scope": True,
                "action": "book",
                "reply": (
                    "예약 가능해요. (action: book, service_id: digital_perm, "
                    "confirmed: false) [Note: proceed]"
                ),
                "service_id": "digital_perm",
                "staff_id": None,
                "starts_at": "2026-07-29T14:00:00+09:00",
                "requested_date": None,
                "customer_name": None,
                "phone": None,
                "reservation_code": None,
                "confirmed": False,
            },
            {
                "in_scope": True,
                "action": "availability",
                "reply": "그 시간에 가능한 담당자를 확인해 볼게요.",
                "service_id": "digital_perm",
                "staff_id": None,
                "starts_at": "2026-07-29T14:00:00+09:00",
                "requested_date": None,
                "customer_name": None,
                "phone": None,
                "reservation_code": None,
                "confirmed": False,
            },
        ]
    )
    calls = []

    def transport(payload):
        calls.append(payload)
        return _response(next(values))

    adapter = SalonVllmConversationHarness(
        policy=load_salon_policy(POLICY_PATH),
        base_url="http://127.0.0.1:46322/v1",
        model="gemma4-12b",
        api_key=API_KEY,
        transport=transport,
    )
    decision = asyncio.run(
        adapter.decide(
            user_message="7월 29일 오후 2시에 디지털 펌 가능해요?",
            state={},
            history=(),
            now=datetime.fromisoformat("2026-07-25T12:00:00+09:00"),
        )
    )

    assert len(calls) == 2
    assert decision.action == "availability"
    assert "action:" not in decision.reply


@pytest.mark.parametrize(
    "turn",
    [
        {},
        {"in_scope": True},
        {
            "in_scope": True,
            "action": "shell",
            "reply": "실행합니다.",
            "service_id": None,
            "staff_id": None,
            "starts_at": None,
            "requested_date": None,
            "customer_name": None,
            "phone": None,
            "reservation_code": None,
            "confirmed": False,
        },
    ],
)
def test_invalid_or_unapproved_model_action_fails_closed(
    turn: dict[str, object],
) -> None:
    adapter = SalonVllmConversationHarness(
        policy=load_salon_policy(POLICY_PATH),
        base_url="http://localhost:46322/v1",
        model="gemma4-12b",
        api_key=API_KEY,
        transport=lambda _: _response(turn),
    )

    with pytest.raises(SalonFaqResponderError):
        asyncio.run(
            adapter.decide(
                user_message="컴퓨터를 꺼줘",
                state={},
                history=(),
                now=datetime.fromisoformat("2026-07-25T12:00:00+09:00"),
            )
        )


def test_date_only_availability_uses_requested_date_slot() -> None:
    adapter = SalonVllmConversationHarness(
        policy=load_salon_policy(POLICY_PATH),
        base_url="http://127.0.0.1:46322/v1",
        model="gemma4-12b",
        api_key=API_KEY,
        transport=lambda _: _response(
            {
                "in_scope": True,
                "action": "availability",
                "reply": "다음 주 화요일 커트 가능한 시간을 확인해 볼게요.",
                "service_id": "haircut",
                "staff_id": None,
                "starts_at": None,
                "requested_date": "2026-07-28",
                "customer_name": None,
                "phone": None,
                "reservation_code": None,
                "confirmed": False,
            }
        ),
    )

    decision = asyncio.run(
        adapter.decide(
            user_message="다음 주 화요일 커트 가능한 시간이 언제예요?",
            state={},
            history=(),
            now=datetime.fromisoformat("2026-07-25T12:00:00+09:00"),
        )
    )

    assert decision.action == "availability"
    assert decision.starts_at is None
    assert decision.requested_date == date(2026, 7, 28)


def test_refused_contact_is_treated_as_missing_instead_of_failing_turn() -> None:
    adapter = SalonVllmConversationHarness(
        policy=load_salon_policy(POLICY_PATH),
        base_url="http://127.0.0.1:46322/v1",
        model="gemma4-e4b",
        api_key=API_KEY,
        transport=lambda _: _response(
            {
                "in_scope": True,
                "action": "book",
                "reply": "예약 확정에는 연락 가능한 번호가 필요해요. 번호 없이 가능 여부까지만 안내해 드릴까요?",
                "service_id": None,
                "staff_id": None,
                "starts_at": None,
                "requested_date": None,
                "customer_name": None,
                "phone": "안 알려주고 싶어요",
                "reservation_code": None,
                "confirmed": False,
            }
        ),
    )

    decision = asyncio.run(
        adapter.decide(
            user_message="연락처는 안 알려주고 싶은데요",
            state={
                "action": "book",
                "service_id": "digital_perm",
                "staff_id": "minji",
                "starts_at": "2026-07-29T14:00:00+09:00",
                "customer_name": "이규태",
            },
            history=(),
            now=datetime.fromisoformat("2026-07-25T12:00:00+09:00"),
        )
    )

    assert decision.action == "book"
    assert decision.phone is None


def test_markdown_reply_is_regenerated_as_spoken_korean() -> None:
    values = iter(
        [
            {
                "in_scope": True,
                "action": "respond",
                "reply": "**커트:** 이만 오천 원입니다.\n- 예약을 도와드릴까요?",
                "service_id": "haircut",
                "staff_id": None,
                "starts_at": None,
                "requested_date": None,
                "customer_name": None,
                "phone": None,
                "reservation_code": None,
                "confirmed": False,
            },
            {
                "in_scope": True,
                "action": "respond",
                "reply": "커트는 이만 오천 원이에요. 예약도 도와드릴까요?",
                "service_id": "haircut",
                "staff_id": None,
                "starts_at": None,
                "requested_date": None,
                "customer_name": None,
                "phone": None,
                "reservation_code": None,
                "confirmed": False,
            },
        ]
    )
    calls = []

    def transport(payload):
        calls.append(payload)
        return _response(next(values))

    adapter = SalonVllmConversationHarness(
        policy=load_salon_policy(POLICY_PATH),
        base_url="http://127.0.0.1:46322/v1",
        model="gemma4-12b",
        api_key=API_KEY,
        transport=transport,
    )

    decision = asyncio.run(
        adapter.decide(
            user_message="커트 가격이 얼마예요?",
            state={},
            history=(),
            now=datetime.fromisoformat("2026-07-25T12:00:00+09:00"),
        )
    )

    assert len(calls) == 2
    assert decision.reply == "커트는 이만 오천 원이에요. 예약도 도와드릴까요?"
