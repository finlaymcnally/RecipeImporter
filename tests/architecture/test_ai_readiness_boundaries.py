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


def test_templates_and_llm_orchestrators_stay_thin_facades() -> None:
    templates_text = _read("cookimport/analytics/dashboard_renderers/templates.py")
    knowledge_orchestrator_text = _read("cookimport/llm/codex_farm_knowledge_orchestrator.py")
    recipe_orchestrator_text = _read("cookimport/llm/codex_farm_orchestrator.py")

    assert "from .html_shell import _HTML" in templates_text
    assert "from .script_asset import _JS" in templates_text
    assert "from .style_asset import _CSS" in templates_text
    assert len(templates_text.splitlines()) <= 10

    assert "from cookimport.llm.knowledge_stage.planning import (" in knowledge_orchestrator_text
    assert "from cookimport.llm.knowledge_stage.recovery import (" in knowledge_orchestrator_text
    assert "from cookimport.llm.knowledge_stage.runtime import (" in knowledge_orchestrator_text
    assert len(knowledge_orchestrator_text.splitlines()) <= 20

    assert "recipe_stage as _recipe_stage" in recipe_orchestrator_text
    assert "sys.modules[__name__] = _recipe_stage" in recipe_orchestrator_text
    assert len(recipe_orchestrator_text.splitlines()) <= 10


def test_run_settings_root_exports_helpers_without_reowning_them() -> None:
    run_settings_text = _read("cookimport/config/run_settings.py")

    assert "class RunSettingUiSpec" not in run_settings_text
    assert "def run_settings_ui_specs(" not in run_settings_text
    assert "def build_run_settings(" not in run_settings_text
    assert "class EpubExtractor" not in run_settings_text
    assert "def _ui_meta(" not in run_settings_text
    assert "from .run_settings_builders import build_run_settings" in run_settings_text
    assert "from .run_settings_ui import RunSettingUiSpec, run_settings_ui_specs" in run_settings_text
    assert "from .run_settings_types import (" in run_settings_text


def test_package_owner_modules_exist_for_split_domains() -> None:
    expected_paths = [
        REPO_ROOT / "cookimport" / "cli_support" / "bench.py",
        REPO_ROOT / "cookimport" / "cli_support" / "bench_all_method.py",
        REPO_ROOT / "cookimport" / "cli_support" / "bench_artifacts.py",
        REPO_ROOT / "cookimport" / "cli_support" / "bench_cache.py",
        REPO_ROOT / "cookimport" / "cli_support" / "bench_oracle.py",
        REPO_ROOT / "cookimport" / "cli_support" / "bench_single_book.py",
        REPO_ROOT / "cookimport" / "cli_support" / "bench_single_profile.py",
        REPO_ROOT / "cookimport" / "cli_support" / "progress.py",
        REPO_ROOT / "cookimport" / "cli_support" / "settings_flow.py",
        REPO_ROOT / "cookimport" / "cli_support" / "interactive_flow.py",
        REPO_ROOT / "cookimport" / "parsing" / "canonical_line_roles" / "artifacts.py",
        REPO_ROOT / "cookimport" / "parsing" / "canonical_line_roles" / "planning.py",
        REPO_ROOT / "cookimport" / "parsing" / "canonical_line_roles" / "policy.py",
        REPO_ROOT / "cookimport" / "parsing" / "canonical_line_roles" / "runtime.py",
        REPO_ROOT / "cookimport" / "parsing" / "canonical_line_roles" / "validation.py",
        REPO_ROOT / "cookimport" / "llm" / "knowledge_stage" / "planning.py",
        REPO_ROOT / "cookimport" / "llm" / "knowledge_stage" / "promotion.py",
        REPO_ROOT / "cookimport" / "llm" / "knowledge_stage" / "recovery.py",
        REPO_ROOT / "cookimport" / "llm" / "knowledge_stage" / "reporting.py",
        REPO_ROOT / "cookimport" / "llm" / "knowledge_stage" / "runtime.py",
        REPO_ROOT / "cookimport" / "llm" / "recipe_stage" / "__init__.py",
        REPO_ROOT / "cookimport" / "llm" / "recipe_stage" / "planning.py",
        REPO_ROOT / "cookimport" / "llm" / "recipe_stage" / "runtime.py",
        REPO_ROOT / "cookimport" / "llm" / "recipe_stage" / "validation.py",
        REPO_ROOT / "cookimport" / "llm" / "recipe_stage" / "promotion.py",
        REPO_ROOT / "cookimport" / "llm" / "recipe_stage" / "recovery.py",
        REPO_ROOT / "cookimport" / "llm" / "recipe_stage" / "reporting.py",
        REPO_ROOT / "cookimport" / "staging" / "nonrecipe_authority_contract.py",
        REPO_ROOT / "cookimport" / "staging" / "nonrecipe_seed.py",
        REPO_ROOT / "cookimport" / "staging" / "nonrecipe_routing.py",
        REPO_ROOT / "cookimport" / "staging" / "nonrecipe_authority.py",
        REPO_ROOT / "cookimport" / "staging" / "nonrecipe_review_status.py",
        REPO_ROOT / "cookimport" / "staging" / "recipe_block_evidence.py",
        REPO_ROOT / "cookimport" / "staging" / "knowledge_block_evidence.py",
        REPO_ROOT / "cookimport" / "staging" / "block_label_resolution.py",
        REPO_ROOT / "cookimport" / "analytics" / "dashboard_renderers" / "html_shell.py",
        REPO_ROOT / "cookimport" / "analytics" / "dashboard_renderers" / "style_asset.py",
        REPO_ROOT / "cookimport" / "analytics" / "dashboard_renderers" / "script_asset.py",
        REPO_ROOT / "cookimport" / "analytics" / "dashboard_renderers" / "script_bootstrap.py",
        REPO_ROOT / "cookimport" / "analytics" / "dashboard_renderers" / "script_filters.py",
        REPO_ROOT / "cookimport" / "analytics" / "dashboard_renderers" / "script_compare_control.py",
        REPO_ROOT / "cookimport" / "analytics" / "dashboard_renderers" / "script_tables.py",
        REPO_ROOT / "cookimport" / "config" / "run_settings_ui.py",
        REPO_ROOT / "cookimport" / "config" / "run_settings_builders.py",
        REPO_ROOT / "cookimport" / "config" / "run_settings_types.py",
    ]
    missing = [str(path.relative_to(REPO_ROOT)) for path in expected_paths if not path.exists()]
    assert missing == []


def test_cli_support_root_stays_a_small_facade() -> None:
    cli_support_text = _read("cookimport/cli_support/__init__.py")

    assert '_load_support_submodule("progress")' in cli_support_text
    assert '_load_support_submodule("bench")' in cli_support_text
    assert '_load_support_submodule("settings_flow")' in cli_support_text
    assert '_load_support_submodule("interactive_flow")' in cli_support_text
    assert "app = typer.Typer(" not in cli_support_text
    assert "@app.callback()" not in cli_support_text
    assert "_sync_cli_command_module_globals" not in cli_support_text
    assert len(cli_support_text.splitlines()) <= 2500


def test_second_wave_owner_roots_stay_small_and_explicit() -> None:
    bench_text = _read("cookimport/cli_support/bench.py")
    line_role_text = _read("cookimport/parsing/canonical_line_roles/__init__.py")
    knowledge_text = _read("cookimport/llm/knowledge_stage/__init__.py")
    recipe_stage_text = _read("cookimport/llm/recipe_stage/__init__.py")
    nonrecipe_text = _read("cookimport/staging/nonrecipe_stage.py")
    stage_predictions_text = _read("cookimport/staging/stage_block_predictions.py")
    script_asset_text = _read("cookimport/analytics/dashboard_renderers/script_asset.py")
    run_settings_text = _read("cookimport/config/run_settings.py")

    assert '"bench_all_method"' in bench_text
    assert '"bench_single_book"' in bench_text
    assert '"bench_single_profile"' in bench_text
    assert len(bench_text.splitlines()) <= 80

    assert '("policy", "planning", "validation", "runtime")' in line_role_text
    assert len(line_role_text.splitlines()) <= 500

    assert "from .planning import CodexFarmNonrecipeKnowledgeReviewResult" in knowledge_text
    assert "from .recovery import _preflight_knowledge_shard" in knowledge_text
    assert "from .runtime import run_codex_farm_nonrecipe_knowledge_review" in knowledge_text
    assert len(knowledge_text.splitlines()) <= 40

    assert "from . import planning as _planning_module" in recipe_stage_text
    assert "from . import runtime as _runtime_module" in recipe_stage_text
    assert "from . import validation as _validation_module" in recipe_stage_text
    assert len(recipe_stage_text.splitlines()) <= 80

    assert "build_nonrecipe_authority_contract" in nonrecipe_text
    assert "build_nonrecipe_routing_result" in nonrecipe_text
    assert len(nonrecipe_text.splitlines()) <= 350

    assert "build_recipe_block_evidence" in stage_predictions_text
    assert "build_knowledge_block_evidence" in stage_predictions_text
    assert "resolve_stage_block_label" in stage_predictions_text
    assert len(stage_predictions_text.splitlines()) <= 160

    assert "from .script_bootstrap import _JS_BOOTSTRAP" in script_asset_text
    assert "from .script_filters import _JS_FILTERS" in script_asset_text
    assert "from .script_compare_control import _JS_COMPARE_CONTROL" in script_asset_text
    assert "from .script_tables import _JS_TABLES" in script_asset_text
    assert len(script_asset_text.splitlines()) <= 20

    assert "class RunSettings(BaseModel):" in run_settings_text
    assert len(run_settings_text.splitlines()) <= 1225


def test_cli_root_stays_a_plain_composition_root() -> None:
    cli_text = _read("cookimport/cli.py")

    assert "from cookimport.cli_support import *" not in cli_text
    assert "_compat_export" not in cli_text
    assert "_publish_runtime_compat_exports" not in cli_text
    assert "_wrap_typer_callbacks" not in cli_text
    assert "from cookimport import cli_support as _support" in cli_text
    assert "interactive_commands.register_callback(app)" in cli_text
    assert "stage_commands.register(app)" in cli_text
    assert "bench_commands.register(bench_app)" in cli_text
    assert "compare_control_commands.register(compare_control_app)" in cli_text
    assert len(cli_text.splitlines()) <= 80
