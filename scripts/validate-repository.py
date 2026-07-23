#!/usr/bin/env python3
"""Run the repository's network-free static validation suite."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATORS = [
    "validate-configs.py",
    "validate-manifests.py",
    "validate-contract-catalog.py",
    "validate-observability.py",
    "validate-benchmark-catalog.py",
    "validate-required-test-catalog.py",
    "validate-status-contracts.py",
    "validate-approval-contracts.py",
    "validate-workspaces.py",
    "validate-security-configs.py",
]


def main() -> int:
    results: list[dict[str, object]] = []
    for name in VALIDATORS:
        started = time.perf_counter()
        completed = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / name)],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        result = {
            "validator": name,
            "exit_code": completed.returncode,
            "elapsed_ms": elapsed_ms,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
        results.append(result)
        if completed.returncode != 0:
            print(
                json.dumps(
                    {
                        "status": "repository_validation_failed",
                        "failed_validator": name,
                        "results": results,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return completed.returncode

    print(
        json.dumps(
            {
                "status": "repository_validation_passed",
                "validators": len(results),
                "elapsed_ms": round(
                    sum(float(item["elapsed_ms"]) for item in results),
                    2,
                ),
                "results": results,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
