# ADR: Inference runtime

Status: Proposed pending benchmark

vLLM 0.25.1 is the primary candidate because its stable documentation
explicitly covers Gemma 4 Unified multimodality, the dedicated assistant MTP
path, function calling, structured output, streaming, and an OpenAI-compatible
API. SGLang 0.5.15.post1 is the required comparison candidate. The final
decision prioritizes tool correctness, stability, multimodality, voice
latency, and switch reliability over raw throughput.

The stable vLLM environment remains the MTP-OFF baseline. Gemma 4 Unified MTP
requires a separate environment pinned to upstream fix commit
`b2b8f679d0589f0c956f3e734cc70dab07b27b8a`, because v0.25.1 predates the
fix that excludes MTP from the EAGLE-only embedding-width share guard. This
unreleased build is not promoted unless the exact-pair smoke and the stable
regression suite pass; rollback is a config switch to the untouched stable
environment.
