from __future__ import annotations

import builtins
import dis
import importlib
import inspect
import subprocess
import sys
import types

from tests.paths import REPO_ROOT


def test_benchmark_stack_has_no_undefined_names() -> None:
    targets = ["cookimport/cli_commands/labelstudio.py"]

    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "F821", *targets],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        output = "\n".join(
            part for part in (result.stdout.strip(), result.stderr.strip()) if part
        )
        raise AssertionError(
            "Ruff F821 found undefined names in the benchmark command surface:\n"
            f"{output}"
        )


def _walk_code_objects(code: types.CodeType):
    yield code
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            yield from _walk_code_objects(const)


def _iter_module_functions(module):
    for value in vars(module).values():
        if inspect.isfunction(value) and value.__module__ == module.__name__:
            yield value
            continue
        if not inspect.isclass(value) or value.__module__ != module.__name__:
            continue
        for member in vars(value).values():
            function = member
            if isinstance(member, (staticmethod, classmethod)):
                function = member.__func__
            if inspect.isfunction(function) and function.__module__ == module.__name__:
                yield function


def _collect_module_unresolved_globals(module_names: tuple[str, ...]) -> list[str]:
    failures: list[str] = []
    for module_name in module_names:
        module = importlib.import_module(module_name)
        for function in _iter_module_functions(module):
            for code in _walk_code_objects(function.__code__):
                for instruction in dis.get_instructions(code):
                    if instruction.opname not in {"LOAD_GLOBAL", "LOAD_NAME"}:
                        continue
                    name = str(instruction.argval)
                    if name in function.__globals__ or hasattr(builtins, name):
                        continue
                    failures.append(
                        f"{module_name}:{function.__qualname__}:{code.co_name}:{name}"
                    )
    return sorted(set(failures))


def _collect_bootstrapped_benchmark_unresolved_globals() -> list[str]:
    import cookimport.cli_support.bench  # noqa: F401

    return _collect_module_unresolved_globals(
        (
            "cookimport.cli_support.bench_artifacts",
            "cookimport.cli_support.bench_all_method",
            "cookimport.cli_support.bench_cache",
            "cookimport.cli_support.bench_oracle",
            "cookimport.cli_support.progress",
            "cookimport.cli_support.bench_single_book",
            "cookimport.cli_support.bench_single_profile",
            "cookimport.cli_support.bench_compare",
        )
    )


def test_bootstrapped_benchmark_modules_have_no_unresolved_global_loads() -> None:
    failures = _collect_bootstrapped_benchmark_unresolved_globals()
    assert not failures, "Unresolved benchmark globals:\n" + "\n".join(failures)


def test_interactive_cli_modules_have_no_unresolved_global_loads() -> None:
    failures = _collect_module_unresolved_globals(
        (
            "cookimport.cli_support.interactive_flow",
            "cookimport.cli_support.settings_flow",
            "cookimport.cli_commands.stage",
        )
    )
    assert not failures, "Unresolved interactive CLI globals:\n" + "\n".join(failures)
