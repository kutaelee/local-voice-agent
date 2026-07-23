# Status adapters

Normalizes observations from coding agents and ordinary terminals without
assuming private APIs.

Adapter sources:

- process
- terminal/PTY
- log
- Git
- recent files
- test/build
- heartbeat
- optional status JSON

Every field is tagged as `observed`, `inferred`, or `unknown`. Adapters never
invent progress percentages. A missing status file is not an error; it lowers
confidence and leaves unverifiable fields unknown.

`schemas/agent-status-input.schema.json` is the closed optional file contract
that agents may publish. `schemas/normalized-agent-status.schema.json` pairs
that status with per-field provenance. Inferred and unknown fields require an
explanation; evidence references remain IDs rather than caller-controlled
paths.
