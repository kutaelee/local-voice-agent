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
    print(
        json.dumps(
            {
                "categories": actual_counts,
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
