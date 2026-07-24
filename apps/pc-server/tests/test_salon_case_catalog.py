import asyncio
from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

from local_voice_agent_server.application.salon_calls import SalonCallCoordinator
from local_voice_agent_server.domain.salon_booking import SalonReservationService
from local_voice_agent_server.infrastructure.file_reservations import (
    FileReservationStore,
)
from local_voice_agent_server.infrastructure.salon_config import load_salon_policy


REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = (
    REPO_ROOT / "benchmarks" / "tool-cases" / "salon-reservation-cases.json"
)


def test_salon_text_case_catalog(tmp_path: Path) -> None:
    document = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    assert set(document) == {
        "schema_version",
        "description",
        "fixed_now",
        "cases",
    }
    assert document["schema_version"] == "1.0"
    cases = document["cases"]
    assert isinstance(cases, list)
    assert len(cases) >= 20
    assert len({case["id"] for case in cases}) == len(cases)

    async def run() -> None:
        policy = load_salon_policy(REPO_ROOT / "configs" / "salon-booking.json")
        fixed_now = datetime.fromisoformat(document["fixed_now"])
        for index, case in enumerate(cases):
            case_root = tmp_path / f"salon-case-{index}"
            store = FileReservationStore(
                data_path=case_root / "reservations.json",
                backup_root=None,
            )
            coordinator = SalonCallCoordinator(
                reservations=SalonReservationService(
                    policy=policy,
                    repository=store,
                    now=lambda: fixed_now,
                ),
                now=lambda: fixed_now,
            )
            session_id = uuid4()
            await coordinator.handle(
                session_id=session_id,
                event_type="salon.call.start",
            )
            final_events = []
            for message in case["messages"]:
                final_events = await coordinator.handle(
                    session_id=session_id,
                    event_type="salon.call.message",
                    text=message,
                )
            text_events = [
                event
                for event in final_events
                if event.type == "salon.assistant.message"
            ]
            assert text_events, case["id"]
            assert case["expected_contains"] in text_events[-1].payload["text"], case["id"]
            expected_event = case.get("expected_event")
            if expected_event:
                assert any(event.type == expected_event for event in final_events), case["id"]
            expected_error = case.get("expected_error_code")
            if expected_error:
                assert text_events[-1].payload.get("error_code") == expected_error, case["id"]

    asyncio.run(run())
