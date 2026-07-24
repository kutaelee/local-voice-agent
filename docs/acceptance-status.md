# Acceptance status

Status: `IN_PROGRESS`

This is the evidence-first status of the 20 product acceptance criteria. A
unit test or offline checkpoint inspection does not substitute for a required
live runtime or physical-device test.

| # | Criterion | Status | Evidence or remaining work |
|---:|---|---|---|
| 1 | Gemma 4 12B runs | VERIFIED | vLLM and SGLang text, tool/schema, streaming, and image smokes passed. |
| 2 | Gemma 4 31B runs | VERIFIED | vLLM constrained text, tool/schema, and streaming smoke passed. |
| 3 | Matching MTP assistants run | VERIFIED | Exact 12B assistants run in vLLM and SGLang; the exact 31B target/assistant also passed live vLLM text, tool, schema, and streaming checks. |
| 4 | MTP ON/OFF measurements exist | VERIFIED | Controlled exact-target ON/OFF pairs exist for vLLM 12B, SGLang 12B, and constrained vLLM 31B. |
| 5 | vLLM/SGLang comparison exists | VERIFIED | Matching 12B comparisons completed; bounded 31B probes selected vLLM after SGLang's W4A16 repack failure and exact-target request timeout. |
| 6 | 12B/31B switching works | VERIFIED | The actual stable-vLLM 12B-to-31B-to-12B stop/load/health sequence passed and returned to a verified 12B state. |
| 7 | Android voice conversation works | PARTIAL | Production WebSocket PCM→STT→12B→TTS smoke passes and the user reports physical Android STT/TTS/continuous-turn QA working. The structured 20-turn collector and new 0.6.6 Qwen voice QA remain open. |
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
| 18 | Android debug APK exists | VERIFIED | Version 0.6.6 API 37 debug APK is v2-signed and hash-recorded. |
| 19 | Install and removal are documented | VERIFIED | Runbook, installation, rollback, artifact, runtime, and model manifests are tracked. |
| 20 | A new environment can reproduce the system from docs | VERIFIED | A fresh public clone at `734405e` with an empty Gradle cache passed prerequisites, 10 validators, 25 root tests, Android 15 tests, lint, and byte-identical debug/release builds. |

## Current totals

- Verified: 18
- Partial: 2
- Failed: 0

## Evidence anchors

- Required failure/security cases:
  `E:\Data\LocalVoiceAgent\runtime\evidence\required-tests\required-cases-20260723T214806159Z.json`
- Fixed-condition vLLM 12B MTP-OFF:
  `E:\Data\LocalVoiceAgent\benchmarks\results\vllm-12b-mtp-off-20260723T221500000Z.json`
- Fixed-condition SGLang 12B MTP-OFF:
  `E:\Data\LocalVoiceAgent\benchmarks\results\sglang-12b-mtp-off-latency.json`
- Fixed-condition vLLM 31B MTP-OFF:
  `E:\Data\LocalVoiceAgent\benchmarks\results\vllm-31b-exact-mtp-off-20260724T003133732Z.json`
- Fixed-condition vLLM 31B MTP-ON:
  `E:\Data\LocalVoiceAgent\benchmarks\results\vllm-31b-exact-mtp-on-s1-20260724T010244662Z.json`
- Live model switch:
  `E:\Data\LocalVoiceAgent\runtime\evidence\model-switch\live-model-switch-20260724T011306766Z.json`
- Clean-clone reproduction:
  `E:\Data\LocalVoiceAgent\runtime\evidence\reproduction\clean-clone-734405e.json`
- Android artifacts:
  `E:\Data\LocalVoiceAgent\artifacts\android\0.6.6-api37`
- Detailed executed tests: `docs/test-report.md`
- Measured performance and caveats: `docs/performance-report.md`

## Closure order

1. Install the current APK on a physical Android device and complete
   microphone, speaker/earpiece, Bluetooth, reconnect, LAN/TLS, and barge-in
   QA using `docs/physical-android-qa.md` and the registered metadata-only
   collector.
