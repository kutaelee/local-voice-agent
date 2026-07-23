# Repository instructions

- Follow the workstation filesystem rules in
  `E:\Workspace\System\workstation-config\docs\filesystem-layout.md`.
- Do not store model weights, caches, database data, logs, evidence, secrets,
  APK signing keys, or `.env` files in this repository.
- Use the canonical paths documented in `README.md`.
- Keep vLLM, SGLang, STT, TTS, quantization, PC server, and Android/Gradle
  environments isolated.
- Do not install or change NVIDIA drivers, Windows features, WSL
  distributions, firewall rules, system PATH, registry, Android Studio, or
  administrator packages without explicit user approval.
- Never execute model-generated shell commands directly.
- Never report a test or benchmark as passed unless its command and result are
  recorded.
- Preserve exact model IDs, repository revisions, file hashes, installed
  versions, source URLs, and installation dates in `manifests/`.
- Prefer stable official releases. A prerelease requires a documented
  compatibility reason and rollback target.
- Keep commits scoped to one investigation or implementation milestone.
