# Product requirements

## Goal

Build a local, interruptible voice agent that lets an Android user converse
naturally with a Gemma 4 model and perform explicitly approved, auditable
computer-use actions on the paired Windows PC.

## End-to-end flow

Android microphone → PC VAD → STT → model router → planning/function calling
→ policy and approval → tool executor → result verification → response
generation → sentence-level TTS → Android playback.

## Product boundaries

- Default model: Gemma 4 12B instruction-tuned.
- Escalation model: Gemma 4 31B instruction-tuned.
- Primary runtime candidate: vLLM in WSL2.
- Comparison runtime: SGLang in an independent WSL environment.
- Windows fallback: GGUF runtime, limited to text and recovery diagnostics.
- Client: Kotlin, Jetpack Compose, ViewModel + StateFlow, UDF/MVI-lite, Room.
- Server: Python, FastAPI, WebSocket, Pydantic/JSON Schema, PostgreSQL.
- Network exposure: loopback or explicitly configured private LAN/VPN only.

## Core capabilities

1. Streaming voice conversation with partial transcripts and barge-in.
2. Text/image/audio-capable Gemma 4 routing and structured function calling.
3. Workspace-scoped file, Git, build/test, system, browser, and UI tools.
4. Explicit risk levels, expiring approvals, optimistic locking, and
   idempotency keys.
5. Observable model switching between 12B and 31B with safe recovery.
6. Status adapters for Codex and other CLI coding agents based only on
   process, PTY, log, Git, recent-file, test, heartbeat, and status JSON facts.
7. Audit records and evidence for every tool call, without default raw audio
   or full-conversation retention.

## Acceptance

A criterion is marked passed only when its command, measured result, logs, and
evidence path are recorded in `docs/test-report.md`.

## Normative operating rules

1. Inspect the current workstation before running installation commands.
2. Verify current official documentation; never invent model IDs, APIs,
   runtime options, or unsupported features.
3. Record exact package versions, model revisions, source URLs, install
   locations, licenses, sizes, and hashes.
4. Never execute arbitrary model-generated shell commands.
5. Never report an unexecuted test or incomplete download as successful.
6. Never use a model whose hash/revision validation has failed.
7. Do not delete existing files, models, environments, or developer tools
   without inventory, validation, and explicit authorization.
8. Do not automatically change drivers, WSL/Windows features, distributions,
   firewall, BIOS, partitions, registry, permanent PATH, or public ports.
9. Keep runtimes isolated and rollback-addressable; never install the whole
   stack into system Python.
10. Keep conflicting CUDA/PyTorch stacks in separate environments.
11. Do not claim performance multipliers without measurements on this PC.
12. Preserve real error logs and reproduction conditions.

Project packages, Android dependencies, selected Gemma/STT/TTS/VAD weights,
vLLM/SGLang, and benchmark packages are pre-authorized. Administrator or
system changes are not. Before any artifact over 5 GB, verify canonical path,
free space with 20% operating reserve, official source, license, exact
revision, expected size, and checksum when published.

## Workstation and storage requirements

The initial survey records CPU, RAM, GPU/VRAM, NVIDIA driver, driver CUDA
capability, disks/free space/media, network interfaces, and Android connection
method. It also records Windows/build versions and availability/versions of
PowerShell, winget, Git/LFS, Python, uv, Node, JDK, Android SDK/ADB, FFmpeg,
Docker, WSL/distributions, Visual Studio Build Tools, CMake, and Ninja.

AI inventory covers nvidia-smi, CUDA runtime/toolkit, PyTorch, Triton,
FlashAttention, FlashInfer, vLLM, SGLang, Ollama, llama.cpp, LM Studio,
Hugging Face tooling/caches, and existing STT/TTS weights. Filesystem inventory
covers projects, model roots, Android projects, virtual environments, WSL
virtual disks, Git repositories, and likely duplicate large weights.

Canonical workstation paths are defined by `AGENTS.md`, the filesystem ADR,
and README. Source, models, cache, runtime/evidence, database data, generated
assets, and backups remain separate. Existing protected backup/transfer
content is never moved, overwritten, deduplicated, or deleted implicitly.
NTFS versus WSL ext4 model placement is selected only after measuring load
time, initialization, throughput, disk use, backup cost, and sharing needs.

## Official compatibility research

Research uses official Google/DeepMind and Gemma distributions first, followed
by vLLM, SGLang, PyTorch, NVIDIA, Transformers, voice-model repositories,
Android Developers, and Playwright. Community sources are diagnostic evidence
only for Blackwell/RTX 5090 field failures or regressions and are checked
against official source.

The compatibility matrix must pin:

- current Gemma release and exact 12B/31B instruction, QAT, and MTP assistant
  IDs/revisions/licenses;
- exact target-to-assistant pairing, never cross-size;
- Gemma tool-calling, thinking, and multimodal formats;
- vLLM/SGLang stable versions or an exact justified prerelease commit/wheel;
- RTX 5090, CUDA, PyTorch, quantization, structured-output, streaming,
  multimodal, and OpenAI-compatible support;
- known issues, selection decision, reason, and rollback.

## Model and runtime behavior

The 12B instruction model is the default conversational, short planning,
status, file/Git, screen-analysis, and tool-calling model. It should remain
loaded when measured VRAM permits. Adjustment order is context/KV limits,
validated quantization, STT/TTS CPU fallback, then model swapping.

The 31B instruction model handles complex multi-application plans, long
logs/diffs, failure and rollback analysis, repeated 12B tool failures, Level 2
preflight review, or explicit user selection. It is not resident by default.
Switching persists conversation/tool state, drains new execution, unloads the
old model, clears only runtime-owned cache, loads and health-checks 31B, runs
and records the request, unloads 31B, reloads and health-checks 12B. Android
shows every switch phase. Any failure returns to a healthy 12B and is
disclosed.

Candidate weight formats are official QAT, supported Q4/INT4 W4A16,
compressed-tensors, supported FP8/NVFP4, and GGUF fallback. Only formats
needed after VRAM, load time, TTFT, throughput, multimodal/MTP support,
Korean quality, and tool JSON accuracy testing are downloaded.

MTP uses the exact same-size target and assistant pair through the runtime's
Gemma-specific MTP path, never an assumed generic draft model. Initial
speculative tokens is 1; 1/2/3 and runtime auto are measured. ON/OFF compares
TTFT, TPOT, throughput, total latency, acceptance, VRAM, utilization, JSON
validity, tool selection/arguments, quality, OOM, and crashes. A speed win
does not justify tool-format or task-quality regression.

vLLM and SGLang use independent WSL environments and identical model revision,
quantization, context, prompt, sampling, output length, tool schema,
background load, and GPU conditions. Selection order is tool correctness,
stability/OOM, multimodal behavior, end-to-end voice latency, switching
stability, throughput, then maintenance complexity. A Windows-native fallback
provides text, simple tools, and recovery diagnostics only.

## Server and persistence

The PC server is a light-DDD modular monolith with hexagonal ports. API
Gateway, Session, Audio/VAD/STT, Model Routing/runtime adapters, Policy,
Approval, Tool Registry/Executor, Computer Use, TTS, Agent Status, GPU
Resource Management, persistence, and Observability are logical modules.
Only GPU workers and the low-privilege Tool Executor require early process
isolation.

Backend target: Python, FastAPI, WebSocket, Pydantic/JSON Schema, structured
JSON logs, and Prometheus metrics. Persistent state uses PostgreSQL 18 when
approved, SQLAlchemy 2.0 async until 2.1 is stable, Alembic, asyncpg,
optimistic version columns, idempotency keys, and a transactional outbox.
Core lifecycle fields are typed columns; variable tool/evidence metadata uses
JSONB. Redis is deferred until multiple workers or distributed queues require
it.

Core state machines include ConversationSession, ToolExecution,
ApprovalRequest, ModelRuntime, and AgentTask. Tool execution follows:

`PLANNED -> WAITING_APPROVAL -> QUEUED -> RUNNING -> VERIFYING -> SUCCEEDED`

and may terminate through `FAILED`, `CANCELLED`, `ROLLING_BACK`, or
`ROLLED_BACK`. Approval is exact, expiring, digest/precondition-bound, and
single-consumption.

## Voice pipeline

The initial product is interruptible half-duplex:

Android capture -> ordered audio transport -> PC VAD -> partial/final STT ->
streaming LLM -> sentence/meaning-segmented TTS -> Android playback.

Silero or a currently verified local VAD is measured for start/end, silence,
noise, and speech during playback. faster-whisper or a better verified local
implementation is measured for Korean accuracy, partial/final latency,
GPU/CPU fallback, preload, and timeout. Chatterbox/Kokoro or a better
commercially usable local TTS is selected only after Korean support, license,
streaming, cloning requirements, VRAM, first audio, and long-form stability
checks. No personal or third-party voice cloning occurs without explicit
authorization and supplied audio.

Barge-in stops playback, discards queued audio, marks the response
interrupted, cancels cancellable generation/tools, explains non-cancellable
work, and accepts the new utterance. Twenty consecutive conversations and
twenty interruptions are required tests.

## Android client

Kotlin and Jetpack Compose are the primary implementation. State management
uses ViewModel, `StateFlow<UiState>`, `SharedFlow<UiEffect>`, coroutines/Flow,
unidirectional data flow, SavedStateHandle, and Room for recent conversation
and pending-request cache. Pairing secrets use Android Keystore.

Required screens are setup/pairing, voice conversation, history, approval,
execution status, evidence/history, server/model diagnostics, and settings.
States include connecting, listening, recognizing, thinking, selecting tool,
waiting approval, executing, verifying, synthesizing, speaking, interrupted,
switching model, reconnecting, and error. Audio covers microphone permission,
foreground service, focus, speaker/earpiece/Bluetooth, reconnection,
backgrounding, rotation, power saving, and timeouts. Android talks only to
the API Gateway, never Tool Executor.

## Protocol and security

Every WebSocket message contains schema version, event type, session/request
UUIDs, monotonic sequence, timestamp, and a closed payload. PCM and Opus are
compared before promotion. Replay rules are explicit; audio/deltas are not
replayed, while terminal state is. Cancellation is an explicit idempotent
operation, never inferred from disconnect.

Default exposure is loopback; deployment may use an explicitly reviewed
private LAN or Tailscale/WireGuard path. Public port forwarding is out of
scope. Required controls include pairing token and rotation, protected
transport, workspace/path/command allowlists, traversal and reparse defenses,
secret masking, rate limits, timeouts, approval expiry, session expiry, and
audit logs. Tokens are never committed or logged.

All model-visible tools have checked-in closed JSON Schemas. The executor
validates schema, allowlist, risk, approval, normalized/resolved path,
symlinks/reparse points, timeout/output/concurrency limits, idempotency,
pre/postconditions, and rollback. General shell is hidden by default.

Risk policy:

- Level 0: scoped observation without approval.
- Level 1: reversible local mutation with plan/diff and session approval.
- Level 2: exact per-execution approval for delete, install, process stop,
  commit/push, external submission/upload/message, or environment change.
- Level 3: default denial for force push, bulk/destructive reset/clean,
  security disablement, credential extraction, production deployment,
  payment, destructive database/disk operations, or arbitrary elevation.

## Agent status and GPU management

Codex, Claude Code, OpenCode, Aider, terminals, and future coding agents are
observed through process, PTY, log, Git, recent-file, test/build, heartbeat,
and optional status-JSON adapters. No private API is assumed. Every normalized
field says observed, inferred, or unknown; inferred fields explain evidence
and no fabricated percentage is allowed.

GPU management queries current VRAM, admits only measured/estimated-safe work,
records peaks, queues work, unloads models, clears only owned cache, restarts
failed workers, and enters degraded mode. Voice and first audio have priority.
31B forbids concurrent image/video generation, and unknown high-VRAM peaks
fail closed.

## Observability and benchmarks

Metrics include VAD, STT partial/final, LLM TTFT/TPOT/tokens per second, TTS
first audio/synthesis speed, network/tool latency, tool/schema failure rate,
MTP acceptance, VRAM/utilization, queue length, model load, and switch time.
p50 and p95 are retained where meaningful. Logs carry timestamp, level,
session/request/tool IDs, component/event, model/runtime, latency, risk,
approval, result/error, and evidence ID/path. Raw audio and full conversation
are off unless the user explicitly enables debug retention.

The fixed benchmark has 20 Korean conversations, 30 single tools, 20 complex
plans, 20 Git tasks, 20 UI tasks, 20 agent-status queries, 10 recovery cases,
and 20 interruptions. It compares 12B/31B, MTP ON/OFF, vLLM/SGLang, and
Windows fallback for latency, throughput, VRAM/OOM, tool/argument correctness,
completion, unnecessary tools, rollback, and crashes.

## Delivery slices

0. Environment/storage/official compatibility/download/rollback survey.
1. Repository, directories, isolated environments, manifests, download tools.
2. Exact 12B/31B targets and assistants downloaded, hashed, minimally loaded.
3. vLLM text/stream/tool/multimodal/MTP/health validation.
4. SGLang equivalent validation and fair comparison.
5. PC text agent and Level 0 file/Git/system tools.
6. Approved file mutation, diff, hash preconditions, verification, rollback.
7. VAD/STT/TTS streaming and interruption.
8. Android pairing/WebSocket/text/status/reconnect.
9. Android microphone/playback/foreground/Bluetooth/interruption.
10. Playwright, Windows UI Automation, screenshots, approval, evidence.
11. Codex and generic coding-agent adapters.
12. Windows scripts, health, APKs, install/rollback/test/performance reports.

Each slice reports executed work, files, actual tests, measurements, observed
problems, rollback, next slice, and approval needs.

## Mandatory failure and security tests

The suite covers invalid pairing, traversal, symlink/reparse escape, outside
allowlist, concurrent modification, hash mismatch, duplicate call, tool/STT/
LLM/TTS timeout, GPU OOM, MTP initialization failure, 31B load failure, WSL
failure, WebSocket disconnect, Android reconnect, TTS barge-in, non-Git
workspace, large diff, corrupt log, changed browser element, changed screen
resolution, and rollback failure.

## Acceptance criteria

1. Gemma 4 12B runs successfully.
2. Gemma 4 31B runs successfully.
3. Exact corresponding MTP assistants run for both sizes.
4. MTP ON/OFF measurements exist.
5. vLLM/SGLang comparison results exist.
6. 12B/31B switching works with health verification.
7. Android voice conversation works.
8. User speech interrupts TTS.
9. Files and Git status can be observed.
10. Approved workspace file mutation works.
11. Before/after diff is visible.
12. Failure rollback works.
13. Browser and Windows UI can be controlled within policy.
14. Codex and other coding-agent status can be observed.
15. Every tool call has audit and evidence.
16. Level 2+ never executes without its required policy/approval path.
17. Windows fallback diagnostics work during WSL failure.
18. Android debug APK is built.
19. Install and removal/rollback procedures are documented.
20. A new environment is reproducible from checked-in documentation.

## Stop and escalation conditions

Stop and report current state, confirmed facts, blocker, requested approval,
options, recommendation, impact, and rollback if official support or license
is unclear; administrator, driver, WSL, firewall, credential, public-port,
personal voice data, deletion, disk-capacity, hash, repository trust, existing
environment safety, or irreversible-change issues arise.
