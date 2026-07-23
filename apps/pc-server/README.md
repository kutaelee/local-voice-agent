# PC server

FastAPI modular-monolith host for REST management and WebSocket session/audio
events. It composes domain packages through ports and adapters.

The initial process contains the API gateway, session manager, model router,
policy/approval orchestration, and observability. GPU workers and the tool
executor run out of process. The server binds to loopback until pairing,
transport protection, rate limiting, and LAN policy are verified.

## Current implementation

The first domain slice lives under `src/local_voice_agent_server` and is
transport- and persistence-neutral:

- explicit `ToolExecution` transitions with optimistic version checks;
- exact argument/precondition-bound, expiring, single-use approvals;
- fail-closed Level 0-3 policy decisions;
- deterministic UTF-8 JSON digests;
- WebSocket envelope construction matching protocol schema version 1.0.
- immutable loading of all 74 tool contracts with definition/argument
  validation and stable hashes; disabled tools are not exposed to the model,
  and server-issued approval/idempotency fields are stripped from model
  function schemas while retained in executor validation contracts.
- a non-executing planner that maps validated Level 0 requests to `QUEUED`,
  Level 1/2 requests to exact approval-bound `WAITING_APPROVAL`, and Level 3
  or disabled tools to a denial without creating an execution aggregate;
  queue activation requires an approved record with the same approval ID,
  tool call, argument digest, precondition version, and execution version.
- a versioned model-runtime lifecycle that cannot skip load/health/drain
  states and requires an error code plus evidence path on failure;
- a 12B/31B router that defaults to 12B, plans exclusive model switches,
  defers 31B for voice/GPU priority, enforces measured modality/context
  capability, and cleans a failed 31B runtime before fallback to 12B;
- an optional registered vLLM process coordinator that executes only fixed
  12B/31B profiles, verifies PID/status/health/API model identity, broadcasts
  model-switch phases, drains capture/response/approval model leases before
  stop, and writes external evidence for every action.

The current composition executes approved plans only through the separately
authenticated Tool Executor and persists the lifecycle in PostgreSQL.
The pure router never starts a process. When explicitly enabled, the separate
runtime coordinator executes the router lifecycle through registered scripts;
live 12B↔31B switching remains gated on an idle shared GPU. The FastAPI
composition root exposes a read-only health route and a
bearer-token-authenticated WebSocket gateway. It rejects
missing/short tokens, closed-schema violations, session mismatches, and
replayed sequence numbers. A reconnect uses the same session UUID and an
`after_sequence` query value. The server retains at most 256 events and 4 MiB
for 120 seconds, rejects concurrent session sockets and expired replay
windows, and suspends pending approvals only during that bounded grace
period. Its incremental outbound emitter can send state and transcript events
before a handler returns. The plain-conversation vLLM
adapter consumes bounded SSE deltas and synthesizes complete sentence units as
they arrive, so first-sentence audio need not wait for the full model answer.
Tool-enabled turns deliberately retain the complete structured-response path
so tool names and arguments are validated before planning or execution.

The environment and lock are isolated from model runtimes:

```bash
cd apps/pc-server
export UV_PROJECT_ENVIRONMENT=\
/home/kutae/.local/share/local-voice-agent/runtimes/pc-server/.venv
uv sync --locked --extra test --extra persistence
uv run --locked --extra test --extra persistence pytest
```
