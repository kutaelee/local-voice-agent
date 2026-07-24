# ADR: Inference runtime

Status: Accepted

vLLM 0.25.1 is the primary candidate because its stable documentation
explicitly covers Gemma 4 Unified multimodality, the dedicated assistant MTP
path, function calling, structured output, streaming, and an OpenAI-compatible
API. SGLang 0.5.15.post1 was the required comparison candidate. Stable vLLM
is selected for the 12B default and 31B on-demand production profiles; native
llama.cpp is the WSL-failure diagnostic fallback. The decision prioritizes
tool correctness, stability, multimodality, voice latency, and switch
reliability over raw throughput.

The stable vLLM environment remains the MTP-OFF baseline. Gemma 4 Unified MTP
requires a separate environment pinned to upstream fix commit
`b2b8f679d0589f0c956f3e734cc70dab07b27b8a`, because v0.25.1 predates the
fix that excludes MTP from the EAGLE-only embedding-width share guard. This
unreleased build passed isolated exact-pair measurements but is not promoted:
the validated exact targets are text-only and CPU-offloaded 31B is
operationally too slow. SGLang remains installed for reproducible 12B
comparison; its 31B W4A16 Marlin repack failed and exact-target first request
timed out. Rollback is a config switch to the untouched stable environment.
