[CmdletBinding()]
param(
    [switch]$PlanOnly
)

$ErrorActionPreference = 'Stop'

if (-not $PlanOnly) {
    throw 'Slice 0 guard: use -PlanOnly. Windows package installation is not enabled yet.'
}

@'
Local Voice Agent Windows installation plan

Already present:
- Git, Git LFS, GitHub CLI, uv, JDK 17, WSL2 Ubuntu, Docker Desktop

Missing and not installed by this script:
- Android SDK command-line tools and ADB
- Node.js
- FFmpeg
- PostgreSQL 18
- Windows fallback runtime

Approval-gated:
- Full Android Studio
- Visual Studio Build Tools
- system PATH, firewall, registry, Windows feature, driver changes

Project paths:
- source: C:\Dev\Repos\local-voice-agent
- models: E:\AI\Models\Standalone\LocalVoiceAgent
- cache: E:\Cache\LocalVoiceAgent
- runtime: E:\Data\LocalVoiceAgent
'@
