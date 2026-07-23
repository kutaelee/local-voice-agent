# Security model

## Trust boundaries

1. Android client and local storage.
2. Network transport and pairing endpoint.
3. PC API gateway and authenticated session.
4. Model output, which is always untrusted data.
5. Policy/approval engine.
6. Low-privilege tool executor.
7. Workspaces, Git repositories, browser, and Windows UI.
8. PostgreSQL, audit log, and evidence store.

## Required controls

- Bind to `127.0.0.1` by default; LAN/VPN binding is an explicit
  configuration change.
- Pair with a one-time token, rotate credentials, and store Android secrets in
  Android Keystore.
- Authenticate WebSocket and REST requests; expire idle sessions.
- Validate every event against a versioned schema and enforce monotonic
  sequence numbers.
- Treat model-generated tool names and arguments as hostile input.
- Normalize paths, resolve final targets, reject traversal, and validate
  symbolic links/reparse points against workspace roots.
- Use a fixed tool registry and registered project commands. Do not expose a
  general shell by default.
- Apply rate limits, timeouts, output limits, concurrency limits, and
  idempotency keys.
- Mask tokens, credentials, environment secrets, and likely private keys from
  logs and evidence.
- Store no raw audio or full conversation by default.
- Never make the tool executor an administrator.

## Approval integrity

Approvals bind to the exact tool, normalized arguments, target fingerprint,
workspace, expected change, risk level, expiry, and execution id. Any argument
or precondition change invalidates approval.

## Threat cases

Required tests include invalid tokens, traversal, symlink/reparse bypass,
allowlist escape, concurrent write/hash mismatch, duplicate execution,
timeouts, WebSocket replay, prompt injection in files/pages, malicious tool
arguments, oversized output, and evidence tampering.
