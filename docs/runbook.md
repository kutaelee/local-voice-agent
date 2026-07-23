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
