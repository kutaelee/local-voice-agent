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

Workspace configuration is a closed schema. Windows drive roots, the user
profile root, wildcards, traversal, the backup-only `D:` drive, and protected
`E:\backup`/`E:\transfer` write roots are rejected. Linux-native workspaces
must be under `/home/<user>/src`, never `/mnt/c` or `/mnt/e`. Registered
command profiles store executable IDs and argv arrays, not shell strings or
environment values.

The implemented read-only executor repeats contract validation at its own
process boundary. It rejects absolute and drive-relative paths, `..`, empty
or dot segments, Windows alternate streams, reserved device names, trailing
spaces/dots, symlinks, junctions, and other reparse points. Before reading a
file it compares the pre-open path, opened handle, and post-open path identity
and re-resolves the workspace boundary. Directory walks report but never
follow blocked links. Windows-native junction tests and WSL symlink tests pass.
This does not authorize writes: the executor is not connected to the server,
the workspace allowlist is empty, and mutation/approval/rollback adapters do
not exist yet.

The checked-in application and pairing schemas permit only loopback server
binding and WSS, require Android Keystore token storage, and keep cleartext,
raw-audio retention, and full-conversation retention disabled. LAN or VPN
binding requires a future explicit configuration and threat review rather
than changing these baseline fields.

## Approval integrity

Approvals bind to the exact tool, normalized arguments, target fingerprint,
workspace, expected change, risk level, expiry, and execution id. Any argument
or precondition change invalidates approval.

## Threat cases

Required tests include invalid tokens, traversal, symlink/reparse bypass,
allowlist escape, concurrent write/hash mismatch, duplicate execution,
timeouts, WebSocket replay, prompt injection in files/pages, malicious tool
arguments, oversized output, and evidence tampering.
