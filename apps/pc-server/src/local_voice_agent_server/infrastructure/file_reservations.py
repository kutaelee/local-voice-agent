"""Atomic JSON reservation store with append-only local recovery snapshots."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import threading
from typing import Any, Iterator
from uuid import UUID, uuid4

from ..domain.salon_booking import Mutation, Reservation, ReservationRepository

try:
    import fcntl
except ImportError:  # pragma: no cover - the registered PC server runs in WSL.
    fcntl = None  # type: ignore[assignment]


class FileReservationStore(ReservationRepository):
    def __init__(
        self,
        *,
        data_path: Path,
        backup_root: Path | None = None,
    ) -> None:
        if not data_path.is_absolute():
            raise ValueError("reservation data path must be absolute")
        if backup_root is not None and not backup_root.is_absolute():
            raise ValueError("reservation backup root must be absolute")
        self._data_path = data_path
        self._backup_root = backup_root
        self._lock = threading.RLock()

    @property
    def data_path(self) -> Path:
        return self._data_path

    def initialize(self) -> None:
        with self._exclusive_access():
            self._initialize_unlocked()

    def list(self) -> tuple[Reservation, ...]:
        with self._exclusive_access():
            self._initialize_unlocked()
            document = self._load_document()
            return tuple(_reservation_from_dict(item) for item in document["reservations"])

    def mutate(self, mutation: Mutation) -> Reservation:
        with self._exclusive_access():
            self._initialize_unlocked()
            document = self._load_document()
            current = [
                _reservation_from_dict(item) for item in document["reservations"]
            ]
            changed, result = mutation(list(current))
            if not isinstance(result, Reservation):
                raise ValueError("reservation mutation result is invalid")
            if len({item.reservation_id for item in changed}) != len(changed):
                raise ValueError("reservation identifiers are not unique")
            self._backup_current()
            next_document = {
                "schema_version": "1.0",
                "version": int(document["version"]) + 1,
                "reservations": [_reservation_to_dict(item) for item in changed],
            }
            self._atomic_write(next_document)
            return result

    def _initialize_unlocked(self) -> None:
        if self._data_path.exists():
            self._load_document()
            return
        self._atomic_write(
            {"schema_version": "1.0", "version": 0, "reservations": []}
        )

    @contextmanager
    def _exclusive_access(self) -> Iterator[None]:
        if fcntl is None:
            raise RuntimeError("reservation file locking requires the WSL runtime")
        with self._lock:
            self._validate_parent(self._data_path.parent)
            self._data_path.parent.mkdir(parents=True, exist_ok=True)
            self._validate_parent(self._data_path.parent)
            lock_path = self._data_path.with_name(f".{self._data_path.name}.lock")
            if lock_path.is_symlink():
                raise ValueError("reservation lock file may not be a symlink")
            flags = os.O_CREAT | os.O_RDWR
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(lock_path, flags, 0o600)
            try:
                with os.fdopen(descriptor, "a+b", closefd=False) as handle:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _load_document(self) -> dict[str, Any]:
        if self._data_path.is_symlink() or not self._data_path.is_file():
            raise ValueError("reservation data file is invalid")
        raw = self._data_path.read_bytes()
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError("reservation data file is too large")
        document = json.loads(raw.decode("utf-8"))
        if (
            not isinstance(document, dict)
            or set(document) != {"schema_version", "version", "reservations"}
            or document["schema_version"] != "1.0"
            or not isinstance(document["version"], int)
            or document["version"] < 0
            or not isinstance(document["reservations"], list)
        ):
            raise ValueError("reservation data document is invalid")
        return document

    def _backup_current(self) -> None:
        if self._backup_root is None:
            return
        self._validate_parent(self._backup_root)
        self._backup_root.mkdir(parents=True, exist_ok=True)
        self._validate_parent(self._backup_root)
        timestamp = datetime.now(timezone.utc)
        container = self._backup_root / (
            timestamp.strftime("%Y%m%dT%H%M%S.%fZ") + f"-{uuid4().hex[:8]}"
        )
        container.mkdir()
        current = self._data_path.read_bytes()
        backup_path = container / "reservations.json"
        backup_path.write_bytes(current)
        digest = sha256(current).hexdigest()
        manifest = {
            "schema_version": "1.0",
            "service": "LocalVoiceAgent-salon",
            "recoverable_at": timestamp.isoformat(),
            "source_path": str(self._data_path),
            "artifact": backup_path.name,
            "size_bytes": len(current),
            "sha256": digest,
        }
        (container / "recovery-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _atomic_write(self, document: dict[str, Any]) -> None:
        encoded = (
            json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        temporary = self._data_path.with_name(
            f".{self._data_path.name}.{uuid4().hex}.tmp"
        )
        try:
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._data_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _validate_parent(path: Path) -> None:
        for candidate in (path, *path.parents):
            if candidate.exists() and candidate.is_symlink():
                raise ValueError("reservation path may not traverse a symlink")


def _reservation_to_dict(item: Reservation) -> dict[str, object]:
    return {
        "reservation_id": str(item.reservation_id),
        "customer_name": item.customer_name,
        "phone": item.phone,
        "service_id": item.service_id,
        "staff_id": item.staff_id,
        "starts_at": item.starts_at.isoformat(),
        "ends_at": item.ends_at.isoformat(),
        "status": item.status,
        "version": item.version,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def _reservation_from_dict(value: object) -> Reservation:
    if not isinstance(value, dict):
        raise ValueError("reservation record is invalid")
    expected = {
        "reservation_id",
        "customer_name",
        "phone",
        "service_id",
        "staff_id",
        "starts_at",
        "ends_at",
        "status",
        "version",
        "created_at",
        "updated_at",
    }
    if set(value) != expected:
        raise ValueError("reservation record fields are invalid")
    return Reservation(
        reservation_id=UUID(str(value["reservation_id"])),
        customer_name=str(value["customer_name"]),
        phone=str(value["phone"]),
        service_id=str(value["service_id"]),
        staff_id=str(value["staff_id"]),
        starts_at=datetime.fromisoformat(str(value["starts_at"])),
        ends_at=datetime.fromisoformat(str(value["ends_at"])),
        status=str(value["status"]),  # type: ignore[arg-type]
        version=int(value["version"]),
        created_at=datetime.fromisoformat(str(value["created_at"])),
        updated_at=datetime.fromisoformat(str(value["updated_at"])),
    )
