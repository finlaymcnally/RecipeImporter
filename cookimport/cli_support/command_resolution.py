from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

import typer


def resolve_registered_command(module_path: str, command_name: str) -> Callable[..., Any]:
    module = importlib.import_module(module_path)
    resolved = getattr(module, command_name, None)
    if callable(resolved):
        return resolved

    importlib.import_module("cookimport.cli")
    resolved = getattr(module, command_name, None)
    if callable(resolved):
        return resolved

    register = getattr(module, "register", None)
    if callable(register):
        exports = register(typer.Typer(add_completion=False))
        candidate = exports.get(command_name)
        if callable(candidate):
            return candidate

    resolved = getattr(module, command_name, None)
    if callable(resolved):
        return resolved

    raise AttributeError(
        f"Unable to resolve registered command {module_path}.{command_name}"
    )
