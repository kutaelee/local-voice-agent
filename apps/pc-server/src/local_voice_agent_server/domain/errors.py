"""Domain errors with stable machine-readable codes."""

from __future__ import annotations


class DomainError(Exception):
    """Base class for expected domain rule violations."""

    code = "DOMAIN_ERROR"


class InvalidTransition(DomainError):
    code = "INVALID_TRANSITION"


class OptimisticLockError(DomainError):
    code = "OPTIMISTIC_LOCK_CONFLICT"


class ApprovalBindingError(DomainError):
    code = "APPROVAL_BINDING_MISMATCH"


class ApprovalExpired(DomainError):
    code = "APPROVAL_EXPIRED"


class OperationNotCancellable(DomainError):
    code = "OPERATION_NOT_CANCELLABLE"
