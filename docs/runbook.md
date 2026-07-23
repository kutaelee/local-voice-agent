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
python scripts/audio-worker-health.py

export LVA_VLLM_API_KEY='<random-vllm-api-key>'
bash scripts/start-vllm.sh
```

The audio workers use mode-0600 Unix sockets. vLLM binds only to
`127.0.0.1:8766`; its first model load from the canonical NTFS model store can
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

Stop only registered project processes:

```bash
bash scripts/stop-vllm.sh
bash scripts/stop-audio-workers.sh
```

`scripts/start-server.ps1` remains fail-closed until registered PID/status
handling and the Android-facing TLS termination path are implemented.

## Tool Executor

The Windows-native Tool Executor is independently locked and always starts on
loopback. Keep its IPC token in the current process environment or a future OS
credential-store integration, never in Git:

```powershell
$env:LVA_TOOL_EXECUTOR_TOKEN = '<at-least-32-random-characters>'
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\scripts\start-tool-executor.ps1
Invoke-RestMethod http://127.0.0.1:8790/health
.\scripts\stop-tool-executor.ps1
```

The process-scoped execution-policy command does not change the user or
machine policy. Runtime PID/status, logs, audit JSONL, and evidence are written
under `E:\Data\LocalVoiceAgent\runtime`. The checked-in
`configs/workspaces.yaml` grants Windows read-only filesystem/Git observation
only to `C:\Dev\Repos\local-voice-agent`; other paths fail closed. With the
executor running, `smoke-tool-execution.py` validates the actual planner,
state machine, HTTP adapter, file read, receipt hash, and evidence path:

```powershell
C:\Dev\Tools\LocalVoiceAgent\runtimes\tool-executor\.venv\Scripts\python.exe `
  .\scripts\smoke-tool-execution.py
```

A restart clears the current in-memory idempotency cache; do not treat it as
durable until PostgreSQL-backed execution persistence is implemented.

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
  E:\Data\LocalVoiceAgent\artifacts\android\0.3.0-api37\local-voice-agent-0.3.0-debug.apk
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
