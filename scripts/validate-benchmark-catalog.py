#!/usr/bin/env python3
"""Expand and validate the deterministic benchmark prompt catalog."""

from __future__ import annotations

import json
from pathlib import Path


EXPECTED_COUNTS = {
    "conversation": 20,
    "single_tool": 30,
    "complex_plan": 20,
    "git": 20,
    "ui": 20,
    "agent_status": 20,
    "failure_recovery": 10,
    "interruption": 20,
}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    path = root / "benchmarks" / "prompts" / "catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    groups = catalog.get("groups")
    if not isinstance(groups, list):
        raise ValueError("catalog groups must be an array")

    actual_counts: dict[str, int] = {}
    expanded_prompts: set[str] = set()
    ids: set[str] = set()
    for group in groups:
        category = group["category"]
        if category in actual_counts:
            raise ValueError(f"duplicate category: {category}")
        variants = group["variants"]
        prompts = group["prompts"]
        expanded = []
        for prompt_index, prompt in enumerate(prompts, start=1):
            for variant_index, variant in enumerate(variants, start=1):
                rendered = variant.format(prompt=prompt).strip()
                case_id = (
                    f"{category}-{prompt_index:02d}-{variant_index:02d}"
                )
                if not rendered or rendered in expanded_prompts:
                    raise ValueError(f"empty or duplicate prompt: {case_id}")
                if case_id in ids:
                    raise ValueError(f"duplicate case id: {case_id}")
                ids.add(case_id)
                expanded_prompts.add(rendered)
                expanded.append(rendered)
        actual_counts[category] = len(expanded)
        if group["expected_count"] != len(expanded):
            raise ValueError(
                f"{category}: declared {group['expected_count']}, "
                f"expanded {len(expanded)}"
            )

    if actual_counts != EXPECTED_COUNTS:
        raise ValueError(
            f"benchmark counts differ: expected={EXPECTED_COUNTS}, "
            f"actual={actual_counts}"
        )

    results_path = root / "benchmarks" / "results" / "raw-results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    expected_result_keys = {
        "schema_version",
        "status",
        "generated_at",
        "hardware_snapshot",
        "fixed_conditions",
        "runs",
    }
    if set(results) != expected_result_keys:
        raise ValueError("raw result envelope keys differ")
    if results["schema_version"] != "1.0":
        raise ValueError("raw result schema version differs")
    if results["status"] not in {"not_run", "running", "complete"}:
        raise ValueError("invalid raw result status")
    if not isinstance(results["runs"], list):
        raise ValueError("raw result runs must be an array")
    if results["status"] == "not_run" and results["runs"]:
        raise ValueError("not_run raw results cannot contain runs")
    if results["status"] == "complete":
        if (
            not results["runs"]
            or results["generated_at"] is None
            or results["hardware_snapshot"] is None
            or results["fixed_conditions"] is None
        ):
            raise ValueError("complete raw results require conditions and runs")

    for report_name in ("model-comparison.md", "runtime-comparison.md"):
        report = root / "benchmarks" / "reports" / report_name
        if not report.is_file() or "Status:" not in report.read_text(encoding="utf-8"):
            raise ValueError(f"missing benchmark report status: {report_name}")

    print(
        json.dumps(
            {
                "categories": actual_counts,
                "raw_result_status": results["status"],
                "status": "benchmark_catalog_passed",
                "total_cases": sum(actual_counts.values()),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
