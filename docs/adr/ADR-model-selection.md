# ADR: Model selection

Status: Proposed pending Slice 2 validation

Use Gemma 4 12B IT W4A16 compressed-tensors as the default candidate and
Gemma 4 31B IT W4A16 compressed-tensors as the on-demand candidate. MTP uses
separate Q4_0-unquantized target revisions paired with the same-size official
Q4_0-unquantized assistants in `manifests/models.yaml`; W4A16 targets are not
paired with those assistants. Enable MTP only after the runtime identifies
the Gemma 4 MTP path and quality/tool tests pass. The 31B MTP target also
requires a measured CPU-offload feasibility gate because its weights exceed
32 GB VRAM. Official static memory estimates rule out 31B BF16 on this GPU.
