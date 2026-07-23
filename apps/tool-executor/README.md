# Tool executor

Separate least-privilege process for validated, approved tool operations.

Execution order:

1. validate the closed JSON Schema;
2. resolve the registered workspace and normalize paths;
3. reject traversal and reparse/symlink escapes;
4. verify risk, approval, idempotency, hash, and version preconditions;
5. capture pre-state and evidence;
6. execute one bounded operation with timeout/output limits;
7. verify postconditions and persist the result;
8. expose rollback only when its preconditions still hold.

There is no model-visible unrestricted shell. Elevation is unsupported.
