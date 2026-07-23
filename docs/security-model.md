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
  configuration change and requires TLS plus a private-address allowlist.
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

The implemented executor repeats contract validation at its own process
boundary. It rejects absolute and drive-relative paths, `..`, empty
or dot segments, Windows alternate streams, reserved device names, trailing
spaces/dots, symlinks, junctions, and other reparse points. Before reading a
file it compares the pre-open path, opened handle, and post-open path identity
and re-resolves the workspace boundary. Directory walks report but never
follow blocked links. Read-only Git commands use an absolute executable and
argv without a shell, literal pathspecs, commit-ID resolution, a minimal
environment, timeouts, and temporary-file output bounds. Optional locks,
prompts, pagers, hooks, fsmonitor, external diff, and textconv are disabled.
The executor rejects `.git` links/reparse points, linked worktrees, alternate
object stores, and config includes before invoking Git. Windows-native
junction tests and WSL symlink tests pass.

The checked-in allowlist grants read-write access only to this public
repository. Level 1 file changes still fail closed without a canonical
approval UUID, exact normalized-argument digest, unexpired approval, matching
idempotency key, and SHA-256 precondition. Writes and single-file patches use
bounded UTF-8 input and atomic replacement. Pre-state backups and metadata
are stored outside the worktree under the runtime backup root. Rollback is a
separate approved operation and requires the exact backup ID, workspace,
relative path, and current post-change hash; a concurrent change invalidates
it. Delete, Git mutation, process, coordinate UI, external browser
submission, and shell adapters remain unimplemented.

The Playwright adapter creates isolated sessions and routes only explicit
loopback HTTP(S); external requests and WebSockets, downloads, submit controls,
and stale element references are blocked. Windows UI Automation observations
are bounded by depth/node count. Element actions require a current tree
fingerprint and are restricted to the executable allowlist, currently
`notepad.exe`; coordinate input is disabled. Both screenshot paths write
UUID-addressed no-replace PNG evidence outside Git.

The implemented IPC boundary accepts closed-schema Level 0 and approved Level
1 requests on a launcher-enforced loopback address by default. NAT-mode WSL
may explicitly select the single RFC1918 address of the Windows Hyper-V WSL
adapter. The server never binds a wildcard or LAN address, and the WSL client
accepts the non-loopback URL only when it exactly matches a separately
configured canonical IP. A bearer token of at least 32 characters is required before request parsing. Request bodies,
response bodies, expiry, UUID canonical form, normalized-argument hashes, and
tool-definition hashes are bounded or verified. Idempotency keys are bound to
the complete execution fingerprint; an exact duplicate cannot repeat a
completed in-process execution, while conflicting reuse is rejected. The
current cache is process-local, so restart-safe deduplication remains gated
on durable storage.

Audit JSONL and evidence files are append/no-replace and stored below
`E:\Data\LocalVoiceAgent\runtime`. Evidence contains hashes, IDs, timings,
status, and sanitized error codes but not tool arguments or result bodies.
The launcher writes the actual listener and virtual-environment launcher
PIDs/executables to its status record. The stop script verifies each
executable and command line before stopping it, then confirms the listener is
gone.

The Android client permits only WSS, stores the pairing token in Android
Keystore, and keeps cleartext, raw-audio retention, and full-conversation
retention disabled. Release builds trust only system CAs. Debug builds may
trust a device-owner-installed CA for private-LAN testing, avoiding a mutable
CA or a broad user-CA trust anchor in the release candidate. The server remains
loopback-only by default. A private listener must use an
explicit launcher switch, an RFC1918 IPv4 or IPv6 ULA address, and a PEM TLS
certificate/key; wildcard, public-address, and non-TLS bindings fail before a
server process starts. The launcher never creates a firewall rule. Device CA
installation and any firewall change require a user-controlled approval step.
Private debug certificates are generated only through a hash-locked isolated
environment and a Windows wrapper that refuses overwrite, encrypts the CA key,
and verifies non-inherited NTFS ACLs granting access only to the current user
and LocalSystem. The unencrypted server key is runtime-only and never enters
Git, an APK, or logs.

## Approval integrity

Approvals bind to the exact tool, normalized arguments, target fingerprint,
workspace, expected change, risk level, expiry, and execution id. Any argument
or precondition change invalidates approval.

## Threat cases

Required tests include invalid tokens, traversal, symlink/reparse bypass,
allowlist escape, concurrent write/hash mismatch, duplicate execution,
timeouts, WebSocket replay, prompt injection in files/pages, malicious tool
arguments, oversized output, and evidence tampering.
