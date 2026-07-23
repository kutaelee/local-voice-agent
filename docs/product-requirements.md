# Product requirements

## Goal

Build a local, interruptible voice agent that lets an Android user converse
naturally with a Gemma 4 model and perform explicitly approved, auditable
computer-use actions on the paired Windows PC.

## End-to-end flow

Android microphone → PC VAD → STT → model router → planning/function calling
→ policy and approval → tool executor → result verification → response
generation → sentence-level TTS → Android playback.

## Product boundaries

- Default model: Gemma 4 12B instruction-tuned.
- Escalation model: Gemma 4 31B instruction-tuned.
- Primary runtime candidate: vLLM in WSL2.
- Comparison runtime: SGLang in an independent WSL environment.
- Windows fallback: GGUF runtime, limited to text and recovery diagnostics.
- Client: Kotlin, Jetpack Compose, ViewModel + StateFlow, UDF/MVI-lite, Room.
- Server: Python, FastAPI, WebSocket, Pydantic/JSON Schema, PostgreSQL.
- Network exposure: loopback or explicitly configured private LAN/VPN only.

## Core capabilities

1. Streaming voice conversation with partial transcripts and barge-in.
2. Text/image/audio-capable Gemma 4 routing and structured function calling.
3. Workspace-scoped file, Git, build/test, system, browser, and UI tools.
4. Explicit risk levels, expiring approvals, optimistic locking, and
   idempotency keys.
5. Observable model switching between 12B and 31B with safe recovery.
6. Status adapters for Codex and other CLI coding agents based only on
   process, PTY, log, Git, recent-file, test, heartbeat, and status JSON facts.
7. Audit records and evidence for every tool call, without default raw audio
   or full-conversation retention.

## Acceptance

The 20 acceptance criteria from the project brief remain authoritative. A
criterion is marked passed only when its command, measured result, logs, and
evidence path are recorded in `docs/test-report.md`.
