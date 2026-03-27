from __future__ import annotations

import builtins
import dis
import importlib
import inspect
import pkgutil
import types

import cookimport.llm as llm_pkg


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


def _discover_llm_module_names() -> list[str]:
    names = [
        module_info.name
        for module_info in pkgutil.walk_packages(
            llm_pkg.__path__,
            llm_pkg.__name__ + ".",
        )
        if module_info.name != "cookimport.llm.__main__"
    ]
    return sorted(set(names))


def test_llm_modules_import_and_have_no_unresolved_global_loads() -> None:
    import_failures: list[str] = []
    unresolved_failures: list[str] = []

    for module_name in _discover_llm_module_names():
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            import_failures.append(f"{module_name}: {exc!r}")
            continue

        for function in _iter_module_functions(module):
            for code in _walk_code_objects(function.__code__):
                for instruction in dis.get_instructions(code):
                    if instruction.opname not in {"LOAD_GLOBAL", "LOAD_NAME"}:
                        continue
                    name = str(instruction.argval)
                    if name in function.__globals__ or hasattr(builtins, name):
                        continue
                    unresolved_failures.append(
                        f"{module_name}:{function.__qualname__}:{code.co_name}:{name}"
                    )

    messages: list[str] = []
    if import_failures:
        messages.append("LLM import failures:")
        messages.extend(sorted(set(import_failures)))
    if unresolved_failures:
        messages.append("LLM unresolved globals:")
        messages.extend(sorted(set(unresolved_failures)))
    assert not messages, "\n".join(messages)
