"""Pure model-routing decisions; this module never starts a runtime."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping

from ..domain.model_runtime import ModelRuntime, ModelRuntimeState


class ModelId(str, Enum):
    GEMMA4_12B = "gemma4-12b"
    GEMMA4_31B = "gemma4-31b"


class Modality(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class EscalationReason(str, Enum):
    EXPLICIT_USER_REQUEST = "explicit_user_request"
    COMPLEX_MULTISTEP_PLAN = "complex_multistep_plan"
    LONG_LOG_OR_DIFF_ANALYSIS = "long_log_or_diff_analysis"
    FAILURE_RECOVERY_OR_ROLLBACK_PLAN = "failure_recovery_or_rollback_plan"
    LEVEL_2_PREFLIGHT_REVIEW = "level_2_preflight_review"
    REPEATED_12B_TOOL_FAILURE = "repeated_12b_tool_failure"


class RouteDisposition(str, Enum):
    ROUTE = "ROUTE"
    SWITCH = "SWITCH"
    DEFER = "DEFER"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class ModelCapability:
    model_id: ModelId
    supported_modalities: frozenset[Modality]
    validated_modalities: frozenset[Modality]
    max_context_tokens: int

    def __post_init__(self) -> None:
        if self.max_context_tokens < 1:
            raise ValueError("max_context_tokens must be positive")
        if not self.validated_modalities.issubset(self.supported_modalities):
            raise ValueError("validated modalities must be supported")


@dataclass(frozen=True, slots=True)
class RouteRequest:
    modalities: frozenset[Modality] = frozenset({Modality.TEXT})
    escalation_reasons: frozenset[EscalationReason] = frozenset()
    required_context_tokens: int = 1

    def __post_init__(self) -> None:
        if not self.modalities:
            raise ValueError("at least one modality is required")
        if self.required_context_tokens < 1:
            raise ValueError("required_context_tokens must be positive")


@dataclass(frozen=True, slots=True)
class RouteDecision:
    disposition: RouteDisposition
    target_model: ModelId | None
    reason_codes: tuple[str, ...]
    actions: tuple[str, ...] = ()
    degraded: bool = False


class ModelRouter:
    def __init__(self, capabilities: Iterable[ModelCapability]) -> None:
        indexed = {capability.model_id: capability for capability in capabilities}
        required = {ModelId.GEMMA4_12B, ModelId.GEMMA4_31B}
        if set(indexed) != required:
            raise ValueError("router requires exactly the 12B and 31B models")
        self._capabilities: Mapping[ModelId, ModelCapability] = MappingProxyType(
            indexed
        )

    def decide(
        self,
        request: RouteRequest,
        *,
        runtimes: Mapping[ModelId, ModelRuntime],
        voice_priority_active: bool = False,
        high_vram_task_active: bool = False,
        vram_admission_granted: bool = True,
    ) -> RouteDecision:
        self._validate_runtime_set(runtimes)
        ready_models = tuple(
            model_id
            for model_id, runtime in runtimes.items()
            if runtime.state is ModelRuntimeState.READY
        )
        if len(ready_models) > 1:
            return RouteDecision(
                disposition=RouteDisposition.REJECT,
                target_model=None,
                reason_codes=("MULTIPLE_READY_MODELS",),
            )
        if any(
            runtime.state
            in {
                ModelRuntimeState.LOADING,
                ModelRuntimeState.HEALTH_CHECKING,
                ModelRuntimeState.DRAINING,
                ModelRuntimeState.UNLOADING,
            }
            for runtime in runtimes.values()
        ):
            return RouteDecision(
                disposition=RouteDisposition.DEFER,
                target_model=None,
                reason_codes=("MODEL_SWITCH_IN_PROGRESS",),
            )

        desired = (
            ModelId.GEMMA4_31B
            if request.escalation_reasons
            else ModelId.GEMMA4_12B
        )
        reason_codes = [
            "ESCALATION_REQUESTED"
            if desired is ModelId.GEMMA4_31B
            else "DEFAULT_ROUTE"
        ]

        if desired is ModelId.GEMMA4_31B:
            if voice_priority_active:
                return RouteDecision(
                    disposition=RouteDisposition.DEFER,
                    target_model=desired,
                    reason_codes=("VOICE_PRIORITY_ACTIVE",),
                )
            if high_vram_task_active:
                return RouteDecision(
                    disposition=RouteDisposition.DEFER,
                    target_model=desired,
                    reason_codes=("HIGH_VRAM_TASK_ACTIVE",),
                )
            if not vram_admission_granted:
                if (
                    EscalationReason.EXPLICIT_USER_REQUEST
                    in request.escalation_reasons
                ):
                    return RouteDecision(
                        disposition=RouteDisposition.REJECT,
                        target_model=desired,
                        reason_codes=("VRAM_ADMISSION_REJECTED",),
                    )
                desired = ModelId.GEMMA4_12B
                reason_codes = ["VRAM_ADMISSION_FALLBACK"]

        desired, capability_reason = self._apply_capability_gate(
            desired,
            request,
        )
        if desired is None:
            return RouteDecision(
                disposition=RouteDisposition.REJECT,
                target_model=None,
                reason_codes=(capability_reason,),
            )
        if capability_reason:
            reason_codes = [capability_reason]

        failed_31b = (
            runtimes[ModelId.GEMMA4_31B].state is ModelRuntimeState.FAILED
        )
        if desired is ModelId.GEMMA4_31B and failed_31b:
            desired = ModelId.GEMMA4_12B
            reason_codes = ["FALLBACK_AFTER_31B_FAILURE"]

        target_runtime = runtimes[desired]
        if target_runtime.state is ModelRuntimeState.READY:
            if failed_31b and desired is ModelId.GEMMA4_12B:
                return RouteDecision(
                    disposition=RouteDisposition.SWITCH,
                    target_model=desired,
                    reason_codes=(
                        *reason_codes,
                        "FAILED_31B_CLEANUP_REQUIRED",
                    ),
                    actions=(
                        "unload_failed:gemma4-31b",
                        "route:gemma4-12b",
                    ),
                    degraded=reason_codes[0]
                    == "FALLBACK_AFTER_31B_FAILURE",
                )
            return RouteDecision(
                disposition=RouteDisposition.ROUTE,
                target_model=desired,
                reason_codes=tuple(reason_codes),
                degraded=reason_codes[0].endswith("FALLBACK")
                or reason_codes[0] == "FALLBACK_AFTER_31B_FAILURE",
            )

        actions: list[str] = []
        if failed_31b and desired is ModelId.GEMMA4_12B:
            actions.append("unload_failed:gemma4-31b")
        if ready_models and ready_models[0] is not desired:
            current = ready_models[0].value
            actions.extend((f"drain:{current}", f"unload:{current}"))
        if target_runtime.state is ModelRuntimeState.FAILED:
            actions.append(f"unload_failed:{desired.value}")
        actions.extend(
            (
                f"load:{desired.value}",
                f"health_check:{desired.value}",
                f"route:{desired.value}",
            )
        )
        return RouteDecision(
            disposition=RouteDisposition.SWITCH,
            target_model=desired,
            reason_codes=tuple(reason_codes),
            actions=tuple(actions),
            degraded=reason_codes[0].endswith("FALLBACK")
            or reason_codes[0] == "FALLBACK_AFTER_31B_FAILURE",
        )

    def _apply_capability_gate(
        self,
        desired: ModelId,
        request: RouteRequest,
    ) -> tuple[ModelId | None, str]:
        capability = self._capabilities[desired]
        capable = (
            request.modalities.issubset(capability.validated_modalities)
            and request.required_context_tokens <= capability.max_context_tokens
        )
        if capable:
            return desired, ""
        if desired is ModelId.GEMMA4_31B:
            default = self._capabilities[ModelId.GEMMA4_12B]
            if (
                request.modalities.issubset(default.validated_modalities)
                and request.required_context_tokens <= default.max_context_tokens
            ):
                return ModelId.GEMMA4_12B, "ESCALATION_CAPABILITY_FALLBACK"
        return None, "NO_VALIDATED_MODEL_CAPABILITY"

    @staticmethod
    def _validate_runtime_set(
        runtimes: Mapping[ModelId, ModelRuntime],
    ) -> None:
        required = {ModelId.GEMMA4_12B, ModelId.GEMMA4_31B}
        if set(runtimes) != required:
            raise ValueError("runtime set must contain exactly 12B and 31B")
        for model_id, runtime in runtimes.items():
            if runtime.model_id != model_id.value:
                raise ValueError(f"runtime identity mismatch for {model_id.value}")
