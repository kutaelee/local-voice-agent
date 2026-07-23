# Protocol contracts

`schemas/websocket-message.schema.json` defines the strict versioned envelope.
`event-catalog.json` is the authoritative event-name and direction catalog.
`schemas/event-payloads.schema.json` defines a closed payload for every event.

Audio chunks are never replayed; final transcripts, approvals, tool terminal
events, model switches, and errors are replayable after reconnect. JSON audio
chunks are bounded; a binary-frame optimization requires a versioned protocol
extension rather than an undocumented alternate shape.

Run `scripts/validate-contract-catalog.py` to detect enum/catalog drift.
