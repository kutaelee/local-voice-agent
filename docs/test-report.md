# Test report

Status: Slice 0 only. No product acceptance test has run.

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
| 12B parallel range transfer | Passed | 153/153 chunks; 1,227.345 s wall time including restart = 7.98 MiB/s |
| 12B target SHA-256 | Passed | `60b6e3989502969d8ae04185d72ecbbc7db63978d5af747a493d53895aa6bfa3` |
| 12B MTP assistant SHA-256 | Passed | `67f1420cf24aa5065089aaed175223f7c245ccfda16111b6c56765afd7280db6` |
| 12B target safetensors structure | Passed | 1,334 tensors; file end matches final tensor offset |
| 12B MTP pair offline structure | Passed | Dedicated unified assistant; vocab, context, and backbone width match target |
| Identical-hash mirror resume | Passed | vLLM wheel reused 1/4 ranges after GitHub-to-PyPI URL change |
| vLLM wheel SHA-256 | Passed | `16fc7a28df1576eb6f7ca0455026551b8f9adb674c19c66059359ef3e964bd1e` |
| vLLM isolated dependency install | Passed | vLLM 0.25.1, Python 3.12.13, torch 2.11.0+cu130; 192-package compatibility check |
| vLLM RTX 5090 CUDA smoke | Passed | Compute capability 12.0; CUDA matrix multiplication returned expected 1024.0 |
| vLLM CLI capability inspection | Passed | `gemma4` tool parser and speculative/chat/model/GPU configuration flags present |
| Download state isolation | Passed | Explicit cache-side state path; 29,372-byte live transfer and 1/1 resume passed |
| Protocol/tool contract catalog consistency | Passed | 22 events, 3 seed tools; drift checks and Draft 2020-12 schema validation passed |
| Benchmark prompt catalog | Passed | 160 unique Korean cases with required 20/30/20/20/20/20/10/20 category counts |
| Mandatory failure/security test catalog | Passed | All 24 required case IDs have explicit expected outcomes; execution remains `NOT_RUN` |

Model artifact download and SHA-256 validation are in progress. All functional,
security, Android, model-loading, MTP, benchmark, and rollback tests are
`NOT_RUN`.
