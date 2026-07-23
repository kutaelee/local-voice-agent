# Benchmark catalog

`prompts/catalog.json` expands deterministically to the required 160 Korean
cases:

- general conversation: 20
- single tool: 30
- complex plan: 20
- Git: 20
- browser/Windows UI: 20
- coding-agent status: 20
- failure recovery: 10
- interruption: 20

Validate counts, IDs, formatting, and prompt uniqueness with:

```powershell
.\scripts\benchmark.ps1 -ValidateCatalog
```

The catalog is input only. No quality, latency, accuracy, or completion result
is claimed until each runtime/model/MTP condition produces a raw result with
its exact revision, configuration, hardware state, and evidence reference.

The checked-in raw-results and comparison files intentionally begin with
`NOT_RUN` placeholders. Automation must replace a row only from a completed,
validated run; it must never translate a missing sample or failed launch into
zero or success.
