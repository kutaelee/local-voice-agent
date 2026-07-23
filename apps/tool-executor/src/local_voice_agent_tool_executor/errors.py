"""Stable expected errors for tool-executor boundaries."""

from __future__ import annotations


class ToolExecutorError(Exception):
    code = "TOOL_EXECUTOR_ERROR"


class ToolContractError(ToolExecutorError):
    code = "TOOL_CONTRACT_ERROR"


class ToolArgumentsInvalid(ToolExecutorError):
    code = "SCHEMA_INVALID"


class ToolNotSupported(ToolExecutorError):
    code = "TOOL_NOT_SUPPORTED"


class WorkspaceConfigurationError(ToolExecutorError):
    code = "WORKSPACE_CONFIGURATION_INVALID"


class WorkspaceNotFound(ToolExecutorError):
    code = "WORKSPACE_NOT_FOUND"


class WorkspacePathRejected(ToolExecutorError):
    code = "WORKSPACE_PATH_REJECTED"


class WorkspacePathNotFound(ToolExecutorError):
    code = "WORKSPACE_PATH_NOT_FOUND"


class WorkspaceTypeMismatch(ToolExecutorError):
    code = "WORKSPACE_PATH_TYPE_MISMATCH"


class WorkspacePathChanged(ToolExecutorError):
    code = "WORKSPACE_PATH_CHANGED"


class TextDecodingError(ToolExecutorError):
    code = "TEXT_DECODING_ERROR"


class MutationPreconditionFailed(ToolExecutorError):
    code = "MUTATION_PRECONDITION_FAILED"


class PatchRejected(ToolExecutorError):
    code = "PATCH_REJECTED"


class RollbackRejected(ToolExecutorError):
    code = "ROLLBACK_REJECTED"


class GitWorkspaceRejected(ToolExecutorError):
    code = "GIT_WORKSPACE_REJECTED"


class GitCommandFailed(ToolExecutorError):
    code = "GIT_COMMAND_FAILED"


class GitCommandTimedOut(ToolExecutorError):
    code = "GIT_COMMAND_TIMED_OUT"


class GitOutputDecodingError(ToolExecutorError):
    code = "GIT_OUTPUT_DECODING_ERROR"


class ExecutionBindingError(ToolExecutorError):
    code = "EXECUTION_BINDING_MISMATCH"


class ExecutionExpired(ToolExecutorError):
    code = "EXECUTION_EXPIRED"


class IdempotencyConflict(ToolExecutorError):
    code = "IDEMPOTENCY_CONFLICT"


class EvidenceWriteError(ToolExecutorError):
    code = "EVIDENCE_WRITE_ERROR"


class InternalExecutionError(ToolExecutorError):
    code = "INTERNAL_EXECUTION_ERROR"
