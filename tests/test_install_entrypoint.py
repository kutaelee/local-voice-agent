from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_installer_is_scoped_and_reproducible() -> None:
    source = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")

    assert "InstallProjectEnvironments" in source
    assert "ValidatePrerequisites" in source
    assert "BuildAndroid" in source
    assert "$sourceRoot" in source
    assert "Assert-SourceRepository" in source
    assert "Project-environment installation is allowed only" in source
    assert "--locked" in source
    assert "UV_PROJECT_ENVIRONMENT" in source
    assert "PLAYWRIGHT_BROWSERS_PATH" in source
    assert "-m playwright install chromium" in source
    assert "install-project-environments.sh" in source
    assert "pip install --global" not in source
    assert "SetEnvironmentVariable" not in source
    assert "Start-Process" not in source
    assert "winget install" not in source
    assert "Set-NetFirewall" not in source


def test_wsl_project_installer_is_locked_and_external() -> None:
    source = (
        ROOT / "scripts" / "install-project-environments.sh"
    ).read_text(encoding="utf-8")

    assert "set -euo pipefail" in source
    assert "UV_PROJECT_ENVIRONMENT" in source
    assert "--locked" in source
    assert "--require-hashes" in source
    assert "${HOME}/.local/share/local-voice-agent/runtimes" in source
    assert "/mnt/c/Dev/Repos/local-voice-agent" in source
    assert "sudo " not in source
    assert "pip install" not in source
