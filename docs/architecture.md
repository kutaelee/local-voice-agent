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
contracts and supports bounded filesystem, Git, browser, Windows UI, and
Windows system observations plus approval-bound Level 1 file write, patch,
and rollback. It resolves an
explicit workspace before every operation, rejects ambiguous or escaping
paths and link/reparse segments, verifies file identity against pre/post path
state, and bounds traversal, subprocess time, and output. File changes bind
an exact approval, idempotency key, SHA-256 precondition, external backup, and
verified post-state; rollback has its own approval and concurrent-change
guard. Git uses fixed argv with external execution features disabled and
rejects metadata escape mechanisms. Browser and Windows UI adapters now cover
their bounded Level 0/1 subsets. Read-only CPU, memory, GPU, disk, network,
process, service, and local-port adapters use only fixed code-owned queries
and mask opt-in command lines. Delete, Git mutation, process mutation, coordinate UI,
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
loop exposes only the 47 implemented executor tools, rejects malformed,
parallel, or unavailable calls, and runs at most four sequential calls.
Level 0 results return to the model immediately; Level 1 pauses with the exact
approval binding and resumes the same voice turn only after approval. The
WSL-to-Windows process smoke completed a model-selected `read_file` and
persisted metadata-only evidence. The executor revalidates those bindings,
serializes duplicate keys in process, and returns the prior terminal response
without repeating a successful call. The PostgreSQL adapter durably recovers
exact idempotent tool records and rejects stale versions across new
connections. When tools are enabled the PC server now requires
`LVA_DATABASE_URL`, creates the authenticated session on WebSocket acceptance,
and fails closed if that durable session cannot be created. Planning writes
`PLANNED` and its first policy transition together; an approval decision
atomically updates both the approval and its execution; and a Tool Executor
dispatch occurs only after `RUNNING` is committed. Receipt verification and
terminal state are then written as separate ordered events with bounded
evidence metadata. A restarted server must reconcile a leftover `RUNNING`
record from executor evidence before any manual retry; it never blindly
replays a side effect. Cancelling a pending approval durably performs the
same exact reject-and-`CANCELLED` transition before the voice turn drops its
in-memory approval reference.

Registered development profiles are an additional Level 1 boundary. The model
may select only a profile ID from the allowlisted workspace configuration; it
cannot supply an executable, shell fragment, working directory, environment,
or flags. The first profile invokes the repository validation suite through a
fixed WSL argv, stores a bounded redacted log outside Git, and exposes it only
through its workspace-bound evidence UUID.

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
The pure planner emits ordered switch actions but does not control runtime
processes. It rejects concurrent READY models, defers while any switch is
active, and requires failed-31B cleanup before routing fallback work to 12B.

An optional runtime coordinator executes only the closed 12B/31B vLLM
profiles. It serializes transitions, drains and stops the exact registered
source process, starts the target, verifies the status PID plus `/health` and
`/v1/models`, and marks READY only after those checks. Every
start/health/stop action writes external evidence. A 31B load or health
failure is recorded, the failed owned process is cleaned, and 12B is restored;
cleanup failure prevents the fallback load. Authenticated REST requests start
the operation and connected WebSocket sessions receive versioned
`model.switch.*` phase events. A shared activity barrier rejects no active
turn: it stops admission of new turns, waits for capture, response generation,
and approval continuation to drain, then permits the registered stop. A
bounded drain timeout leaves the current runtime untouched. The live
shared-GPU switch test remains gated on an idle ComfyUI queue.

## Persistence

PostgreSQL 18 stores sessions, messages, agent tasks, tool executions,
approvals, transition events, runtime events, audit logs, workspaces, and a
transactional outbox. Flexible tool arguments and evidence metadata use
JSONB; lifecycle fields remain typed columns.

SQLAlchemy 2.0.51 is selected for the first implementation because 2.1 is
still beta as of 2026-07-23. Alembic 1.18.5 and asyncpg are compatible with
PostgreSQL 18. The exact PostgreSQL 18.4 container is loopback-only and keeps
its data and generated secret outside Git. Redis is deferred.

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
stack, and Qwen3-TTS 1.7B Base on its isolated CUDA 13 stack. Qwen reference
audio and exact transcripts stay in external application data; a bounded
four-entry prompt cache supports sentence-level neutral/happy/dark/advert
tone changes. Chatterbox V3 remains an isolated rollback fallback. VAD consumes ordered
PCM chunks and returns a server endpoint decision; Android then stops capture
and sends the terminal input event. Voice-response completion runs as a
background task so a monotonic cancellation event can be processed while
STT, model inference, or TTS is pending. Cancellation IDs are bounded and
deduplicated per session; later output from a cancelled task is discarded.
The gateway also accepts emitted events before the handler returns. For plain
conversation, the vLLM adapter consumes SSE text deltas and synthesizes each
complete sentence unit before the remaining answer is available. It does not
split at commas because independent generations produced audible word-boundary
discontinuities. Tool-enabled
turns keep the full structured response so the policy path never executes a
partial tool call. Chunk indexes remain monotonic across the single output
stream; cancellation and TTS failure explicitly terminate an already-open
stream.
