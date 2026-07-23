# Protocol contracts

`schemas/websocket-message.schema.json` defines the strict versioned envelope.
`event-catalog.json` is the authoritative event-name and direction catalog.
`schemas/event-payloads.schema.json` defines a closed payload for every event.

Audio chunks are never replayed; final transcripts, approvals, tool terminal
events, model switches, and errors are replayable after reconnect. JSON audio
chunks are bounded; a binary-frame optimization requires a versioned protocol
extension rather than an undocumented alternate shape.

Cancellation is explicit and idempotent. `operation.cancel.requested` targets
one assistant response, tool execution, agent task, or model switch.
`operation.cancel.result` distinguishes immediate cancellation, accepted but
still-draining cancellation, non-cancellable work, already-terminal work, and
unknown targets. A disconnect alone is never interpreted as authorization to
repeat or cancel an impactful tool.

Run `scripts/validate-contract-catalog.py` to detect enum/catalog drift.
