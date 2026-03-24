from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_cli_commands_do_not_wildcard_import_cli_support() -> None:
    cli_commands_dir = REPO_ROOT / "cookimport" / "cli_commands"
    offenders = [
        path.name
        for path in sorted(cli_commands_dir.glob("*.py"))
        if "from cookimport.cli_support import *" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_run_settings_contracts_stays_model_agnostic() -> None:
    contracts_text = _read("cookimport/config/run_settings_contracts.py")
    assert "RunSettings" not in contracts_text
    assert "from .run_settings import" not in contracts_text
    assert "from cookimport.config.run_settings import" not in contracts_text


def test_templates_and_knowledge_orchestrator_stay_thin_facades() -> None:
    templates_text = _read("cookimport/analytics/dashboard_renderers/templates.py")
    orchestrator_text = _read("cookimport/llm/codex_farm_knowledge_orchestrator.py")

    assert "from .html_shell import _HTML" in templates_text
    assert "from .script_asset import _JS" in templates_text
    assert "from .style_asset import _CSS" in templates_text
    assert len(templates_text.splitlines()) <= 10

    assert "knowledge_stage as _knowledge_stage" in orchestrator_text
    assert "sys.modules[__name__] = _knowledge_stage" in orchestrator_text
    assert len(orchestrator_text.splitlines()) <= 12


def test_run_settings_root_exports_helpers_without_reowning_them() -> None:
    run_settings_text = _read("cookimport/config/run_settings.py")

    assert "class RunSettingUiSpec" not in run_settings_text
    assert "def run_settings_ui_specs(" not in run_settings_text
    assert "def build_run_settings(" not in run_settings_text
    assert "from .run_settings_builders import build_run_settings" in run_settings_text
    assert "from .run_settings_ui import RunSettingUiSpec, run_settings_ui_specs" in run_settings_text


def test_package_owner_modules_exist_for_split_domains() -> None:
    expected_paths = [
        REPO_ROOT / "cookimport" / "cli_support" / "bench.py",
        REPO_ROOT / "cookimport" / "cli_support" / "progress.py",
        REPO_ROOT / "cookimport" / "cli_support" / "settings_flow.py",
        REPO_ROOT / "cookimport" / "cli_support" / "interactive_flow.py",
        REPO_ROOT / "cookimport" / "parsing" / "canonical_line_roles" / "artifacts.py",
        REPO_ROOT / "cookimport" / "llm" / "knowledge_stage" / "reporting.py",
        REPO_ROOT / "cookimport" / "analytics" / "dashboard_renderers" / "html_shell.py",
        REPO_ROOT / "cookimport" / "analytics" / "dashboard_renderers" / "style_asset.py",
        REPO_ROOT / "cookimport" / "analytics" / "dashboard_renderers" / "script_asset.py",
        REPO_ROOT / "cookimport" / "config" / "run_settings_ui.py",
        REPO_ROOT / "cookimport" / "config" / "run_settings_builders.py",
    ]
    missing = [str(path.relative_to(REPO_ROOT)) for path in expected_paths if not path.exists()]
    assert missing == []


def test_cli_support_root_stays_a_small_facade() -> None:
    cli_support_text = _read("cookimport/cli_support/__init__.py")

    assert "from . import progress as _progress_module" in cli_support_text
    assert "from . import bench as _bench_module" in cli_support_text
    assert "from . import settings_flow as _settings_flow_module" in cli_support_text
    assert "from . import interactive_flow as _interactive_flow_module" in cli_support_text
    assert len(cli_support_text.splitlines()) <= 2500
