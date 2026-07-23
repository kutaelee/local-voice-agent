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
