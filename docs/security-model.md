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

Inference bearer tokens are process-environment secrets. The Windows runtime
wrappers bridge only the variable names through `WSLENV`; they never append
token values to a command line. The SGLang wrapper removes its bridge variable
before importing the runtime, injects the value only into the parsed
`ServerArgs`, and redacts API, admin, and TLS-password fields from its
representation. vLLM uses its official `VLLM_API_KEY` environment contract
instead of `--api-key`. Both launch paths use unauthenticated loopback health
endpoints so probes do not expose an Authorization header in `ps` output.

The launchers also fail closed when measured free VRAM is below the
model-specific admission floor. SGLang takes two samples two seconds apart
before starting. Neither runtime unloads, stops, or signals a foreign GPU
process. A ComfyUI model may be unloaded only after its queue is observed idle
and the user has authorized alternating use; the ComfyUI process itself stays
running.

The model-switch API requires the same pairing bearer token as other
management routes. It accepts only the closed `gemma4-12b`/`gemma4-31b`
identifiers and never converts model text into a command. The process adapter
calls two registered scripts with an environment allowlist, validates the
owned PID and expected model path before stop, verifies the exact served model
after health, bounds command and HTTP responses, redacts the inference token,
and stores action evidence outside Git. A still-open listener or failed
cleanup prevents a new model from loading.

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

The Web QA portal does not receive the long-lived pairing token. Its bootstrap
requires an exact same-origin request from a loopback client and issues a
bounded, memory-only credential tied to the client address and user agent.
Remote-LAN and cross-origin bootstrap requests fail closed. The credential is
lost on page/server restart and is exchanged for the existing 45-second
single-use WebSocket ticket.

Reference-voice data is a separate, explicit exception to default raw-audio
non-retention. Registration requires affirmative voice-rights and
local-processing consent flags, accepts only a bounded 3–30 second PCM WAV,
and stores the clip under `E:\Data\LocalVoiceAgent\voice-profiles` with a
SHA-256 metadata record. The clip, user-supplied transcript, profile IDs, and
voice-derived output never enter Git or the APK. The TTS worker independently
resolves the selected file beneath the fixed profile root, rejects symlinks
and path escape, and receives no arbitrary model-generated path. Removing a
profile remains a separate destructive operation and is not exposed in this
slice.

Salon reservation handling has a separate deterministic authority boundary.
The model-led receptionist cannot write files directly. It may return only a
closed-schema conversational action and slots. Only the reservation domain
service may mutate the fixed active
JSON path, and only after an explicit caller confirmation. It validates
hours, horizon, slot alignment, staff capability and overlap. Change and
cancellation additionally require both the reservation code and normalized
phone number. The file adapter rejects symbolic-link paths, bounds input,
writes atomically, and creates a checksummed append-only pre-mutation recovery
copy on D:. Browser snapshots, WebSocket owner notifications, and Android
notification text mask the customer phone number. Full phone numbers never
enter Git, application logs, or protocol evidence.

The loopback `web-qa` instance uses a separate
`qa-reservations.json` table and a separate `salon-qa` recovery root. Its
optional seed contains only fictitious customers and is accepted only when
the final data filename is exactly `qa-reservations.json`. This fail-closed
binding prevents QA startup from seeding or overwriting the active reservation
table.

The conversation harness connects only to an authenticated loopback vLLM URL,
disables thinking, requests a strict action/slot/reply object, and bounds both
input history and output. Unknown actions and identifiers, invalid dates and
phone numbers, oversized output, and verbatim caller echoes fail closed.
Recent assistant responses are similarity-checked and internal action/slot
markers are rejected before customer delivery. A single bounded retry asks
the model to answer only the latest caller turn with different natural
wording; application code still does not author customer-facing dialogue.
Reservation creation, change, or cancellation additionally requires a pending
proposal and a distinct explicit confirmation turn. The optional TTS
adapter receives only the already-approved assistant text and selected local
voice profile; a TTS failure cannot roll back or alter a reservation result.

## Approval integrity

Approvals bind to the exact tool, normalized arguments, target fingerprint,
workspace, expected change, risk level, expiry, and execution id. Any argument
or precondition change invalidates approval.

## Threat cases

Required tests include invalid tokens, traversal, symlink/reparse bypass,
allowlist escape, concurrent write/hash mismatch, duplicate execution,
timeouts, WebSocket replay, prompt injection in files/pages, malicious tool
arguments, oversized output, and evidence tampering.
