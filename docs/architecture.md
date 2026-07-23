# Architecture

## Style

Use a modular monolith with light DDD and hexagonal ports/adapters. DDD is
reserved for rule-heavy domains: tool policy, approval, execution state,
rollback, model runtime state, and agent task state.

## Modules

| Domain module | Responsibility |
|---|---|
| Conversation | Session, messages, interruption, streaming lifecycle |
| ModelRouting | 12B/31B selection, runtime health, switch state |
| ToolExecution | Plan, idempotency, execution, verification, rollback |
| Approval | Expiring approval requests and responses |
| Workspace | Allowlisted roots, project profiles, hash preconditions |
| AgentStatus | Fact adapters and confidence labels |
| Observability | Structured logs, metrics, evidence metadata |

## Process boundaries

- `pc-server`: API gateway, session manager, audio orchestration, model router,
  policy/approval, persistence, and observability.
- `tool-executor`: separate low-privilege process with a fixed registry.
- GPU workers: separate runtime processes for vLLM/SGLang, STT, and TTS.
- Android client: only communicates with the API gateway.

The current Tool Executor slice independently reloads the checked-in
contracts and supports only six Level 0 filesystem reads. It resolves an
explicit workspace before every operation, rejects ambiguous or escaping
paths and link/reparse segments, verifies the opened file identity against
pre/post path state, and bounds traversal and output. It has no transport
connection to `pc-server` yet; write, delete, Git, process, browser, UI, and
shell adapters remain unavailable.

## State machines

`ToolExecution`:

`PLANNED → WAITING_APPROVAL → QUEUED → RUNNING → VERIFYING → SUCCEEDED`

Failure states are `FAILED`, `CANCELLED`, `ROLLING_BACK`, and `ROLLED_BACK`.
Every transition uses an integer version for optimistic locking.

`ModelRuntime`:

`UNLOADED → LOADING → VERIFYING → READY → DRAINING → UNLOADING`

Failures transition to `FAILED`, then attempt a recorded fallback. Switching
to 31B first persists conversation and tool state and blocks new executions.

## Persistence

PostgreSQL 18 stores sessions, messages, agent tasks, tool executions,
approvals, transition events, runtime events, audit logs, workspaces, and a
transactional outbox. Flexible tool arguments and evidence metadata use
JSONB; lifecycle fields remain typed columns.

SQLAlchemy 2.0.51 is selected for the first implementation because 2.1 is
still beta as of 2026-07-23. Alembic 1.18.5 and asyncpg are compatible with
PostgreSQL 18. Redis is deferred.

Aggregate ownership, compare-and-swap transitions, idempotency constraints,
transaction boundaries, and migration rollback are detailed in
[`database-design.md`](database-design.md).

## Protocol

WebSocket envelopes contain `schema_version`, `type`, `session_id`,
`request_id`, `sequence`, and `timestamp`. Binary audio frames are correlated
with JSON control events. PCM is the baseline; Opus becomes the default only
after measured LAN latency and complexity comparisons.

Android UDF state, audio interruption, pairing, reconnection, and device-test
boundaries are detailed in [`android-design.md`](android-design.md).
VAD, STT/TTS isolation, streaming boundaries, and barge-in measurements are
detailed in [`audio-design.md`](audio-design.md).
