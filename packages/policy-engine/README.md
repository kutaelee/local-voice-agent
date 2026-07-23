# Policy engine

Maps a validated tool request and current scope to one of:

- `ALLOW`
- `REQUIRE_APPROVAL`
- `DENY`

Inputs include tool definition, normalized arguments, workspace policy,
session grants, risk level, resource state, and approval state. Outputs are
pure decisions with reason codes; this package never reads files, launches
processes, or calls tools.

Level 0 is allowed only inside configured scope. Level 1 requires a valid
session grant or approval. Level 2 always requires an exact unexpired
approval. Level 3 is denied unless a separate manual policy is explicitly
configured.
