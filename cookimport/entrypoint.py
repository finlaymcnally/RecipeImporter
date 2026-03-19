from __future__ import annotations

import sys

from cookimport.cli import DEFAULT_INPUT, DEFAULT_OUTPUT, _fail, _load_settings, app, stage
from cookimport.config.run_settings import (
    RUN_SETTING_CONTRACT_FULL,
    RunSettings,
    project_run_config_payload,
)
from cookimport.config.run_settings_adapters import (
    build_stage_call_kwargs_from_run_settings,
)


def main() -> None:
    args = sys.argv[1:]
    allow_codex = False
    filtered_args: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--allow-codex":
            allow_codex = True
            index += 1
            continue
        filtered_args.append(arg)
        index += 1
    args = filtered_args
    settings = _load_settings()
    run_settings = RunSettings.from_dict(
        project_run_config_payload(settings, contract=RUN_SETTING_CONTRACT_FULL),
        warn_context="import entrypoint global settings",
    )
    common_args = build_stage_call_kwargs_from_run_settings(
        run_settings,
        out=DEFAULT_OUTPUT,
        mapping=None,
        overrides=None,
        limit=None,
        write_markdown=True,
    )
    common_args["allow_codex"] = allow_codex
    if not args:
        stage(path=DEFAULT_INPUT, **common_args)
        return
    if len(args) == 1:
        try:
            limit = int(args[0])
        except ValueError:
            limit = None
        if limit is not None:
            if limit <= 0:
                _fail("Limit must be a positive integer.")
            stage(path=DEFAULT_INPUT, **{**common_args, "limit": limit})
            return
    sys.argv = [sys.argv[0], *args]
    app()
