from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def script(name: str) -> str:
    return (ROOT / "scripts" / name).read_text(encoding="utf-8")


def test_sglang_launcher_keeps_api_key_out_of_argv() -> None:
    start = script("start-sglang.sh")

    assert "--api-key" not in start
    assert "launch-sglang-secure.py" in start
    assert 'unset LVA_SGLANG_API_KEY' in start
    assert "minimum_free_mib=28500" in start
    assert '--cpu-offload-gb "${mtp_cpu_offload_gib}"' in start
    assert "mtp-target-off" in start
    assert "gemma4-12b-mtp-target-off" in start
    assert "gemma4/31b/mtp-target" in start
    assert "output width 8608 is not divisible" in start


def test_vllm_launcher_uses_official_environment_key() -> None:
    serve = script("serve-vllm-smoke.sh")
    start = script("start-vllm.sh")
    start_ps1 = script("start-vllm.ps1")

    assert 'export VLLM_API_KEY="${LVA_VLLM_API_KEY}"' in serve
    assert 'unset LVA_VLLM_API_KEY' in serve
    assert 'args+=(--api-key' not in serve
    assert '--header "Authorization: Bearer' not in start
    assert "free_mib < minimum_free_mib" in start
    assert "minimum_free_mib=22000" in start
    assert "minimum_free_mib=27000" in start
    assert "minimum_free_mib=28500" in start
    assert '31b:on)' in start
    assert "31B MTP is not enabled" in start
    assert "VLLM_SMOKE_CPU_OFFLOAD_GB" in serve
    assert "exact-off)" in serve
    assert 'served_name="${served_name}-mtp-target-off"' in serve
    assert '"${model_size}" == "31b" && "${mtp_mode}" != "off"' in serve
    assert "'exact-off', 'on'" in start_ps1
    assert "12b:exact-off)" in start
    assert '--cpu-offload-gb "${cpu_offload_gb}"' in serve
    assert "integer from 0 to 48" in serve


def test_vllm_stop_validates_owned_model_identity() -> None:
    stop = script("stop-vllm.sh")

    assert '"/gemma4/${expected_model_size}/"' in stop
    assert "refusing to signal" in stop
    assert 'kill -TERM "${pid}"' in stop
    assert "kill -KILL" not in stop


def test_windows_wrappers_bridge_only_variable_names() -> None:
    sglang = script("start-sglang.ps1")
    vllm = script("start-vllm.ps1")
    stop_vllm = script("stop-vllm.ps1")

    assert '"$_/u"' in sglang
    assert '"$_/u"' in vllm
    assert "-ArgumentList" not in sglang
    assert "-ArgumentList" not in vllm
    assert "LVA_VLLM_EXPECTED_MODEL_SIZE/u" in stop_vllm


def test_shared_sglang_benchmark_yields_to_comfyui() -> None:
    shared = script("run-shared-sglang-mtp-benchmark.ps1")

    assert "Get-ComfyUiQueueState" in shared
    assert "Wait-ChildOrYield" in shared
    assert "$Process.WaitForExit()" in shared
    assert "independent health probe failed" in shared
    assert "Test-Path -LiteralPath $evidencePath" in shared
    assert "[ValidateSet('on', 'off')]" in shared
    assert "'12b-exact-mtp-off'" in shared
    assert "'31b-exact-mtp-off'" in shared
    assert '"31b-exact-mtp-on-s$SpeculativeSteps"' in shared
    assert "$benchmarkExitCode = -1" in shared
    assert "'mtp-target-off'" in shared
    assert "Get-CimInstance Win32_Process" in shared
    assert "ComfyUI[\\\\/]main\\.py" in shared
    assert "busy = $processCount -gt 0" in shared
    assert "$queue.busy" in shared
    assert "Stop-OwnedSglang" in shared
    assert "stop-sglang.sh" in shared
    assert "A ComfyUI process appeared before its queue endpoint" in shared
    assert "The shared GPU was not reserved" in shared
    assert "LVA_SGLANG_API_KEY = $apiKey" in shared
    assert "LVA_RUNTIME_API_KEY = $apiKey" in shared
    assert "Bearer " not in shared
    assert "/free" not in shared


def test_31b_mtp_probe_is_bounded_and_yields_to_comfyui() -> None:
    start = script("start-vllm-31b-mtp-probe.sh")
    shared = script("run-shared-vllm-31b-mtp-probe.ps1")

    assert "cpu_offload_gb" in start
    assert "28 to 48 GiB" in start
    assert "MemAvailable" in start
    assert "VLLM_SMOKE_CPU_OFFLOAD_GB" in start
    assert "VLLM_SMOKE_MAX_MODEL_LEN=\"256\"" in start
    assert "VLLM_SMOKE_GPU_MEMORY_UTILIZATION=\"0.90\"" in start
    assert "VLLM_SMOKE_KV_CACHE_MEMORY_BYTES=\"268435456\"" in start
    assert 'serve-vllm-smoke.sh" 31b "${mtp_mode}"' in start
    assert "LVA_VLLM_PROBE_MTP_MODE" in start
    assert "--api-key" not in start
    assert "Get-ComfyUiQueueState" in shared
    assert "Get-FreeGpuMemoryMiB" in shared
    assert "freeMemory -lt 28500" in shared
    assert "Stop-OwnedProbe" in shared
    assert "stop script's 30-second" in shared
    assert "if (-not $pidExists -and -not $healthy)" in shared
    assert "$Process.WaitForExit()" in shared
    assert "independent health probe failed" in shared
    assert "Test-Path -LiteralPath $evidence" in shared
    assert "-ExpectedModelSize 31b" in shared
    assert "No vLLM process was started." in shared
    assert "LVA_VLLM_API_KEY = $apiKey" in shared
    assert "Bearer " not in shared
    assert "/free" not in shared
    assert "[ValidateSet('on', 'off')]" in shared
    assert "[switch]$RunBenchmark" in shared
    assert "31b-exact-mtp-off" in shared
    assert "Functional gate passed; running bounded 31B samples." in shared
    assert "LVA_VLLM_PROBE_MTP_MODE" in shared


def test_shared_vllm_mtp_benchmark_is_functionally_gated_and_yields() -> None:
    shared = script("run-shared-vllm-mtp-benchmark.ps1")

    assert "[ValidateSet('on', 'off')]" in shared
    assert "'exact-off'" in shared
    assert "Get-ComfyUiQueueState" in shared
    assert "Get-FreeGpuMemoryMiB" in shared
    assert "freeMemory -lt 28500" in shared
    assert "Wait-ChildOrYield" in shared
    assert "Stop-OwnedVllm" in shared
    assert "-ExpectedModelSize 12b" in shared
    assert "'Functional gate passed" in shared
    assert "smoke-openai-api.py" in shared
    assert "benchmark.ps1" in shared
    assert "LVA_VLLM_API_KEY = $apiKey" in shared
    assert "LVA_RUNTIME_API_KEY = $apiKey" in shared
    assert "Bearer " not in shared
    assert "/free" not in shared


def test_live_model_switch_is_identity_checked_and_yields_to_comfyui() -> None:
    shared = script("run-shared-live-model-switch.ps1")

    assert "12B -> 31B -> 12B" in shared
    assert "Get-ComfyUiQueueState" in shared
    assert "freeMemory -lt 28500" in shared
    assert "Wait-ChildOrYield" in shared
    assert "Stop-OwnedModel" in shared
    assert "Assert-ModelIdentity" in shared
    assert "/v1/models" in shared
    assert "stopped_after_verified_12b_return" in shared
    assert "No vLLM process was started." in shared
    assert "/free" not in shared
