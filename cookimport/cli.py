from __future__ import annotations

import typer

from cookimport import cli_support as _support
from cookimport.bitter_recipe.app import app as bitter_recipe_app
from cookimport.cli_commands import (
    analytics as analytics_commands,
    bench as bench_commands,
    compare_control as compare_control_commands,
    interactive as interactive_commands,
    labelstudio as labelstudio_commands,
    stage as stage_commands,
)
from cookimport.epubdebug.cli import epub_app


app = typer.Typer(add_completion=False, invoke_without_command=True)
bench_app = typer.Typer(name="bench", help="Offline benchmark suite tools.")
compare_control_app = typer.Typer(
    name="compare-control",
    help="Backend Compare & Control analytics for CLI and agent workflows.",
)
app.add_typer(bench_app)
app.add_typer(compare_control_app, name="compare-control")
app.add_typer(epub_app, name="epub")
app.add_typer(bitter_recipe_app, name="bitter-recipe")


globals().update(
    {
        name: value
        for name, value in vars(_support).items()
        if not name.startswith("__")
        and name not in {"app", "bench_app", "compare_control_app"}
    }
)

_COMMAND_EXPORTS: dict[str, object] = {}
for _exports in (
    interactive_commands.register_callback(app),
    stage_commands.register(app),
    labelstudio_commands.register(app),
    analytics_commands.register(app),
    bench_commands.register(bench_app),
    compare_control_commands.register(compare_control_app),
):
    _COMMAND_EXPORTS.update(_exports)

globals().update(_COMMAND_EXPORTS)


if __name__ == "__main__":
    app()
