from __future__ import annotations

import importlib
import inspect
import pkgutil

import cookimport.cli  # noqa: F401
import cookimport.cli_support as cli_support


def _discover_command_wrappers() -> list[tuple[str, str]]:
    wrappers: list[tuple[str, str]] = []
    for module_info in pkgutil.iter_modules(
        cli_support.__path__, cli_support.__name__ + "."
    ):
        module = importlib.import_module(module_info.name)
        for name, value in vars(module).items():
            if not inspect.isfunction(value):
                continue
            if value.__module__ != module.__name__:
                continue
            if not name.startswith("_") or not name.endswith("_command"):
                continue
            wrappers.append((module.__name__, name))
    return sorted(wrappers)


def test_command_wrappers_resolve_expected_command_after_export_attr_is_missing(
    monkeypatch,
) -> None:
    wrappers = _discover_command_wrappers()
    assert wrappers

    for module_name, wrapper_name in wrappers:
        module = importlib.import_module(module_name)
        wrapper = getattr(module, wrapper_name)
        expected_name = wrapper_name[1:-8]

        resolved = wrapper()
        assert callable(resolved), f"{module_name}.{wrapper_name} did not return a callable"
        assert (
            resolved.__name__ == expected_name
        ), f"{module_name}.{wrapper_name} resolved {resolved.__module__}.{resolved.__name__}"

        owner_module = importlib.import_module(resolved.__module__)
        monkeypatch.delattr(owner_module, expected_name, raising=False)

        recovered = wrapper()
        assert callable(recovered), f"{module_name}.{wrapper_name} did not recover a callable"
        assert recovered.__name__ == expected_name
        assert recovered is getattr(owner_module, expected_name)
        assert inspect.signature(recovered) == inspect.signature(
            getattr(owner_module, expected_name)
        )
