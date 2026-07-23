# Rollback plan

## Source

Each slice is committed independently. Revert a slice with `git revert` of
the relevant commit; never use destructive reset on user work.

## Python runtimes

Each environment is self-contained under the WSL user runtime root. Rollback
means stop its processes, point configuration to the previous locked
environment, health-check it, and only then archive the failed environment.
No global pip state is changed.

## Models

Model downloads are revision-addressed. Configuration references an explicit
revision directory. Rollback changes the active manifest pointer to a
previous validated revision; it does not delete weights automatically.

## Database

Alembic migrations must include a tested downgrade when technically safe.
Before a destructive or non-reversible migration, create a logical dump under
`E:\Data\DB\Dumps` and require Level 3 manual authorization.

## Files and tools

Workspace mutation captures precondition hashes and a backup/evidence record.
Rollback applies the inverse patch only when the current hash still matches
the postcondition. A mismatch stops automatic rollback and requests manual
review.

## External/system changes

No driver, WSL feature, distribution, firewall, registry, system PATH, BIOS,
or partition change is automated. Their rollback must be supplied with the
separate approval request before action.
