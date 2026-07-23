# ADR: Model selection

Status: Proposed pending Slice 2 validation

Use Gemma 4 12B IT W4A16 compressed-tensors as the default candidate and
Gemma 4 31B IT W4A16 compressed-tensors as the on-demand candidate. Use only
the exact QAT assistant revisions in `manifests/models.yaml`, and enable MTP
only after the runtime identifies the Gemma 4 MTP path and quality/tool tests
pass. Official static memory estimates rule out 31B BF16 on 32 GB VRAM.
