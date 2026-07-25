from datetime import datetime
from pathlib import Path

from local_voice_agent_server.domain.salon_booking import SalonReservationService
from local_voice_agent_server.infrastructure.file_reservations import (
    FileReservationStore,
)
from local_voice_agent_server.infrastructure.salon_config import load_salon_policy
from local_voice_agent_server.infrastructure.salon_qa_seed import (
    seed_salon_qa_reservations,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_qa_seed_populates_only_an_empty_isolated_table(tmp_path: Path) -> None:
    policy = load_salon_policy(REPO_ROOT / "configs" / "salon-booking.json")
    fixed_now = datetime(2026, 7, 25, 12, 0, tzinfo=policy.timezone)
    service = SalonReservationService(
        policy=policy,
        repository=FileReservationStore(
            data_path=tmp_path / "qa-reservations.json",
            backup_root=None,
        ),
        now=lambda: fixed_now,
    )

    assert seed_salon_qa_reservations(service, now=fixed_now) == 3
    reservations = service.list_reservations()
    assert {item.service_id for item in reservations} == {
        "haircut",
        "root_color",
        "digital_perm",
    }
    assert all(item.starts_at > fixed_now for item in reservations)
    assert seed_salon_qa_reservations(service, now=fixed_now) == 0
    assert service.list_reservations() == reservations


def test_policy_exposes_detailed_cut_color_and_perm_menus() -> None:
    policy = load_salon_policy(REPO_ROOT / "configs" / "salon-booking.json")
    by_category = {
        category: [item for item in policy.services if item.category == category]
        for category in ("커트", "염색", "펌")
    }

    assert all(len(items) >= 3 for items in by_category.values())
    assert {item.name for item in by_category["커트"]} >= {
        "기본 커트",
        "디자인 커트",
        "앞머리 커트",
    }
