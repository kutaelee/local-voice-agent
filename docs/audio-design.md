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

Chatterbox Multilingual V3 is the Korean quality candidate. It is not
installed until its package PyTorch pin is reconciled in a separate
Blackwell-compatible environment. The built-in condition data may be used for
testing; no personal or third-party voice is cloned without explicit
authorization and provided reference audio.

LLM text is segmented at safe sentence/meaning boundaries. TTS begins after
the first stable segment, not after the full answer. Segments carry ordering
and response IDs so interruption can discard every remaining buffer without
mixing a previous response into the next one.

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
