from __future__ import annotations

import typer

from cookimport.cli_support import *  # noqa: F401,F403
from cookimport import cli_support as _cli

globals().update(
    {name: getattr(_cli, name) for name in dir(_cli) if not name.startswith("__")}
)


def register_callback(app: typer.Typer) -> dict[str, object]:
    @app.callback()
    def main(ctx: typer.Context) -> None:
        """Recipe Import - Convert source files to schema.org Recipe JSON and cookbook3 outputs."""
        if "_sync_cli_command_module_globals" in globals():
            _sync_cli_command_module_globals()
        if ctx.invoked_subcommand is None:
            limit_value = os.getenv("C3IMP_LIMIT")
            limit = None
            if limit_value:
                try:
                    limit = int(limit_value)
                except ValueError:
                    limit = None
            interactive_mode_token = _INTERACTIVE_CLI_ACTIVE.set(True)
            try:
                _interactive_mode(limit=limit)
            finally:
                _INTERACTIVE_CLI_ACTIVE.reset(interactive_mode_token)

    return {"main": main}
