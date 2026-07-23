# Test report

Status: Slice 2 validation in progress. No product acceptance test has run.

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
| 12B target safetensors structure | Passed | 1,334 tensors; file end matches final tensor offset |
| 12B target/assistant tensor contract | Passed | Target embedding 262,144×3,840; assistant pre-projection 1,024×7,680; target embedding sharing is required |
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
| Official exact MTP target metadata | Passed | 12B `b6ed862…` and 31B `1e4d8be…` revisions, sizes, and SHA-256 values pinned |
| Chatterbox Multilingual V3 metadata | Passed | Official HF revision `5bb1f6e…`, source `5de7a54…`, MIT license, Korean support, 3,208,951,924 selected bytes, and primary weight hashes pinned |
| Chatterbox runtime dependency gate | Passed | Package 0.1.7 torch/torchaudio 2.6 pin detected; isolated Blackwell runtime remains uninstalled |
| OpenAI-compatible smoke client static checks | Passed | Python compile and generated 32×32 red PNG decode/pixel validation |
| Runtime/model/GPU config references | Passed | 4 configured models, 6 manifest roles, and 9 runtime IDs cross-validated; unvalidated MTP routes remain disabled |
| Download state isolation | Passed | Explicit cache-side state path; 29,372-byte live transfer and 1/1 resume passed |
| Protocol/tool contract catalog consistency | Passed | 22 events, 21 tools; drift checks and Draft 2020-12 schema validation passed |
| Event payload contract coverage | Passed | All 22 catalog events have closed, bounded Draft 2020-12 payload definitions |
| Observability contracts | Passed | 18 required metrics, histogram p50/p95 coverage, and closed structured-log schema validated |
| Benchmark prompt catalog | Passed | 160 unique Korean cases with required 20/30/20/20/20/20/10/20 category counts |
| Mandatory failure/security test catalog | Passed | All 24 required case IDs have explicit expected outcomes; execution remains `NOT_RUN` |

Exact Q4_0 MTP-target download/runtime test, 31B artifact completion, SGLang,
audio/video, full benchmark, security,
Android, rollback, and product acceptance tests remain `NOT_RUN` or in
progress.
