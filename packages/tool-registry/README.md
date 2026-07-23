# Tool registry contracts

Every model-visible tool is a checked-in definition with a closed parameter
object, bounded timeout, explicit risk level, and idempotency policy.

The current definitions are contracts, not an executable registry:

- system observation: CPU, memory, GPU, disk, network, processes, local port
- workspace observation: list/search/recent files, bounded reads, SHA-256
- Git observation: status, diff/stat, log, branch, and show
- workspace mutation: write, patch, copy, move, create directory, bounded ZIP
  archive creation, and bounded ZIP extraction at Level 1
- deletion: one hash-pinned file or one empty directory at Level 2

Path normalization, workspace containment, reparse-point defense, approval,
execution, and rollback remain executor responsibilities; JSON Schema alone
is not treated as a security boundary.

`write_file.expected_sha256 = null` means the target must not exist. Archive
extraction must reject absolute members, `..` traversal, links/reparse points,
duplicate normalized names, and declared or observed expansion-limit
violations. Recursive directory deletion is intentionally not exposed.
