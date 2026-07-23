"""Append-only structured audit events and atomic metadata-only evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import stat
import tempfile
from threading import RLock
from typing import Any, Mapping
from uuid import UUID

from .digests import canonical_json
from .errors import EvidenceWriteError
from .workspaces import _is_link_or_reparse


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    evidence_id: str
    path: Path


class AuditEvidenceStore:
    def __init__(self, *, audit_log: Path, evidence_dir: Path) -> None:
        self._audit_log = Path(audit_log)
        self._evidence_dir = Path(evidence_dir)
        self._lock = RLock()
        if not self._audit_log.is_absolute() or not self._evidence_dir.is_absolute():
            raise EvidenceWriteError("audit/evidence paths must be absolute")
        try:
            self._audit_log.parent.mkdir(parents=True, exist_ok=True)
            self._evidence_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise EvidenceWriteError("cannot prepare audit/evidence paths") from error
        if self._audit_log.exists() and not self._audit_log.is_file():
            raise EvidenceWriteError("audit path is not a file")
        if not self._evidence_dir.is_dir():
            raise EvidenceWriteError("evidence path is not a directory")
        _assert_no_link_segments(self._audit_log.parent)
        _assert_no_link_segments(self._evidence_dir)
        if self._audit_log.exists():
            _assert_regular_file(self._audit_log)

    def append_event(self, event: Mapping[str, Any]) -> None:
        line = canonical_json(dict(event)) + b"\n"
        with self._lock:
            _assert_no_link_segments(self._audit_log.parent)
            if self._audit_log.exists():
                _assert_regular_file(self._audit_log)
            try:
                flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
                flags |= getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(self._audit_log, flags, 0o600)
                with os.fdopen(descriptor, "ab", buffering=0) as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise EvidenceWriteError("audit target is not a regular file")
                    stream.write(line)
                    os.fsync(stream.fileno())
            except OSError as error:
                raise EvidenceWriteError("cannot append audit event") from error

    def write_evidence(
        self,
        *,
        execution_id: str,
        evidence: Mapping[str, Any],
    ) -> EvidenceReference:
        try:
            parsed = UUID(execution_id)
        except (ValueError, TypeError, AttributeError) as error:
            raise EvidenceWriteError("execution_id must be a UUID") from error
        if str(parsed) != execution_id.lower():
            raise EvidenceWriteError("execution_id must use canonical UUID text")
        target = self._evidence_dir / f"{execution_id}.json"
        payload = canonical_json(dict(evidence)) + b"\n"
        with self._lock:
            _assert_no_link_segments(self._evidence_dir)
            if target.exists():
                raise EvidenceWriteError("evidence target already exists")
            temporary_name: str | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=self._evidence_dir,
                    prefix=f".{execution_id}.",
                    suffix=".partial",
                    delete=False,
                ) as stream:
                    temporary_name = stream.name
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(temporary_name, target)
                Path(temporary_name).unlink()
            except OSError as error:
                raise EvidenceWriteError("cannot write evidence atomically") from error
            finally:
                if temporary_name is not None:
                    temporary = Path(temporary_name)
                    if temporary.exists():
                        temporary.unlink()
        return EvidenceReference(evidence_id=execution_id, path=target)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _assert_no_link_segments(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            current_stat = current.lstat()
        except OSError as error:
            raise EvidenceWriteError("audit/evidence path is unavailable") from error
        if _is_link_or_reparse(current, current_stat):
            raise EvidenceWriteError(
                "audit/evidence links and reparse points are forbidden"
            )


def _assert_regular_file(path: Path) -> None:
    try:
        path_stat = path.lstat()
    except OSError as error:
        raise EvidenceWriteError("audit target is unavailable") from error
    if _is_link_or_reparse(path, path_stat) or not stat.S_ISREG(path_stat.st_mode):
        raise EvidenceWriteError("audit target must be a regular non-link file")
