# Approval engine

Owns approval lifecycle and binding, not tool execution.

State flow:

`DRAFTED -> PENDING -> APPROVED | REJECTED | EXPIRED | CANCELLED`

An approval becomes `CONSUMED` exactly once when the executor accepts the
matching idempotency key, normalized argument digest, workspace, risk level,
and precondition version. Level 2 approvals are per execution and cannot be
cached. Any argument or precondition change invalidates the approval.

The application port returns a decision plus the user-visible tool, target,
exact arguments, expected changes, impact scope, rollback, and ordered steps.
No credential value may appear in approval payloads or logs.
