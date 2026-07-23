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


def test_vllm_launcher_uses_official_environment_key() -> None:
    serve = script("serve-vllm-smoke.sh")
    start = script("start-vllm.sh")

    assert 'export VLLM_API_KEY="${LVA_VLLM_API_KEY}"' in serve
    assert 'unset LVA_VLLM_API_KEY' in serve
    assert 'args+=(--api-key' not in serve
    assert '--header "Authorization: Bearer' not in start
    assert "free_mib < 22000" in start


def test_windows_wrappers_bridge_only_variable_names() -> None:
    sglang = script("start-sglang.ps1")
    vllm = script("start-vllm.ps1")

    assert '"$_/u"' in sglang
    assert '"$_/u"' in vllm
    assert "-ArgumentList" not in sglang
    assert "-ArgumentList" not in vllm
