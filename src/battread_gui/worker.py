# SPDX-FileCopyrightText: 2026 Alessandro Gregucci
# SPDX-License-Identifier: GPL-3.0-or-later

"""Isolated worker communicating newline-delimited JSON through standard output.

No Qt imports are needed here. The parent owns the temporary workspace and cleans
it even after forcibly terminating a blocked vendor reader. Diagnostics go to
stderr; progress and warning events use stdout exclusively.
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path
from typing import IO, Any, cast

import psutil

from battread_gui.models import CancelledError, Job, OutputFormat


def emit(event: dict[str, Any]) -> None:
    """Flush one structured event so the UI receives it without polling files."""
    print(json.dumps(event), flush=True)


def main() -> int:
    """Execute the parent's validated job file and return a meaningful exit code.

    Code 0 means success, 2 cancellation, and 1 failure. Failed jobs never publish
    incomplete destinations; previously completed separate outputs are retained.
    """
    workspace = Path(sys.argv[1])
    # The parent installs the Windows allocation cap before letting scientific
    # imports or vendor allocations run. EOF means startup was abandoned.
    if sys.stdin.readline().strip() != "ready":
        return 2
    payload = json.loads((workspace / "job.json").read_text(encoding="utf-8"))
    job = Job(
        inputs=tuple(Path(p) for p in payload["inputs"]),
        outputs=tuple(Path(p) for p in payload["outputs"]),
        merge=bool(payload["merge"]),
        format=cast(OutputFormat, payload["format"]),
        memory_limit=int(payload["memory_limit"]),
        chunk_size=int(payload["chunk_size"]),
    )
    process = psutil.Process()
    active_source = ""

    def report_event(event: dict[str, Any]) -> None:
        """Track the active acquisition to identify the source of warnings/errors."""
        nonlocal active_source
        if "source" in event:
            active_source = str(event["source"])
        emit(event)

    def check() -> None:
        """Observe cancellation and memory limits between bounded chunk operations."""
        if (workspace / "cancel").exists():
            raise CancelledError("Processing was cancelled.")
        if process.memory_info().rss > job.memory_limit:
            raise MemoryError("The worker exceeded its memory budget.")

    def report_warning(
        message: Warning | str,
        category: type[Warning],
        filename: str,
        lineno: int,
        file: IO[str] | None = None,
        line: str | None = None,
    ) -> None:
        """Forward scientific warnings to the UI without hiding data issues."""
        if category.__name__ == "MissingValueWarning":
            # The orchestrator emits one aggregate with its source name as the
            # warning filename; identical counts from different files stay clear.
            message = f"{filename}: {message}"
        elif active_source:
            message = f"{active_source}: {message}"
        emit({"phase": "Warning", "message": f"{category.__name__}: {message}"})

    request_id = 0

    def resolve(
        source: Path, columns: dict[str, str | int], units: dict[str, str]
    ) -> tuple[dict[str, str | int], dict[str, str]]:
        """Wait cancellably for one explicit reply without releasing staged inputs."""
        nonlocal request_id
        from battread_gui.column_choices import apply_choice, choice_request

        request_id += 1
        request = choice_request(source, columns, units)
        report_event({"phase": "Column choice", "request_id": request_id, **request})
        reply = workspace / f"column-choice-{request_id}.json"
        while not reply.exists():
            check()
            time.sleep(0.1)
        check()
        response = json.loads(reply.read_text(encoding="utf-8"))
        reply.unlink()
        if not isinstance(response, dict):
            raise ValueError("Invalid column selection reply.")
        return apply_choice(request, cast(dict[str, Any], response), columns, units)

    try:
        from battread_gui.processing import run_job

        with warnings.catch_warnings():
            warnings.simplefilter("always")
            warnings.showwarning = report_warning
            staging = {
                Path(parent): Path(directory)
                for parent, directory in payload.get("output_workspaces", {}).items()
            }
            run_job(job, workspace, report_event, check, staging or None, resolve)
    except CancelledError as error:
        emit({"phase": "Cancelled", "message": str(error)})
        return 2
    except Exception as error:
        context = f"{active_source}: " if active_source else ""
        emit({"phase": "Error", "message": f"{context}{type(error).__name__}: {error}"})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
