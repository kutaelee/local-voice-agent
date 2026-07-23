# Tests

Planned layers:

- unit: state machines, policies, schema and path normalization;
- contract: WebSocket events, tool definitions, runtime adapters;
- integration: PostgreSQL/outbox, executor sandbox, runtime APIs;
- security: pairing, traversal, reparse points, idempotency, expiry;
- end-to-end: Android voice, interruption, approval, rollback, evidence.

`required-cases.json` maps all 24 mandatory security, timeout, recovery,
reconnection, interruption, Git, and computer-use scenarios to exact
automated test selectors. Run `scripts/run-required-cases.ps1`; it executes
each case in its registered Windows, WSL, or Android environment and writes a
bounded evidence JSON outside the repository. Simulated or static coverage is
explicitly labeled and does not count as a live hardware failure test.
