# Acceptance status

Status: `IN_PROGRESS`

This is the evidence-first status of the 20 product acceptance criteria. A
unit test or offline checkpoint inspection does not substitute for a required
live runtime or physical-device test.

| # | Criterion | Status | Evidence or remaining work |
|---:|---|---|---|
| 1 | Gemma 4 12B runs | VERIFIED | vLLM and SGLang text, tool/schema, streaming, and image smokes passed. |
| 2 | Gemma 4 31B runs | VERIFIED | vLLM constrained text, tool/schema, and streaming smoke passed. |
| 3 | Matching MTP assistants run | PARTIAL | Exact 12B assistant runs in vLLM and SGLang; exact 31B pair is downloaded and integrity-checked but has not produced a live MTP response. |
| 4 | MTP ON/OFF measurements exist | PARTIAL | Matching 12B MTP-OFF baselines exist; fixed-condition MTP-ON and 31B rows remain open. |
| 5 | vLLM/SGLang comparison exists | PARTIAL | Matching 12B MTP-OFF comparison exists; MTP-ON and 31B comparison is incomplete. |
| 6 | 12B/31B switching works | PARTIAL | State-machine, API, drain, cleanup, and recovery tests pass; live GPU process switch remains open. |
| 7 | Android voice conversation works | PARTIAL | Production WebSocket PCM→STT→12B→TTS smoke and emulator UI/install pass; physical Android microphone/LAN playback remains open. |
| 8 | User speech interrupts TTS | PARTIAL | Server and Android cancellation paths pass unit/integration tests; physical-device barge-in timing remains open. |
| 9 | Files and Git state can be read | VERIFIED | Live planner-to-executor file read and Windows/WSL filesystem/Git suites pass. |
| 10 | Approved workspace file mutation works | VERIFIED | Exact Level 1 approval created a workspace file with a hash precondition. |
| 11 | Before/after diff is available | VERIFIED | Patch/diff contracts and executor tests pass. |
| 12 | Rollback works | VERIFIED | Approved live rollback restored the prior state; concurrent-content rollback rejection also passes. |
| 13 | Browser and Windows UI can be controlled narrowly | VERIFIED | Loopback-only Playwright and registered-window UI Automation smokes pass with evidence. |
| 14 | Codex and other coding agents can be observed | VERIFIED | Process, status JSON, log, Git, recent-file, test/build, and heartbeat adapters pass without private APIs. |
| 15 | Tool calls leave audit and evidence | VERIFIED | Executor API and live read/write/browser smokes persist metadata-only audit/evidence records. |
| 16 | Level 2+ cannot run without approval | VERIFIED | Planner, approval binding, schema, coordinate-action, and required security cases pass fail-closed. |
| 17 | WSL failure has a diagnostic fallback | VERIFIED | Pinned native Windows llama.cpp CPU fallback passes Korean text, tool/schema, and streaming smokes. |
| 18 | Android debug APK exists | VERIFIED | Version 0.6.2 API 37 debug APK is v2-signed and hash-recorded. |
| 19 | Install and removal are documented | VERIFIED | Runbook, installation, rollback, artifact, runtime, and model manifests are tracked. |
| 20 | A new environment can reproduce the system from docs | PARTIAL | Locked environments, scripts, manifests, and validators exist; an independent clean-workstation reproduction has not been run. |

## Current totals

- Verified: 13
- Partial: 7
- Failed: 0

## Evidence anchors

- Required failure/security cases:
  `E:\Data\LocalVoiceAgent\runtime\evidence\required-tests\required-cases-20260723T214806159Z.json`
- Fixed-condition vLLM 12B MTP-OFF:
  `E:\Data\LocalVoiceAgent\benchmarks\results\vllm-12b-mtp-off-20260723T221500000Z.json`
- Fixed-condition SGLang 12B MTP-OFF:
  `E:\Data\LocalVoiceAgent\benchmarks\results\sglang-12b-mtp-off-latency.json`
- Android artifacts:
  `E:\Data\LocalVoiceAgent\artifacts\android\0.6.2-api37`
- Detailed executed tests: `docs/test-report.md`
- Measured performance and caveats: `docs/performance-report.md`

## Closure order

1. Use an idle shared-GPU window for 12B MTP-ON comparisons.
2. Attempt and record exact 31B MTP feasibility without affecting foreign
   ComfyUI/Qwen work.
3. Run a live 12B→31B→12B process switch.
4. Install the current APK on a physical Android device and complete
   microphone, speaker/earpiece, Bluetooth, reconnect, LAN/TLS, and barge-in
   QA using `docs/physical-android-qa.md`.
5. Perform an independent documented clean-environment reproduction or record
   an explicit scope decision.
