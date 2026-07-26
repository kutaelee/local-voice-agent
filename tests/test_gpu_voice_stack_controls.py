from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(name: str) -> str:
    return (ROOT / "scripts" / name).read_text(encoding="utf-8")


def test_gpu_voice_start_is_fixed_idempotent_and_scheduler_managed() -> None:
    source = read("start-gpu-voice-stack.ps1")

    assert "C:\\Dev\\Tools\\CodexCLI\\gpuq.cmd" in source
    assert "[ValidateSet('e4b', '12b')]" in source
    assert "$requestedVramMiB = if ($ModelSize -eq 'e4b') { 19000 } else { 25000 }" in source
    assert "--vram $requestedVramMiB" in source
    assert 'env "LVA_VOICE_LLM_SIZE=$ModelSize"' in source
    assert "--workload local-voice-agent-interactive-qa" in source
    assert "run-gpu-voice-stack.sh" in source
    assert "$scheduler.jobs.queued" in source
    assert "$scheduler.jobs.active" in source
    assert "Write-Output $registeredJobId.ToString()" in source
    assert "Invoke-Expression" not in source


def test_gpu_voice_supervisor_uses_external_streaming_tts() -> None:
    source = read("run-gpu-voice-stack.sh")

    assert "LVA_SKIP_TTS_WORKER=1" in source
    assert "run-vllm-omni-tts.sh" in source
    assert "vllm-omni-tts.pid" in source
    assert "for worker in vad stt; do" in source
    assert "Registered vLLM-Omni TTS health check failed." in source


def test_gpu_voice_stop_is_identity_bound_and_cancels_queued_work() -> None:
    source = read("stop-gpu-voice-stack.ps1")

    assert 'pgrep -f "^bash $supervisor$"' in source
    assert '$command.Trim() -ne "bash $supervisor"' in source
    assert "& $gpuq cancel $jobId.ToString()" in source
    assert "GPU voice reservation identity is ambiguous." in source
    assert "kill -TERM $pidValue" in source
    assert "Set-RegisteredState -State 'stopped'" in source
    assert "Invoke-Expression" not in source
