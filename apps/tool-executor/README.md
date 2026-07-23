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

## Current implementation

The executable slice includes thirteen Level 0 filesystem and Git observation
tools:

- `list_files`
- `search_files`
- `read_file`
- `read_file_range`
- `list_recent_files`
- `calculate_hash`
- `git_status`
- `git_diff`
- `git_diff_stat`
- `git_log`
- `git_branch`
- `git_show`
- `git_blame`

It also implements three Level 1, approval-bound file operations:

- `write_file`
- `apply_patch`
- `rollback_file_change`

Ten Windows-native Level 0 system tools inspect CPU, memory, GPU, disks,
network adapters/listeners, processes, services, and loopback ports. They use
fixed code-owned PowerShell/CIM and `nvidia-smi` queries; no model-generated
command is executed. Command lines are opt-in and common credential forms are
masked.

The executor reloads and validates the repository tool contracts rather than
trusting validation performed by the PC server. Workspace lookup is
fail-closed. Absolute paths, traversal, Windows alternate data streams,
reserved device names, symlinks, junctions, and other reparse points are
rejected. Directory walking never follows links and all outputs are bounded.

Git runs only as a fixed absolute executable with an argv array and no shell.
The adapter disables prompting, pagers, optional locks, fsmonitor, external
diff, textconv, hooks, and non-literal pathspecs. Revisions are resolved to a
commit ID using `--end-of-options`. `.git` must be an internal directory; its
metadata is scanned for links/reparse points, and linked worktrees, object
alternates, and config include sections are rejected.

Each file mutation requires an exact argument digest, unexpired approval,
matching idempotency key, read-write workspace registration, and SHA-256
precondition. A successful change creates a no-replace backup outside the
worktree. Rollback is a separate approved Level 1 execution and succeeds only
when the workspace, path, backup identity, and current post-change hash all
still match. Browser and Windows UI adapters cover bounded Level 0/1 subsets.
Delete, Git mutation, process mutation, coordinate UI, external browser
submission, and shell operations remain unavailable. The executor cannot
access user files until a workspace is explicitly registered.

The environment is isolated from the PC server and model runtimes:

```bash
cd apps/tool-executor
export UV_PROJECT_ENVIRONMENT=\
/home/kutae/.local/share/local-voice-agent/runtimes/tool-executor/.venv
uv sync --locked --extra test
uv run --locked --extra test pytest
```
