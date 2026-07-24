import asyncio
import json
from pathlib import Path

import pytest

from local_voice_agent_server.application.salon_calls import SalonFaqResponderError
from local_voice_agent_server.infrastructure.salon_config import load_salon_policy
from local_voice_agent_server.infrastructure.salon_vllm_faq import (
    SalonVllmFaqAdapter,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = REPO_ROOT / "configs" / "salon-booking.json"
API_KEY = "s" * 32


def test_structured_faq_request_and_response_are_bounded() -> None:
    captured = {}

    def transport(payload):
        captured.update(payload)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "in_scope": True,
                                "answer": "동시간대 가능한 담당자가 있으면 예약할 수 있습니다.",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }

    adapter = SalonVllmFaqAdapter(
        policy=load_salon_policy(POLICY_PATH),
        base_url="http://127.0.0.1:46322/v1",
        model="gemma4-12b",
        api_key=API_KEY,
        transport=transport,
    )

    decision = asyncio.run(adapter.answer("두 명이 같이 커트할 수 있나요?"))

    assert decision.in_scope is True
    assert "예약할 수 있습니다" in decision.answer
    assert captured["temperature"] == 0.0
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert captured["chat_template_kwargs"] == {"enable_thinking": False}


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {"content": "not-json"}}]},
        {
            "choices": [
                {
                    "message": {
                        "content": '{"in_scope":true,"answer":"","extra":1}'
                    }
                }
            ]
        },
    ],
)
def test_invalid_model_decision_fails_closed(response: object) -> None:
    adapter = SalonVllmFaqAdapter(
        policy=load_salon_policy(POLICY_PATH),
        base_url="http://localhost:46322/v1",
        model="gemma4-12b",
        api_key=API_KEY,
        transport=lambda _: response,
    )

    with pytest.raises(SalonFaqResponderError):
        asyncio.run(adapter.answer("모르는 질문"))
