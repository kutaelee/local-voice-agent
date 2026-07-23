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

The first executable slice is deliberately limited to six Level 0 filesystem
tools:

- `list_files`
- `search_files`
- `read_file`
- `read_file_range`
- `list_recent_files`
- `calculate_hash`

The executor reloads and validates the repository tool contracts rather than
trusting validation performed by the PC server. Workspace lookup is
fail-closed. Absolute paths, traversal, Windows alternate data streams,
reserved device names, symlinks, junctions, and other reparse points are
rejected. Directory walking never follows links and all outputs are bounded.

No write, delete, Git, process, browser, UI, or shell operation is connected
in this slice. The configured workspace allowlist is empty by default, so the
executor cannot access user files until a workspace is explicitly registered.

The environment is isolated from the PC server and model runtimes:

```bash
cd apps/tool-executor
export UV_PROJECT_ENVIRONMENT=\
/home/kutae/.local/share/local-voice-agent/runtimes/tool-executor/.venv
uv sync --locked --extra test
uv run --locked --extra test pytest
```
