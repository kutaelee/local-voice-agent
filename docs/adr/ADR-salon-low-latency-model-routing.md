# ADR: Low-latency salon model routing

- Status: proposed; checkpoint benchmark pending
- Date: 2026-07-25

## Context

The salon receptionist needs bounded Korean dialogue and closed-schema action
proposals, while the general Computer-Use agent needs stronger multimodal,
tool-calling, recovery, and review behavior. These workloads do not need to
share one latency/quality point.

The current official Gemma 4 12B W4A16 runtime already measured 34.713 ms
streaming TTFT in a direct warm smoke. Live salon turns have taken 2.5 to
5.2 seconds before final response text under the persona/action harness, but
that includes prompt construction, structured generation, parsing, and domain
validation and must not be presented as raw model TTFT. In the same live path,
Qwen3-TTS has been the larger first-audio cost.

## Decision

Keep Gemma 4 12B as the default general Computer-Use model. Benchmark the
official `google/gemma-4-E4B-it-qat-w4a16-ct` checkpoint next as a dedicated
salon fast route only after its exact revision, hashes, size, and runtime
compatibility are pinned.

Use the following candidate order:

1. Gemma 4 E4B W4A16 for the bounded salon dialogue route.
2. Gemma 4 E2B W4A16 only if E4B still misses the warm latency target.
3. Keep 12B for ambiguous scope, tool-heavy requests, and recovery.
4. Do not prioritize Gemma 4 26B-A4B MoE for this route. Its 3.8B active
   parameter count does not remove the cost of loading and retaining the
   25.2B-parameter checkpoint on one 32 GiB GPU.

No model is promoted from this ADR alone. Promotion requires the same salon
prompt set, action-schema validity, scope refusal quality, Korean naturalness,
warm/cold latency, peak VRAM, and failure recovery comparison.

## Consequences

- The current 12B route remains unchanged until evidence exists.
- E4B can reduce the text-generation share without weakening the general
  agent by routing only the constrained receptionist domain.
- A smaller model that emits invalid actions or repetitive refusals fails the
  gate even when faster.
- TTS optimization remains independent and is measured from final text to
  first audio.

## Official references

- [Gemma 4 overview](https://ai.google.dev/gemma/docs/core)
- [Gemma 4 E4B official model](https://huggingface.co/google/gemma-4-E4B-it)
- [Gemma 4 E4B W4A16 QAT checkpoint](https://huggingface.co/google/gemma-4-E4B-it-qat-w4a16-ct)
- [vLLM supported models](https://docs.vllm.ai/en/stable/models/supported_models/)
