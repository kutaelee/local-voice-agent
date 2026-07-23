# Runbook

## Current safe commands

```powershell
pwsh -File scripts\health-check.ps1
pwsh -File scripts\install.ps1 -PlanOnly
pwsh -File scripts\download-models.ps1 -PlanOnly
pwsh -File scripts\download-models.ps1 -PlanOnly -Only mtp_target_12b
```

WSL planning:

```bash
bash scripts/install-wsl.sh --plan-only
bash scripts/download-models.sh --plan-only
```

Selective model transfer:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\download-models.ps1 `
  -Execute -Only mtp_target_12b

powershell -ExecutionPolicy Bypass -File scripts\download-status.ps1 `
  -Role mtp_target_12b
```

Offline target/assistant inspection:

```bash
python scripts/inspect-model-pair.py \
  /mnt/e/AI/Models/Standalone/LocalVoiceAgent/gemma4/12b/mtp-target/b6ed86275a6a5735884e208bfed95b445a684ca2 \
  /mnt/e/AI/Models/Standalone/LocalVoiceAgent/gemma4/12b/mtp-assistant/18934064dd4c5c6cc3621f6381e7d377fc8cb7bd \
  --target-format unquantized
```

After a local vLLM endpoint passes health:

```bash
python scripts/smoke-openai-api.py \
  --model gemma4-12b-mtp \
  --include-image \
  --output /mnt/e/Data/LocalVoiceAgent/runtime/evidence/vllm-12b-mtp-smoke.json
```

The unreleased MTP-fix runtime is installed only into its versioned
environment:

```bash
bash scripts/install-wsl.sh --install-vllm-mtp-fix
```

Rollback is a runtime configuration switch to the untouched
`vllm-0.25.1` environment.

Validate that isolated environment without loading a model:

```bash
/home/kutae/.local/share/local-voice-agent/runtimes/\
vllm-b2b8f679d058-cu130/.venv/bin/python \
  scripts/validate-cuda-runtime.py --package vllm

uv pip check --python \
  /home/kutae/.local/share/local-voice-agent/runtimes/\
vllm-b2b8f679d058-cu130/.venv/bin/python
```

After the exact Q4_0 target and assistant hashes pass, the first compatibility
launch disables CUDA graphs to minimize unmeasured VRAM:

```bash
VLLM_SMOKE_ENFORCE_EAGER=1 \
VLLM_SMOKE_LANGUAGE_MODEL_ONLY=1 \
VLLM_SMOKE_SPECULATIVE_TOKENS=1 \
bash scripts/serve-vllm-smoke.sh 12b on
```

For a shared-GPU 31B compatibility probe, prefer an explicit small KV cache
over inflating total GPU utilization. Example values are test conditions, not
production defaults:

```bash
VLLM_SMOKE_MAX_MODEL_LEN=256 \
VLLM_SMOKE_MAX_NUM_SEQS=1 \
VLLM_SMOKE_KV_CACHE_MEMORY_BYTES=402653184 \
VLLM_SMOKE_ENFORCE_EAGER=1 \
VLLM_SMOKE_LANGUAGE_MODEL_ONLY=1 \
bash scripts/serve-vllm-smoke.sh 31b off
```

Do not run MTP API smoke until `/health` returns success. Preserve server
stdout/stderr under the external runtime log root. On startup failure, stop
only that runtime process, retain logs/evidence, verify VRAM returned, and
leave the stable MTP-OFF environment untouched. Eager mode is removed only
after this exact-pair path passes and measured headroom permits graph capture.
The exact Q4_0 target revision currently omits
`vision_config.num_soft_tokens`, so the first MTP compatibility run is
language-only and cannot count as an MTP multimodal pass. Do not patch the
official model config in place; resolve and record an upstream-compatible
multimodal path separately.

## PC server development

The project environment is outside the repository and the lock remains
tracked:

```bash
cd /mnt/c/Dev/Repos/local-voice-agent/apps/pc-server
export UV_PROJECT_ENVIRONMENT=\
/home/kutae/.local/share/local-voice-agent/runtimes/pc-server/.venv
/home/kutae/.local/bin/uv sync --locked --extra test
/home/kutae/.local/bin/uv run --locked --extra test pytest
```

Process-level loopback smoke with a test-only token:

```bash
bash scripts/smoke-pc-server.sh
```

The Uvicorn factory refuses to start without a non-placeholder token. A
manual loopback-only development launch is:

```bash
export LVA_PAIRING_TOKEN='<at-least-32-random-characters>'
/home/kutae/.local/bin/uv run --locked uvicorn \
  local_voice_agent_server.api:create_app_from_environment \
  --factory --host 127.0.0.1 --port 8787
```

Do not put tokens in command history or tracked files in normal use.

### Live voice workers and 12B endpoint

Use independently generated values of at least 32 characters. The examples
below are placeholders, not usable credentials:

```bash
export LVA_AUDIO_WORKER_TOKEN='<random-audio-worker-token>'
bash scripts/start-audio-workers.sh
python scripts/audio-worker-health.py \
  /home/kutae/.local/share/local-voice-agent/run/vad.sock

export LVA_VLLM_API_KEY='<random-vllm-api-key>'
bash scripts/start-vllm.sh
```

The audio workers use mode-0600 Unix sockets. The launcher health-checks VAD,
STT, and TTS before returning. A VAD-only process smoke that does not start
the GPU workers is available while the GPU is occupied:

```bash
export LVA_AUDIO_WORKER_TOKEN='<random-audio-worker-token>'
bash scripts/smoke-vad-process.sh
```

vLLM binds only to `127.0.0.1:8766`; its first model load from the canonical
NTFS model store can
take several minutes. Startup waits up to 360 seconds by default and can be
bounded from 60 through 900 seconds with
`LVA_VLLM_STARTUP_TIMEOUT_SECONDS`.

Run the production composition through an in-process authenticated WebSocket:

```bash
export LVA_PAIRING_TOKEN='<random-pairing-token>'
export LVA_VOICE_ENABLED=1
export LVA_VLLM_MODEL=gemma4-12b
export LVA_VLLM_BASE_URL=http://127.0.0.1:8766/v1
python scripts/smoke-voice-websocket.py \
  --input-wav /mnt/e/Data/LocalVoiceAgent/runtime/evidence/audio/chatterbox-v3-ko-smoke.wav \
  --evidence /mnt/e/Data/LocalVoiceAgent/runtime/evidence/audio/voice-websocket-e2e.json
```

For the registered loopback PC-server process, start PostgreSQL and apply
migrations first. Keep every token in the invoking process environment or an
OS-backed secret store; neither launcher writes token values to its status or
log files.

```powershell
$env:LVA_PAIRING_TOKEN = '<at-least-32-random-characters>'
$env:LVA_VOICE_ENABLED = '0' # Set to 1 only after workers and vLLM are healthy.
$env:LVA_TOOLS_ENABLED = '0' # Set to 1 only with an authenticated executor.
.\scripts\start-server.ps1
Invoke-RestMethod http://127.0.0.1:8765/health
.\scripts\stop-server.ps1
```

The launcher binds only `127.0.0.1` unless the private-network mode below is
explicitly selected. It derives the loopback PostgreSQL URL from the external
password file, records verified Windows/WSL PIDs and log paths, and sends
`SIGTERM` to the registered Linux server before stopping its owned launcher.
It never creates a firewall rule.

Stop only registered project processes:

```bash
bash scripts/stop-vllm.sh
bash scripts/stop-audio-workers.sh
```

### Android private-network TLS

The Android app accepts only `wss://` origins and continues to reject
cleartext traffic. The unsigned release candidate trusts the Android platform
system CA store only. The debug APK also permits a device-owner-installed
private CA for local testing. The certificate subject alternative name must
match the exact LAN IP address or DNS name entered in the app.

Keep the server loopback-only by default. A LAN listener is intentionally an
explicit runtime action: it accepts only RFC1918 IPv4 or IPv6 ULA addresses,
requires a PEM certificate and key, and requires the
`-EnablePrivateNetwork` switch. It still does **not** open Windows Firewall;
if the existing firewall blocks the chosen port, stop and obtain explicit
approval before changing a firewall rule.

```powershell
$env:LVA_PAIRING_TOKEN = '<at-least-32-random-characters>'
.\scripts\start-server.ps1 `
  -ListenAddress 192.168.1.20 `
  -EnablePrivateNetwork `
  -TlsCertificatePath 'E:\Data\LocalVoiceAgent\tls\server-cert.pem' `
  -TlsPrivateKeyPath 'E:\Data\LocalVoiceAgent\tls\server-key.pem'
```

The private key and certificate are runtime data, not repository files. For a
debug APK test, import the private CA on the Android device using the
device-owner flow, then pair the app with `wss://192.168.1.20:8765` and the
pairing token. A release candidate instead needs a system-trusted certificate
(for example, from an approved private-network solution). For an Android
Emulator, prefer the loopback-only listener through `adb reverse` rather than
exposing a LAN port; authorizing USB debugging remains a physical-device action.

## Tool Executor

The Windows-native Tool Executor is independently locked and starts on
loopback by default. Keep its IPC token in the current process environment or a future OS
credential-store integration, never in Git:

```powershell
$env:LVA_TOOL_EXECUTOR_TOKEN = '<at-least-32-random-characters>'
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\scripts\start-tool-executor.ps1
Invoke-RestMethod http://127.0.0.1:8790/health
.\scripts\stop-tool-executor.ps1
```

For a PC server running inside NAT-mode WSL2, bind only the detected internal
Hyper-V adapter and configure the same exact address in WSL:

```powershell
.\scripts\start-tool-executor.ps1 -EnableWslNatBinding
Get-Content E:\Data\LocalVoiceAgent\runtime\status\tool-executor.json
```

```bash
export LVA_TOOL_EXECUTOR_URL=http://172.18.0.1:8790
export LVA_WINDOWS_HOST_IP=172.18.0.1
```

Replace the example address with the `host` field from the status file.
The launcher fails unless exactly one `vEthernet (WSL ...)` RFC1918 address
exists; it never selects a LAN interface or `0.0.0.0`. No firewall rule is
created. If the WSL Hyper-V firewall blocks the endpoint, stop and report it
instead of changing firewall policy automatically.

The process-scoped execution-policy command does not change the user or
machine policy. Runtime PID/status, logs, audit JSONL, and evidence are written
under `E:\Data\LocalVoiceAgent\runtime`. The checked-in
`configs/workspaces.yaml` grants Windows filesystem/Git observation and
explicitly approved Level 1 file changes only to
`C:\Dev\Repos\local-voice-agent`; other paths fail closed. Mutation backups
are stored outside Git under
`E:\Data\LocalVoiceAgent\runtime\backups\tool-executor`. With the executor
running, `smoke-tool-execution.py` validates the actual planner,
state machine, HTTP adapter, file read, receipt hash, and evidence path:

```powershell
C:\Dev\Tools\LocalVoiceAgent\runtimes\tool-executor\.venv\Scripts\python.exe `
  .\scripts\smoke-tool-execution.py
```

The mutation smoke separately approves a unique file creation and its exact
rollback, then verifies that the file is absent. It never touches an existing
user file:

```powershell
C:\Dev\Tools\LocalVoiceAgent\runtimes\tool-executor\.venv\Scripts\python.exe `
  .\scripts\smoke-file-rollback.py
```

From WSL, `scripts/smoke-tool-agent.py` exercises the model-facing tool loop
with a deterministic mock model response and the real Windows executor. It
must be given the executor URL, exact WSL host IP, and the same transient
token; its final output includes the metadata-only evidence ID.

A restart still clears the Tool Executor's response-body cache. The PC-server
requires PostgreSQL when tools are enabled, creates a durable session on
WebSocket acceptance, commits `RUNNING` before dispatch, and preserves
normalized execution identity, approval binding, versioned events, audit, and
outbox records. A leftover `RUNNING` record requires evidence reconciliation;
the server must not reissue it automatically.

## PostgreSQL

The database uses the existing Docker Desktop backend and binds only to
`127.0.0.1:55432`. The start script creates a random external secret on first
use, refuses a non-empty unregistered data directory, starts the exact pinned
image, waits for health, and writes a secret-free status record:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\start-postgres.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\migrate-postgres.ps1
```

Stop without deleting the container, cluster, secret, or network:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\stop-postgres.ps1
```

Rollback is application-first: stop the PC server, switch back to a compatible
Git revision, and keep the database intact. Never run `compose down -v`, remove
the bind directory, or downgrade a destructive migration automatically.

## Computer-use

Playwright 1.61.0 and Chrome for Testing 149 are isolated under
`C:\Dev\Tools\LocalVoiceAgent\browsers\playwright-1.61.0`. The executor
launcher sets the official `PLAYWRIGHT_BROWSERS_PATH`; do not add the browser
to system PATH. The `local-loopback` profile rejects external HTTP(S),
external WebSockets, downloads, submit controls, and stale page fingerprints.

With the executor running on loopback, this smoke starts its own local HTTP
server and performs approved launch, navigation, input, click, screenshot,
and close operations:

```powershell
C:\Dev\Tools\LocalVoiceAgent\runtimes\tool-executor\.venv\Scripts\python.exe `
  .\scripts\smoke-browser.py
```

`smoke-windows-ui.py` requires exactly one visible Notepad window whose title
contains the isolated `.lva-ui-smoke-...` filename supplied in
`LVA_UI_SMOKE_FILENAME`. It fails before input if modern Notepad restores a
different tab. Never run it against a restored user tab. Windows UI actions
are restricted to the registered `notepad.exe` executable, require fresh
window/tree fingerprints and exact approval, and cannot press Enter, submit,
or use coordinates.

## Android client build and install

The command-line toolchain is isolated from the system PATH:

```powershell
cd C:\Dev\Repos\local-voice-agent\apps\android-client
$env:JAVA_HOME = 'C:\Dev\Java\jdk17'
$env:ANDROID_HOME = 'C:\Dev\SDK\Android'
$env:ANDROID_SDK_ROOT = 'C:\Dev\SDK\Android'
$env:GRADLE_USER_HOME = 'E:\Cache\LocalVoiceAgent\gradle'
.\gradlew.bat --no-daemon --non-interactive `
  clean testDebugUnitTest lintDebug assembleDebug assembleRelease
```

Install the verified debug APK only when a device is visible in
`adb devices`:

```powershell
C:\Dev\SDK\Android\platform-tools\adb.exe devices
C:\Dev\SDK\Android\platform-tools\adb.exe install -r `
  E:\Data\LocalVoiceAgent\artifacts\android\0.5.0-api37\local-voice-agent-0.5.0-debug.apk
```

The release APK is intentionally unsigned and cannot be installed until the
user supplies a release-signing policy and private key outside Git. Pairing
tokens are encrypted by an Android Keystore key and their preferences file is
excluded from cloud backup and device transfer.

## Installation gates

1. Confirm manifests reference exact official revisions.
2. Confirm per-file sizes and E: has at least 20% free after staging.
3. Confirm license and whether credentials are required.
4. Create isolated uv environments.
5. Install locked packages and save `uv.lock`/package inventory.
6. Keep resumable state and the Hugging Face cache under
   `E:\Cache\LocalVoiceAgent`; stream the pinned file to a stable partial path
   beside its revision-addressed canonical target.
7. Verify upstream LFS OIDs/ETags and compute local SHA-256.
8. Atomically rename the fully validated partial file to its final filename.
9. Run minimal load, generation, multimodal, tool, and MTP-path tests.
10. Record results before selecting a runtime.

## Model switch recovery

Persist state, stop accepting tool executions, drain the model adapter,
unload 12B, clear only the runtime-owned GPU cache, load and health-check 31B,
process the request, persist evidence, unload 31B, reload 12B, and health
check. On any 31B failure, return to 12B and report the actual error.

## Network

The initial server binds only to loopback. LAN pairing is not enabled until
authentication, TLS/private-network protection, Android local-network
permission, and firewall implications have been reviewed.
