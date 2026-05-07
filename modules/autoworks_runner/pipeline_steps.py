from __future__ import annotations

import importlib.util
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PipelineStepDefinition:
    name: str
    required: bool
    module_name: str | None = None
    args: list[str] = field(default_factory=list)
    expected_outputs: dict[str, Path] = field(default_factory=dict)
    optional_when_missing: bool = False
    kind: str = "python_module"


def module_is_available(module_name: str | None) -> bool:
    if not module_name:
        return False
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def run_python_module(
    module_name: str,
    args: list[str] | None = None,
    expected_outputs: dict[str, Path] | None = None,
    *,
    cwd: Path | None = None,
    min_mtime: datetime | None = None,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    if not module_is_available(module_name):
        return {
            "status": "skipped",
            "summary": f"module {module_name} is not implemented",
            "output_paths": {},
            "warnings": [f"module {module_name} is not implemented"],
            "errors": [],
            "metadata": {"module": module_name, "args": args or []},
        }

    command = [sys.executable, "-m", module_name, *(args or [])]
    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    output_paths = existing_outputs(expected_outputs or {}, min_mtime=min_mtime)
    metadata = {
        "module": module_name,
        "args": args or [],
        "command": command,
        "command_text": " ".join(command),
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
        "stdout_summary": completed.stdout[-1000:],
        "stderr_summary": completed.stderr[-1000:],
    }
    if completed.returncode != 0:
        return {
            "status": "failed",
            "summary": f"{module_name} exited with {completed.returncode}",
            "output_paths": output_paths,
            "warnings": [],
            "errors": [completed.stderr.strip() or completed.stdout.strip()],
            "metadata": metadata,
        }

    missing = missing_outputs(expected_outputs or {}, min_mtime=min_mtime)
    if missing:
        return {
            "status": "failed",
            "summary": "missing or stale expected outputs: " + ", ".join(missing),
            "output_paths": output_paths,
            "warnings": [],
            "errors": ["missing or stale expected outputs: " + ", ".join(missing)],
            "metadata": metadata,
        }

    return {
        "status": "success",
        "summary": f"ran {module_name}",
        "output_paths": output_paths,
        "warnings": [],
        "errors": [],
        "metadata": metadata,
    }


def existing_outputs(
    expected_outputs: dict[str, Path],
    *,
    min_mtime: datetime | None = None,
) -> dict[str, str]:
    return {
        label: str(path)
        for label, path in expected_outputs.items()
        if output_is_fresh(path, min_mtime=min_mtime)
    }


def missing_outputs(
    expected_outputs: dict[str, Path],
    *,
    min_mtime: datetime | None = None,
) -> list[str]:
    return [
        str(path)
        for path in expected_outputs.values()
        if not output_is_fresh(path, min_mtime=min_mtime)
    ]


def output_is_fresh(path: Path, *, min_mtime: datetime | None = None) -> bool:
    if not path.exists():
        return False
    if min_mtime is None:
        return True
    return path.stat().st_mtime >= min_mtime.timestamp()
