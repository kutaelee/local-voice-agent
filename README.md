# Local Voice Agent

Local Voice Agent is a Windows + Android system for interruptible voice
conversation and policy-controlled computer use. The target workstation is a
Windows 11 PC with an RTX 5090 32 GB GPU; inference runtimes run in WSL2 and
the Android client uses Kotlin and Jetpack Compose.

Current status: **core implementation is integrated; final acceptance is in
progress**. Eighteen of the twenty product criteria are verified and two
remain partial; see [docs/acceptance-status.md](docs/acceptance-status.md).
The pinned 12B W4A16 model passed text, image, structured-output, streaming,
and function-calling smoke tests. The exact 12B Q4_0 target/assistant pair
also passed text-only MTP loading and API smoke on a pinned upstream-fix
runtime; its multimodal initialization remains blocked and MTP stays disabled
by default. The pinned 31B W4A16 model passed a constrained text, tool,
structured-output, and streaming smoke run with an explicit small KV cache.
A locked PC-server environment now runs state, approval, policy, protocol,
model-runtime/router, authenticated FastAPI/WebSocket, persistent STT/TTS
workers, and the Tool Executor client adapter. A live Korean PCM test has
passed WebSocket input, faster-whisper STT, Gemma 4 12B, and local TTS,
and chunked PCM output. Silero VAD 6.2.1 now runs in an isolated CPU ONNX
worker; its authenticated streaming smoke detected speech and a 500 ms
endpoint, and Android stops capture when the server reports that endpoint.
The WebSocket response path accepts and deduplicates cancellation while
STT/LLM/TTS processing is still active, emits events before the turn handler
returns, streams plain-conversation model deltas, and starts first-sentence
TTS before later model text is complete. Tool-enabled turns remain on the
non-streaming structured path so a complete tool call is validated before any
execution.
An authenticated registered-runtime coordinator now serializes fixed
12B/31B stop, load, health, and fallback actions and broadcasts their phases
to connected clients. New voice turns are paused during a switch, and active
capture, response, or approval continuations drain before the source process
is stopped. Its unit/API integration and a live 12B-to-31B-to-12B process
switch both pass.
Gemma's model-visible tool loop now
limits itself to 47 implemented tools, validates every call through
the planner/policy engine, pauses Level 1 work for an exact approval, resumes
the same turn, and returns verified results to the model. A separate Tool
Executor implements bounded filesystem, Git, browser, Windows UI, and ten
Windows system observation tools plus approval-bound Level 1
`write_file`, `apply_patch`, and hash-preconditioned rollback. Its
authenticated loopback API enforces execution binding and idempotency and
writes metadata-only audit/evidence records plus external rollback backups.
Windows-native and WSL suites pass, and live process smokes passed both
planner-driven reads and approved create/rollback. Coding-agent status
adapters observe supported processes, optional strict status files, and
workspace Git state without assuming private APIs. An isolated Playwright
1.61.0 browser now permits loopback-only DOM/accessibility observation and
approved non-submit navigation/input/clicks; Microsoft UI Automation supports
bounded window/tree/screenshot observation and approved actions only in
registered Notepad windows. The Android 0.6.9 client records and streams PCM,
plays ordered PCM output, supports client-side interruption, and keeps pairing
tokens in Android Keystore-backed storage. Its authenticated Voice settings
screen selects a consented local reference profile and records its exact
transcript and tone. Qwen3-TTS 0.6B Base is the selected low-latency clone
checkpoint; 1.7B remains a quality comparison and Chatterbox V3 remains a
rollback fallback. The primary serving candidate is isolated vLLM-Omni
0.24.0 with raw PCM streaming; the authenticated Unix-socket worker is
retained for rollback. The runtime reuses the workstation-wide canonical
model snapshot and keeps one consented speaker reference stable across
sentences. Streaming coalesces short
sentences into 32-character-or-longer semantic speech units, prefers natural
clause boundaries after 40 characters, binds short list markers to their text,
and expands an isolated number into a complete spoken phrase. Each generated
unit gets a bounded release and breath pause; the completed-response tail is
held until the stream closes so Korean final phonemes are not truncated.
Reference audio stays under external
application data and never enters Git or the APK. The
installed SGLang 0.5.15.post1
runtime now passes the 12B base text, tool/schema, streaming, image, thinking,
and latency smoke set. Its exact 12B target/assistant pair is recognized as
`FROZEN_KV_MTP` and passes the same functional API checks with 4 GiB CPU
offload; its fixed-condition ON/OFF latency comparison passes. SGLang was not
selected for 31B because W4A16 Marlin repack failed and the CPU-offloaded exact
target exceeded the bounded request timeout. A pinned native
Windows llama.cpp Q4_0 fallback also
passes CPU-only Korean text, tool/schema, and streaming while WSL/GPU work
continues. The required 24-case failure/security matrix and the bounded
computer-use smokes pass. No full product acceptance is claimed until the
physical-device barge-in/audio QA is complete.

## Architecture

The product is a modular monolith with light DDD and hexagonal boundaries.
GPU workers and the tool executor are separate processes. The main domains are
Conversation, Model Routing, Tool Execution, Approval, Workspace, Agent
Status, Observability, and the file-backed Salon Receptionist demonstration.

See [docs/architecture.md](docs/architecture.md) and
[docs/product-requirements.md](docs/product-requirements.md).

## Canonical paths

| Purpose | Path |
|---|---|
| Windows source repository | `C:\Dev\Repos\local-voice-agent` |
| Shared Hugging Face models | `E:\AI\Models\HuggingFace\hub` |
| Shared Hugging Face download cache | `E:\Cache\HuggingFace` |
| Project download state | `E:\Cache\LocalVoiceAgent\download-state` |
| Windows Ollama generation models | `E:\AI\Models\Ollama\generation\models` |
| Runtime logs, sessions, evidence, backups, temp | `E:\Data\LocalVoiceAgent` |
| Active salon reservation data | `E:\Data\LocalVoiceAgent\salon` |
| Salon fast-recovery copies | `D:\LocalBackup\LocalVoiceAgent\salon` |
| PostgreSQL active data | `E:\Data\DB\Active\LocalVoiceAgent` |
| Windows Tool Executor runtime | `C:\Dev\Tools\LocalVoiceAgent\runtimes\tool-executor` |
| WSL user runtimes | `/home/kutae/.local/share/local-voice-agent/runtimes` |

`D:` is backup-only on this workstation and must never host active workloads.
Model weights and runtime data are intentionally excluded from Git.
Repositories reference immutable shared snapshots by model ID and revision;
they do not own separate copies of model weights. Ollama's GGUF blob store and
Hugging Face Safetensors/GGUF snapshots are different artifact formats and are
not interchangeable.
GPU admission and measured-peak gates are defined in
[`configs/gpu-resources.yaml`](configs/gpu-resources.yaml); unknown high-VRAM
peaks fail closed until measured.

## Build, test, and run

Installation scripts default to planning or validation and do not silently
install system components. The PC-server domain/API slice and the standalone
Tool Executor have isolated lockfiles.

```powershell
pwsh -File scripts\health-check.ps1
pwsh -File scripts\install.ps1 -PlanOnly
pwsh -File scripts\install.ps1 -ValidatePrerequisites
pwsh -File scripts\install.ps1 -InstallProjectEnvironments
pwsh -File scripts\install.ps1 -BuildAndroid
pwsh -File scripts\download-models.ps1 -PlanOnly
```

The installer mutates only the registered project runtime/cache paths. It
uses locked Windows and WSL environments, hash-locks the TLS tools, keeps the
Playwright browser outside Git, and never installs a driver, Windows feature,
system PATH entry, firewall rule, or administrator package.

Physical-device acceptance is intentionally separate from emulator evidence;
use [docs/physical-android-qa.md](docs/physical-android-qa.md) without
recording pairing tokens or raw audio.

Most server, voice, approval, tool, and latency QA can be completed before an
APK build in the local web console:

```powershell
.\scripts\start-gpu-voice-stack.ps1
.\scripts\start-tool-executor.ps1 -EnableWslNatBinding
.\scripts\start-server.ps1 `
  -InstanceName web-qa `
  -ListenAddress 127.0.0.1 `
  -Port 46326 `
  -EnableVoice `
  -EnableTools
```

Open `http://127.0.0.1:46326/qa`. The same-origin loopback console
automatically obtains a fingerprint-bound, memory-only QA session and
connects without exposing or storing the long-lived pairing token. It
exchanges that session for a 45-second single-use WebSocket ticket and shows
STT, LLM, first-audio, and playback-underrun timing. The dedicated 46326
listener is loopback-only and does not create a firewall rule. Use
`scripts\stop-server.ps1 -InstanceName web-qa` and
`scripts\stop-gpu-voice-stack.ps1` for registered shutdown.

Physical Android QA is still required for foreground-service lifecycle,
Bluetooth/earpiece routing, audio focus, Keystore persistence, and power
management.

The same portal also exposes a text-first **예약 전화 시뮬레이션**.
Starting that conversation represents an incoming salon call. It exercises
the Gemma-led receptionist persona, committed hours/services policy,
confirmation-bound reservation changes, an isolated prefilled QA schedule,
ten detailed cut/color/perm/clinic menus, and connected-app owner
notifications without starting VAD, STT, or TTS. See
[docs/salon-receptionist.md](docs/salon-receptionist.md).
The salon voice profile uses the pinned `google/gemma-4-E4B-it-qat-mobile-ct`
checkpoint by default after its six-case Korean intent/FAQ gate passed; 12B
remains the fallback for failed or out-of-policy E4B operation.
The independently gated Qwen3-TTS projection can be enabled for final QA;
neither model receives reservation mutation authority.

After setting an untracked `LVA_TOOL_EXECUTOR_TOKEN` with at least 32 random
characters, the isolated executor can be started and stopped with
`scripts\start-tool-executor.ps1` and `scripts\stop-tool-executor.ps1`.
The default is `127.0.0.1:46323`. NAT-mode WSL integration may explicitly bind
only the detected private `vEthernet (WSL ...)` address with
`-EnableWslNatBinding`; it never binds a LAN address or `0.0.0.0`. The
checked-in workspace
allowlist grants filesystem/Git observation and explicitly approved,
preconditioned Level 1 file changes only to this repository. Backups remain
outside the worktree under
`E:\Data\LocalVoiceAgent\runtime\backups\tool-executor`.

From an isolated project/runtime environment containing PyYAML and
jsonschema, all network-free repository checks can be run with:

```text
python scripts/validate-repository.py
```

WSL runtime setup, model loading, server startup, and benchmarks are enabled
only after the corresponding compatibility gate is recorded in the
manifests. The Android API 37 command-line build is operational; see
[manifests/android-sdk.yaml](manifests/android-sdk.yaml) and
[docs/runbook.md](docs/runbook.md).

## Data and artifacts

- Application source and tests stay in this repository.
- Generated benchmark results go under `benchmarks/results/`.
- Reviewed benchmark reports go under `benchmarks/reports/`.
- Runtime evidence is written outside Git under
  `E:\Data\LocalVoiceAgent\runtime\evidence`.
- Consented reference-voice data stays outside Git under
  `E:\Data\LocalVoiceAgent\voice-profiles`.
- Verified Android APKs are copied to
  `E:\Data\LocalVoiceAgent\artifacts\android\0.6.9-api37`; hashes and signing
  state are recorded in
  [manifests/android-artifacts.yaml](manifests/android-artifacts.yaml).

## Safety

The server binds to loopback by default. Android never connects directly to
the tool executor. The optional Tool Executor WSL endpoint is restricted to
the exact private Hyper-V adapter and an environment-only bearer token. Every
tool call passes schema validation, workspace and path checks, risk
classification, approval policy, execution, and postcondition verification.
Level 2 and Level 3 actions are never auto-approved.

See [docs/security-model.md](docs/security-model.md) and
[docs/tool-permission-model.md](docs/tool-permission-model.md).
