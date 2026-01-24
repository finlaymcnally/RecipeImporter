from __future__ import annotations

import os
import sys

from cookimport.cli import _fail, app


def main() -> None:
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
