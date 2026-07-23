# ADR-0003: State store

Status: Accepted and initial migration applied

Use PostgreSQL 18 with SQLAlchemy 2.0 async, asyncpg, and Alembic for durable
conversation, approval, execution, audit, and outbox state. Keep core state in
typed columns and only variable tool/evidence metadata in JSONB. Use
optimistic versions, scoped idempotency keys, and a transactional outbox.

Room is an Android cache, not an authority. Redis is deferred because the
initial deployment is one PC server; add it only for measured multi-worker
queue or pub/sub requirements. PostgreSQL installation must not create a
service, PATH change, firewall rule, or elevated package without explicit
approval.

The selected deployment is the existing Docker Desktop backend using
PostgreSQL 18.4 by exact image digest, a bind mount under the approved database
root, a Docker secret sourced outside Git, and a loopback-only host port.
