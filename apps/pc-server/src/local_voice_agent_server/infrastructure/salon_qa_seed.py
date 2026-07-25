"""Reproducible fictitious reservation seed used only by the Web QA instance."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from ..domain.salon_booking import (
    ReservationRequest,
    SalonBookingError,
    SalonReservationService,
    local_datetime,
)


_QA_CASES = (
    ("QA 고객 1", "010-0000-1001", "haircut", "jun", time(11, 0)),
    ("QA 고객 2", "010-0000-1002", "root_color", "sora", time(13, 0)),
    ("QA 고객 3", "010-0000-1003", "digital_perm", "minji", time(14, 0)),
)


def seed_salon_qa_reservations(
    service: SalonReservationService,
    *,
    now: datetime | None = None,
) -> int:
    """Seed an empty QA table with future, domain-validated fake reservations."""

    if service.list_reservations():
        return 0
    current = now or datetime.now(service.policy.timezone)
    if current.tzinfo is None:
        current = current.replace(tzinfo=service.policy.timezone)
    else:
        current = current.astimezone(service.policy.timezone)

    created = 0
    minimum_offset = 1
    for name, phone, service_id, staff_id, preferred_time in _QA_CASES:
        selected = None
        for offset in range(minimum_offset, minimum_offset + 30):
            selected_date = current.date() + timedelta(days=offset)
            hours = service.policy.business_hours[selected_date.weekday()]
            if hours is None:
                continue
            candidate = local_datetime(
                selected_date,
                preferred_time,
                service.policy.timezone_name,
            )
            duration = service.policy.service(service_id).duration_minutes
            closes_at = local_datetime(
                selected_date,
                hours.closes_at,
                service.policy.timezone_name,
            )
            if candidate <= current or candidate + timedelta(minutes=duration) > closes_at:
                continue
            try:
                service.available_staff(
                    service_id=service_id,
                    starts_at=candidate,
                )
            except SalonBookingError:
                continue
            selected = candidate
            minimum_offset = offset + 1
            break
        if selected is None:
            raise RuntimeError("could not place the bounded salon QA seed")
        service.create(
            ReservationRequest(
                customer_name=name,
                phone=phone,
                service_id=service_id,
                starts_at=selected,
                staff_id=staff_id,
            )
        )
        created += 1
    return created
