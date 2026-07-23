# Runbook

## Current safe commands

```powershell
pwsh -File scripts\health-check.ps1
pwsh -File scripts\install.ps1 -PlanOnly
pwsh -File scripts\download-models.ps1 -PlanOnly
```

WSL planning:

```bash
bash scripts/install-wsl.sh --plan-only
bash scripts/download-models.sh --plan-only
```

## Installation gates

1. Confirm manifests reference exact official revisions.
2. Confirm per-file sizes and E: has at least 20% free after staging.
3. Confirm license and whether credentials are required.
4. Create isolated uv environments.
5. Install locked packages and save `uv.lock`/package inventory.
6. Download into `E:\Cache\LocalVoiceAgent\downloads`.
7. Verify upstream LFS OIDs/ETags and compute local SHA-256.
8. Materialize the validated snapshot under the canonical model root.
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
