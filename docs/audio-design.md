# Audio pipeline design

The first production target is interruptible half-duplex. Full duplex is not
required for acceptance and is not enabled until echo and cancellation tests
show it is reliable.

## Capture and transport

Android captures mono PCM S16LE at 16 kHz in bounded frames and sends ordered
chunks over the authenticated WebSocket. Each stream has a UUID and monotonic
chunk index. The server rejects unsupported formats, oversized chunks,
duplicates with different content, and chunks after the stream end.

PCM remains the baseline. Opus is tested with the same utterances and network
conditions before promotion. The comparison records bandwidth, one-way
latency, loss behavior, CPU use, battery impact, and implementation failures.

## VAD

Silero VAD 6.2.1 ONNX on CPU is the initial candidate. It owns:

- speech-start and speech-end decisions;
- minimum speech and silence windows;
- short pause handling;
- continuous monitoring during TTS playback;
- barge-in notification.

Thresholds are configuration, not model-generated arguments. Tests cover
quiet speech, keyboard/fan noise, speaker playback leakage, and 20 repeated
interruptions.

## STT

faster-whisper 1.2.1 runs in an isolated process because its documented CUDA
12/cuDNN 9 stack must not be mixed with CUDA 13 LLM environments.

Two exact candidates are pinned:

- `large-v3-turbo`: GPU quality/latency candidate;
- `small`: CPU fallback and contention candidate.

Selection uses Korean word/character error observations, partial/final
latency, VRAM, CPU load, timeouts, and coexistence with LLM/TTS. Chunked
transcription is not described as true streaming unless incremental state and
revision behavior are measured.

## TTS

Chatterbox Multilingual V3 is the selected Korean quality runtime. Its package
and PyTorch pins are isolated in a Blackwell-compatible environment. The
built-in condition data may be used for testing; no personal or third-party
voice is cloned without explicit authorization and provided reference audio.

The selected V3 revision is now installed in an isolated CUDA 13 runtime.
Reference-voice support is consent gated: a user must confirm voice rights and
local processing before a 3–30 second PCM WAV is accepted. The server stores
profile data below `E:\Data\LocalVoiceAgent\voice-profiles`, stores no clip in
Git or the APK, and passes only the selected canonical path to the
authenticated Unix-socket worker. The worker rejects paths outside that root
and caches active speaker conditioning across speech units. The built-in voice
remains a virtual `default` profile.

Voice controls are bounded to playback rate 0.85–1.25, exaggeration
0.25–1.0, CFG weight 0–1, and temperature 0.5–1.2. Playback rate is applied
on Android with pitch fixed at 1.0; it changes spoken duration but not
synthesis first-audio latency. The initial user-authorized profile uses
exaggeration 0.5, CFG 0.5, and temperature 0.8.

The plain-conversation vLLM adapter consumes bounded UTF-8 SSE deltas. Stable
sentence/meaning boundaries are synthesized as soon as they arrive, without
waiting for the complete model answer. The WebSocket emitter sends text
deltas and the first sentence's audio before later model text is complete,
uses one ordered output-stream ID across segments, and closes a partially
emitted stream with `cancelled` or `error`. Tool-enabled conversations keep
the non-streaming structured-response path so the complete tool name and
arguments can be validated before planning or execution. Physical-device
first-audio timing remains a required measurement.

For streamed plain replies, hard sentence boundaries are always eligible. A
comma, semicolon, or colon becomes an early synthesis boundary only after at
least 36 characters. This reduces first-audio wait without fragmenting short
phrases. It is an orchestration optimization, not native streaming inside
Chatterbox.

## Barge-in sequence

1. Android and PC VAD observe user speech during playback.
2. Android stops playback immediately and drops queued audio.
3. The server marks the response interrupted and stops future TTS segments.
4. A cancellable tool receives cancellation; a non-cancellable tool continues
   and its state is explained.
5. STT processes the new stream and the conversation resumes.

Steps 3-4 use the replayable `operation.cancel.requested` and
`operation.cancel.result` contracts. Repeating the same cancellation
idempotency key returns the prior result and never repeats tool execution.

Each boundary has a timeout and a terminal error event. Raw audio and full
conversation recording are off by default.

## Required measurements

- VAD start/end latency and false triggers;
- STT partial/final latency and Korean accuracy;
- LLM TTFT and sentence-boundary availability;
- TTS first-audio and realtime factor;
- Android-PC network latency;
- interruption-to-silence latency;
- dropped/duplicated/out-of-order audio chunks;
- VRAM peaks for every concurrent combination.
