# ADR-0005: Serve Qwen3-TTS through isolated vLLM-Omni

- Status: accepted for final listening QA
- Date: 2026-07-26

## Context

The retained Qwen wrapper returns a complete waveform. Warm Korean salon
sentences therefore reached first audio only after several seconds even when
their realtime factor was near one. The workstation must also share one RTX
5090 through `gpuq`, so reserving most of 32 GiB for a 0.6B TTS checkpoint is
not acceptable without evidence.

Official vLLM-Omni 0.24.0 supports Qwen3-TTS 0.6B Base, persistent reference
voices, online Speech API serving, and raw PCM streaming. The proposed 0.24.1
package was not present in the official stable package channel at the
decision date.

## Decision

Use a separately locked WSL vLLM-Omni 0.24.0 environment as the primary
streaming candidate. Reuse the immutable model snapshot in the workstation
Hugging Face store and keep prepared speaker data under the service cache.
Bind the Speech API to `127.0.0.1:46329` and launch it only through `gpuq`.

Use 12% GPU memory utilization for each of its two same-GPU stages and cap
sequence concurrency at four. Stream raw 24 kHz PCM into the existing ordered
WebSocket audio events. Keep only the release-fade tail until synthesis ends;
do not buffer the complete utterance.

The retained authenticated Unix-socket Qwen worker remains the rollback
runtime. CosyVoice3 comparison is deferred until this candidate passes the
objective reliability gate and subjective Korean listening QA.

## Evidence and gates

Warm concurrency-one TTFA was 64/68 ms p50/p95 and warm concurrency-four
TTFA was 179/210 ms. The whole-GPU peak was 14,888 MiB. A corrected
concurrency-one run then completed 1,000/1,000 requests with TTFA p50/p95
61/67 ms, PCM16 alignment, and zero adjacent duplicate chunks. The objective
runtime gate is passed. Browser scheduled-onset and subjective user listening
QA remain the final product gates. Full measurements and evidence hashes are
in `docs/performance-report.md`.

## Consequences

- The first request after restart compiles kernels and cannot be counted as a
  warm result; the service must warm before accepting a call.
- Text-to-first-PCM and PCM-to-playback are measured separately.
- Profile selection must reuse or prepare the matching consented speaker
  cache; it must not silently fall back to another voice.
- Rollback stops only the registered vLLM-Omni reservation and restarts the
  gateway without `LVA_TTS_ADAPTER=vllm-omni`.
