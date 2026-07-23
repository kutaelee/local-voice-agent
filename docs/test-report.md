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
| vLLM/SGLang official support research | Passed with runtime test pending | `docs/compatibility-report.md` |
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
| Approval and policy contracts | Passed | Canonical argument digest/precondition binding validated; Level 2 direct allow and Level 3 approval decisions are rejected by schema |
| Workspace configuration guard | Passed | Closed schema validated; drive root, user profile root, backup-only D:, protected E: backup root, wildcard, and WSL mounted-drive cases rejected |
| Application and pairing security defaults | Passed | Public bind, raw-audio retention, cleartext pairing, and plaintext token storage cases rejected |
| Network-free repository validation using PC-server env | Passed after dependency addition | Initial run stopped at missing `jsonschema`; the runtime tool registry now requires official stable 4.26.0, and all 10 validators passed in 3,927.26 ms |
| Network-free repository validation suite | Passed | Latest run: 10 validators completed in 3,798.71 ms using the isolated validation-capable WSL runtime; configs, manifests, contracts, catalogs, status, approval/policy, workspaces, and security defaults |
| Read-only health check | Passed | Detected both isolated vLLM versions, two finalized 12B artifacts, active partial MTP target, RTX 5090/WSL GPU state, canonical paths, and stopped server without mutation |
| Event payload contract coverage | Passed | All 24 catalog events have closed, bounded Draft 2020-12 payload definitions |
| Explicit cancellation protocol | Passed (static) | Idempotent request/result events distinguish cancelled, draining, non-cancellable, already-terminal, and missing operations |
| Observability contracts | Passed | 18 required metrics, histogram p50/p95 coverage, and closed structured-log schema validated |
| Benchmark prompt catalog | Passed | 160 unique Korean cases with required 20/30/20/20/20/20/10/20 category counts |
| Benchmark result/report envelopes | Passed (static) | Raw result remains explicitly `not_run` with zero runs; model/runtime comparison matrices exist and every unmeasured cell is `NOT_RUN` |
| Mandatory failure/security test catalog | Passed | All 24 required case IDs have explicit expected outcomes; execution remains `NOT_RUN` |
| PC-server isolated dependency lock/install | Passed | Python 3.12.13 environment outside repo; FastAPI 0.139.2, JSON Schema 4.26.0, Pydantic 2.13.4, Starlette 1.3.1, Uvicorn 0.51.0; lock SHA-256 `5a223baf0ace969d7d8d35010f0a7800e99dcc27d4256bb861e533c360a74b0b` |
| PC-server domain/API/registry/planner/router/adapter unit tests | Passed | Latest run: 79 tests in 5.33 s; prior coverage plus RUNNING/VERIFYING/SUCCEEDED and failure outcomes, duplicate receipt acceptance, receipt hash rejection, explicit loopback URL enforcement, exact execution/digest/expiry IPC binding, Level 0-only dispatch, and closed executor-response validation |
| Runtime tool registry | Passed | Draft 2020-12 definition and argument validation; stable definition hashes; unknown tools fail closed; disabled `restricted_shell` omitted from 73 model-visible tools; server-issued approval/idempotency fields hidden from model schemas |
| Tool planner risk routing | Passed | Level 0 queued; Level 1 waits unless a valid session grant exists; Level 2 always waits for exact approval; Level 3 and disabled tools create no execution aggregate |
| Approval-to-queue binding | Passed | Approved exact binding queued; denied approval and mismatched approval ID were rejected; execution CAS version remained enforced |
| Model runtime lifecycle | Passed | Load, health check, ready, drain, unload, failure, evidence requirement, cleanup-before-retry, and optimistic version transitions tested |
| 12B/31B route planner | Passed | Default/escalation/switch-back, voice and high-VRAM deferral, VRAM rejection/degradation, capability gates, multiple-ready rejection, and cleanup-before-31B-failure fallback tested without starting a process |
| PC-server process smoke first wrapper | Failed, corrected | Inline Bash used command substitution that PowerShell parsed first; command failed before starting a process, so a shell-isolated smoke script was added |
| PC-server Uvicorn process smoke | Passed | Loopback `127.0.0.1:8787`, `/health` HTTP 200, owned PID 51847 cleanly stopped, port confirmed closed |
| vLLM smoke explicit-cache argument guards | Passed after wrapper correction | Bash syntax passed; invalid KV-cache bytes exited 8 and invalid max sequences exited 9. The first combined assertion was invalid because PowerShell expanded Bash `$?` before execution; no server was launched |
| Tool Executor first Windows-native run | Failed, corrected | 22/26 passed; one assertion assumed LF after a Windows text write, and three fixtures attempted privileged symlink creation. No production file was accessed |
| Tool Executor Windows-native suite | Passed | Latest run: 57 tests in 4.55 s using isolated Python 3.12.13; prior filesystem/Git coverage plus configuration loading, authenticated bounded API, exact digest/expiry binding, duplicate/conflict behavior, and sanitized no-replace evidence |
| Tool Executor WSL suite | Passed | Latest run: same 57 tests in 3.66 s using a separate WSL Python 3.12.13 environment; internal and escaping symlinks rejected and host-specific workspace filtering verified |
| Tool Executor Windows process smoke | Passed | `127.0.0.1:8790` health returned `ok`; an unauthenticated execution returned HTTP 401; registered process stopped and no listener remained |
| Live planner-to-executor read smoke | Passed | PC planner and state-machine use case invoked the Windows loopback executor, read this repository's `README.md` through the registered read-only workspace, verified receipt hash, reached `SUCCEEDED`, and stopped cleanly. Executor latency was 10.371 ms for this single non-benchmark sample; evidence `507e23ab-fd3a-482e-810e-c76990929ebc.json` contains metadata only |
| Tool execution audit/evidence privacy | Passed | Successful secret-bearing read returned content to the caller but persisted only result/argument/definition hashes and IDs; failure evidence stored sanitized error codes; existing evidence IDs cannot be replaced |
| Tool execution idempotency | Passed (process scope) | Exact successful duplicate returned cached receipt without re-execution; conflicting reuse was rejected; failed execution was not repeated. Durable restart behavior remains `NOT_RUN` |
| Read-only Git executor | Passed | Status/diff/staged diff/stat/log/branch/show/blame; literal `--stat` path, `--help` revision injection rejection, output truncation, no index modification, and external diff suppression |
| Git metadata escape gates | Passed | Non-Git and disabled workspaces, `.git` file/worktree, object alternates, config includes, and Windows junction/WSL symlink metadata paths rejected |

Exact Q4_0 MTP multimodal compatibility, statistical MTP quality/latency
benchmark, 31B multimodal and exact-pair MTP, SGLang, audio/video, full benchmark, security,
Android, rollback, and product acceptance tests remain `NOT_RUN` or in
progress.
