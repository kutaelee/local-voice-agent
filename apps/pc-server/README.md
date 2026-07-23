# PC server

FastAPI modular-monolith host for REST management and WebSocket session/audio
events. It composes domain packages through ports and adapters.

The initial process contains the API gateway, session manager, model router,
policy/approval orchestration, and observability. GPU workers and the tool
executor run out of process. The server binds to loopback until pairing,
transport protection, rate limiting, and LAN policy are verified.
