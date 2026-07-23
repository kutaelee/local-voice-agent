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
  validation and stable hashes; disabled tools are not exposed to the model.

No tool is executed by this slice. PostgreSQL adapters and application use
cases remain follow-up work. The FastAPI composition root currently exposes a
read-only health route and a bearer-token-authenticated WebSocket gateway. It
rejects missing/short tokens, closed-schema violations, session mismatches,
and replayed sequence numbers.

The environment and lock are isolated from model runtimes:

```bash
cd apps/pc-server
export UV_PROJECT_ENVIRONMENT=\
/home/kutae/.local/share/local-voice-agent/runtimes/pc-server/.venv
uv sync --locked --extra test
uv run --locked --extra test pytest
```
