#!/usr/bin/env python3
"""Validate model/download manifest consistency without touching large files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verify-files",
        action="store_true",
        help="verify size for weights whose model has downloaded_at set",
    )
    parser.add_argument(
        "--verify-sha256",
        action="store_true",
        help="hash downloaded weights; implies --verify-files and can be slow",
    )
    return parser.parse_args()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_yaml(relative_path: str) -> dict:
    value = yaml.safe_load(
        (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    )
    require(isinstance(value, dict), f"{relative_path}: expected mapping")
    return value


def model_weights(entry: dict) -> list[dict]:
    if "primary_weight" in entry:
        item = entry["primary_weight"]
        return [
            {
                "path": item["filename"],
                "size_bytes": item["size_bytes"],
                "sha256": item["sha256"],
            }
        ]
    return [
        {
            "path": item["filename"],
            "size_bytes": item["size_bytes"],
            "sha256": item["sha256"],
        }
        for item in entry.get("primary_weights", [])
    ]


def download_weights(entry: dict) -> list[dict]:
    if "largest_file" in entry:
        return [entry["largest_file"]]
    return entry.get("weight_files", [])


def local_path(path_value: str) -> Path:
    windows_path = PureWindowsPath(path_value)
    if os.name == "nt":
        return Path(windows_path)
    require(bool(windows_path.drive), f"expected absolute Windows path: {path_value}")
    drive = windows_path.drive.rstrip(":").lower()
    return Path("/mnt") / drive / Path(*windows_path.parts[1:])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    args = parse_args()
    verify_files = args.verify_files or args.verify_sha256
    models_manifest = load_yaml("manifests/models.yaml")
    downloads_manifest = json.loads(
        (REPO_ROOT / "manifests/downloads.json").read_text(encoding="utf-8")
    )

    models = models_manifest.get("models", [])
    downloads = downloads_manifest.get("downloads", [])
    require(models, "model manifest is empty")
    require(downloads, "download manifest is empty")

    model_keys = {(item["model_id"], item["revision"]) for item in models}
    download_by_key = {
        (item["model_id"], item["revision"]): item for item in downloads
    }
    require(len(model_keys) == len(models), "duplicate model ID/revision")
    require(len(download_by_key) == len(downloads), "duplicate download ID/revision")
    require(
        model_keys == set(download_by_key),
        "model and download manifests contain different ID/revision pairs",
    )

    verified_files = 0
    verified_hashes = 0
    for model in models:
        key = (model["model_id"], model["revision"])
        download = download_by_key[key]
        role = model["role"]

        require(HEX_40.fullmatch(model["revision"]) is not None, f"{role}: bad revision")
        require(model["size_bytes"] == download["size_bytes"], f"{role}: size drift")
        require(model["license"] == download["license"], f"{role}: license drift")
        require(
            model.get("downloaded_at") == download.get("downloaded_at"),
            f"{role}: downloaded_at drift",
        )
        require(
            PureWindowsPath(model["local_path"]).name == model["revision"],
            f"{role}: local path is not revision-pinned",
        )

        declared_weights = model_weights(model)
        download_declared_weights = download_weights(download)
        require(declared_weights, f"{role}: no weight file declared")
        require(
            declared_weights == download_declared_weights,
            f"{role}: weight metadata drift",
        )
        for weight in declared_weights:
            require(weight["size_bytes"] > 0, f"{role}: non-positive weight size")
            require(
                HEX_64.fullmatch(weight["sha256"]) is not None,
                f"{role}: bad SHA-256",
            )

        if verify_files and model.get("downloaded_at"):
            root = local_path(model["local_path"])
            for weight in declared_weights:
                path = root / weight["path"]
                require(path.is_file(), f"{role}: missing downloaded weight {path}")
                require(
                    path.stat().st_size == weight["size_bytes"],
                    f"{role}: downloaded weight size mismatch {path}",
                )
                verified_files += 1
                if args.verify_sha256:
                    require(
                        sha256_file(path) == weight["sha256"],
                        f"{role}: downloaded weight SHA-256 mismatch {path}",
                    )
                    verified_hashes += 1

    print(
        json.dumps(
            {
                "models": len(models),
                "download_records": len(downloads),
                "verified_files": verified_files,
                "verified_hashes": verified_hashes,
                "status": "manifest_validation_passed",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
