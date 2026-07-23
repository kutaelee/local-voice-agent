# Tool registry contracts

Every model-visible tool is a checked-in definition with a closed parameter
object, bounded timeout, explicit risk level, and idempotency policy.

The current definitions are contract seeds, not an executable registry:

- `read_file`: Level 0
- `git_status`: Level 0
- `apply_patch`: Level 1 with content hash and idempotency preconditions

Path normalization, workspace containment, reparse-point defense, approval,
execution, and rollback remain executor responsibilities; JSON Schema alone
is not treated as a security boundary.
