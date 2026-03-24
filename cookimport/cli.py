from __future__ import annotations

import functools
import inspect as pyinspect
from typing import Any, Callable

import typer

from cookimport.cli_support import *  # noqa: F401,F403
from cookimport.cli_support import _sync_cli_command_module_globals as _raw_sync_cli_compat_state
from cookimport import cli_support as _runtime


def _compat_export(
    fn: Callable[..., Any],
    _sync: Callable[[], None] = _raw_sync_cli_compat_state,
) -> Callable[..., Any]:
    @functools.wraps(fn)
    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        _sync()
        return fn(*args, **kwargs)

    setattr(_wrapped, "_codex_cli_compat_export", True)
    return _wrapped


def _publish_runtime_compat_exports() -> None:
    for name, value in tuple(_runtime.__dict__.items()):
        if name.startswith("__"):
            continue
        if name in {"_sync_cli_command_module_globals", "_raw_sync_cli_compat_state"}:
            globals()[name] = value
            continue
        if pyinspect.isfunction(value):
            globals()[name] = _compat_export(value)
        else:
            globals()[name] = value


_publish_runtime_compat_exports()

app = _runtime.app
bench_app = _runtime.bench_app
compare_control_app = _runtime.compare_control_app


def _wrap_typer_callbacks(typer_app: typer.Typer) -> None:
    if typer_app.registered_callback is not None and typer_app.registered_callback.callback is not None:
        typer_app.registered_callback.callback = _compat_export(typer_app.registered_callback.callback)

    for command_info in typer_app.registered_commands:
        if command_info.callback is not None:
            command_info.callback = _compat_export(command_info.callback)

    for group_info in typer_app.registered_groups:
        _wrap_typer_callbacks(group_info.typer_instance)


def _rebuild_cli_apps_from_command_packages() -> tuple[typer.Typer, typer.Typer, typer.Typer]:
    from cookimport.cli_commands import (
        analytics as analytics_commands,
        bench as bench_commands,
        compare_control as compare_control_commands,
        interactive as interactive_commands,
        labelstudio as labelstudio_commands,
        stage as stage_commands,
    )

    root_app = typer.Typer(add_completion=False, invoke_without_command=True)
    bench_group = typer.Typer(name="bench", help="Offline benchmark suite tools.")
    compare_group = typer.Typer(
        name="compare-control",
        help="Backend Compare & Control analytics for CLI and agent workflows.",
    )
    root_app.add_typer(bench_group)
    root_app.add_typer(compare_group, name="compare-control")
    root_app.add_typer(epub_app, name="epub")

    _raw_sync_cli_compat_state()
    interactive_exports = interactive_commands.register_callback(root_app)
    stage_exports = stage_commands.register(root_app)
    labelstudio_exports = labelstudio_commands.register(root_app)
    analytics_exports = analytics_commands.register(root_app)
    bench_exports = bench_commands.register(bench_group)
    compare_control_exports = compare_control_commands.register(compare_group)
    _wrap_typer_callbacks(root_app)

    for export_group in (
        interactive_exports,
        stage_exports,
        labelstudio_exports,
        analytics_exports,
        bench_exports,
        compare_control_exports,
    ):
        for name, value in export_group.items():
            globals()[name] = _compat_export(value) if callable(value) else value

    global app, bench_app, compare_control_app
    app = root_app
    bench_app = bench_group
    compare_control_app = compare_group
    _runtime.app = root_app
    _runtime.bench_app = bench_group
    _runtime.compare_control_app = compare_group
    _publish_runtime_compat_exports()
    for export_group in (
        interactive_exports,
        stage_exports,
        labelstudio_exports,
        analytics_exports,
        bench_exports,
        compare_control_exports,
    ):
        for name, value in export_group.items():
            globals()[name] = _compat_export(value) if callable(value) else value
    return root_app, bench_group, compare_group


app, bench_app, compare_control_app = _rebuild_cli_apps_from_command_packages()


if __name__ == "__main__":
    app()
