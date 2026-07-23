# ADR: Inference runtime

Status: Proposed pending benchmark

vLLM 0.25.1 is the primary candidate because its stable documentation
explicitly covers Gemma 4 Unified multimodality, the dedicated assistant MTP
path, function calling, structured output, streaming, and an OpenAI-compatible
API. SGLang 0.5.15.post1 is the required comparison candidate. The final
decision prioritizes tool correctness, stability, multimodality, voice
latency, and switch reliability over raw throughput.
