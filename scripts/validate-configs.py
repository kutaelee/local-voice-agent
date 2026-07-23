#!/usr/bin/env python3
"""Validate cross-file runtime, model, and GPU configuration references."""

from __future__ import annotations

import json
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_yaml(relative_path: str) -> dict:
    path = REPO_ROOT / relative_path
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected mapping")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> int:
    runtime_manifest = load_yaml("manifests/runtimes.yaml")
    model_manifest = load_yaml("manifests/models.yaml")
    runtime_config = load_yaml("configs/runtimes.yaml")
    model_config = load_yaml("configs/models.yaml")
    gpu_config = load_yaml("configs/gpu-resources.yaml")

    runtime_ids = {
        item["id"] for item in runtime_manifest.get("runtimes", [])
    }
    require(len(runtime_ids) == len(runtime_manifest["runtimes"]), "duplicate runtime ID")
    for key in ("primary", "mtp_candidate", "comparison"):
        runtime_id = runtime_config.get(key)
        require(runtime_id in runtime_ids, f"unknown {key} runtime: {runtime_id}")

    manifest_models = model_manifest.get("models", [])
    model_roles = {item["role"]: item for item in manifest_models}
    require(
        len(model_roles) == len(manifest_models),
        "duplicate model manifest role",
    )

    configured_models = model_config.get("models", {})
    require(
        model_config.get("default_model") in configured_models,
        "default model is not configured",
    )
    require(
        model_config.get("escalation_model") in configured_models,
        "escalation model is not configured",
    )

    for model_name, entry in configured_models.items():
        role = entry.get("manifest_role")
        require(role in model_roles, f"{model_name}: unknown manifest role {role}")
        assistant_role = entry.get("assistant_manifest_role")
        if assistant_role is not None:
            require(
                assistant_role in model_roles,
                f"{model_name}: unknown assistant role {assistant_role}",
            )
            target_model_id = model_roles[role].get("model_id")
            assistant_target = model_roles[assistant_role].get("mtp_target")
            require(
                assistant_target == target_model_id,
                f"{model_name}: assistant target does not match target model",
            )
            require(
                entry.get("runtime") == runtime_config.get("mtp_candidate"),
                f"{model_name}: MTP runtime is not the pinned candidate",
            )
            require(
                entry.get("enabled") is False,
                f"{model_name}: unvalidated MTP model must remain disabled",
            )

    measurements = gpu_config.get("measurements", {})
    require(
        set(configured_models).issubset(measurements),
        "GPU measurements must include every configured model",
    )
    require(
        gpu_config.get("capacity", {}).get("require_preflight_vram_query")
        is True,
        "GPU preflight query must remain enabled",
    )
    require(
        gpu_config.get("oom", {}).get("reject_when_peak_estimate_unknown")
        is True,
        "unknown peak VRAM must fail closed",
    )

    print(
        json.dumps(
            {
                "configured_models": len(configured_models),
                "manifest_model_roles": len(model_roles),
                "runtime_ids": len(runtime_ids),
                "status": "config_reference_validation_passed",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
