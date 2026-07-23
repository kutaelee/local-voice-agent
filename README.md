# Local Voice Agent

Local Voice Agent is a Windows + Android system for interruptible voice
conversation and policy-controlled computer use. The target workstation is a
Windows 11 PC with an RTX 5090 32 GB GPU; inference runtimes run in WSL2 and
the Android client uses Kotlin and Jetpack Compose.

Current status: **Slice 2/3 validation plus an early Slice 5 server core**.
The pinned 12B W4A16 model passed text, image, structured-output, streaming,
and function-calling smoke tests. The exact 12B Q4_0 target/assistant pair
also passed text-only MTP loading and API smoke on a pinned upstream-fix
runtime; its multimodal initialization remains blocked and MTP stays disabled
by default. The pinned 31B W4A16 model passed a constrained text, tool,
structured-output, and streaming smoke run with an explicit small KV cache.
A locked PC-server environment now runs the first state, approval, policy,
protocol, model-runtime/router, authenticated FastAPI/WebSocket, and Tool
Executor client-adapter tests. A separate read-only Tool Executor implements
thirteen bounded Level 0 filesystem/Git observation tools, an authenticated
loopback API, execution-binding/idempotency checks, and metadata-only
audit/evidence records. Windows-native and WSL suites pass, and the Windows
process passed loopback start, authentication rejection, health, and clean
stop smoke checks. The adapter is implemented but session orchestration does
not invoke it yet. No end-to-end product acceptance criterion is claimed yet.

## Architecture

The product is a modular monolith with light DDD and hexagonal boundaries.
GPU workers and the tool executor are separate processes. The main domains are
Conversation, Model Routing, Tool Execution, Approval, Workspace, Agent
Status, and Observability.

See [docs/architecture.md](docs/architecture.md) and
[docs/product-requirements.md](docs/product-requirements.md).

## Canonical paths

| Purpose | Path |
|---|---|
| Windows source repository | `C:\Dev\Repos\local-voice-agent` |
| Models | `E:\AI\Models\Standalone\LocalVoiceAgent` |
| Download and Hugging Face cache | `E:\Cache\LocalVoiceAgent` |
| Runtime logs, sessions, evidence, backups, temp | `E:\Data\LocalVoiceAgent` |
| PostgreSQL active data | `E:\Data\DB\Active\LocalVoiceAgent` |
| Windows Tool Executor runtime | `C:\Dev\Tools\LocalVoiceAgent\runtimes\tool-executor` |
| WSL user runtimes | `/home/kutae/.local/share/local-voice-agent/runtimes` |

`D:` is backup-only on this workstation and must never host active workloads.
Model weights and runtime data are intentionally excluded from Git.
GPU admission and measured-peak gates are defined in
[`configs/gpu-resources.yaml`](configs/gpu-resources.yaml); unknown high-VRAM
peaks fail closed until measured.

## Build, test, and run

Installation scripts default to planning or validation and do not silently
install system components. The PC-server domain/API slice and the standalone
read-only Tool Executor have isolated lockfiles.

```powershell
pwsh -File scripts\health-check.ps1
pwsh -File scripts\install.ps1 -PlanOnly
pwsh -File scripts\download-models.ps1 -PlanOnly
```

After setting an untracked `LVA_TOOL_EXECUTOR_TOKEN` with at least 32 random
characters, the isolated executor can be started and stopped with
`scripts\start-tool-executor.ps1` and `scripts\stop-tool-executor.ps1`.
Both scripts keep the service on `127.0.0.1:8790`; the checked-in workspace
allowlist is empty and therefore permits no file access by default.

From an isolated project/runtime environment containing PyYAML and
jsonschema, all network-free repository checks can be run with:

```text
python scripts/validate-repository.py
```

WSL runtime setup, model loading, server startup, Android builds, and
benchmarks are enabled only after the corresponding compatibility gate is
recorded in the manifests. See [docs/runbook.md](docs/runbook.md).

## Data and artifacts

- Application source and tests stay in this repository.
- Generated benchmark results go under `benchmarks/results/`.
- Reviewed benchmark reports go under `benchmarks/reports/`.
- Runtime evidence is written outside Git under
  `E:\Data\LocalVoiceAgent\runtime\evidence`.
- APKs will be produced under the Android Gradle build directory and copied to
  a documented release artifact location only after verification.

## Safety

The server binds to loopback by default. Android never connects directly to
the tool executor. Every tool call passes schema validation, workspace and
path checks, risk classification, approval policy, execution, and
postcondition verification. Level 2 and Level 3 actions are never
auto-approved.

See [docs/security-model.md](docs/security-model.md) and
[docs/tool-permission-model.md](docs/tool-permission-model.md).
