# Storage report

Captured on 2026-07-23. Protected backup and transfer locations were not
modified.

## Physical disks and volumes

| Volume | Physical device | Media | Total | Free | Policy |
|---|---|---|---:|---:|---|
| C: | Samsung SSD 990 PRO 2TB | NVMe SSD | 1861.95 GiB | 1699.61 GiB | Source, tools, WSL, Docker |
| E: | Seagate FireCuda ZP4000GM30073 | NVMe SSD | 3726.01 GiB | 3411.21 GiB | Models, data, caches |
| D: | ST1000DM003-1CH162 | SATA HDD | 930.62 GiB | 551.56 GiB | Backup-only; prohibited for active workloads |

The currently pinned default, exact-MTP, primary TTS, and STT candidate set is
approximately 118.55 GiB of repository content before cache overhead. This includes both
W4A16 serving targets and the separate Q4_0-unquantized targets required for
officially matched MTP testing, the pinned Chatterbox Multilingual V3 files,
and two measured-selection STT candidates. Even with a conservative 2×
download/staging allowance,
E: remains well above the required 20% operational free-space reserve.

## Canonical project placement

| Data class | Canonical location |
|---|---|
| Repository | `C:\Dev\Repos\local-voice-agent` |
| Shared Gemma/STT/TTS/VAD snapshots | `E:\AI\Models\HuggingFace\hub` |
| Shared Hugging Face download cache | `E:\Cache\HuggingFace` |
| Project resumable-download state | `E:\Cache\LocalVoiceAgent\download-state` |
| Windows Ollama generation store | `E:\AI\Models\Ollama\generation\models` |
| Runtime logs/sessions/status/evidence/backups/temp | `E:\Data\LocalVoiceAgent\runtime` |
| PostgreSQL cluster | `E:\Data\DB\Active\LocalVoiceAgent` |

## WSL versus NTFS model placement

No conclusion is claimed before measurement. The WSL ext4 root has 933 GiB
available and `/mnt/e` exposes the FireCuda through WSL 9p. Slice 2 will
compare cold/warm load time, initialization time, throughput, and disk usage
using the same model revision. The authoritative copy stays on E: until the
comparison proves an ext4 copy is materially beneficial. A second full copy
requires an explicit inventory entry and cleanup plan.

## Existing large models

Existing assets are unrelated ComfyUI and standalone image/video/3D models.
The largest observed file is a 27.144 GiB LTX checkpoint. No Gemma 4 file was
found.

Several files share identical byte sizes (notably paired Wan high/low-noise
weights and Z-Image variants). Equal size is not proof of duplicate content,
so none was deleted or deduplicated. Hashing those protected existing assets
is deferred because it is unrelated to this project.

## Download safety

Before downloading any individual file over 5 GB, the download script must
record the official URL, exact revision, expected size, available space,
license, destination, and upstream ETag/OID when available. Downloaded files
remain in cache until revision and file hashes are validated.

## Shared model migration

On 2026-07-25, 12 pinned Gemma, STT, and TTS snapshots were registered under
the workstation-wide Hugging Face root. Existing E: files were linked with
same-volume hardlinks, so registration did not create a second set of weight
bytes. All 12 source/target trees passed relative-path and size validation;
all 16 files of at least 100 MiB had both a canonical and legacy hardlink.

Windows Ollama 0.32.3 was configured to use
`E:\AI\Models\Ollama\generation\models`. Its four existing generation models
were visible immediately without downloading. The Local Knowledge Portal
keeps its separately owned embedding store at `E:\AI\Models\Ollama\models` so
the two daemons never write the same model directory.
