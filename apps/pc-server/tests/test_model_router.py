from __future__ import annotations

import pytest

from local_voice_agent_server.application.model_router import (
    EscalationReason,
    ModelCapability,
    ModelId,
    ModelRouter,
    Modality,
    RouteDisposition,
    RouteRequest,
)
from local_voice_agent_server.domain.errors import (
    InvalidTransition,
    OptimisticLockError,
)
from local_voice_agent_server.domain.model_runtime import (
    ModelRuntime,
    ModelRuntimeState,
)


def router() -> ModelRouter:
    return ModelRouter(
        [
            ModelCapability(
                model_id=ModelId.GEMMA4_12B,
                supported_modalities=frozenset(Modality),
                validated_modalities=frozenset({Modality.TEXT, Modality.IMAGE}),
                max_context_tokens=8_192,
            ),
            ModelCapability(
                model_id=ModelId.GEMMA4_31B,
                supported_modalities=frozenset({Modality.TEXT, Modality.IMAGE}),
                validated_modalities=frozenset({Modality.TEXT}),
                max_context_tokens=256,
            ),
        ]
    )


def runtime(model_id: ModelId, state: ModelRuntimeState) -> ModelRuntime:
    return ModelRuntime(model_id=model_id.value, state=state)


def fleet(
    state_12b: ModelRuntimeState,
    state_31b: ModelRuntimeState,
) -> dict[ModelId, ModelRuntime]:
    return {
        ModelId.GEMMA4_12B: runtime(ModelId.GEMMA4_12B, state_12b),
        ModelId.GEMMA4_31B: runtime(ModelId.GEMMA4_31B, state_31b),
    }


def escalated_request(
    reason: EscalationReason = EscalationReason.COMPLEX_MULTISTEP_PLAN,
    *,
    modalities: frozenset[Modality] = frozenset({Modality.TEXT}),
) -> RouteRequest:
    return RouteRequest(
        modalities=modalities,
        escalation_reasons=frozenset({reason}),
    )


def test_model_runtime_happy_path_is_versioned_and_stops_accepting_on_drain() -> None:
    item = ModelRuntime(model_id=ModelId.GEMMA4_12B.value)
    for target in (
        ModelRuntimeState.LOADING,
        ModelRuntimeState.HEALTH_CHECKING,
        ModelRuntimeState.READY,
    ):
        item = item.transition(
            target,
            expected_version=item.version,
            reason="test",
        )
    assert item.accepts_new_requests is True
    item = item.transition(
        ModelRuntimeState.DRAINING,
        expected_version=item.version,
        reason="switch requested",
    )
    assert item.accepts_new_requests is False
    assert item.version == 4
    assert tuple(event.version for event in item.events) == (1, 2, 3, 4)


def test_model_runtime_rejects_skipped_and_stale_transitions() -> None:
    item = ModelRuntime(model_id=ModelId.GEMMA4_12B.value)
    with pytest.raises(InvalidTransition):
        item.transition(
            ModelRuntimeState.READY,
            expected_version=0,
            reason="skip checks",
        )
    loading = item.transition(
        ModelRuntimeState.LOADING,
        expected_version=0,
        reason="load",
    )
    with pytest.raises(OptimisticLockError):
        loading.transition(
            ModelRuntimeState.HEALTH_CHECKING,
            expected_version=0,
            reason="stale",
        )


def test_failed_runtime_requires_evidence_and_cleanup_before_retry() -> None:
    loading = ModelRuntime(model_id=ModelId.GEMMA4_31B.value).transition(
        ModelRuntimeState.LOADING,
        expected_version=0,
        reason="load",
    )
    with pytest.raises(ValueError):
        loading.transition(
            ModelRuntimeState.FAILED,
            expected_version=1,
            reason="load failed",
        )
    failed = loading.transition(
        ModelRuntimeState.FAILED,
        expected_version=1,
        reason="load failed",
        failure_code="KV_CACHE_UNAVAILABLE",
        evidence_path=r"E:\Data\LocalVoiceAgent\runtime\evidence\failure.json",
    )
    assert failed.events[-1].failure_code == "KV_CACHE_UNAVAILABLE"
    with pytest.raises(InvalidTransition):
        failed.transition(
            ModelRuntimeState.LOADING,
            expected_version=2,
            reason="unsafe retry",
        )
    unloading = failed.transition(
        ModelRuntimeState.UNLOADING,
        expected_version=2,
        reason="cleanup owned runtime",
    )
    unloaded = unloading.transition(
        ModelRuntimeState.UNLOADED,
        expected_version=3,
        reason="cleanup complete",
    )
    assert unloaded.state is ModelRuntimeState.UNLOADED


def test_default_request_routes_to_ready_12b() -> None:
    decision = router().decide(
        RouteRequest(),
        runtimes=fleet(ModelRuntimeState.READY, ModelRuntimeState.UNLOADED),
    )
    assert decision.disposition is RouteDisposition.ROUTE
    assert decision.target_model is ModelId.GEMMA4_12B
    assert decision.reason_codes == ("DEFAULT_ROUTE",)


def test_escalation_plans_drain_unload_load_health_and_route() -> None:
    decision = router().decide(
        escalated_request(),
        runtimes=fleet(ModelRuntimeState.READY, ModelRuntimeState.UNLOADED),
    )
    assert decision.disposition is RouteDisposition.SWITCH
    assert decision.target_model is ModelId.GEMMA4_31B
    assert decision.actions == (
        "drain:gemma4-12b",
        "unload:gemma4-12b",
        "load:gemma4-31b",
        "health_check:gemma4-31b",
        "route:gemma4-31b",
    )


def test_escalation_routes_directly_to_ready_31b() -> None:
    decision = router().decide(
        escalated_request(),
        runtimes=fleet(ModelRuntimeState.UNLOADED, ModelRuntimeState.READY),
    )
    assert decision.disposition is RouteDisposition.ROUTE
    assert decision.target_model is ModelId.GEMMA4_31B


def test_normal_request_switches_back_to_12b() -> None:
    decision = router().decide(
        RouteRequest(),
        runtimes=fleet(ModelRuntimeState.UNLOADED, ModelRuntimeState.READY),
    )
    assert decision.disposition is RouteDisposition.SWITCH
    assert decision.actions[:2] == (
        "drain:gemma4-31b",
        "unload:gemma4-31b",
    )
    assert decision.actions[-1] == "route:gemma4-12b"


@pytest.mark.parametrize(
    "state",
    [
        ModelRuntimeState.LOADING,
        ModelRuntimeState.HEALTH_CHECKING,
        ModelRuntimeState.DRAINING,
        ModelRuntimeState.UNLOADING,
    ],
)
def test_router_defers_while_any_model_transition_is_active(
    state: ModelRuntimeState,
) -> None:
    decision = router().decide(
        RouteRequest(),
        runtimes=fleet(state, ModelRuntimeState.UNLOADED),
    )
    assert decision.disposition is RouteDisposition.DEFER
    assert decision.reason_codes == ("MODEL_SWITCH_IN_PROGRESS",)


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"voice_priority_active": True}, "VOICE_PRIORITY_ACTIVE"),
        ({"high_vram_task_active": True}, "HIGH_VRAM_TASK_ACTIVE"),
    ],
)
def test_31b_escalation_defers_for_priority_or_gpu_contention(
    kwargs: dict[str, bool],
    reason: str,
) -> None:
    decision = router().decide(
        escalated_request(),
        runtimes=fleet(ModelRuntimeState.READY, ModelRuntimeState.UNLOADED),
        **kwargs,
    )
    assert decision.disposition is RouteDisposition.DEFER
    assert decision.reason_codes == (reason,)


def test_explicit_31b_request_rejects_failed_vram_admission() -> None:
    decision = router().decide(
        escalated_request(EscalationReason.EXPLICIT_USER_REQUEST),
        runtimes=fleet(ModelRuntimeState.READY, ModelRuntimeState.UNLOADED),
        vram_admission_granted=False,
    )
    assert decision.disposition is RouteDisposition.REJECT
    assert decision.target_model is ModelId.GEMMA4_31B
    assert decision.reason_codes == ("VRAM_ADMISSION_REJECTED",)


def test_automatic_escalation_degrades_to_ready_12b_when_vram_is_denied() -> None:
    decision = router().decide(
        escalated_request(),
        runtimes=fleet(ModelRuntimeState.READY, ModelRuntimeState.UNLOADED),
        vram_admission_granted=False,
    )
    assert decision.disposition is RouteDisposition.ROUTE
    assert decision.target_model is ModelId.GEMMA4_12B
    assert decision.reason_codes == ("VRAM_ADMISSION_FALLBACK",)
    assert decision.degraded is True


def test_failed_31b_is_cleaned_before_falling_back_to_ready_12b() -> None:
    decision = router().decide(
        escalated_request(),
        runtimes=fleet(ModelRuntimeState.READY, ModelRuntimeState.FAILED),
    )
    assert decision.disposition is RouteDisposition.SWITCH
    assert decision.target_model is ModelId.GEMMA4_12B
    assert decision.reason_codes == (
        "FALLBACK_AFTER_31B_FAILURE",
        "FAILED_31B_CLEANUP_REQUIRED",
    )
    assert decision.actions == (
        "unload_failed:gemma4-31b",
        "route:gemma4-12b",
    )
    assert decision.degraded is True


def test_failed_31b_is_unloaded_before_12b_recovery_load() -> None:
    decision = router().decide(
        escalated_request(),
        runtimes=fleet(ModelRuntimeState.UNLOADED, ModelRuntimeState.FAILED),
    )
    assert decision.disposition is RouteDisposition.SWITCH
    assert decision.actions == (
        "unload_failed:gemma4-31b",
        "load:gemma4-12b",
        "health_check:gemma4-12b",
        "route:gemma4-12b",
    )


def test_unvalidated_31b_image_falls_back_to_validated_12b_image() -> None:
    decision = router().decide(
        escalated_request(modalities=frozenset({Modality.TEXT, Modality.IMAGE})),
        runtimes=fleet(ModelRuntimeState.READY, ModelRuntimeState.UNLOADED),
    )
    assert decision.disposition is RouteDisposition.ROUTE
    assert decision.target_model is ModelId.GEMMA4_12B
    assert decision.reason_codes == ("ESCALATION_CAPABILITY_FALLBACK",)


def test_unvalidated_audio_and_oversized_context_are_rejected() -> None:
    audio = router().decide(
        RouteRequest(modalities=frozenset({Modality.AUDIO})),
        runtimes=fleet(ModelRuntimeState.READY, ModelRuntimeState.UNLOADED),
    )
    oversized = router().decide(
        RouteRequest(required_context_tokens=8_193),
        runtimes=fleet(ModelRuntimeState.READY, ModelRuntimeState.UNLOADED),
    )
    assert audio.disposition is RouteDisposition.REJECT
    assert oversized.disposition is RouteDisposition.REJECT
    assert audio.reason_codes == ("NO_VALIDATED_MODEL_CAPABILITY",)
    assert oversized.reason_codes == ("NO_VALIDATED_MODEL_CAPABILITY",)


def test_router_rejects_impossible_multiple_ready_models() -> None:
    decision = router().decide(
        RouteRequest(),
        runtimes=fleet(ModelRuntimeState.READY, ModelRuntimeState.READY),
    )
    assert decision.disposition is RouteDisposition.REJECT
    assert decision.reason_codes == ("MULTIPLE_READY_MODELS",)


def test_router_rejects_runtime_identity_mismatch() -> None:
    mismatched = fleet(ModelRuntimeState.READY, ModelRuntimeState.UNLOADED)
    mismatched[ModelId.GEMMA4_12B] = ModelRuntime(
        model_id=ModelId.GEMMA4_31B.value,
        state=ModelRuntimeState.READY,
    )
    with pytest.raises(ValueError):
        router().decide(RouteRequest(), runtimes=mismatched)
