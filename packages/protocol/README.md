# Protocol contracts

`schemas/websocket-message.schema.json` defines the strict versioned envelope.
`event-catalog.json` is the authoritative event-name and direction catalog.

Payload-specific schemas will be added with the service implementation. Audio
chunks are never replayed; final transcripts, approvals, tool terminal events,
model switches, and errors are replayable after reconnect.

Run `scripts/validate-contract-catalog.py` to detect enum/catalog drift.
