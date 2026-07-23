"""Execute a router-approved model switch through a registered runtime port."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, replace
from time import perf_counter
from types import MappingProxyType
from typing import Awaitable, Callable, Mapping, Protocol
from uuid import UUID

from .model_router import ModelId
from ..domain.model_runtime import ModelRuntime, ModelRuntimeState


@dataclass(frozen=True, slots=True)
class RuntimeActionReceipt:
    model_id: ModelId
    action: str
    evidence_path: str

    def __post_init__(self) -> None:
        if self.action not in {"start", "health", "stop"}:
            raise ValueError("runtime receipt action is invalid")
        if not self.evidence_path:
            raise ValueError("runtime receipt requires evidence")


class RuntimeProcessError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        evidence_path: str,
    ) -> None:
        if not code or not evidence_path:
            raise ValueError("runtime process errors require code and evidence")
        super().__init__(message)
        self.code = code
        self.evidence_path = evidence_path


@dataclass(frozen=True, slots=True)
class _RuntimeActionFailure(Exception):
    model_id: ModelId
    error: RuntimeProcessError


class RuntimeProcessPort(Protocol):
    async def start(self, model_id: ModelId) -> RuntimeActionReceipt: ...

    async def health_check(self, model_id: ModelId) -> RuntimeActionReceipt: ...

    async def stop(self, model_id: ModelId) -> RuntimeActionReceipt: ...


class ModelSwitchDeferred(RuntimeError):
    pass


class ModelActivityBarrier:
    """Block new voice turns while a model switch drains active turns."""

    def __init__(self, *, drain_timeout_seconds: float = 300) -> None:
        if not 0.01 <= drain_timeout_seconds <= 900:
            raise ValueError("model drain timeout is invalid")
        self._drain_timeout_seconds = drain_timeout_seconds
        self._condition = asyncio.Condition()
        self._active_users = 0
        self._switching = False

    @property
    def active_users(self) -> int:
        return self._active_users

    async def acquire_usage(self) -> None:
        async with self._condition:
            await self._condition.wait_for(lambda: not self._switching)
            self._active_users += 1

    async def release_usage(self) -> None:
        async with self._condition:
            if self._active_users < 1:
                raise RuntimeError("model usage release is unbalanced")
            self._active_users -= 1
            self._condition.notify_all()

    async def begin_switch(self) -> None:
        async with self._condition:
            if self._switching:
                raise RuntimeError("model switch barrier is already active")
            self._switching = True
            try:
                async with asyncio.timeout(self._drain_timeout_seconds):
                    await self._condition.wait_for(
                        lambda: self._active_users == 0
                    )
            except BaseException as error:
                self._switching = False
                self._condition.notify_all()
                if isinstance(error, TimeoutError):
                    raise ModelSwitchDeferred(
                        "active model requests did not drain"
                    ) from error
                raise

    async def end_switch(self) -> None:
        async with self._condition:
            if not self._switching:
                raise RuntimeError("model switch barrier is not active")
            self._switching = False
            self._condition.notify_all()


@dataclass(frozen=True, slots=True)
class ModelSwitchEvent:
    type: str
    payload: dict[str, object]


ModelSwitchEmitter = Callable[[ModelSwitchEvent], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ModelSwitchResult:
    requested_model: ModelId
    ready_model: ModelId | None
    changed: bool
    degraded: bool
    failure_code: str | None
    duration_ms: float
    events: tuple[ModelSwitchEvent, ...]
    replayed: bool = False


class ModelSwitchCoordinator:
    """Serializes exclusive-GPU model lifecycle actions.

    The coordinator never constructs a command. The runtime port accepts only
    the closed ``ModelId`` enum and owns process identity, command, timeout,
    health, and evidence validation.
    """

    def __init__(
        self,
        *,
        process_port: RuntimeProcessPort,
        runtimes: Mapping[ModelId, ModelRuntime],
        activity_barrier: ModelActivityBarrier | None = None,
    ) -> None:
        required = {ModelId.GEMMA4_12B, ModelId.GEMMA4_31B}
        if set(runtimes) != required:
            raise ValueError("runtime set must contain exactly 12B and 31B")
        for model_id, runtime in runtimes.items():
            if runtime.model_id != model_id.value:
                raise ValueError(f"runtime identity mismatch for {model_id.value}")
        self._process_port = process_port
        self._runtimes = dict(runtimes)
        self._activity_barrier = activity_barrier or ModelActivityBarrier()
        self._lock = asyncio.Lock()
        self._results: OrderedDict[
            UUID,
            tuple[ModelId, ModelSwitchResult],
        ] = OrderedDict()

    @property
    def runtimes(self) -> Mapping[ModelId, ModelRuntime]:
        return MappingProxyType(dict(self._runtimes))

    async def switch(
        self,
        target: ModelId,
        *,
        idempotency_key: UUID | None = None,
        emit: ModelSwitchEmitter | None = None,
    ) -> ModelSwitchResult:
        started = perf_counter()
        events: list[ModelSwitchEvent] = []
        async with self._lock:
            if idempotency_key is not None and idempotency_key in self._results:
                prior_target, prior_result = self._results[idempotency_key]
                if prior_target is not target:
                    raise ValueError(
                        "model switch idempotency key conflicts with target"
                    )
                return replace(prior_result, events=(), replayed=True)
            ready = self._ready_model()
            if ready is target:
                return self._cache_result(
                    idempotency_key,
                    target,
                    ModelSwitchResult(
                        requested_model=target,
                        ready_model=ready,
                        changed=False,
                        degraded=False,
                        failure_code=None,
                        duration_ms=(perf_counter() - started) * 1_000,
                        events=(),
                    ),
                )
            await self._started_event(
                from_model=ready,
                to_model=target,
                phase="saving_state",
                events=events,
                emit=emit,
            )
            try:
                await self._activity_barrier.begin_switch()
            except ModelSwitchDeferred:
                await self._completed_event(
                    from_model=ready,
                    to_model=target,
                    ready=False,
                    duration_ms=(perf_counter() - started) * 1_000,
                    events=events,
                    emit=emit,
                )
                return self._cache_result(
                    idempotency_key,
                    target,
                    self._result(
                        requested_model=target,
                        changed=False,
                        degraded=False,
                        failure_code="MODEL_SWITCH_DRAIN_TIMEOUT",
                        started=started,
                        events=events,
                    ),
                )
            try:
                try:
                    await self._switch_once(
                        target,
                        from_model=ready,
                        operation_started=started,
                        events=events,
                        emit=emit,
                    )
                except _RuntimeActionFailure as failure:
                    error = failure.error
                    await self._record_failure(
                        failure.model_id,
                        event_target=target,
                        error=error,
                        from_model=ready,
                        events=events,
                        emit=emit,
                        started=started,
                    )
                    if (
                        target is not ModelId.GEMMA4_31B
                        or failure.model_id is not target
                    ):
                        return self._cache_result(
                            idempotency_key,
                            target,
                            self._result(
                                requested_model=target,
                                changed=True,
                                degraded=True,
                                failure_code=error.code,
                                started=started,
                                events=events,
                            ),
                        )
                    cleaned = await self._cleanup_failed(
                        target,
                        from_model=ready,
                        events=events,
                        emit=emit,
                        started=started,
                    )
                    if not cleaned:
                        return self._cache_result(
                            idempotency_key,
                            target,
                            self._result(
                                requested_model=target,
                                changed=True,
                                degraded=True,
                                failure_code=error.code,
                                started=started,
                                events=events,
                            ),
                        )
                    try:
                        await self._switch_once(
                            ModelId.GEMMA4_12B,
                            from_model=None,
                            operation_started=started,
                            events=events,
                            emit=emit,
                        )
                    except _RuntimeActionFailure as fallback_failure:
                        fallback_error = fallback_failure.error
                        await self._record_failure(
                            fallback_failure.model_id,
                            event_target=ModelId.GEMMA4_12B,
                            error=fallback_error,
                            from_model=None,
                            events=events,
                            emit=emit,
                            started=started,
                        )
                        return self._cache_result(
                            idempotency_key,
                            target,
                            self._result(
                                requested_model=target,
                                changed=True,
                                degraded=True,
                                failure_code=fallback_error.code,
                                started=started,
                                events=events,
                            ),
                        )
                    return self._cache_result(
                        idempotency_key,
                        target,
                        self._result(
                            requested_model=target,
                            changed=True,
                            degraded=True,
                            failure_code=error.code,
                            started=started,
                            events=events,
                        ),
                    )

                return self._cache_result(
                    idempotency_key,
                    target,
                    self._result(
                        requested_model=target,
                        changed=True,
                        degraded=False,
                        failure_code=None,
                        started=started,
                        events=events,
                    ),
                )
            finally:
                await self._activity_barrier.end_switch()

    async def _switch_once(
        self,
        target: ModelId,
        *,
        from_model: ModelId | None,
        operation_started: float,
        events: list[ModelSwitchEvent],
        emit: ModelSwitchEmitter | None,
    ) -> None:
        if from_model is not None and from_model is not target:
            self._transition(
                from_model,
                ModelRuntimeState.DRAINING,
                reason=f"switch to {target.value}",
            )
            await self._started_event(
                from_model=from_model,
                to_model=target,
                phase="unloading",
                events=events,
                emit=emit,
            )
            self._transition(
                from_model,
                ModelRuntimeState.UNLOADING,
                reason="new requests drained",
            )
            await self._invoke(
                "stop",
                self._process_port.stop,
                from_model,
            )
            self._transition(
                from_model,
                ModelRuntimeState.UNLOADED,
                reason="owned runtime stopped",
            )

        target_runtime = self._runtimes[target]
        if target_runtime.state is ModelRuntimeState.FAILED:
            cleaned = await self._cleanup_failed(
                target,
                from_model=from_model,
                events=events,
                emit=emit,
                started=operation_started,
            )
            if not cleaned:
                latest = self._runtimes[target].events[-1]
                if not latest.failure_code or not latest.evidence_path:
                    raise RuntimeError(
                        "failed runtime cleanup has no failure evidence"
                    )
                raise _RuntimeActionFailure(
                    target,
                    RuntimeProcessError(
                        "failed target runtime cleanup did not complete",
                        code=latest.failure_code,
                        evidence_path=latest.evidence_path,
                    ),
                )

        self._transition(
            target,
            ModelRuntimeState.LOADING,
            reason="registered runtime start requested",
        )
        await self._started_event(
            from_model=from_model,
            to_model=target,
            phase="loading",
            events=events,
            emit=emit,
        )
        await self._invoke(
            "start",
            self._process_port.start,
            target,
        )
        self._transition(
            target,
            ModelRuntimeState.HEALTH_CHECKING,
            reason="runtime process started",
        )
        await self._started_event(
            from_model=from_model,
            to_model=target,
            phase="health_checking",
            events=events,
            emit=emit,
        )
        await self._invoke(
            "health",
            self._process_port.health_check,
            target,
        )
        self._transition(
            target,
            ModelRuntimeState.READY,
            reason="runtime health check passed",
        )
        await self._completed_event(
            from_model=from_model,
            to_model=target,
            ready=True,
            duration_ms=(perf_counter() - operation_started) * 1_000,
            events=events,
            emit=emit,
        )

    async def _record_failure(
        self,
        model_id: ModelId,
        *,
        event_target: ModelId,
        error: RuntimeProcessError,
        from_model: ModelId | None,
        events: list[ModelSwitchEvent],
        emit: ModelSwitchEmitter | None,
        started: float,
    ) -> None:
        runtime = self._runtimes[model_id]
        if runtime.state in {
            ModelRuntimeState.LOADING,
            ModelRuntimeState.HEALTH_CHECKING,
            ModelRuntimeState.DRAINING,
            ModelRuntimeState.UNLOADING,
            ModelRuntimeState.READY,
        }:
            self._transition(
                model_id,
                ModelRuntimeState.FAILED,
                reason=str(error),
                failure_code=error.code,
                evidence_path=error.evidence_path,
            )
        await self._completed_event(
            from_model=from_model,
            to_model=event_target,
            ready=False,
            duration_ms=(perf_counter() - started) * 1_000,
            events=events,
            emit=emit,
        )

    async def _cleanup_failed(
        self,
        model_id: ModelId,
        *,
        from_model: ModelId | None,
        events: list[ModelSwitchEvent],
        emit: ModelSwitchEmitter | None,
        started: float,
    ) -> bool:
        runtime = self._runtimes[model_id]
        if runtime.state is not ModelRuntimeState.FAILED:
            return runtime.state is ModelRuntimeState.UNLOADED
        self._transition(
            model_id,
            ModelRuntimeState.UNLOADING,
            reason="cleanup failed owned runtime",
        )
        await self._started_event(
            from_model=from_model,
            to_model=model_id,
            phase="unloading",
            events=events,
            emit=emit,
        )
        try:
            await self._invoke(
                "stop",
                self._process_port.stop,
                model_id,
            )
        except _RuntimeActionFailure as cleanup_failure:
            cleanup_error = cleanup_failure.error
            self._transition(
                model_id,
                ModelRuntimeState.FAILED,
                reason=str(cleanup_error),
                failure_code=cleanup_error.code,
                evidence_path=cleanup_error.evidence_path,
            )
            await self._completed_event(
                from_model=from_model,
                to_model=model_id,
                ready=False,
                duration_ms=(perf_counter() - started) * 1_000,
                events=events,
                emit=emit,
            )
            return False
        self._transition(
            model_id,
            ModelRuntimeState.UNLOADED,
            reason="failed runtime cleanup complete",
        )
        return True

    @staticmethod
    async def _invoke(
        action_name: str,
        action: Callable[[ModelId], Awaitable[RuntimeActionReceipt]],
        model_id: ModelId,
    ) -> RuntimeActionReceipt:
        try:
            receipt = await action(model_id)
        except RuntimeProcessError as error:
            raise _RuntimeActionFailure(model_id, error) from error
        if receipt.model_id is not model_id:
            raise RuntimeError("runtime action receipt model identity mismatch")
        if receipt.action != action_name:
            raise RuntimeError("runtime action receipt action mismatch")
        return receipt

    def _transition(
        self,
        model_id: ModelId,
        state: ModelRuntimeState,
        *,
        reason: str,
        failure_code: str | None = None,
        evidence_path: str | None = None,
    ) -> None:
        current = self._runtimes[model_id]
        self._runtimes[model_id] = current.transition(
            state,
            expected_version=current.version,
            reason=reason,
            failure_code=failure_code,
            evidence_path=evidence_path,
        )

    def _ready_model(self) -> ModelId | None:
        ready = [
            model_id
            for model_id, runtime in self._runtimes.items()
            if runtime.state is ModelRuntimeState.READY
        ]
        if len(ready) > 1:
            raise RuntimeError("multiple model runtimes are READY")
        return ready[0] if ready else None

    def _result(
        self,
        *,
        requested_model: ModelId,
        changed: bool,
        degraded: bool,
        failure_code: str | None,
        started: float,
        events: list[ModelSwitchEvent],
    ) -> ModelSwitchResult:
        return ModelSwitchResult(
            requested_model=requested_model,
            ready_model=self._ready_model(),
            changed=changed,
            degraded=degraded,
            failure_code=failure_code,
            duration_ms=(perf_counter() - started) * 1_000,
            events=tuple(events),
        )

    def _cache_result(
        self,
        idempotency_key: UUID | None,
        target: ModelId,
        result: ModelSwitchResult,
    ) -> ModelSwitchResult:
        if idempotency_key is None:
            return result
        self._results[idempotency_key] = (target, result)
        self._results.move_to_end(idempotency_key)
        while len(self._results) > 256:
            self._results.popitem(last=False)
        return result

    async def _started_event(
        self,
        *,
        from_model: ModelId | None,
        to_model: ModelId,
        phase: str,
        events: list[ModelSwitchEvent],
        emit: ModelSwitchEmitter | None,
    ) -> None:
        await self._deliver(
            ModelSwitchEvent(
                "model.switch.started",
                {
                    "from_model": (
                        from_model.value if from_model is not None else None
                    ),
                    "to_model": to_model.value,
                    "phase": phase,
                },
            ),
            events=events,
            emit=emit,
        )

    async def _completed_event(
        self,
        *,
        from_model: ModelId | None,
        to_model: ModelId,
        ready: bool,
        duration_ms: float,
        events: list[ModelSwitchEvent],
        emit: ModelSwitchEmitter | None,
    ) -> None:
        await self._deliver(
            ModelSwitchEvent(
                "model.switch.completed",
                {
                    "from_model": (
                        from_model.value if from_model is not None else None
                    ),
                    "to_model": to_model.value,
                    "ready": ready,
                    "duration_ms": max(0.0, duration_ms),
                },
            ),
            events=events,
            emit=emit,
        )

    @staticmethod
    async def _deliver(
        event: ModelSwitchEvent,
        *,
        events: list[ModelSwitchEvent],
        emit: ModelSwitchEmitter | None,
    ) -> None:
        events.append(event)
        if emit is not None:
            await emit(event)
