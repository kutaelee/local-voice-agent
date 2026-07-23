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
    parser.add_argument(
        "--target-format",
        choices=("auto", "compressed-tensors", "unquantized"),
        default="auto",
    )
    return parser.parse_args()


def load_config(directory: Path) -> dict[str, object]:
    path = directory / "config.json"
    return json.loads(path.read_text(encoding="utf-8"))


def read_safetensors(path: Path) -> tuple[dict[str, object], dict[str, object]]:
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

    result = {
        "path": str(path),
        "size_bytes": file_size,
        "header_bytes": header_size,
        "tensor_count": len(tensors),
        "dtype_counts": dict(sorted(dtypes.items())),
        "validation_status": "safetensors_structure_passed",
    }
    return result, tensors


def inspect_safetensors(
    directory: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    paths = sorted(directory.glob("model*.safetensors"))
    if not paths:
        raise ValueError(f"{directory}: no finalized model safetensors found")

    index_path = directory / "model.safetensors.index.json"
    index_status = "not_required"
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        weight_map = index.get("weight_map")
        if not isinstance(weight_map, dict) or not weight_map:
            raise ValueError(f"{index_path}: missing weight_map")
        referenced = {str(value) for value in weight_map.values()}
        available = {path.name for path in paths}
        missing = sorted(referenced - available)
        if missing:
            raise ValueError(f"{index_path}: missing shards: {missing}")
        index_status = "weight_map_shards_present"

    files: list[dict[str, object]] = []
    tensors: dict[str, object] = {}
    total_bytes = 0
    total_tensors = 0
    for path in paths:
        result, file_tensors = read_safetensors(path)
        duplicate_names = sorted(set(tensors) & set(file_tensors))
        if duplicate_names:
            raise ValueError(
                f"{directory}: duplicate tensor names: {duplicate_names[:3]}"
            )
        tensors.update(file_tensors)
        files.append(result)
        total_bytes += int(result["size_bytes"])
        total_tensors += int(result["tensor_count"])

    return (
        {
            "directory": str(directory),
            "files": files,
            "file_count": len(files),
            "size_bytes": total_bytes,
            "tensor_count": total_tensors,
            "index_status": index_status,
            "validation_status": "safetensors_structure_passed",
        },
        tensors,
    )


def tensor_shape(tensors: dict[str, object], name: str) -> list[int] | None:
    descriptor = tensors.get(name)
    if not isinstance(descriptor, dict):
        return None
    shape = descriptor.get("shape")
    if not isinstance(shape, list) or not all(
        isinstance(value, int) for value in shape
    ):
        return None
    return shape


def main() -> int:
    args = parse_args()
    target = load_config(args.target_dir)
    assistant = load_config(args.assistant_dir)
    target_text = target.get("text_config", {})
    assistant_text = assistant.get("text_config", {})
    target_inspection, target_tensors = inspect_safetensors(args.target_dir)
    assistant_inspection, assistant_tensors = inspect_safetensors(
        args.assistant_dir
    )

    quantization = target.get("quantization_config")
    detected_target_format = (
        "compressed-tensors"
        if isinstance(quantization, dict)
        and quantization.get("quant_method") == "compressed-tensors"
        else "unquantized"
        if quantization is None
        else "unknown"
    )
    requested_target_format = args.target_format
    target_format_matches = (
        requested_target_format == "auto"
        or requested_target_format == detected_target_format
    )

    target_hidden_size = target_text.get("hidden_size")
    target_vocab_size = target_text.get("vocab_size")
    assistant_hidden_size = assistant_text.get("hidden_size")
    target_embedding = tensor_shape(
        target_tensors, "model.language_model.embed_tokens.weight"
    )
    assistant_embedding = tensor_shape(
        assistant_tensors, "model.embed_tokens.weight"
    )
    assistant_pre_projection = tensor_shape(
        assistant_tensors, "pre_projection.weight"
    )
    assistant_post_projection = tensor_shape(
        assistant_tensors, "post_projection.weight"
    )
    dimensions_are_ints = all(
        isinstance(value, int)
        for value in (
            target_hidden_size,
            target_vocab_size,
            assistant_hidden_size,
        )
    )
    expected_pre_projection = (
        [assistant_hidden_size, 2 * target_hidden_size]
        if dimensions_are_ints
        else None
    )

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
        "target_format": target_format_matches,
        "model_dimensions_present": dimensions_are_ints,
        "target_embedding_shape": dimensions_are_ints
        and target_embedding
        == [target_vocab_size, target_hidden_size],
        "assistant_embedding_shape": dimensions_are_ints
        and assistant_embedding
        == [target_vocab_size, assistant_hidden_size],
        "assistant_pre_projection_shape": assistant_pre_projection
        == expected_pre_projection,
        "assistant_post_projection_shape": assistant_post_projection
        == [target_hidden_size, assistant_hidden_size],
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"model pair checks failed: {', '.join(failed)}")

    result = {
        "target": target_inspection,
        "assistant": assistant_inspection,
        "target_format": {
            "requested": requested_target_format,
            "detected": detected_target_format,
        },
        "target_embedding_share_required": (
            dimensions_are_ints and assistant_hidden_size != target_hidden_size
        ),
        "tensor_shapes": {
            "target_embedding": target_embedding,
            "assistant_embedding": assistant_embedding,
            "assistant_pre_projection": assistant_pre_projection,
            "assistant_post_projection": assistant_post_projection,
        },
        "pair_checks": checks,
        "validation_status": "offline_structure_passed_runtime_loading_pending",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
