#!/usr/bin/env python3
"""Inspect a pinned Gemma 4 target/assistant pair without loading GPU weights."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import struct


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("target_dir", type=Path)
    parser.add_argument("assistant_dir", type=Path)
    return parser.parse_args()


def load_config(directory: Path) -> dict[str, object]:
    path = directory / "config.json"
    return json.loads(path.read_text(encoding="utf-8"))


def inspect_safetensors(directory: Path) -> dict[str, object]:
    path = directory / "model.safetensors"
    file_size = path.stat().st_size
    with path.open("rb") as stream:
        header_size_raw = stream.read(8)
        if len(header_size_raw) != 8:
            raise ValueError(f"{path}: missing safetensors header length")
        header_size = struct.unpack("<Q", header_size_raw)[0]
        if header_size < 2 or header_size > 128 * 1024 * 1024:
            raise ValueError(f"{path}: unreasonable header size {header_size}")
        header = json.loads(stream.read(header_size))

    tensors = {
        name: descriptor
        for name, descriptor in header.items()
        if name != "__metadata__"
    }
    if not tensors:
        raise ValueError(f"{path}: no tensors in header")

    data_ends = []
    dtypes: Counter[str] = Counter()
    for name, descriptor in tensors.items():
        offsets = descriptor.get("data_offsets")
        dtype = descriptor.get("dtype")
        shape = descriptor.get("shape")
        if (
            not isinstance(offsets, list)
            or len(offsets) != 2
            or not all(isinstance(value, int) for value in offsets)
            or offsets[0] < 0
            or offsets[1] < offsets[0]
        ):
            raise ValueError(f"{path}: invalid offsets for tensor {name}")
        if not isinstance(dtype, str) or not isinstance(shape, list):
            raise ValueError(f"{path}: invalid descriptor for tensor {name}")
        data_ends.append(offsets[1])
        dtypes[dtype] += 1

    expected_size = 8 + header_size + max(data_ends)
    if expected_size != file_size:
        raise ValueError(
            f"{path}: tensor data ends at {expected_size}, file is {file_size}"
        )

    return {
        "path": str(path),
        "size_bytes": file_size,
        "header_bytes": header_size,
        "tensor_count": len(tensors),
        "dtype_counts": dict(sorted(dtypes.items())),
        "validation_status": "safetensors_structure_passed",
    }


def main() -> int:
    args = parse_args()
    target = load_config(args.target_dir)
    assistant = load_config(args.assistant_dir)
    target_text = target.get("text_config", {})
    assistant_text = assistant.get("text_config", {})

    checks = {
        "target_model_type": target.get("model_type") == "gemma4_unified",
        "assistant_model_type": (
            assistant.get("model_type") == "gemma4_unified_assistant"
        ),
        "vocab_size": (
            target_text.get("vocab_size") == assistant_text.get("vocab_size")
        ),
        "context_length": (
            target_text.get("max_position_embeddings")
            == assistant_text.get("max_position_embeddings")
        ),
        "backbone_hidden_size": (
            target_text.get("hidden_size")
            == assistant.get("backbone_hidden_size")
        ),
        "target_quantization": (
            target.get("quantization_config", {}).get("quant_method")
            == "compressed-tensors"
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"model pair checks failed: {', '.join(failed)}")

    result = {
        "target": inspect_safetensors(args.target_dir),
        "assistant": inspect_safetensors(args.assistant_dir),
        "pair_checks": checks,
        "validation_status": "offline_structure_passed_runtime_loading_pending",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
