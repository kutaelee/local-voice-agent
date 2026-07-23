# Database design

PostgreSQL 18.4 is the authoritative state store. It runs in the existing
Docker Desktop backend from an exact digest, publishes only
`127.0.0.1:55432`, and does not install a Windows service or change PATH,
firewall, or Windows features. Active cluster data belongs only at
`E:\Data\DB\Active\LocalVoiceAgent`; logical dumps belong under
`E:\Data\DB\Dumps`. The generated database password is outside Git at
`E:\Data\LocalVoiceAgent\secrets\postgres-password`.

## Ownership

| Table | Aggregate owner | Stable relational fields | JSONB fields |
|---|---|---|---|
| `sessions` | Conversation | ID, state, version, timestamps | client capabilities |
| `messages` | Conversation | session, role, sequence, interrupted | multimodal references |
| `agent_tasks` | Agent task | session, phase, version, timestamps | progress evidence |
| `tool_executions` | Tool execution | tool, risk, state, version, idempotency key | normalized arguments, result metadata |
| `approval_requests` | Approval | execution, state, expiry, version, digest, precondition version | display summary |
| `tool_execution_events` | Tool execution | execution, sequence, event, timestamp | bounded event payload |
| `model_runtime_events` | Model routing | model, runtime, state, timestamp | resource snapshot |
| `audit_logs` | Audit | actor, action, risk, result, timestamp | redacted metadata |
| `outbox_events` | Integration | topic, aggregate, sequence, published time | event payload |
| `workspaces` | Workspace | ID, root, enabled, version | registered command profiles |

Core states, foreign keys, sequence numbers, risk levels, timestamps, hashes,
and versions are columns. Tool arguments and evidence metadata are JSONB
because their shape varies by registered tool. Secret material, raw audio,
and full credential-bearing command lines are never stored.

## Concurrency invariants

- Every mutable aggregate has `version BIGINT NOT NULL`.
- State changes use `UPDATE ... SET version = version + 1 WHERE id = ? AND
  version = ?`; zero rows means a conflict.
- `tool_executions.idempotency_key` is unique within its session.
- `(aggregate_type, aggregate_id, sequence)` is unique for ordered events.
- An approval stores the exact normalized-argument digest and precondition
  version. Its decision and the matching `WAITING_APPROVAL -> QUEUED` or
  `WAITING_APPROVAL -> CANCELLED` execution transition occur in one
  transaction.
- A dispatch records `QUEUED -> RUNNING` before the isolated Tool Executor is
  called. A restart therefore treats a lingering `RUNNING` row as
  reconciliation/manual-review work, never as safe work to replay.

## Transaction boundaries

1. Planning inserts `PLANNED`, the policy transition, ordered execution events,
   outbox rows, and an approval request when required.
2. Approval response verifies digest, precondition, expiry, and version, then
   updates approval and execution together with audit/outbox records.
3. Execution start performs a CAS `QUEUED -> RUNNING` commit before crossing
   the executor boundary.
4. Receipt verification and terminal success/failure write ordered state
   events, bounded evidence ID/hash metadata, audit, and outbox rows.
5. Rollback is a new state transition with its own preconditions and evidence;
   it never rewrites the original event history.

The transactional outbox is durable but is not yet an external delivery
mechanism; its unpublished count is a health signal. A publisher must be added
before any external subscriber depends on delivery. `LISTEN/NOTIFY` and Redis
remain deferred until measurement shows a need.

## Migration and rollback

SQLAlchemy 2.0 async, asyncpg, and Alembic run in the PC-server environment.
Migrations are forward-only in normal operation. Every schema change includes
a logical backup command, compatibility window, application rollback target,
and explicit data-loss assessment. Destructive down migrations are not
automatic.

The `0001_initial` and `0002_approval_recovery` migrations and async store have
been exercised against PostgreSQL 18.4. Integration tests verify exact
idempotent replay, conflicting-key rejection, stale CAS rejection, a durable
approval-to-queue decision, `RUNNING -> VERIFYING -> SUCCEEDED` execution
ordering, audit/outbox insertion, and recovery through a new database
connection.
