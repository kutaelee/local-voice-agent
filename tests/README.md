# Tests

Planned layers:

- unit: state machines, policies, schema and path normalization;
- contract: WebSocket events, tool definitions, runtime adapters;
- integration: PostgreSQL/outbox, executor sandbox, runtime APIs;
- security: pairing, traversal, reparse points, idempotency, expiry;
- end-to-end: Android voice, interruption, approval, rollback, evidence.

`required-cases.json` is the checked-in specification for the 24 mandatory
security, timeout, recovery, reconnection, interruption, Git, and
computer-use scenarios in the product requirements.

Catalog presence is not execution. Results remain `NOT_RUN` until a concrete
test command and observed outcome are recorded in `docs/test-report.md`.
