# Test report

Status: Slice 2/3 validation and early Slice 5 implementation are in
progress. No product acceptance test has run.

## Checks completed

| Check | Result | Evidence |
|---|---|---|
| Windows/GPU discovery | Passed | `docs/environment-report.md` |
| WSL GPU visibility | Passed | RTX 5090 visible in Ubuntu |
| Canonical storage capacity | Passed | `docs/storage-report.md` |
| Existing Gemma 4 duplicate check | Passed | No Gemma 4 checkpoint found |
| Official model IDs/revisions metadata query | Passed | `manifests/models.yaml` |
| vLLM/SGLang official support research | Passed; SGLang CUDA runtime passed, model comparison pending | `docs/compatibility-report.md` |
| Model-download environment bootstrap, first attempt | Failed as expected | Non-login WSL did not expose `~/.local/bin/uv`; no package installed |
| Model-download environment bootstrap, retry | Passed | Python 3.12.13, Hugging Face Hub 1.24.0 |
| PowerShell script parse | Passed | All tracked `.ps1` scripts parsed with `ScriptBlock::Create` |
| Bash syntax check | Passed | `bash -n` for both WSL scripts |
| `hf --local-dir` interrupted-transfer resume | Failed | Xet and HTTP fallback created different random partial names; preserved as evidence |
| Stable range-resume strategy | Passed (small-file test) | 29,372-byte official file; HTTP 206, SHA-256 pass, second run reused 1/1 completed chunk |
| 12B interrupted transfer resume | Passed | Restart resumed at 24/153 completed 64 MiB chunks |
| Range worker comparison | Preliminary | 8 workers: 1,536 MiB/289 s = 5.31 MiB/s; 16 workers: 1,216 MiB/211 s = 5.76 MiB/s |
| Selective download reserve calculation | Passed | 12B MTP target plan selected 23,919,549,408 weight bytes plus 1 GiB metadata headroom and preserved the E: 20% volume reserve |
| Read-only model download status | Passed | Active 12B MTP transfer and finalized 12B W4A16 target both reported exact revision, byte progress, finalization, and process state |
| 12B parallel range transfer | Passed | 153/153 chunks; 1,227.345 s wall time including restart = 7.98 MiB/s |
| 12B target SHA-256 | Passed | `60b6e3989502969d8ae04185d72ecbbc7db63978d5af747a493d53895aa6bfa3` |
| 12B MTP assistant SHA-256 | Passed | `67f1420cf24aa5065089aaed175223f7c245ccfda16111b6c56765afd7280db6` |
| 12B exact MTP target SHA-256 | Passed | 23,919,549,408-byte final file; downloader and wrapper both matched `26f2cee4292298a3f9f92209643c37c80e34e011381e22434088870d9439a0a0` |
| 12B target safetensors structure | Passed | 1,334 tensors; file end matches final tensor offset |
| 12B target/assistant tensor contract | Passed | Target embedding 262,144×3,840; assistant pre-projection 1,024×7,680; target embedding sharing is required |
| 12B exact target/assistant offline pair | Passed | Target 677 BF16 tensors, assistant 48 BF16 tensors; all 11 model/dimension/embedding/projection/context checks passed |
| 12B exact MTP multimodal initialization | Failed | Official Q4_0 target config omits `vision_config.num_soft_tokens`; exact-fix vLLM input processor raised `AttributeError` before weight load and health |
| 12B exact MTP text-only load/health | Passed | Exact-fix runtime selected `method='mtp'` and `Gemma4MTPModel`; target + assistant loaded, health 200, 2,048-token context |
| 12B exact MTP smoke client first invocation | Failed, corrected | Base URL incorrectly included `/v1`, causing `GET /v1/health` HTTP 404; retry used the documented port-root URL |
| 12B exact MTP text API smoke | Passed | Korean text, `inspect_gpu` tool call with valid `{}`, strict JSON Schema, and 32-chunk streaming all passed; evidence `vllm-12b-mtp-textonly-smoke.json` |
| 12B exact MTP speculative metrics | Passed (preliminary) | 48 draft tokens, 43 accepted (89.6%); 4/4 API requests succeeded, no request errors |
| 12B exact MTP controlled stop | Passed | Only owned API/engine PIDs stopped; port closed and total GPU use fell from 32,038 MiB to 2,957 MiB |
| 31B W4A16 parallel range transfer | Passed | Resumed at 147/347 chunks; completed 347/347 at approximately 13.06 MiB/s near transfer end |
| 31B W4A16 SHA-256 | Passed | Downloader and wrapper both matched `1b9b1d622a93f02c0d33f98e502f233b5d707443af6ddc464ed0bf5498506c20`; partial finalized atomically |
| 31B W4A16 safetensors structure | Passed | 23,265,352,448-byte file, 2,009 tensors; final tensor offset exactly matches file end; compressed-tensors W4 group size 32 |
| 31B MTP assistant SHA-256 | Passed | 939,042,560-byte weight matched `50008e854554a1a9c26317216cd99ae5a3567d4942c9e061398b995cc48c34b9`; exact 31B Q4_0 target remains not downloaded |
| vLLM 31B first text-only load | Failed, corrected | W4A16 weights loaded in 110.04 s using 18.7 GiB, but the shared-host 0.72 utilization budget left -3.17 GiB for KV cache; the owned processes exited and GPU memory returned before retry |
| vLLM 31B explicit-KV load/health | Passed | V1 runner, text-only, eager, 256-token context, one sequence, and 384 MiB explicit KV cache; weights loaded in 106.34 s, model load used 18.7 GiB, engine initialization took 2.31 s, and health returned HTTP 200 |
| vLLM 31B text API smoke | Passed | Korean text, `inspect_gpu({})`, strict JSON Schema, and 51-chunk streaming passed; streaming TTFT 67.33 ms; evidence `vllm-31b-textonly-smoke.json` SHA-256 `987b979d…` |
| vLLM 31B controlled stop | Passed | Only owned API/engine PIDs 53260/53453 were terminated; port 8767 closed and total GPU use fell from 27,187 MiB to 6,720 MiB while the unrelated Ollama process remained running |
| Identical-hash mirror resume | Passed | vLLM wheel reused 1/4 ranges after GitHub-to-PyPI URL change |
| vLLM wheel SHA-256 | Passed | `16fc7a28df1576eb6f7ca0455026551b8f9adb674c19c66059359ef3e964bd1e` |
| vLLM isolated dependency install | Passed | vLLM 0.25.1, Python 3.12.13, torch 2.11.0+cu130; 192-package compatibility check |
| vLLM RTX 5090 CUDA smoke | Passed | Compute capability 12.0; CUDA matrix multiplication returned expected 1024.0 |
| vLLM CLI capability inspection | Passed | `gemma4` tool parser and speculative/chat/model/GPU configuration flags present |
| vLLM 12B default V2 runner | Failed | WSL CUDA UVA unavailable; engine stopped before weight load |
| vLLM 12B V1 runner load/health | Passed | 9.56 GiB checkpoint; health 200; exact W4A16 compressed-tensors model |
| vLLM 12B Korean text | Passed | Correct UTF-8 response: 대한민국의 수도는 서울입니다 |
| vLLM 12B function calling | Passed | `inspect_gpu` selected with valid `{}` arguments and `tool_calls` finish |
| vLLM 12B structured output | Passed | Strict schema returned South Korea / Seoul JSON |
| vLLM 12B streaming | Passed | 49 SSE chunks; preliminary single-sample TTFT 175.88 ms |
| vLLM 12B image input | Passed | In-memory 32x32 red PNG classified as `Red` |
| vLLM 12B controlled stop | Passed | API and engine processes exited; VRAM returned to 1,107 MiB |
| vLLM W4A16 + Q4_0 assistant MTP dispatch | Passed | vLLM selected `Gemma4MTPModel` and `method='mtp'`, not generic draft decoding |
| vLLM W4A16 + Q4_0 assistant MTP compile | Failed | Stable guard kept the 1,024-wide assistant embedding separate: measured 4,864 versus required 7,680; no health endpoint |
| vLLM MTP regression root-cause check | Passed | Upstream PR 47953 changes the width guard to EAGLE-only; exact fix commit `b2b8f679d058…` pinned |
| vLLM MTP fix wheel integrity | Passed | Official exact-commit cu130 wheel, 308,229,710 bytes, SHA-256 `d19e66ce501be98d2790a64c01d07d10c376e7785b0b4ca623db23ca4ebf0d61`; embedded source contains the EAGLE-only guard |
| vLLM MTP fix isolated install | Passed | Exact commit wheel installed in a separate Python 3.12.13 environment; 192-package compatibility check passed |
| vLLM MTP fix RTX 5090 CUDA smoke | Passed | torch 2.11.0+cu130, CUDA 13.0, compute capability 12.0; 32×32 matrix result 32.0 |
| vLLM MTP fix installed source guard | Passed | Installed proposer applies embedding-width rejection only when the draft exposes the EAGLE `has_own_embed_tokens` contract |
| Official exact MTP target metadata | Passed | 12B `b6ed862…` and 31B `1e4d8be…` revisions, sizes, and SHA-256 values pinned |
| Chatterbox Multilingual V3 metadata | Passed | Official HF revision `5bb1f6e…`, source `5de7a54…`, MIT license, Korean support, 3,208,951,924 selected bytes, and primary weight hashes pinned |
| Chatterbox runtime dependency gate | Passed | Package 0.1.7 torch/torchaudio 2.6 pin detected; isolated Blackwell runtime remains uninstalled |
| STT candidate metadata | Passed | faster-whisper 1.2.1 source/package pinned; linked large-v3-turbo and Systran small revisions, sizes, licenses, and SHA-256 values recorded |
| OpenAI-compatible smoke client static checks | Passed | Python compile and generated 32×32 red PNG decode/pixel validation |
| Runtime/model/GPU config references | Passed | 4 configured models, 9 manifest roles, and 9 runtime IDs cross-validated; unvalidated MTP routes remain disabled |
| Model/download manifest metadata consistency | Passed | 9 exact model ID/revision pairs, per-artifact licenses, sizes, weight lists, SHA-256 syntax, timestamps, and revision-pinned paths cross-validated without reading active large transfers |
| Download state isolation | Passed | Explicit cache-side state path; 29,372-byte live transfer and 1/1 resume passed |
| Protocol/tool contract catalog consistency | Passed | 24 events, 74 tools; all 73 required tool names present; drift checks and Draft 2020-12 schema validation passed |
| Filesystem mutation contract safety | Passed (static) | Level 1 writes/copies/moves/archives require preconditions and idempotency; Level 2 deletion is limited to one hash-pinned file or one empty directory |
| Registered development tool contracts | Passed (static) | Test/lint/format/build/server tools accept profile IDs instead of commands; dev servers are loopback-only and can be stopped only by executor-issued handles |
| Git mutation contract safety | Passed (static) | Exact commit/fingerprint preconditions; force push unavailable; merge fast-forward-only; hard reset and clean remain Level 3 deny-by-default |
| Process and restricted-shell contracts | Passed (static) | Process stop binds handle/PID/start time at Level 2; restricted shell accepts only allowlisted executable/environment IDs and is disabled by default |
| Browser tool contracts | Passed (static) | Fresh page fingerprints bind interactions; click/type/select cannot submit; external form submission is isolated at Level 2 with reviewed payload fingerprint |
| Windows UI tool contracts | Passed (static) | Accessibility elements require fresh state; text/key tools cannot submit; coordinate click/drag require Level 2 approval bound to screenshot hash and dimensions |
| Coding-agent status contracts | Passed | Closed optional status input and per-field provenance schemas validated; inferred fields without explanations and invented progress percentages are rejected |
| Coding-agent status adapters | Passed | Five adapter unit cases plus two authenticated API cases cover strict optional status JSON, workspace association, Git observation, invalid status rejection, and sanitized provider failure; live Windows/WSL observation detected Codex, Codex Desktop, and the workspace terminal without exposing command lines |
| Approval and policy contracts | Passed | Canonical argument digest/precondition binding validated; Level 2 direct allow and Level 3 approval decisions are rejected by schema |
| Workspace configuration guard | Passed | Closed schema validated; drive root, user profile root, backup-only D:, protected E: backup root, wildcard, and WSL mounted-drive cases rejected |
| Application and pairing security defaults | Passed | Public bind, raw-audio retention, cleartext pairing, and plaintext token storage cases rejected |
| Network-free repository validation using PC-server env | Passed after dependency addition | Initial run stopped at missing `jsonschema`; the runtime tool registry now requires official stable 4.26.0, and all 10 validators passed in 3,927.26 ms |
| Network-free repository validation suite | Passed | Latest run: 10 validators completed in 4,093.36 ms using the isolated validation-capable WSL runtime; configs, manifests, contracts, catalogs, status, approval/policy, workspaces, and security defaults |
| Read-only health check | Passed | Detected both isolated vLLM versions, two finalized 12B artifacts, active partial MTP target, RTX 5090/WSL GPU state, canonical paths, and stopped server without mutation |
| Event payload contract coverage | Passed | All 24 catalog events have closed, bounded Draft 2020-12 payload definitions |
| Explicit cancellation protocol | Passed (static) | Idempotent request/result events distinguish cancelled, draining, non-cancellable, already-terminal, and missing operations |
| Observability contracts | Passed | 18 required metrics, histogram p50/p95 coverage, and closed structured-log schema validated |
| Benchmark prompt catalog | Passed | 160 unique Korean cases with required 20/30/20/20/20/20/10/20 category counts |
| Benchmark result/report envelopes | Passed (static) | Raw result remains explicitly `not_run` with zero runs; model/runtime comparison matrices exist and every unmeasured cell is `NOT_RUN` |
| Mandatory failure/security test catalog | Passed | All 24 required case IDs have explicit expected outcomes; execution remains `NOT_RUN` |
| PC-server isolated dependency lock/install | Passed | Python 3.12.13 environment outside repo; FastAPI 0.139.2, JSON Schema 4.26.0, Pydantic 2.13.4, Starlette 1.3.1, Uvicorn 0.51.0; lock SHA-256 `5a223baf0ace969d7d8d35010f0a7800e99dcc27d4256bb861e533c360a74b0b` |
| PC-server domain/API/registry/planner/router/adapter/audio tests | Passed | Latest run: 121 tests with PostgreSQL enabled; includes the bounded model tool loop, exact approval continuation/rejection, WSL-gateway allowlist, VAD worker/endpoint handling, in-flight cancellation, closed client payloads, Unix worker adapters, STT/conversation/TTS sequencing, and durable plan/approval/execution lifecycle checks |
| Runtime tool registry | Passed | Draft 2020-12 definition and argument validation; 75 stable definition hashes; unknown tools fail closed; disabled `restricted_shell` omitted from 74 model-visible tools; server-issued approval/idempotency fields hidden from model schemas |
| Tool planner risk routing | Passed | Level 0 queued; Level 1 waits unless a valid session grant exists; Level 2 always waits for exact approval; Level 3 and disabled tools create no execution aggregate |
| Approval-to-queue binding | Passed | Approved exact binding queued; denied approval and mismatched approval ID were rejected; execution CAS version remained enforced |
| Model runtime lifecycle | Passed | Load, health check, ready, drain, unload, failure, evidence requirement, cleanup-before-retry, and optimistic version transitions tested |
| 12B/31B route planner | Passed | Default/escalation/switch-back, voice and high-VRAM deferral, VRAM rejection/degradation, capability gates, multiple-ready rejection, and cleanup-before-31B-failure fallback tested without starting a process |
| PC-server process smoke first wrapper | Failed, corrected | Inline Bash used command substitution that PowerShell parsed first; command failed before starting a process, so a shell-isolated smoke script was added |
| PC-server Uvicorn process smoke | Passed | Loopback `127.0.0.1:8787`, `/health` HTTP 200, owned PID 51847 cleanly stopped, port confirmed closed |
| Registered PC-server lifecycle scripts | Passed | `start-server.ps1` derived the local PostgreSQL URL without logging its secret, launched the WSL Uvicorn factory on `127.0.0.1:8787`, recorded verified Windows/WSL PIDs, served `/health`, then `stop-server.ps1` sent a graceful Linux stop; port and process were absent afterward |
| vLLM smoke explicit-cache argument guards | Passed after wrapper correction | Bash syntax passed; invalid KV-cache bytes exited 8 and invalid max sequences exited 9. The first combined assertion was invalid because PowerShell expanded Bash `$?` before execution; no server was launched |
| Tool Executor first Windows-native run | Failed, corrected | 22/26 passed; one assertion assumed LF after a Windows text write, and three fixtures attempted privileged symlink creation. No production file was accessed |
| Tool Executor Windows-native suite | Passed | Latest run: 81 passed and one symlink case skipped with the registered Playwright path; filesystem/Git, browser/UI, system observation, approval-bound write/patch/rollback, registered-test profiles, atomic replacement, concurrent-hash rejection, API binding, and no-replace evidence passed |
| Tool Executor WSL suite | Passed | Latest run: 78 passed and four Windows-only cases skipped using a separate WSL Python 3.12.13 environment; portable contracts plus filesystem/Git, registered-profile invariants, internal and escaping symlink mutation rejection, create/replace/patch, concurrent-change rollback rejection, and browser URL policy passed |
| Windows system observation tools | Passed (live) | Fixed-query CPU, memory, RTX GPU, C: disk, filtered process, running-service, secret-redaction, and live loopback-port probes passed. The adapter exposes no mutation, arbitrary command, service control, or process termination path |
| Approved registered test profile over API | Passed | A loopback Tool Executor ran the fixed `repository-validation` WSL argv only after exact Level 1 approval, captured bounded external test evidence `34aae793-3643-49cc-a911-124f5d90f696`, and returned it through workspace-bound `inspect_test_log`; the log contained `repository_validation_passed`. The task-owned listener was stopped and port 8790 was absent afterward |
| Tool Executor Windows process smoke | Passed | `127.0.0.1:8790` health returned `ok`; an unauthenticated execution returned HTTP 401; registered process stopped and no listener remained |
| Live planner-to-executor read smoke | Passed | PC planner and state-machine use case invoked the Windows loopback executor, read this repository's `README.md` through the registered workspace, verified receipt hash, reached `SUCCEEDED`, and stopped cleanly. Executor latency was 10.371 ms for this single non-benchmark sample; evidence `507e23ab-fd3a-482e-810e-c76990929ebc.json` contains metadata only |
| Live approved file mutation and rollback | Passed | A unique non-existing smoke file was created under the registered workspace with an exact approval and SHA precondition, then removed by a separately approved exact-backup rollback. Create execution `ea24cd44-d0f2-46ee-b003-1a1defdc3dbd` took 12.214 ms; rollback `f3c021e1-5f31-4457-a148-b91e602fb1bf` took 12.758 ms; final file is absent. The first combined PowerShell wrapper timed out before any mutation/audit event; separate owned-process start/smoke/stop succeeded |
| WSL-to-Windows model tool-loop smoke | Passed | The deterministic model response selected `read_file`; the real Windows executor accepted the authenticated request only on exact WSL Hyper-V address `172.18.0.1`, returned a verified result, and persisted metadata-only evidence `917e11fb-8140-433b-931e-7af3174a9dca` (executor latency 0.86 ms). An initial combined wrapper timed out during cleanup after the request path was still under investigation; no mutation occurred. The corrected launcher records both actual listener and virtual-environment launcher PIDs, and the final run stopped both with no listener left |
| Loopback-only Playwright computer-use | Passed after environment-name correction | The first real launch failed because the launcher set a project-prefixed browser-path variable instead of Playwright's official `PLAYWRIGHT_BROWSERS_PATH`; evidence recorded `BROWSER_AUTOMATION_FAILED` and no browser opened. After correction, official Playwright 1.61.0 with Chrome for Testing 149.0.7827.55 launched in an isolated profile; eight real planner/approval/executor operations covered local navigation, DOM/accessibility state, fresh-fingerprint type/click, screenshot, and close. External HTTP/WebSocket, download, and submit paths are blocked. Screenshot artifact `e874748d-295e-4e04-be06-3b80d873cc28`, SHA-256 `e976c9f14390fb41137b4fb4d2476074a07b4ed6874b4e9eddfbc269e689691c`; owned browser processes were absent after stop |
| Microsoft UI Automation observation | Passed | Windows-visible-window observation and a 2,880×1,541 virtual-desktop PNG capture passed in the isolated executor test; screenshot paths are UUID/no-replace and coordinate tools remain disabled |
| Approved Windows UI text action | Passed with cleanup incident | Five real planner/approval/executor operations focused Notepad, read its bounded UIA tree, typed 47 non-submit characters, and captured evidence `476e581d-3a2b-417d-aecd-a992d64a7b3f`. Windows 11 Notepad unexpectedly restored a prior user tab instead of the requested test target. No file was saved; the test text was removed, the modified restored tab was discarded, Notepad was stopped, and no smoke file exists. The smoke now fails before input unless the exact isolated filename is visible |
| Tool execution audit/evidence privacy | Passed | Successful secret-bearing read returned content to the caller but persisted only result/argument/definition hashes and IDs; failure evidence stored sanitized error codes; existing evidence IDs cannot be replaced |
| Tool execution idempotency | Passed (process and durable adapter) | Exact successful duplicate returned cached receipt without re-execution; conflicting reuse was rejected; failed execution was not repeated. PostgreSQL 18.4 integration additionally recovered the exact record through a new connection and rejected stale CAS updates |
| PostgreSQL durable lifecycle migration and outbox | Passed | Exact PostgreSQL 18.4 image remains healthy on `127.0.0.1:55432`; Alembic applied `0001_initial` and `0002_approval_recovery`. Real asyncpg tests verify atomic plan/policy event/outbox insertion, exact approval binding and queueing, pre-dispatch `RUNNING`, receipt verification to `SUCCEEDED`, audit/outbox insertion, idempotent replay, stale-CAS rejection, reconnect recovery, and scoped test-data cleanup |
| Read-only Git executor | Passed | Status/diff/staged diff/stat/log/branch/show/blame; literal `--stat` path, `--help` revision injection rejection, output truncation, no index modification, and external diff suppression |
| Git metadata escape gates | Passed | Non-Git and disabled workspaces, `.git` file/worktree, object alternates, config includes, and Windows junction/WSL symlink metadata paths rejected |
| Android command-line SDK integrity | Passed | Official 155,655,386-byte command-line tools archive matched SHA-256 `90ae805d20434428bffcb699c290860f19bb5f66a67e6b330067e3de801fb04a`; API 37, Build Tools 36.0.0, Platform Tools 37.0.0 installed without PATH/registry changes |
| Android API 37 clean build | Passed | Gradle 9.6.1 distribution checksum pinned; AGP 9.3.0; latest `clean testDebugUnitTest lintDebug assembleDebug assembleRelease` succeeded in 1m02s |
| Android network/reducer unit tests | Passed | 11 tests, 0 failures, 0 errors, 0 skipped; strict protocol envelopes, secure endpoint parsing, authenticated trusted-TLS WebSocket exchange, and reducer state covered |
| Android lint | Passed | 0 findings after secure backup rules, current stable AndroidX dependencies, and adaptive/monochrome icon fixes |
| Android package metadata | Passed | AAPT2 verified application ID `dev.localvoiceagent.android`, min SDK 26, compile/target SDK 37 |
| Android debug signature | Passed | APK Signature Scheme v2 verified with the generated Android debug certificate |
| Android unsigned release state | Passed | `apksigner verify` rejected the release artifact as expected; no release key was created or assumed |
| Android 0.4.1 artifacts | Passed | Debug APK 12,456,668 bytes SHA-256 `b020672fc3b5b85574def24cebfb3fa30f2a2ed8c5da8eaeb689499d259659f1`; unsigned release APK 8,869,323 bytes SHA-256 `cee2bdc920580f7e3c723e177ae6f74001be87cf52e0d68df9b9f1e160ce5f7f`; AAPT2 confirmed version code 5/name 0.4.1 and API 37 |
| faster-whisper small download integrity | Passed | Official pinned revision `536b0662742c02347bc0e980a01041f333bce120`; 483,546,902-byte `model.bin` matched SHA-256 `3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671`; runtime loading remains pending |
| faster-whisper isolated runtime | Passed | Python 3.12.13, faster-whisper 1.2.1, CTranslate2 4.8.1, cuBLAS 12.9.2.10 and cuDNN 9.25.0.15 installed from a hash-locked dependency set; CPU and RTX 5090 CUDA paths passed |
| faster-whisper Korean synthetic sample | Passed (smoke) | Both small and large-v3-turbo transcribed the 3.12-second Chatterbox sample as the intended Korean sentence with only spacing/punctuation differences; small GPU inference 0.354 s and large 0.341 s, excluding model load; one synthetic sample is not an accuracy benchmark |
| Silero VAD isolated runtime | Passed (smoke) | Official 6.2.1 wheel SHA-256 passed; ONNX Runtime 1.27.0 CPU loaded in 45.126 ms, processed the 3.12-second Korean sample in 7.834 ms, and returned no segments for two seconds of silence |
| Persistent VAD worker endpoint | Passed (smoke) | Authenticated mode-0600 Unix-socket worker detected first speech by 160 ms and endpoint at 3,136 ms after a 500 ms silence gate; 98 sequential frame requests completed in 122.187 ms wall time. This is one deterministic process smoke, not a latency distribution |
| Chatterbox Multilingual V3 local Korean synthesis | Passed (smoke) | Official revision `5bb1f6e…` weights and built-in conditions loaded offline using exact official source commit `5de7a54…`; 3.12-second 24 kHz output synthesized in 2.331 s after an 18.080 s load, RTF 0.747, peak allocated VRAM 3,338,263,040 bytes; one run is not a benchmark |
| Persistent audio-worker composition | Passed (smoke) | Authenticated mode-0600 Unix-socket STT/TTS workers completed TTS-to-STT process integration; the sample recognized `통합` as `톤업`, so this is a process smoke rather than an accuracy pass |
| Live 12B loopback API | Passed | Stable vLLM 0.25.1 returned health 200 and a Korean chat completion from `127.0.0.1:8766`; model load from the canonical NTFS path took 132.38 s and total cold initialization was about 200 s |
| SGLang isolated CUDA runtime | Passed; model load deferred | SGLang 0.5.15.post1, PyTorch 2.11.0+cu130, and official `sglang-kernel` 0.4.4+cu130 passed a 194-package compatibility check, detected RTX 5090 compute capability 12.0, and completed CUDA matrix multiplication. Gemma loading was not attempted when an unrelated Windows process left only 2,954 MiB free |
| Production WebSocket voice path | Passed (smoke) | A 149,760-byte 24 kHz Korean PCM sample traversed authenticated WebSocket → faster-whisper → Gemma 4 12B → Chatterbox V3 and returned 215,040 PCM bytes in 7 chunks; evidence `voice-websocket-e2e.json` |
| In-flight voice cancellation | Passed (unit/integration) | Voice completion runs outside the WebSocket receive loop; an exact assistant-response cancel interrupts the task, deduplicates the idempotency key, emits `operation.cancel.result` plus `interrupted`, discards later output, and permits the next capture. Physical-device timing remains open |
| Android emulator install and UI interaction | Passed (partial device QA) | The 0.4.1 debug APK installed on a booted API 37 x86_64 emulator, launched as the resumed activity, exposed Pairing/Voice/Approval/More plus all four secondary destinations, survived a real rotation (`rotation=1`, 2400×1080 hierarchy), and relaunched after force-stop without AndroidRuntime/FATAL errors. The initial 0.4.0 capture found a status-bar overlap and clipped eight-item bottom row; 0.4.1 corrected both and the recapture passed. Physical-device microphone, Bluetooth, network reconnect, and end-to-end voice remain open |

Exact Q4_0 MTP multimodal compatibility, statistical MTP quality/latency
benchmark, 31B multimodal and exact-pair MTP, SGLang model comparison,
audio/video coverage, full benchmark, security matrix, Android device/voice,
and product acceptance tests remain `NOT_RUN` or in progress.
