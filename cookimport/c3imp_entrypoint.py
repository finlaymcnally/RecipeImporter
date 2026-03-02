from __future__ import annotations

import os
import sys

from cookimport.cli import _fail, app


_COOKIMPORT_WORKER_UTILIZATION_DEFAULT = "90"
_COOKIMPORT_IO_PACE_EVERY_WRITES = "16"
_COOKIMPORT_IO_PACE_SLEEP_MS = "8"
_COOKIMPORT_BENCH_WRITE_MARKDOWN = "0"
_COOKIMPORT_BENCH_WRITE_LABELSTUDIO_TASKS = "0"


def main() -> None:
    os.environ.setdefault("COOKIMPORT_WORKER_UTILIZATION", _COOKIMPORT_WORKER_UTILIZATION_DEFAULT)
    os.environ.setdefault(
        "COOKIMPORT_IO_PACE_EVERY_WRITES",
        _COOKIMPORT_IO_PACE_EVERY_WRITES,
    )
    os.environ.setdefault(
        "COOKIMPORT_IO_PACE_SLEEP_MS",
        _COOKIMPORT_IO_PACE_SLEEP_MS,
    )
    os.environ.setdefault(
        "COOKIMPORT_BENCH_WRITE_MARKDOWN",
        _COOKIMPORT_BENCH_WRITE_MARKDOWN,
    )
    os.environ.setdefault(
        "COOKIMPORT_BENCH_WRITE_LABELSTUDIO_TASKS",
        _COOKIMPORT_BENCH_WRITE_LABELSTUDIO_TASKS,
    )

    args = sys.argv[1:]
    if len(args) == 1:
        try:
            limit = int(args[0])
        except ValueError:
            limit = None
        if limit is not None:
            if limit <= 0:
                _fail("Limit must be a positive integer.")
            os.environ["C3IMP_LIMIT"] = str(limit)
            sys.argv = [sys.argv[0]]
            app()
            return
    app()
