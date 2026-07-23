# Database design

PostgreSQL 18 is the intended authoritative state store. Installation remains
approval-gated because no existing server or client is present and a Windows
service/installer may require elevation. Active cluster data belongs only at
`E:\Data\DB\Active\LocalVoiceAgent`; logical dumps belong under
`E:\Data\DB\Dumps`.

## Ownership

| Table | Aggregate owner | Stable relational fields | JSONB fields |
|---|---|---|---|
| `sessions` | Conversation | ID, state, version, timestamps | client capabilities |
| `messages` | Conversation | session, role, sequence, interrupted | multimodal references |
| `agent_tasks` | Agent task | session, phase, version, timestamps | progress evidence |
| `tool_executions` | Tool execution | tool, risk, state, version, idempotency key | normalized arguments, result metadata |
| `approval_requests` | Approval | execution, state, expiry, version, digest | display summary |
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
- An approval stores a digest of normalized tool name, arguments, workspace,
  risk, and preconditions. Consumption is a compare-and-swap transition.
- Level 2 approval is one-shot. `APPROVED -> CONSUMED` and execution
  `QUEUED -> RUNNING` occur in one transaction.

## Transaction boundaries

1. Planning inserts the tool execution, first state event, and outbox row.
2. Approval response changes approval state and emits its outbox event.
3. Execution start consumes approval, checks versions/idempotency, records
   pre-state, and transitions the execution.
4. Completion or failure writes bounded result metadata, the terminal event,
   audit row, and outbox row.
5. Rollback is a new state transition with its own preconditions and evidence;
   it never rewrites the original event history.

The transactional outbox is polled by one in-process publisher initially.
`LISTEN/NOTIFY` and Redis are deferred until measurement shows a need.

## Migration and rollback

SQLAlchemy 2.0 async, asyncpg, and Alembic run in the PC-server environment.
Migrations are forward-only in normal operation. Every schema change includes
a logical backup command, compatibility window, application rollback target,
and explicit data-loss assessment. Destructive down migrations are not
automatic.
