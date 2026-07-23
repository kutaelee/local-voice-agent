# ADR-0001: Filesystem layout

Status: Accepted — 2026-07-23

Use C: for the repository and WSL/Docker tooling, E: for models, caches,
runtime data, and database data, and never D: for active workloads. This
follows the workstation's physical-disk mapping and prevents backup storage
from becoming authoritative application state.
