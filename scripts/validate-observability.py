#!/usr/bin/env python3
"""Validate required observability metrics and the structured log schema."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
OBSERVABILITY_ROOT = REPO_ROOT / "packages" / "observability"

REQUIRED_METRICS = {
    "vad_latency_ms",
    "stt_partial_latency_ms",
    "stt_final_latency_ms",
    "llm_ttft_ms",
    "llm_tpot_ms",
    "llm_tokens_per_second",
    "tts_first_audio_ms",
    "tts_synthesis_realtime_factor",
    "android_pc_network_latency_ms",
    "tool_execution_latency_ms",
    "tool_failure_rate",
    "tool_schema_failure_rate",
    "mtp_acceptance_rate",
    "vram_peak_bytes",
    "gpu_utilization_percent",
    "queue_length",
    "model_load_time_ms",
    "model_switch_time_ms",
}


def main() -> int:
    catalog = json.loads(
        (OBSERVABILITY_ROOT / "metrics-catalog.json").read_text(
            encoding="utf-8"
        )
    )
    metrics = catalog.get("metrics")
    if not isinstance(metrics, list):
        raise ValueError("metrics must be a list")
    names = [metric.get("name") for metric in metrics]
    if len(names) != len(set(names)):
        raise ValueError("duplicate metric names")
    if set(names) != REQUIRED_METRICS:
        raise ValueError(
            f"metric mismatch: missing={sorted(REQUIRED_METRICS - set(names))}, "
            f"extra={sorted(set(names) - REQUIRED_METRICS)}"
        )
    for metric in metrics:
        if metric.get("type") == "histogram" and metric.get("summaries") != [
            "p50",
            "p95",
        ]:
            raise ValueError(f"{metric['name']}: histogram lacks p50/p95")
        if metric.get("type") not in {"histogram", "gauge", "counter"}:
            raise ValueError(f"{metric['name']}: invalid metric type")

    log_schema = json.loads(
        (OBSERVABILITY_ROOT / "schemas" / "log-event.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(log_schema)
    Draft202012Validator(log_schema).validate(
        {
            "timestamp": "2026-07-23T00:00:00Z",
            "level": "info",
            "component": "validator",
            "event": "observability.contract.checked",
            "result": "succeeded",
        }
    )
    print(
        json.dumps(
            {
                "metrics": len(metrics),
                "status": "observability_contracts_passed",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
