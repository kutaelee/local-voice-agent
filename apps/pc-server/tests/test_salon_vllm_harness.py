import asyncio
from datetime import datetime
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
            user_message="커트하려고요",
            state={"awaiting_confirmation": False},
            history=(),
            now=datetime.fromisoformat("2026-07-25T12:00:00+09:00"),
        )
    )

    assert decision.action == "book"
    assert decision.service_id == "haircut"
    assert decision.starts_at is None
    assert decision.phone is None
    assert decision.reply != "커트하려고요"
    assert captured["temperature"] == 0.35
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert "고객 문장을 그대로 되풀이" in captured["messages"][0]["content"]
    assert '"다음주 수요일":"2026-07-29"' in captured["messages"][1]["content"]
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
