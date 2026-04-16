from __future__ import annotations

import importlib.util
import configparser
from types import SimpleNamespace

from tests.paths import REPO_ROOT


def _load_tests_conftest():
    module_path = REPO_ROOT / "tests" / "conftest.py"
    spec = importlib.util.spec_from_file_location("tests_conftest_module", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tests_conftest = _load_tests_conftest()


def _config_with_args(*args: str) -> SimpleNamespace:
    return SimpleNamespace(invocation_params=SimpleNamespace(args=args))


def test_verbose_output_opt_out_only_applies_to_one_explicit_test_target(
    monkeypatch,
) -> None:
    monkeypatch.setenv("COOKIMPORT_PYTEST_VERBOSE_OUTPUT", "1")

    assert tests_conftest._should_honor_verbose_output(
        _config_with_args("tests/cli/test_cli_limits.py::test_cli_help")
    )
    assert not tests_conftest._should_honor_verbose_output(
        _config_with_args("tests/cli")
    )
    assert not tests_conftest._should_honor_verbose_output(
        _config_with_args("-m", "cli")
    )
    assert not tests_conftest._should_honor_verbose_output(
        _config_with_args("tests/cli/test_cli_limits.py", "tests/core/test_atoms.py")
    )


def test_failure_hints_prefer_compact_scoped_rerun(monkeypatch) -> None:
    lines: list[str] = []

    class _Reporter:
        def write_line(self, line: str = "") -> None:
            lines.append(line)

    monkeypatch.setattr(tests_conftest, "_HINTS_EMITTED", False)
    monkeypatch.setattr(tests_conftest, "_FAILED_MARKERS", {"cli"})
    monkeypatch.setattr(
        tests_conftest,
        "_FAILED_NODEIDS",
        ["tests/cli/test_cli_limits.py::test_cli_help"],
    )

    tests_conftest._emit_failure_hints(_Reporter())

    assert not any(line.startswith("log: docs/") for line in lines)
    assert "rerun: pytest tests/cli/test_cli_limits.py::test_cli_help" in lines
    assert any(
        line.startswith("deep-debug: after a scoped compact rerun")
        for line in lines
    )
    assert not any(line.startswith("verbose: COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1") for line in lines)


def test_pytest_ini_uses_sys_capture_for_repo_default_runs() -> None:
    parser = configparser.ConfigParser()
    parser.read(REPO_ROOT / "pytest.ini", encoding="utf-8")

    addopts = parser.get("pytest", "addopts")

    assert "--capture=sys" in addopts.split()
