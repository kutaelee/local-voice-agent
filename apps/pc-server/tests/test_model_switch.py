from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from local_voice_agent_server.application.model_router import ModelId
from local_voice_agent_server.application.model_switch import (
    ModelActivityBarrier,
    ModelSwitchCoordinator,
    RuntimeActionReceipt,
    RuntimeProcessError,
)
from local_voice_agent_server.domain.model_runtime import (
    ModelRuntime,
    ModelRuntimeState,
)


class FakeRuntimeProcessPort:
    def __init__(
        self,
        *,
        failures: dict[tuple[str, ModelId], list[RuntimeProcessError]]
        | None = None,
    ) -> None:
        self.calls: list[tuple[str, ModelId]] = []
        self.failures = failures or {}

    async def start(self, model_id: ModelId) -> RuntimeActionReceipt:
        return self._run("start", model_id)

    async def health_check(self, model_id: ModelId) -> RuntimeActionReceipt:
        return self._run("health", model_id)

    async def stop(self, model_id: ModelId) -> RuntimeActionReceipt:
        return self._run("stop", model_id)

    def _run(self, action: str, model_id: ModelId) -> RuntimeActionReceipt:
        self.calls.append((action, model_id))
        queued = self.failures.get((action, model_id), [])
        if queued:
            raise queued.pop(0)
        return RuntimeActionReceipt(
            model_id=model_id,
            action=action,
            evidence_path=f"/evidence/{model_id.value}-{action}.json",
        )


def fleet(
    state_12b: ModelRuntimeState,
    state_31b: ModelRuntimeState,
) -> dict[ModelId, ModelRuntime]:
    return {
        ModelId.GEMMA4_12B: ModelRuntime(
            model_id=ModelId.GEMMA4_12B.value,
            state=state_12b,
        ),
        ModelId.GEMMA4_31B: ModelRuntime(
            model_id=ModelId.GEMMA4_31B.value,
            state=state_31b,
        ),
    }


def failure(code: str) -> RuntimeProcessError:
    return RuntimeProcessError(
        f"synthetic {code}",
        code=code,
        evidence_path=f"/evidence/{code}.json",
    )


def test_switch_stops_ready_12b_before_starting_and_checking_31b() -> None:
    port = FakeRuntimeProcessPort()
    coordinator = ModelSwitchCoordinator(
        process_port=port,
        runtimes=fleet(
            ModelRuntimeState.READY,
            ModelRuntimeState.UNLOADED,
        ),
    )
    emitted = []

    async def emit(event) -> None:
        emitted.append(event)

    async def scenario():
        return await coordinator.switch(
            ModelId.GEMMA4_31B,
            emit=emit,
        )

    result = asyncio.run(scenario())

    assert port.calls == [
        ("stop", ModelId.GEMMA4_12B),
        ("start", ModelId.GEMMA4_31B),
        ("health", ModelId.GEMMA4_31B),
    ]
    assert result.ready_model is ModelId.GEMMA4_31B
    assert result.degraded is False
    assert coordinator.runtimes[ModelId.GEMMA4_12B].state is (
        ModelRuntimeState.UNLOADED
    )
    assert coordinator.runtimes[ModelId.GEMMA4_31B].state is (
        ModelRuntimeState.READY
    )
    assert [event.type for event in emitted] == [
        "model.switch.started",
        "model.switch.started",
        "model.switch.started",
        "model.switch.started",
        "model.switch.completed",
    ]
    assert [event.payload.get("phase") for event in emitted[:-1]] == [
        "saving_state",
        "unloading",
        "loading",
        "health_checking",
    ]
    assert emitted[-1].payload["ready"] is True
    assert emitted[-1].payload["duration_ms"] >= 0


def test_switch_to_already_ready_model_is_idempotent() -> None:
    port = FakeRuntimeProcessPort()
    coordinator = ModelSwitchCoordinator(
        process_port=port,
        runtimes=fleet(
            ModelRuntimeState.READY,
            ModelRuntimeState.UNLOADED,
        ),
    )

    result = asyncio.run(coordinator.switch(ModelId.GEMMA4_12B))

    assert result.changed is False
    assert result.ready_model is ModelId.GEMMA4_12B
    assert result.events == ()
    assert port.calls == []


def test_idempotency_key_replays_exact_result_and_rejects_conflict() -> None:
    port = FakeRuntimeProcessPort()
    coordinator = ModelSwitchCoordinator(
        process_port=port,
        runtimes=fleet(
            ModelRuntimeState.READY,
            ModelRuntimeState.UNLOADED,
        ),
    )
    key = uuid4()

    first = asyncio.run(
        coordinator.switch(
            ModelId.GEMMA4_31B,
            idempotency_key=key,
        )
    )
    replay = asyncio.run(
        coordinator.switch(
            ModelId.GEMMA4_31B,
            idempotency_key=key,
        )
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.ready_model is ModelId.GEMMA4_31B
    assert replay.events == ()
    assert port.calls == [
        ("stop", ModelId.GEMMA4_12B),
        ("start", ModelId.GEMMA4_31B),
        ("health", ModelId.GEMMA4_31B),
    ]
    with pytest.raises(ValueError, match="conflicts"):
        asyncio.run(
            coordinator.switch(
                ModelId.GEMMA4_12B,
                idempotency_key=key,
            )
        )


def test_31b_start_failure_cleans_failed_process_and_restores_12b() -> None:
    port = FakeRuntimeProcessPort(
        failures={
            ("start", ModelId.GEMMA4_31B): [
                failure("MODEL_31B_LOAD_FAILED")
            ]
        }
    )
    coordinator = ModelSwitchCoordinator(
        process_port=port,
        runtimes=fleet(
            ModelRuntimeState.READY,
            ModelRuntimeState.UNLOADED,
        ),
    )

    result = asyncio.run(coordinator.switch(ModelId.GEMMA4_31B))

    assert port.calls == [
        ("stop", ModelId.GEMMA4_12B),
        ("start", ModelId.GEMMA4_31B),
        ("stop", ModelId.GEMMA4_31B),
        ("start", ModelId.GEMMA4_12B),
        ("health", ModelId.GEMMA4_12B),
    ]
    assert result.requested_model is ModelId.GEMMA4_31B
    assert result.ready_model is ModelId.GEMMA4_12B
    assert result.degraded is True
    assert result.failure_code == "MODEL_31B_LOAD_FAILED"
    assert coordinator.runtimes[ModelId.GEMMA4_31B].state is (
        ModelRuntimeState.UNLOADED
    )
    assert coordinator.runtimes[ModelId.GEMMA4_12B].state is (
        ModelRuntimeState.READY
    )
    assert any(
        event.type == "model.switch.completed"
        and event.payload["to_model"] == ModelId.GEMMA4_31B.value
        and event.payload["ready"] is False
        for event in result.events
    )


def test_source_stop_failure_never_starts_target() -> None:
    port = FakeRuntimeProcessPort(
        failures={
            ("stop", ModelId.GEMMA4_12B): [
                failure("OWNED_PROCESS_STOP_FAILED")
            ]
        }
    )
    coordinator = ModelSwitchCoordinator(
        process_port=port,
        runtimes=fleet(
            ModelRuntimeState.READY,
            ModelRuntimeState.UNLOADED,
        ),
    )

    result = asyncio.run(coordinator.switch(ModelId.GEMMA4_31B))

    assert port.calls == [("stop", ModelId.GEMMA4_12B)]
    assert result.ready_model is None
    assert result.failure_code == "OWNED_PROCESS_STOP_FAILED"
    assert coordinator.runtimes[ModelId.GEMMA4_12B].state is (
        ModelRuntimeState.FAILED
    )
    assert coordinator.runtimes[ModelId.GEMMA4_31B].state is (
        ModelRuntimeState.UNLOADED
    )
    assert result.events[-1].payload["from_model"] == "gemma4-12b"
    assert result.events[-1].payload["to_model"] == "gemma4-31b"
    assert result.events[-1].payload["ready"] is False


def test_31b_cleanup_failure_prevents_12b_reload() -> None:
    port = FakeRuntimeProcessPort(
        failures={
            ("start", ModelId.GEMMA4_31B): [
                failure("MODEL_31B_LOAD_FAILED")
            ],
            ("stop", ModelId.GEMMA4_31B): [
                failure("MODEL_31B_CLEANUP_FAILED")
            ],
        }
    )
    coordinator = ModelSwitchCoordinator(
        process_port=port,
        runtimes=fleet(
            ModelRuntimeState.READY,
            ModelRuntimeState.UNLOADED,
        ),
    )

    result = asyncio.run(coordinator.switch(ModelId.GEMMA4_31B))

    assert port.calls == [
        ("stop", ModelId.GEMMA4_12B),
        ("start", ModelId.GEMMA4_31B),
        ("stop", ModelId.GEMMA4_31B),
    ]
    assert result.ready_model is None
    assert result.degraded is True
    assert result.failure_code == "MODEL_31B_LOAD_FAILED"
    assert coordinator.runtimes[ModelId.GEMMA4_31B].state is (
        ModelRuntimeState.FAILED
    )


def test_switch_waits_for_active_model_usage_to_drain() -> None:
    async def scenario() -> None:
        port = FakeRuntimeProcessPort()
        barrier = ModelActivityBarrier(drain_timeout_seconds=1)
        coordinator = ModelSwitchCoordinator(
            process_port=port,
            runtimes=fleet(
                ModelRuntimeState.READY,
                ModelRuntimeState.UNLOADED,
            ),
            activity_barrier=barrier,
        )
        await barrier.acquire_usage()
        switching = asyncio.create_task(
            coordinator.switch(ModelId.GEMMA4_31B)
        )
        await asyncio.sleep(0)
        assert port.calls == []
        await barrier.release_usage()

        result = await asyncio.wait_for(switching, timeout=1)

        assert result.ready_model is ModelId.GEMMA4_31B
        assert port.calls[0] == ("stop", ModelId.GEMMA4_12B)

    asyncio.run(scenario())


def test_switch_drain_timeout_is_fail_closed_and_barrier_recovers() -> None:
    async def scenario() -> None:
        port = FakeRuntimeProcessPort()
        barrier = ModelActivityBarrier(drain_timeout_seconds=0.01)
        coordinator = ModelSwitchCoordinator(
            process_port=port,
            runtimes=fleet(
                ModelRuntimeState.READY,
                ModelRuntimeState.UNLOADED,
            ),
            activity_barrier=barrier,
        )
        await barrier.acquire_usage()

        result = await coordinator.switch(ModelId.GEMMA4_31B)

        assert result.changed is False
        assert result.failure_code == "MODEL_SWITCH_DRAIN_TIMEOUT"
        assert result.ready_model is ModelId.GEMMA4_12B
        assert port.calls == []
        await barrier.release_usage()
        await barrier.acquire_usage()
        await barrier.release_usage()

    asyncio.run(scenario())
