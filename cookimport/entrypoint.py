from __future__ import annotations

import sys

from cookimport.cli import DEFAULT_INPUT, DEFAULT_OUTPUT, _fail, app, stage


def main() -> None:
    args = sys.argv[1:]
    if not args:
        stage(path=DEFAULT_INPUT, out=DEFAULT_OUTPUT, mapping=None, limit=None)
        return
    if len(args) == 1:
        try:
            limit = int(args[0])
        except ValueError:
            limit = None
        if limit is not None:
            if limit <= 0:
                _fail("Limit must be a positive integer.")
            stage(path=DEFAULT_INPUT, out=DEFAULT_OUTPUT, mapping=None, limit=limit)
            return
    app()
