from __future__ import annotations

import builtins
import dis
import importlib
import inspect
import pkgutil
import types

from cookimport.llm.knowledge_stage.recovery import (
    _KnowledgeRecoveryGovernor,
    _detect_knowledge_workspace_stage_violation,
)
import cookimport.llm.knowledge_stage as knowledge_stage_pkg


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


def test_knowledge_workspace_stage_violation_returns_inventory_dump_violation() -> None:
    violation = _detect_knowledge_workspace_stage_violation(
        "cat assigned_shards.json"
    )

    assert violation is not None
    assert violation.policy == "knowledge_assigned_shards_inventory_dump"
    assert violation.reason_code == "watchdog_phase_contract_bypass_inventory_dump"
    assert violation.enforce is False


def test_knowledge_followup_governor_returns_decision_object() -> None:
    governor = _KnowledgeRecoveryGovernor()

    decision = governor.allow_followup(
        kind="repair",
        worker_id="worker-1",
        failure_signature="validation_error",
        near_miss=False,
    )

    assert decision.allowed is False
    assert decision.reason_code == "repair_skipped_not_near_miss"


def test_knowledge_stage_modules_have_no_unresolved_global_loads() -> None:
    module_names = [
        module_info.name
        for module_info in pkgutil.iter_modules(
            knowledge_stage_pkg.__path__,
            knowledge_stage_pkg.__name__ + ".",
        )
    ]

    failures: list[str] = []
    for module_name in sorted(module_names):
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

    assert not failures, "Unresolved knowledge-stage globals:\n" + "\n".join(
        sorted(set(failures))
    )
