"""Loopback-only authenticated HTTP boundary for bound tool executions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hmac
from typing import Any, Literal
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .errors import (
    ExecutionExpired,
    IdempotencyConflict,
    ToolExecutorError,
)
from .service import BoundExecutionService, ExecutionCommand


class ExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    execution_id: UUID
    session_id: UUID
    request_id: UUID
    tool_call_id: UUID
    idempotency_key: UUID
    tool_name: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=128)
    arguments: dict[str, Any]
    normalized_arguments_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    tool_definition_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    risk_level: Literal[0]
    requested_at: datetime
    expires_at: datetime

    @field_validator("requested_at", "expires_at")
    @classmethod
    def timestamps_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a UTC offset")
        return value

    def to_command(self) -> ExecutionCommand:
        return ExecutionCommand(
            execution_id=str(self.execution_id),
            session_id=str(self.session_id),
            request_id=str(self.request_id),
            tool_call_id=str(self.tool_call_id),
            idempotency_key=str(self.idempotency_key),
            tool_name=self.tool_name,
            arguments=self.arguments,
            normalized_arguments_sha256=self.normalized_arguments_sha256,
            tool_definition_sha256=self.tool_definition_sha256,
            risk_level=self.risk_level,
            requested_at=self.requested_at,
            expires_at=self.expires_at,
        )


@dataclass(frozen=True, slots=True)
class ExecutorApiSettings:
    ipc_token: str
    max_request_bytes: int = 65_536

    def __post_init__(self) -> None:
        if len(self.ipc_token) < 32:
            raise ValueError("IPC token must contain at least 32 characters")
        if self.ipc_token == "CHANGE_ME":
            raise ValueError("placeholder IPC token is forbidden")
        if not 1_024 <= self.max_request_bytes <= 1_048_576:
            raise ValueError("max_request_bytes is outside the safety range")


def create_app(
    *,
    settings: ExecutorApiSettings,
    service: BoundExecutionService,
) -> FastAPI:
    app = FastAPI(
        title="Local Voice Agent Tool Executor",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def authenticate_and_bound_body(
        request: Request,
        call_next: Any,
    ) -> Any:
        if request.url.path != "/v1/executions":
            return await call_next(request)
        authorization = request.headers.get("authorization", "")
        if not hmac.compare_digest(
            authorization,
            f"Bearer {settings.ipc_token}",
        ):
            return JSONResponse(
                status_code=401,
                content={"error_code": "UNAUTHORIZED", "message": "unauthorized"},
            )
        content_type = request.headers.get("content-type", "")
        if not content_type.lower().startswith("application/json"):
            return JSONResponse(
                status_code=415,
                content={
                    "error_code": "CONTENT_TYPE_INVALID",
                    "message": "application/json required",
                },
            )
        body = await request.body()
        if len(body) > settings.max_request_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "error_code": "REQUEST_TOO_LARGE",
                    "message": "request body exceeds limit",
                },
            )
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        _request: Request,
        _error: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "error_code": "SCHEMA_INVALID",
                "message": "request does not match the closed schema",
            },
        )

    @app.exception_handler(ToolExecutorError)
    async def executor_error(
        _request: Request,
        error: ToolExecutorError,
    ) -> JSONResponse:
        if isinstance(error, ExecutionExpired):
            status_code = 410
        elif isinstance(error, IdempotencyConflict):
            status_code = 409
        else:
            status_code = 400
        return JSONResponse(
            status_code=status_code,
            content={
                "error_code": error.code,
                "message": "execution rejected",
            },
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "component": "tool-executor"}

    @app.post("/v1/executions")
    def execute(request: ExecutionRequest) -> dict[str, Any]:
        return service.execute(request.to_command())

    return app
