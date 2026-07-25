"""Salon reservation rules kept independent from transport and storage."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Callable, Iterable, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ReservationStatus = Literal["confirmed", "cancelled"]


class SalonBookingError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class SalonService:
    service_id: str
    name: str
    duration_minutes: int
    price_won: int
    aliases: tuple[str, ...] = ()
    category: str = ""

    def __post_init__(self) -> None:
        if (
            not self.service_id
            or not self.name
            or not self.category
            or not 10 <= self.duration_minutes <= 480
            or not 0 <= self.price_won <= 10_000_000
        ):
            raise ValueError("salon service configuration is invalid")


@dataclass(frozen=True, slots=True)
class SalonStaff:
    staff_id: str
    name: str
    service_ids: frozenset[str]

    def __post_init__(self) -> None:
        if not self.staff_id or not self.name or not self.service_ids:
            raise ValueError("salon staff configuration is invalid")


@dataclass(frozen=True, slots=True)
class BusinessHours:
    opens_at: time
    closes_at: time

    def __post_init__(self) -> None:
        if self.opens_at >= self.closes_at:
            raise ValueError("business hours are invalid")


@dataclass(frozen=True, slots=True)
class SalonPolicy:
    salon_name: str
    receptionist_name: str
    timezone_name: str
    address: str
    phone: str
    parking: str
    cancellation_policy: str
    booking_horizon_days: int
    slot_minutes: int
    business_hours: dict[int, BusinessHours | None]
    services: tuple[SalonService, ...]
    staff: tuple[SalonStaff, ...]

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as error:
            raise ValueError("salon timezone is invalid") from error
        if (
            not self.salon_name
            or not self.receptionist_name
            or not self.address
            or not self.phone
            or set(self.business_hours) != set(range(7))
            or not 1 <= self.booking_horizon_days <= 365
            or self.slot_minutes not in {10, 15, 20, 30, 60}
            or not self.services
            or not self.staff
        ):
            raise ValueError("salon policy configuration is invalid")
        service_ids = {service.service_id for service in self.services}
        if len(service_ids) != len(self.services):
            raise ValueError("salon service identifiers must be unique")
        staff_ids = {member.staff_id for member in self.staff}
        if len(staff_ids) != len(self.staff):
            raise ValueError("salon staff identifiers must be unique")
        if any(not member.service_ids.issubset(service_ids) for member in self.staff):
            raise ValueError("salon staff references an unknown service")

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    def service(self, service_id: str) -> SalonService:
        for service in self.services:
            if service.service_id == service_id:
                return service
        raise SalonBookingError("SERVICE_UNKNOWN", "지원하지 않는 시술입니다.")

    def staff_member(self, staff_id: str) -> SalonStaff:
        for member in self.staff:
            if member.staff_id == staff_id:
                return member
        raise SalonBookingError("STAFF_UNKNOWN", "등록되지 않은 담당자입니다.")

    def service_by_text(self, text: str) -> SalonService | None:
        normalized = text.casefold()
        candidates: list[tuple[int, SalonService]] = []
        for service in self.services:
            for alias in (service.name, service.service_id, *service.aliases):
                if alias.casefold() in normalized:
                    candidates.append((len(alias), service))
        return max(candidates, default=(0, None), key=lambda item: item[0])[1]

    def staff_by_text(self, text: str) -> SalonStaff | None:
        normalized = text.casefold()
        for member in self.staff:
            if member.name.casefold() in normalized:
                return member
        return None


@dataclass(frozen=True, slots=True)
class Reservation:
    reservation_id: UUID
    customer_name: str
    phone: str
    service_id: str
    staff_id: str
    starts_at: datetime
    ends_at: datetime
    status: ReservationStatus
    version: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if (
            not self.customer_name.strip()
            or not self.phone
            or not self.service_id
            or not self.staff_id
            or self.starts_at.tzinfo is None
            or self.ends_at.tzinfo is None
            or self.starts_at >= self.ends_at
            or self.status not in {"confirmed", "cancelled"}
            or self.version < 1
            or self.created_at.tzinfo is None
            or self.updated_at.tzinfo is None
        ):
            raise ValueError("reservation is invalid")

    @property
    def short_code(self) -> str:
        return self.reservation_id.hex[:8].upper()


Mutation = Callable[[list[Reservation]], tuple[list[Reservation], Reservation]]


class ReservationRepository:
    def list(self) -> tuple[Reservation, ...]:
        raise NotImplementedError

    def mutate(self, mutation: Mutation) -> Reservation:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ReservationRequest:
    customer_name: str
    phone: str
    service_id: str
    starts_at: datetime
    staff_id: str | None = None


class SalonReservationService:
    def __init__(
        self,
        *,
        policy: SalonPolicy,
        repository: ReservationRepository,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.policy = policy
        self._repository = repository
        self._now = now or (lambda: datetime.now(policy.timezone))

    def list_reservations(self) -> tuple[Reservation, ...]:
        return self._repository.list()

    def available_staff(
        self,
        *,
        service_id: str,
        starts_at: datetime,
        excluding_reservation_id: UUID | None = None,
    ) -> tuple[SalonStaff, ...]:
        service = self.policy.service(service_id)
        normalized_start, end = self._validated_window(starts_at, service)
        reservations = self._repository.list()
        available = []
        for member in self.policy.staff:
            if service_id not in member.service_ids:
                continue
            if not _staff_has_overlap(
                reservations,
                staff_id=member.staff_id,
                starts_at=normalized_start,
                ends_at=end,
                excluding_reservation_id=excluding_reservation_id,
            ):
                available.append(member)
        return tuple(available)

    def create(self, request: ReservationRequest) -> Reservation:
        service = self.policy.service(request.service_id)
        starts_at, ends_at = self._validated_window(request.starts_at, service)
        phone = normalize_phone(request.phone)
        name = request.customer_name.strip()
        if not 1 <= len(name) <= 64:
            raise SalonBookingError("CUSTOMER_NAME_INVALID", "예약자 이름을 확인해 주세요.")

        def mutation(items: list[Reservation]) -> tuple[list[Reservation], Reservation]:
            duplicate = next(
                (
                    item
                    for item in items
                    if item.status == "confirmed"
                    and item.phone == phone
                    and item.starts_at == starts_at
                ),
                None,
            )
            if duplicate is not None:
                raise SalonBookingError(
                    "DUPLICATE_RESERVATION",
                    f"같은 번호와 시간의 예약이 이미 있습니다. 예약번호 {duplicate.short_code}입니다.",
                )
            staff = self._choose_staff(
                items,
                service_id=request.service_id,
                requested_staff_id=request.staff_id,
                starts_at=starts_at,
                ends_at=ends_at,
            )
            now = self._normalized_now()
            reservation = Reservation(
                reservation_id=uuid4(),
                customer_name=name,
                phone=phone,
                service_id=request.service_id,
                staff_id=staff.staff_id,
                starts_at=starts_at,
                ends_at=ends_at,
                status="confirmed",
                version=1,
                created_at=now,
                updated_at=now,
            )
            return [*items, reservation], reservation

        return self._repository.mutate(mutation)

    def cancel(self, *, reservation_code: str, phone: str) -> Reservation:
        normalized_phone = normalize_phone(phone)

        def mutation(items: list[Reservation]) -> tuple[list[Reservation], Reservation]:
            index, existing = _find_reservation(items, reservation_code)
            if existing.phone != normalized_phone:
                raise SalonBookingError(
                    "CUSTOMER_MISMATCH",
                    "예약자 전화번호가 일치하지 않습니다.",
                )
            if existing.status == "cancelled":
                raise SalonBookingError(
                    "ALREADY_CANCELLED",
                    "이미 취소된 예약입니다.",
                )
            updated = replace(
                existing,
                status="cancelled",
                version=existing.version + 1,
                updated_at=self._normalized_now(),
            )
            changed = list(items)
            changed[index] = updated
            return changed, updated

        return self._repository.mutate(mutation)

    def modify(
        self,
        *,
        reservation_code: str,
        phone: str,
        starts_at: datetime,
        service_id: str | None = None,
        staff_id: str | None = None,
    ) -> Reservation:
        normalized_phone = normalize_phone(phone)

        def mutation(items: list[Reservation]) -> tuple[list[Reservation], Reservation]:
            index, existing = _find_reservation(items, reservation_code)
            if existing.phone != normalized_phone:
                raise SalonBookingError(
                    "CUSTOMER_MISMATCH",
                    "예약자 전화번호가 일치하지 않습니다.",
                )
            if existing.status != "confirmed":
                raise SalonBookingError(
                    "RESERVATION_NOT_ACTIVE",
                    "변경할 수 있는 활성 예약이 아닙니다.",
                )
            selected_service_id = service_id or existing.service_id
            service = self.policy.service(selected_service_id)
            normalized_start, ends_at = self._validated_window(starts_at, service)
            selected_staff = self._choose_staff(
                items,
                service_id=selected_service_id,
                requested_staff_id=staff_id,
                starts_at=normalized_start,
                ends_at=ends_at,
                excluding_reservation_id=existing.reservation_id,
            )
            updated = replace(
                existing,
                service_id=selected_service_id,
                staff_id=selected_staff.staff_id,
                starts_at=normalized_start,
                ends_at=ends_at,
                version=existing.version + 1,
                updated_at=self._normalized_now(),
            )
            changed = list(items)
            changed[index] = updated
            return changed, updated

        return self._repository.mutate(mutation)

    def _validated_window(
        self,
        starts_at: datetime,
        service: SalonService,
    ) -> tuple[datetime, datetime]:
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=self.policy.timezone)
        else:
            starts_at = starts_at.astimezone(self.policy.timezone)
        now = self._normalized_now()
        if starts_at < now:
            raise SalonBookingError("RESERVATION_IN_PAST", "지난 시간은 예약할 수 없습니다.")
        if starts_at.date() > now.date() + timedelta(
            days=self.policy.booking_horizon_days
        ):
            raise SalonBookingError(
                "BOOKING_HORIZON_EXCEEDED",
                f"예약은 {self.policy.booking_horizon_days}일 이내만 가능합니다.",
            )
        hours = self.policy.business_hours[starts_at.weekday()]
        if hours is None:
            raise SalonBookingError("SALON_CLOSED", "선택한 날짜는 정기 휴무일입니다.")
        if starts_at.minute % self.policy.slot_minutes:
            raise SalonBookingError(
                "SLOT_ALIGNMENT_INVALID",
                f"예약은 {self.policy.slot_minutes}분 단위로 가능합니다.",
            )
        opens = datetime.combine(starts_at.date(), hours.opens_at, self.policy.timezone)
        closes = datetime.combine(
            starts_at.date(), hours.closes_at, self.policy.timezone
        )
        ends_at = starts_at + timedelta(minutes=service.duration_minutes)
        if starts_at < opens or ends_at > closes:
            raise SalonBookingError(
                "OUTSIDE_BUSINESS_HOURS",
                "영업시간 안에 시술이 끝나는 시간으로 예약해 주세요.",
            )
        return starts_at, ends_at

    def _choose_staff(
        self,
        reservations: Iterable[Reservation],
        *,
        service_id: str,
        requested_staff_id: str | None,
        starts_at: datetime,
        ends_at: datetime,
        excluding_reservation_id: UUID | None = None,
    ) -> SalonStaff:
        if requested_staff_id is not None:
            candidates = (self.policy.staff_member(requested_staff_id),)
        else:
            candidates = self.policy.staff
        for member in candidates:
            if service_id not in member.service_ids:
                continue
            if not _staff_has_overlap(
                reservations,
                staff_id=member.staff_id,
                starts_at=starts_at,
                ends_at=ends_at,
                excluding_reservation_id=excluding_reservation_id,
            ):
                return member
        raise SalonBookingError(
            "SLOT_UNAVAILABLE",
            "해당 시간에는 예약 가능한 담당자가 없습니다.",
        )

    def _normalized_now(self) -> datetime:
        now = self._now()
        if now.tzinfo is None:
            return now.replace(tzinfo=self.policy.timezone)
        return now.astimezone(self.policy.timezone)


def normalize_phone(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    if not (digits.startswith("01") and 10 <= len(digits) <= 11):
        raise SalonBookingError(
            "PHONE_INVALID",
            "휴대전화 번호를 숫자 포함 10~11자리로 알려주세요.",
        )
    return digits


def _staff_has_overlap(
    reservations: Iterable[Reservation],
    *,
    staff_id: str,
    starts_at: datetime,
    ends_at: datetime,
    excluding_reservation_id: UUID | None,
) -> bool:
    return any(
        item.status == "confirmed"
        and item.staff_id == staff_id
        and item.reservation_id != excluding_reservation_id
        and starts_at < item.ends_at
        and ends_at > item.starts_at
        for item in reservations
    )


def _find_reservation(
    items: list[Reservation],
    code: str,
) -> tuple[int, Reservation]:
    normalized = code.strip().replace("-", "").upper()
    matches = [
        (index, item)
        for index, item in enumerate(items)
        if item.reservation_id.hex.upper().startswith(normalized)
    ]
    if len(normalized) < 8 or len(matches) != 1:
        raise SalonBookingError(
            "RESERVATION_NOT_FOUND",
            "예약번호를 확인해 주세요.",
        )
    return matches[0]


def local_datetime(day: date, at: time, timezone_name: str) -> datetime:
    return datetime.combine(day, at, ZoneInfo(timezone_name))
