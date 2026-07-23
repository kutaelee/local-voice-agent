#!/usr/bin/env python3
"""Resumable, bounded parallel downloader for pinned model weight files."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

import httpx


CHUNK_SIZE = 64 * 1024 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("output", type=Path)
    parser.add_argument("size_bytes", type=int)
    parser.add_argument("sha256")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--state-file", type=Path)
    return parser.parse_args()


def state_path(args: argparse.Namespace) -> Path:
    if args.state_file is not None:
        return args.state_file
    return args.output.with_name(f"{args.output.name}.ranges.json")


def write_state(path: Path, state: dict[str, object]) -> None:
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_or_create_state(args: argparse.Namespace, chunks: int) -> dict[str, object]:
    path = state_path(args)
    expected = {
        "schema_version": "1.0",
        "url": args.url,
        "size_bytes": args.size_bytes,
        "sha256": args.sha256.lower(),
        "chunk_size": CHUNK_SIZE,
        "chunks": chunks,
    }
    if path.exists():
        if not args.output.exists():
            raise RuntimeError("resume state exists but partial output is missing")
        if args.output.stat().st_size != args.size_bytes:
            raise RuntimeError("resume state exists but partial output size changed")
        state = json.loads(path.read_text(encoding="utf-8"))
        for key, value in expected.items():
            if key == "url":
                continue
            if state.get(key) != value:
                raise RuntimeError(f"resume state mismatch for {key}")
        if state.get("url") != args.url:
            source_urls = state.setdefault("source_urls", [state.get("url")])
            if args.url not in source_urls:
                source_urls.append(args.url)
            state["url"] = args.url
            write_state(path, state)
        state.setdefault("completed", [])
        return state

    state = {**expected, "completed": [], "created_at": time.time()}
    write_state(path, state)
    return state


def download_chunk(
    url: str,
    output: Path,
    index: int,
    size_bytes: int,
) -> tuple[int, int]:
    start = index * CHUNK_SIZE
    end = min(size_bytes - 1, start + CHUNK_SIZE - 1)
    expected_length = end - start + 1
    headers = {
        "Range": f"bytes={start}-{end}",
        "User-Agent": "local-voice-agent-model-downloader/1.0",
    }
    timeout = httpx.Timeout(120.0, connect=30.0)
    for attempt in range(1, 6):
        bytes_written = 0
        descriptor = os.open(output, os.O_WRONLY)
        try:
            with httpx.Client(follow_redirects=True, timeout=timeout) as client:
                with client.stream("GET", url, headers=headers) as response:
                    if response.status_code != 206:
                        raise RuntimeError(
                            f"range {index}: expected HTTP 206, "
                            f"got {response.status_code}"
                        )
                    expected_range = f"bytes {start}-{end}/{size_bytes}"
                    if response.headers.get("content-range") != expected_range:
                        raise RuntimeError(
                            f"range {index}: unexpected Content-Range "
                            f"{response.headers.get('content-range')!r}"
                        )
                    for block in response.iter_bytes(1024 * 1024):
                        os.pwrite(descriptor, block, start + bytes_written)
                        bytes_written += len(block)
            if bytes_written != expected_length:
                raise RuntimeError(
                    f"range {index}: expected {expected_length} bytes, "
                    f"got {bytes_written}"
                )
            return index, bytes_written
        except Exception:
            if attempt == 5:
                raise
            time.sleep(attempt * 2)
        finally:
            os.close(descriptor)

    raise AssertionError("unreachable")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    args = parse_args()
    if args.workers < 1 or args.workers > 16:
        raise ValueError("workers must be between 1 and 16")
    if args.size_bytes < 1:
        raise ValueError("size_bytes must be positive")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    state_path(args).parent.mkdir(parents=True, exist_ok=True)
    chunks = (args.size_bytes + CHUNK_SIZE - 1) // CHUNK_SIZE
    state = load_or_create_state(args, chunks)
    completed = {int(value) for value in state["completed"]}

    descriptor = os.open(args.output, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        os.ftruncate(descriptor, args.size_bytes)
    finally:
        os.close(descriptor)

    pending = [index for index in range(chunks) if index not in completed]
    transferred = sum(
        min(CHUNK_SIZE, args.size_bytes - index * CHUNK_SIZE)
        for index in completed
    )
    session_transferred = 0
    lock = threading.Lock()
    started = time.monotonic()
    print(
        f"resume: {len(completed)}/{chunks} chunks, "
        f"{transferred}/{args.size_bytes} bytes",
        flush=True,
    )

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=args.workers
    ) as executor:
        futures = {
            executor.submit(
                download_chunk,
                args.url,
                args.output,
                index,
                args.size_bytes,
            ): index
            for index in pending
        }
        for future in concurrent.futures.as_completed(futures):
            index, chunk_bytes = future.result()
            with lock:
                completed.add(index)
                transferred += chunk_bytes
                session_transferred += chunk_bytes
                state["completed"] = sorted(completed)
                state["updated_at"] = time.time()
                write_state(state_path(args), state)
                elapsed = max(time.monotonic() - started, 0.001)
                print(
                    f"progress: {len(completed)}/{chunks} chunks, "
                    f"{transferred}/{args.size_bytes} bytes, "
                    f"{session_transferred / elapsed / 1024 / 1024:.2f} MiB/s",
                    flush=True,
                )

    actual_sha = sha256_file(args.output)
    if actual_sha != args.sha256.lower():
        raise RuntimeError(
            f"SHA-256 mismatch: expected {args.sha256.lower()}, got {actual_sha}"
        )
    state["validated_at"] = time.time()
    state["validation_status"] = "sha256_passed"
    write_state(state_path(args), state)
    print(f"validated: {actual_sha}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"download failed: {error}", file=sys.stderr, flush=True)
        raise
