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
- Git, Git LFS, GitHub CLI, uv, Node.js 24, JDK 17, WSL2 Ubuntu, Docker Desktop
- Android command-line tools 22.0, API 37, Build Tools 36.0.0, ADB 37.0.0
- PostgreSQL 18.4 exact container image; project start/migration scripts
- llama.cpp b10092 Windows CUDA 13.3 fallback and pinned Gemma 4 12B Q4_0 GGUF

Optional developer tools not required by the validated runtime path:
- FFmpeg
- CMake and Ninja

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
