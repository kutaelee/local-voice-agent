# Tool registry contracts

Every model-visible tool is a checked-in definition with a closed parameter
object, bounded timeout, explicit risk level, and idempotency policy.

The current definitions are validated runtime contracts, not tool
implementations:

- system observation: CPU, memory, GPU, disk, network, processes, local port
- workspace observation: list/search/recent files, bounded reads, SHA-256
- Git observation: status, diff/stat, log, branch, show, and bounded blame
- Git mutation: local branch/patch at Level 1; commit, non-force push,
  fast-forward merge, and clean-worktree rebase at Level 2; hard reset and
  clean at deny-by-default Level 3
- workspace mutation: write, patch, copy, move, create directory, bounded ZIP
  archive creation, and bounded ZIP extraction at Level 1
- deletion: one hash-pinned file or one empty directory at Level 2
- development: registered test, lint, format, build, and loopback-only
  development-server profiles; logs are retrieved by evidence ID
- system: service observation, registered non-elevated process start, and
  identity-bound Level 2 process stop
- restricted shell: exact allowlisted executable/arguments/environment at
  Level 2, while remaining disabled in the model-visible registry by default
- browser: isolated session lifecycle, bounded DOM/accessibility/evidence
  reads, and freshness-bound interaction; external form submission is a
  separate Level 2 tool
- Windows UI: accessibility-first observation and interaction at Levels 0-1;
  coordinate click/drag is a fresh-screenshot-bound Level 2 fallback

Path normalization, workspace containment, reparse-point defense, approval,
execution, and rollback remain executor responsibilities; JSON Schema alone
is not treated as a security boundary.

The PC-server loader derives model-visible function schemas by removing the
server-managed `approval_id` and `idempotency_key` properties. The server
issues those values; the model never invents them. Immediately before
execution, fully composed arguments must be validated again against the
original executor contract.

`write_file.expected_sha256 = null` means the target must not exist. Archive
extraction must reject absolute members, `..` traversal, links/reparse points,
duplicate normalized names, and declared or observed expansion-limit
violations. Recursive directory deletion is intentionally not exposed.

Development tools accept a `profile_id`, never a command string or arbitrary
flags. `stop_dev_server` accepts only an executor-issued process handle, so it
cannot be used as a general process-kill primitive.

Git mutation contracts bind exact commit and worktree/index fingerprints.
`git_push.force` is always false, merge is fast-forward-only, and clean cannot
include ignored files. Level 3 definitions exist for explicit policy denial
and auditability, not to make destructive operations normally available.

Process termination binds the executor handle, PID, and observed start time to
defend against PID reuse. The restricted shell has no raw shell command
string, elevation path, or caller-supplied environment variables.

Browser click, type, and select operations bind a fresh page-state
fingerprint. They cannot submit; `browser_submit` separately binds the reviewed
page and redacted payload fingerprints to an exact approval. Downloads remain
executor-tracked evidence and are never opened automatically.

UI text entry cannot submit, and the key tool omits Enter and destructive
keys. Coordinate actions bind screenshot evidence ID, SHA-256, and screen
dimensions so a resolution or display-layout change invalidates approval.
