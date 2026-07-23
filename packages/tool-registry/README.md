# Tool registry contracts

Every model-visible tool is a checked-in definition with a closed parameter
object, bounded timeout, explicit risk level, and idempotency policy.

The current definitions are contracts, not an executable registry:

- system observation: CPU, memory, GPU, disk, network, processes, local port
- workspace observation: list/search/recent files, bounded reads, SHA-256
- Git observation: status, diff/stat, log, branch, and show
- `apply_patch`: Level 1 with content hash and idempotency preconditions

Path normalization, workspace containment, reparse-point defense, approval,
execution, and rollback remain executor responsibilities; JSON Schema alone
is not treated as a security boundary.
