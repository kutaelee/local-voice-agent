# Rollback plan

## Source

Each slice is committed independently. Revert a slice with `git revert` of
the relevant commit; never use destructive reset on user work.

## Python runtimes

Each environment is self-contained under the WSL user runtime root. Rollback
means stop its processes, point configuration to the previous locked
environment, health-check it, and only then archive the failed environment.
No global pip state is changed.

The PC-server environment is
`/home/kutae/.local/share/local-voice-agent/runtimes/pc-server/.venv`.
Stop and verify the registered server PID before switching or archiving it.
Source rollback uses `git revert`; the environment is not automatically
deleted.

The Windows Tool Executor environment is
`C:\Dev\Tools\LocalVoiceAgent\runtimes\tool-executor\.venv`; Playwright
browser assets are isolated at
`C:\Dev\Tools\LocalVoiceAgent\browsers\playwright-1.61.0`. Stop the registered
executor, verify port 46323 and its recorded PID are absent, inventory the
exact directory, and then move only the selected directory with
`E:\Workspace\System\workstation-config\scripts\Move-ToWorkstationTrash.ps1`.
Do not recursively delete `C:\Dev\Tools` or a shared browser root.

For a WSL runtime rollback, first use its registered stop script and verify
the listener/PID are absent. Rename the exact revisioned environment into a
timestamped `~/.local/share/local-voice-agent/retired` directory; do not
delete the runtime root. Re-run the locked installer to recreate only the
selected environment, validate health, and retain the retired copy until the
replacement is proven.

## Android SDK and emulator

The project did not install Android Studio or change system PATH. The SDK is
isolated at `C:\Dev\SDK\Android`, Gradle downloads at
`E:\Cache\LocalVoiceAgent\gradle`, and the project QA AVD at
`E:\Data\LocalVoiceAgent\runtime\android-avd\lva_api36.avd` with its pointer
file at `C:\Users\kutae\.android\avd\lva_api36.ini`.

To remove only the QA AVD, stop `emulator-5556` through `adb emu kill`, verify
the serial and owned emulator/QEMU processes are absent, inventory both exact
AVD paths, and move them to the corresponding same-drive workstation trash.
The SDK may be trashed only after verifying that no other Android project
references it. Gradle and SDK download caches are disposable but still use
the trash helper for task cleanup. APKs and evidence under
`E:\Data\LocalVoiceAgent` are retained unless a separate, exact cleanup
authorization includes them.

## Models

Model downloads are revision-addressed. Configuration references an explicit
revision directory. Rollback changes the active manifest pointer to a
previous validated revision; it does not delete weights automatically.

The Windows fallback is versioned at
`C:\Dev\Tools\LocalVoiceAgent\runtimes\llama.cpp-b10092`. Stop it through
`scripts\stop-fallback.ps1`, verify port 46327 and the registered PID are gone,
then use the workstation trash helper to move only that exact runtime if a
rollback is required. Retain the revision-addressed GGUF unless a separate
inventory and cleanup authorization explicitly includes it.

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
