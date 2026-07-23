# Tool permission model

| Level | Meaning | Default approval |
|---|---|---|
| 0 | Observation only | Allowed within configured workspace/session |
| 1 | Reversible local change | Session approval may be allowed |
| 2 | Impactful change | Exact per-execution approval required |
| 3 | High-risk or irreversible | Denied unless a separate manual policy exists |

## Representative classification

- Level 0: read/list/search files, Git status/diff/log, system inspection,
  process inspection, browser state, screenshots.
- Level 1: create/modify workspace files, apply patch, formatter, linter,
  tests, builds, registered dev server, temporary files.
- Level 2: delete, package install, process stop, Git commit/push, upload,
  external submission/message, environment-variable change.
- Level 3: force push, destructive reset/clean, bulk deletion, security
  disablement, credential extraction, production deployment, payment, disk or
  database destructive operations, arbitrary elevated command.

Every Level 1+ plan displays targets, normalized arguments, expected changes,
rollback method, and ordered steps. Level 2 approval cannot be cached.

The current executor implements `write_file`, `apply_patch`, and
`rollback_file_change` at Level 1. Each invocation binds an unexpired approval
to the complete normalized-argument SHA-256 and binds the tool-managed
idempotency key to the execution request. Mutation also requires an exact
pre-state hash (or explicit non-existence), while rollback requires the exact
backup ID and current post-state hash. No approval can be reused after an
argument or state change.

## Restricted shell

The restricted shell is absent from the model-visible registry by default. If
enabled for a diagnosed gap, it always requires Level 2 approval and shows the
exact command, working directory, timeout, output cap, and environment
allowlist. Elevation and destructive command families are blocked.
