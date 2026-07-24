from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time
from pathlib import Path
from threading import Barrier

import pytest

from local_voice_agent_server.domain.salon_booking import (
    Reservation,
    ReservationRequest,
    SalonBookingError,
    SalonReservationService,
    local_datetime,
)
from local_voice_agent_server.infrastructure.file_reservations import (
    FileReservationStore,
)
from local_voice_agent_server.infrastructure.salon_config import load_salon_policy


REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = REPO_ROOT / "configs" / "salon-booking.json"


def _service(tmp_path: Path) -> tuple[SalonReservationService, FileReservationStore]:
    policy = load_salon_policy(POLICY_PATH)
    store = FileReservationStore(
        data_path=tmp_path / "active" / "reservations.json",
        backup_root=tmp_path / "backup",
    )
    return (
        SalonReservationService(
            policy=policy,
            repository=store,
            now=lambda: datetime(2026, 7, 25, 9, 0, tzinfo=policy.timezone),
        ),
        store,
    )


def _request(
    service: SalonReservationService,
    *,
    phone: str = "010-1234-5678",
    starts_at: datetime | None = None,
    staff_id: str | None = None,
) -> ReservationRequest:
    return ReservationRequest(
        customer_name="김규태",
        phone=phone,
        service_id="haircut",
        starts_at=starts_at
        or local_datetime(date(2026, 7, 26), time(14, 0), service.policy.timezone_name),
        staff_id=staff_id,
    )


def test_file_store_creates_reservation_and_recovery_snapshot(tmp_path: Path) -> None:
    service, store = _service(tmp_path)

    reservation = service.create(_request(service))

    assert reservation.status == "confirmed"
    assert store.data_path.is_file()
    manifests = tuple((tmp_path / "backup").glob("*/recovery-manifest.json"))
    assert len(manifests) == 1
    assert '"sha256":' in manifests[0].read_text(encoding="utf-8")
    assert service.list_reservations() == (reservation,)


def test_duplicate_phone_and_time_is_rejected(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    service.create(_request(service))

    with pytest.raises(SalonBookingError) as raised:
        service.create(_request(service))

    assert raised.value.code == "DUPLICATE_RESERVATION"


def test_overlapping_staff_is_automatically_distributed(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)

    first = service.create(_request(service, phone="010-1111-1111"))
    second = service.create(_request(service, phone="010-2222-2222"))
    third = service.create(_request(service, phone="010-3333-3333"))

    assert {first.staff_id, second.staff_id, third.staff_id} == {
        "minji",
        "jun",
        "sora",
    }
    with pytest.raises(SalonBookingError) as raised:
        service.create(_request(service, phone="010-4444-4444"))
    assert raised.value.code == "SLOT_UNAVAILABLE"


@pytest.mark.parametrize(
    ("starts_at", "expected_code"),
    [
        (datetime(2026, 7, 27, 14, 0), "SALON_CLOSED"),
        (datetime(2026, 7, 26, 9, 30), "OUTSIDE_BUSINESS_HOURS"),
        (datetime(2026, 7, 26, 14, 10), "SLOT_ALIGNMENT_INVALID"),
    ],
)
def test_closed_outside_hours_and_misaligned_slots_are_rejected(
    tmp_path: Path,
    starts_at: datetime,
    expected_code: str,
) -> None:
    service, _ = _service(tmp_path)

    with pytest.raises(SalonBookingError) as raised:
        service.create(_request(service, starts_at=starts_at))

    assert raised.value.code == expected_code


def test_reservation_can_be_modified_and_cancelled_with_phone_check(
    tmp_path: Path,
) -> None:
    service, _ = _service(tmp_path)
    created = service.create(_request(service))
    changed_start = local_datetime(
        date(2026, 7, 28),
        time(15, 30),
        service.policy.timezone_name,
    )

    modified = service.modify(
        reservation_code=created.short_code,
        phone="010-1234-5678",
        starts_at=changed_start,
    )
    cancelled = service.cancel(
        reservation_code=created.short_code,
        phone="010-1234-5678",
    )

    assert modified.starts_at == changed_start
    assert modified.version == 2
    assert cancelled.status == "cancelled"
    assert cancelled.version == 3


def test_wrong_phone_cannot_cancel_reservation(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    created = service.create(_request(service))

    with pytest.raises(SalonBookingError) as raised:
        service.cancel(
            reservation_code=created.short_code,
            phone="010-9999-9999",
        )

    assert raised.value.code == "CUSTOMER_MISMATCH"


def test_two_store_instances_serialize_duplicate_booking(tmp_path: Path) -> None:
    first, _ = _service(tmp_path)
    second, _ = _service(tmp_path)
    barrier = Barrier(2)

    def create(service: SalonReservationService) -> Reservation | str:
        barrier.wait()
        try:
            return service.create(_request(service))
        except SalonBookingError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(create, (first, second)))

    assert sum(isinstance(item, Reservation) for item in results) == 1
    assert "DUPLICATE_RESERVATION" in results
    assert len(first.list_reservations()) == 1


def test_file_store_rejects_symlink_ancestor(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    store = FileReservationStore(
        data_path=linked_parent / "reservations.json",
        backup_root=None,
    )

    with pytest.raises(ValueError, match="symlink"):
        store.initialize()
