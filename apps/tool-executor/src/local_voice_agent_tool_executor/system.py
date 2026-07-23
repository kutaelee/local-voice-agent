"""Bounded, read-only Windows system inspection adapters."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
from typing import Any, Mapping

from .errors import SystemInspectionError, ToolNotSupported


SYSTEM_TOOLS = frozenset(
    {
        "check_port",
        "inspect_cpu",
        "inspect_disk",
        "inspect_gpu",
        "inspect_memory",
        "inspect_network",
        "inspect_process",
        "inspect_service",
        "list_processes",
        "list_services",
    }
)
_MAX_OUTPUT_BYTES = 1024 * 1024
_SECRET_ARGUMENT = re.compile(
    r"(?i)(--?(?:api[-_]?key|authorization|password|secret|token)"
    r"(?:=|\s+))([^\s\"']+|\"[^\"]*\"|'[^']*')"
)
_CREDENTIAL_URL = re.compile(r"(?i)(https?://[^:/\s]+:)[^@\s]+(@)")


class WindowsSystemInspector:
    def __init__(
        self,
        *,
        powershell_executable: Path | None = None,
        nvidia_smi_executable: Path | None = None,
    ) -> None:
        if os.name != "nt":
            raise SystemInspectionError(
                "Windows system inspection requires a Windows-native process"
            )
        discovered_powershell = powershell_executable or _which_path(
            "powershell.exe"
        )
        if discovered_powershell is None:
            raise SystemInspectionError("PowerShell is unavailable")
        self._powershell = discovered_powershell
        self._nvidia_smi = nvidia_smi_executable or _which_path("nvidia-smi.exe")

    def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        if tool_name not in SYSTEM_TOOLS:
            raise ToolNotSupported(tool_name)
        return getattr(self, f"_{tool_name}")(**dict(arguments))

    def _inspect_cpu(self) -> dict[str, Any]:
        records = self._powershell_json(
            "Get-CimInstance Win32_Processor | "
            "Select-Object Name,Manufacturer,NumberOfCores,"
            "NumberOfLogicalProcessors,LoadPercentage,MaxClockSpeed"
        )
        return {"processors": _as_list(records)}

    def _inspect_memory(self) -> dict[str, Any]:
        record = self._powershell_json(
            "Get-CimInstance Win32_OperatingSystem | "
            "Select-Object TotalVisibleMemorySize,FreePhysicalMemory,"
            "TotalVirtualMemorySize,FreeVirtualMemory"
        )
        item = _first(record)
        total = _kilobytes(item.get("TotalVisibleMemorySize"))
        available = _kilobytes(item.get("FreePhysicalMemory"))
        total_virtual = _kilobytes(item.get("TotalVirtualMemorySize"))
        available_virtual = _kilobytes(item.get("FreeVirtualMemory"))
        return {
            "total_bytes": total,
            "available_bytes": available,
            "used_bytes": max(0, total - available),
            "committed_limit_bytes": total_virtual,
            "committed_available_bytes": available_virtual,
        }

    def _inspect_gpu(self, include_processes: bool = True) -> dict[str, Any]:
        if self._nvidia_smi is None:
            raise SystemInspectionError("nvidia-smi is unavailable")
        fields = (
            "index,uuid,name,driver_version,temperature.gpu,utilization.gpu,"
            "memory.total,memory.used,memory.free"
        )
        gpu_rows = self._run_csv(
            [
                str(self._nvidia_smi),
                f"--query-gpu={fields}",
                "--format=csv,noheader,nounits",
            ],
            timeout_seconds=10,
        )
        keys = fields.split(",")
        gpus = [
            {
                key.replace(".", "_"): _numeric_or_text(value)
                for key, value in zip(keys, row, strict=True)
            }
            for row in gpu_rows
        ]
        processes: list[dict[str, Any]] = []
        if include_processes:
            process_fields = "pid,process_name,used_gpu_memory"
            for row in self._run_csv(
                [
                    str(self._nvidia_smi),
                    f"--query-compute-apps={process_fields}",
                    "--format=csv,noheader,nounits",
                ],
                timeout_seconds=10,
                allow_empty=True,
            ):
                processes.append(
                    {
                        key: _numeric_or_text(value)
                        for key, value in zip(
                            process_fields.split(","),
                            row,
                            strict=True,
                        )
                    }
                )
        return {"gpus": gpus, "compute_processes": processes}

    def _inspect_disk(self, volume: str | None = None) -> dict[str, Any]:
        records = _as_list(
            self._powershell_json(
                "Get-CimInstance Win32_LogicalDisk -Filter \"DriveType=3\" | "
                "Select-Object DeviceID,VolumeName,FileSystem,Size,FreeSpace"
            )
        )
        if volume is not None:
            records = [
                item
                for item in records
                if str(item.get("DeviceID", "")).casefold() == volume.casefold()
            ]
        return {"volumes": records}

    def _inspect_network(
        self,
        include_listeners: bool = False,
    ) -> dict[str, Any]:
        adapters = _as_list(
            self._powershell_json(
                "Get-NetAdapter | Select-Object Name,InterfaceDescription,"
                "Status,LinkSpeed,MacAddress,InterfaceIndex"
            )
        )
        addresses = _as_list(
            self._powershell_json(
                "Get-NetIPAddress -AddressFamily IPv4,IPv6 | "
                "Where-Object {$_.AddressState -eq 'Preferred'} | "
                "Select-Object InterfaceIndex,IPAddress,PrefixLength,AddressFamily"
            )
        )
        result: dict[str, Any] = {
            "adapters": adapters,
            "addresses": addresses,
        }
        if include_listeners:
            result["tcp_listeners"] = _as_list(
                self._powershell_json(
                    "Get-NetTCPConnection -State Listen | "
                    "Select-Object LocalAddress,LocalPort,OwningProcess | "
                    "Sort-Object LocalPort"
                )
            )
        return result

    def _list_processes(
        self,
        name_contains: str | None = None,
        include_command_line: bool = False,
        limit: int = 100,
    ) -> dict[str, Any]:
        records = _as_list(
            self._powershell_json(
                "Get-CimInstance Win32_Process | "
                "Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,"
                "CommandLine,CreationDate"
            )
        )
        if name_contains:
            needle = name_contains.casefold()
            records = [
                item
                for item in records
                if needle in str(item.get("Name", "")).casefold()
            ]
        records.sort(key=lambda item: int(item.get("ProcessId") or 0))
        records = records[:limit]
        for item in records:
            if include_command_line:
                item["CommandLine"] = _redact_command_line(
                    item.get("CommandLine")
                )
            else:
                item.pop("CommandLine", None)
        return {"processes": records, "truncated": len(records) == limit}

    def _inspect_process(
        self,
        process_id: int,
        include_command_line: bool = False,
    ) -> dict[str, Any]:
        record = self._powershell_json(
            f"Get-CimInstance Win32_Process -Filter \"ProcessId={process_id}\" | "
            "Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,"
            "CommandLine,CreationDate,KernelModeTime,UserModeTime,WorkingSetSize"
        )
        item = _first(record, required=False)
        if item is None:
            return {"found": False, "process_id": process_id}
        if include_command_line:
            item["CommandLine"] = _redact_command_line(item.get("CommandLine"))
        else:
            item.pop("CommandLine", None)
        return {"found": True, "process": item}

    def _list_services(
        self,
        state: str = "all",
        name_prefix: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        records = _as_list(
            self._powershell_json(
                "Get-CimInstance Win32_Service | "
                "Select-Object Name,DisplayName,State,StartMode,ProcessId"
            )
        )
        if state != "all":
            records = [
                item
                for item in records
                if str(item.get("State", "")).casefold() == state.casefold()
            ]
        if name_prefix:
            prefix = name_prefix.casefold()
            records = [
                item
                for item in records
                if str(item.get("Name", "")).casefold().startswith(prefix)
            ]
        records.sort(key=lambda item: str(item.get("Name", "")).casefold())
        records = records[:limit]
        return {"services": records, "truncated": len(records) == limit}

    def _inspect_service(self, service_name: str) -> dict[str, Any]:
        records = _as_list(
            self._powershell_json(
                "Get-CimInstance Win32_Service | "
                "Select-Object Name,DisplayName,Description,State,Status,"
                "StartMode,ProcessId,PathName,ServiceType"
            )
        )
        item = next(
            (
                record
                for record in records
                if str(record.get("Name", "")).casefold()
                == service_name.casefold()
            ),
            None,
        )
        if item is None:
            return {"found": False, "service_name": service_name}
        item["PathName"] = _redact_command_line(item.get("PathName"))
        return {"found": True, "service": item}

    def _check_port(
        self,
        port: int,
        host: str = "127.0.0.1",
    ) -> dict[str, Any]:
        normalized_host = "127.0.0.1" if host == "localhost" else host
        family = socket.AF_INET6 if normalized_host == "::1" else socket.AF_INET
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.5)
            listening = probe.connect_ex((normalized_host, port)) == 0
        return {"host": host, "port": port, "listening": listening}

    def _powershell_json(self, expression: str) -> Any:
        script = (
            "$ErrorActionPreference='Stop';"
            "$ProgressPreference='SilentlyContinue';"
            "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"
            f"@({expression}) | ConvertTo-Json -Compress -Depth 5"
        )
        completed = _run(
            [
                str(self._powershell),
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            timeout_seconds=15,
        )
        try:
            return json.loads(completed)
        except json.JSONDecodeError as error:
            raise SystemInspectionError(
                "system inspection returned invalid JSON"
            ) from error

    @staticmethod
    def _run_csv(
        command: list[str],
        *,
        timeout_seconds: int,
        allow_empty: bool = False,
    ) -> list[list[str]]:
        import csv
        import io

        output = _run(command, timeout_seconds=timeout_seconds)
        if not output.strip() and allow_empty:
            return []
        return [
            [value.strip() for value in row]
            for row in csv.reader(io.StringIO(output))
            if row
        ]


def _run(command: list[str], *, timeout_seconds: int) -> str:
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
            creationflags=(
                subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            ),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SystemInspectionError("system inspection command failed") from error
    if completed.returncode != 0:
        raise SystemInspectionError(
            f"system inspection command exited {completed.returncode}"
        )
    if len(completed.stdout) > _MAX_OUTPUT_BYTES:
        raise SystemInspectionError("system inspection output exceeds limit")
    try:
        return completed.stdout.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise SystemInspectionError(
            "system inspection output is not valid UTF-8"
        ) from error


def _which_path(name: str) -> Path | None:
    value = shutil.which(name)
    return None if value is None else Path(value).resolve(strict=True)


def _as_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    records = value if isinstance(value, list) else [value]
    if not all(isinstance(item, dict) for item in records):
        raise SystemInspectionError("system inspection result shape is invalid")
    return records


def _first(
    value: Any,
    *,
    required: bool = True,
) -> dict[str, Any] | None:
    records = _as_list(value)
    if records:
        return records[0]
    if required:
        raise SystemInspectionError("system inspection returned no records")
    return None


def _kilobytes(value: Any) -> int:
    try:
        return int(value) * 1024
    except (TypeError, ValueError) as error:
        raise SystemInspectionError("memory value is invalid") from error


def _numeric_or_text(value: str) -> int | float | str | None:
    normalized = value.strip()
    if normalized in {"", "[N/A]", "N/A"}:
        return None
    try:
        return int(normalized)
    except ValueError:
        try:
            return float(normalized)
        except ValueError:
            return normalized


def _redact_command_line(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    text = _SECRET_ARGUMENT.sub(r"\1<redacted>", text)
    return _CREDENTIAL_URL.sub(r"\1<redacted>\2", text)
