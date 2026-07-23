# Observability

Defines metrics, structured logs, redaction, and evidence references.

Logs carry timestamp, level, session/request/tool IDs, component, event,
model, runtime, latency, risk level, approval ID, result, error code, and
evidence path. Metrics expose p50 and p95 for voice stages, model generation,
tool execution, model switching, queues, and GPU memory.

Raw audio and full conversation content are disabled by default. Evidence is
stored outside Git under the canonical runtime path and referenced by opaque
IDs. Secrets, pairing tokens, authorization headers, command-line
credentials, and environment values are masked before serialization.
