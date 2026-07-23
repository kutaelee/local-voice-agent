# Android client design

Status: Slice 8 scaffold builds successfully for Android 17 / API 37 with the
isolated command-line SDK. Android Studio is not installed. WebSocket, real
audio capture/playback, Room, Bluetooth routing, and device QA remain later
slices.

## Application structure

- `app`: Compose navigation, dependency wiring, foreground service entry.
- `core-protocol`: versioned WebSocket envelopes and payload models.
- `core-network`: pairing, authenticated socket, reconnect and acknowledgments.
- `core-audio`: capture, focus, routing, playback buffer, barge-in.
- `data-local`: Room cache and Android Keystore token reference.
- `feature-pairing`: server URL, pairing token, connectivity test.
- `feature-conversation`: transcript, assistant state, push-to-interrupt.
- `feature-approval`: exact arguments, impact, rollback, expiry, approve/reject.
- `feature-history`: completed/failed executions and evidence references.
- `feature-diagnostics`: network, server, runtime, model, audio route.

This remains one Android application module initially; package boundaries do
not require a large Gradle multi-module build until measurements justify it.

## State flow

`UiEvent -> ViewModel -> UseCase -> Repository/WebSocket -> immutable UiState`

Each screen exposes `StateFlow<UiState>`. One-time navigation, permission
launches, and user messages use `SharedFlow<UiEffect>`. `SavedStateHandle`
restores navigation/session identifiers, not tokens or audio. Room caches
recent final messages, last execution states, and unresolved approval
requests; the PC remains authoritative.

Assistant states mirror the protocol exactly: connecting, listening,
recognizing, thinking, selecting tool, waiting approval, executing, verifying,
synthesizing, speaking, interrupted, switching model, reconnecting, and
error. Unknown future states render a safe generic status rather than
crashing.

## Audio and interruption

The first implementation uses mono PCM S16LE at 16 kHz because it is simple
to validate. Opus is promoted only after the same Wi-Fi test set measures
bandwidth, latency, battery, packet loss behavior, and implementation
complexity.

The microphone foreground service owns capture and audio-route observation.
Playback requests transient audio focus and supports speaker, earpiece, and
Bluetooth routes. While TTS plays, VAD continues on capture input. Barge-in:

1. stop the local audio track;
2. discard queued assistant audio;
3. send the input-start event with interruption context;
4. mark the previous response interrupted;
5. display whether an active tool can be cancelled;
6. continue with the new utterance.

The app does not claim acoustic echo cancellation quality until device tests
measure it.

## Pairing and reconnect

The pairing token is stored through Android Keystore-backed encrypted
storage, never Room or logs. The app connects only to the API gateway and
rejects cleartext by default. LAN enablement waits for the Android 17 local
network permission path and PC transport policy.

The client tracks the last accepted server sequence per session. On reconnect
it resumes from that sequence; only catalog events marked replayable may be
resent. Audio chunks and text deltas are discarded. Expired approvals render
expired and cannot be resubmitted.

## Required device matrix

- foreground/background transition;
- rotation and process recreation;
- screen off and power saving;
- Wi-Fi disconnect/reconnect;
- speaker, earpiece, wired, and Bluetooth routes;
- microphone denial and later grant;
- TTS barge-in during silence, speech, tool run, and model switch;
- malformed/expired pairing token;
- Android 17 local-network permission denial.
