"""Strict loader for the committed salon policy document."""

from __future__ import annotations

from datetime import time
import json
from pathlib import Path

from ..domain.salon_booking import (
    BusinessHours,
    SalonPolicy,
    SalonService,
    SalonStaff,
)


def load_salon_policy(path: Path) -> SalonPolicy:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("salon policy path is invalid")
    raw = path.read_bytes()
    if len(raw) > 512 * 1024:
        raise ValueError("salon policy is too large")
    document = json.loads(raw.decode("utf-8"))
    expected = {
        "schema_version",
        "salon",
        "business_hours",
        "services",
        "staff",
    }
    if not isinstance(document, dict) or set(document) != expected:
        raise ValueError("salon policy document is invalid")
    if document["schema_version"] != "1.0":
        raise ValueError("salon policy schema version is unsupported")
    salon = document["salon"]
    if not isinstance(salon, dict) or set(salon) != {
        "name",
        "receptionist_name",
        "timezone",
        "address",
        "phone",
        "parking",
        "cancellation_policy",
        "booking_horizon_days",
        "slot_minutes",
    }:
        raise ValueError("salon identity policy is invalid")
    hours_value = document["business_hours"]
    weekday_keys = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    if not isinstance(hours_value, dict) or set(hours_value) != set(weekday_keys):
        raise ValueError("salon business hours are invalid")
    business_hours = {
        index: _parse_hours(hours_value[key])
        for index, key in enumerate(weekday_keys)
    }
    services_value = document["services"]
    staff_value = document["staff"]
    if not isinstance(services_value, list) or not isinstance(staff_value, list):
        raise ValueError("salon service configuration is invalid")
    services = tuple(
        SalonService(
            service_id=_required_string(item, "service_id"),
            name=_required_string(item, "name"),
            duration_minutes=_required_int(item, "duration_minutes"),
            price_won=_required_int(item, "price_won"),
            aliases=tuple(_required_string_list(item, "aliases")),
        )
        for item in services_value
    )
    staff = tuple(
        SalonStaff(
            staff_id=_required_string(item, "staff_id"),
            name=_required_string(item, "name"),
            service_ids=frozenset(_required_string_list(item, "service_ids")),
        )
        for item in staff_value
    )
    return SalonPolicy(
        salon_name=str(salon["name"]),
        receptionist_name=str(salon["receptionist_name"]),
        timezone_name=str(salon["timezone"]),
        address=str(salon["address"]),
        phone=str(salon["phone"]),
        parking=str(salon["parking"]),
        cancellation_policy=str(salon["cancellation_policy"]),
        booking_horizon_days=int(salon["booking_horizon_days"]),
        slot_minutes=int(salon["slot_minutes"]),
        business_hours=business_hours,
        services=services,
        staff=staff,
    )


def _parse_hours(value: object) -> BusinessHours | None:
    if value is None:
        return None
    if (
        not isinstance(value, dict)
        or set(value) != {"opens_at", "closes_at"}
    ):
        raise ValueError("business hour entry is invalid")
    return BusinessHours(
        opens_at=time.fromisoformat(str(value["opens_at"])),
        closes_at=time.fromisoformat(str(value["closes_at"])),
    )


def _required_string(value: object, key: str) -> str:
    if not isinstance(value, dict) or not isinstance(value.get(key), str):
        raise ValueError(f"salon policy field {key} is invalid")
    return str(value[key])


def _required_int(value: object, key: str) -> int:
    if not isinstance(value, dict) or not isinstance(value.get(key), int):
        raise ValueError(f"salon policy field {key} is invalid")
    return int(value[key])


def _required_string_list(value: object, key: str) -> list[str]:
    if not isinstance(value, dict):
        raise ValueError(f"salon policy field {key} is invalid")
    items = value.get(key)
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise ValueError(f"salon policy field {key} is invalid")
    return items
