# ADR-0004: Workstation-wide shared model registry

Status: Accepted — 2026-07-25

## Decision

Use `E:\AI\Models\HuggingFace\hub` as the canonical store for immutable
Hugging Face snapshots. A snapshot path is derived only from its exact model
ID and 40-character revision:

`models--<owner>--<repository>\snapshots\<revision>`

Repositories keep manifests and canonical paths, not their own model-weight
copies. Before downloading, tooling checks the shared Hugging Face, Ollama,
and ComfyUI stores for an exact compatible artifact. Byte-identical E: files
may be registered with same-volume hardlinks after full tree validation.

Ollama remains a separate content-addressed format under
`E:\AI\Models\Ollama`. Windows generation uses
`E:\AI\Models\Ollama\generation\models`; the Local Knowledge Portal embedding
daemon uses `E:\AI\Models\Ollama\models`. Independent daemons must never write
the same Ollama model directory.

## Consequences

- Gemma, Qwen TTS, Chatterbox, and faster-whisper snapshots can be shared by
  every repository without another download or allocation of weight bytes.
- Runtime-specific formats such as Safetensors, GGUF, CTranslate2, and Ollama
  blobs may coexist when they are genuinely incompatible; they are not
  treated as duplicates merely because they represent the same base model.
- `E:\Cache\HuggingFace` is disposable transfer cache, while model snapshots
  under `E:\AI\Models` are authoritative.
- GPU model loading and inference still require a `gpuq` reservation; storage
  sharing does not imply runtime concurrency.

## Rollback

Restore the timestamped Ollama settings DB from
`E:\Data\Ollama\ConfigBackups`, or change Ollama's model location back through
its settings UI. Legacy snapshot names are moved only to workstation trash
after canonical path, size, and hardlink validation, so they remain
recoverable for 30 days.
