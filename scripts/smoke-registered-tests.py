"""Run the checked-in test profile through the bounded development adapter."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from local_voice_agent_tool_executor.bootstrap import load_workspaces
from local_voice_agent_tool_executor.development import DevelopmentToolExecutor
from local_voice_agent_tool_executor.workspaces import WorkspaceRegistry


REPO_ROOT = Path(r"C:\Dev\Repos\local-voice-agent")
EVIDENCE_ROOT = Path(
    r"E:\Data\LocalVoiceAgent\runtime\evidence\tool-executor\development\tests"
)


def main() -> None:
    workspaces = load_workspaces(
        config_path=REPO_ROOT / "configs/workspaces.yaml",
        schema_path=REPO_ROOT / "configs/schemas/workspaces.schema.json",
    )
    adapter = DevelopmentToolExecutor(
        workspaces=WorkspaceRegistry(workspaces),
        executables={"wsl": Path(r"C:\Windows\System32\wsl.exe")},
        artifact_root=EVIDENCE_ROOT,
    )
    result = adapter.execute(
        "run_tests",
        {
            "workspace_id": "local_voice_agent",
            "profile_id": "repository-validation",
            "idempotency_key": str(uuid4()),
        },
    )
    log = adapter.execute(
        "inspect_test_log",
        {
            "workspace_id": "local_voice_agent",
            "evidence_id": result["evidence_id"],
            "max_bytes": 262144,
        },
    )
    if not result["succeeded"]:
        raise SystemExit("registered test profile failed")
    if "repository_validation_passed" not in log["text"]:
        raise SystemExit("registered test evidence is incomplete")
    print(
        json.dumps(
            {
                "status": "registered_test_profile_passed",
                "profile_id": result["profile_id"],
                "evidence_id": result["evidence_id"],
                "exit_code": result["exit_code"],
                "duration_ms": result["duration_ms"],
                "output_bytes": result["output_bytes"],
                "timed_out": result["timed_out"],
                "output_limited": result["output_limited"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
