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
contracts and supports thirteen Level 0 filesystem and Git observations plus
approval-bound Level 1 file write, patch, and rollback. It resolves an
explicit workspace before every operation, rejects ambiguous or escaping
paths and link/reparse segments, verifies file identity against pre/post path
state, and bounds traversal, subprocess time, and output. File changes bind
an exact approval, idempotency key, SHA-256 precondition, external backup, and
verified post-state; rollback has its own approval and concurrent-change
guard. Git uses fixed argv with external execution features disabled and
rejects metadata escape mechanisms. Browser and Windows UI adapters now cover
their bounded Level 0/1 subsets. Delete, Git mutation, process, coordinate UI,
external browser submission, and shell adapters remain unavailable.

The current transport boundary is an authenticated HTTP API bound by default
to `127.0.0.1:8790`. In WSL NAT mode the launcher can instead bind only the
detected RFC1918 address of the Windows `vEthernet (WSL ...)` Hyper-V adapter;
the client accepts that address only when the same canonical IP is explicitly
configured. LAN addresses, hostnames, and wildcard binds remain rejected. The
PC server has a hexagonal `ToolExecutionPort` and HTTP adapter that carries the exact execution
ID, idempotency key, argument digest, tool-definition digest, risk level,
approval binding, and expiry. Planner-to-executor read and approved
create/rollback paths have passed process smokes. The conversational model
loop exposes only the sixteen implemented executor tools, rejects malformed,
parallel, or unavailable calls, and runs at most four sequential calls.
Level 0 results return to the model immediately; Level 1 pauses with the exact
approval binding and resumes the same voice turn only after approval. The
WSL-to-Windows process smoke completed a model-selected `read_file` and
persisted metadata-only evidence. The executor revalidates those bindings,
serializes duplicate keys in process, and returns the prior terminal response
without repeating a successful call. Durable
idempotency across process restarts remains a PostgreSQL milestone.

Each attempted execution emits structured JSONL audit events and an atomic,
metadata-only evidence record outside Git. Tool arguments, returned file
content, bearer tokens, and raw secrets are not copied into those records.
Pre-mutation bytes live only in the external runtime backup tree.

Browser automation owns isolated Playwright sessions on a single dedicated
thread. Requests and WebSockets are restricted to explicit loopback hosts,
downloads and submit-capable controls are blocked, and each element action
requires the exact fresh DOM-state fingerprint. Screenshot PNGs are
no-replace evidence artifacts. Windows UI Automation similarly returns opaque
window/element references and requires a fresh bounded tree fingerprint.
Actions are currently restricted to `notepad.exe`; coordinate actions and
cursor injection are unavailable.

Agent status observation uses an optional strict status-file contract plus
process, terminal, and Git adapters. Facts are tagged observed, inferred, or
unknown; command lines are used only for workspace association and never
returned to clients.

## State machines

`ToolExecution`:

`PLANNED → WAITING_APPROVAL → QUEUED → RUNNING → VERIFYING → SUCCEEDED`

Failure states are `FAILED`, `CANCELLED`, `ROLLING_BACK`, and `ROLLED_BACK`.
Every transition uses an integer version for optimistic locking.

`ModelRuntime`:

`UNLOADED → LOADING → HEALTH_CHECKING → READY → DRAINING → UNLOADING`

Failures transition to `FAILED`, then attempt a recorded fallback. Switching
to 31B first persists conversation and tool state and blocks new executions.
The current pure planner emits ordered switch actions but does not control
runtime processes. It rejects concurrent READY models, defers while any
switch is active, and requires failed-31B cleanup before routing fallback
work to 12B.

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

The current voice composition uses three authenticated mode-0600 Unix-socket
workers: Silero VAD 6.2.1 on CPU ONNX, faster-whisper on its isolated CUDA 12
stack, and Chatterbox V3 on its isolated CUDA 13 stack. VAD consumes ordered
PCM chunks and returns a server endpoint decision; Android then stops capture
and sends the terminal input event. Voice-response completion runs as a
background task so a monotonic cancellation event can be processed while
STT, model inference, or TTS is pending. Cancellation IDs are bounded and
deduplicated per session; later output from a cancelled task is discarded.
