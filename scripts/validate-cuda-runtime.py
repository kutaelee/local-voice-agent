#!/usr/bin/env python3
"""Validate an isolated inference runtime's package and CUDA basics."""

from __future__ import annotations

import argparse
from importlib import metadata
import json
import math

import torch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument("--expected-cuda-prefix", default="13.")
    parser.add_argument("--expected-compute-capability", default="12.0")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    package_version = metadata.version(args.package)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available")

    device = torch.cuda.current_device()
    capability_tuple = torch.cuda.get_device_capability(device)
    capability = f"{capability_tuple[0]}.{capability_tuple[1]}"
    if capability != args.expected_compute_capability:
        raise RuntimeError(
            f"expected compute capability {args.expected_compute_capability}, "
            f"observed {capability}"
        )
    if not str(torch.version.cuda).startswith(args.expected_cuda_prefix):
        raise RuntimeError(
            f"expected CUDA {args.expected_cuda_prefix}x, "
            f"observed {torch.version.cuda}"
        )

    left = torch.full((32, 32), 2.0, device="cuda")
    right = torch.full((32, 32), 0.5, device="cuda")
    product = left @ right
    observed = float(product[0, 0].item())
    if not math.isclose(observed, 32.0, rel_tol=0, abs_tol=1e-5):
        raise RuntimeError(f"CUDA matrix check failed: {observed}")
    torch.cuda.synchronize()

    free_bytes, total_bytes = torch.cuda.mem_get_info(device)
    print(
        json.dumps(
            {
                "package": args.package,
                "package_version": package_version,
                "python_torch": torch.__version__,
                "cuda": torch.version.cuda,
                "device": torch.cuda.get_device_name(device),
                "compute_capability": capability,
                "matrix_result": observed,
                "free_vram_bytes": free_bytes,
                "total_vram_bytes": total_bytes,
                "status": "cuda_runtime_validation_passed",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
