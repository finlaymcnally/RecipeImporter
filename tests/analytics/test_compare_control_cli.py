from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from cookimport.cli import app


runner = CliRunner()


def _sample_records() -> list[dict[str, object]]:
    base = "/tmp/golden/benchmark-vs-golden/2026-03-03_23.00.00/single-offline-benchmark/book"
    return [
        {
            "run_timestamp": "2026-03-03_23.00.00",
            "artifact_dir": f"{base}/codexfarm",
            "strict_accuracy": 0.82,
            "source_file": "book.epub",
            "run_config": {
                "llm_recipe_pipeline": "codex-recipe-shard-v1",
                "line_role_pipeline": "codex-line-role-shard-v1",
                "codex_farm_model": "gpt-5",
                "codex_farm_reasoning_effort": "medium",
            },
        },
        {
            "run_timestamp": "2026-03-03_23.00.00",
            "artifact_dir": f"{base}/vanilla",
            "strict_accuracy": 0.74,
            "source_file": "book.epub",
            "run_config": {
                "llm_recipe_pipeline": "off",
                "line_role_pipeline": "off",
            },
        },
    ]


def test_compare_control_run_returns_machine_json(monkeypatch) -> None:
    monkeypatch.setattr(
        "cookimport.analytics.compare_control_engine.load_dashboard_records",
        lambda **_: _sample_records(),
    )

    result = runner.invoke(
        app,
        [
            "compare-control",
            "run",
            "--action",
            "analyze",
            "--view",
            "raw",
            "--outcome-field",
            "strict_accuracy",
            "--compare-field",
            "ai_model",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["result"]["analysis"]["type"] == "categorical"
    assert payload["result"]["compare_field"] == "ai_model"


def test_compare_control_run_returns_structured_domain_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        "cookimport.analytics.compare_control_engine.load_dashboard_records",
        lambda **_: _sample_records(),
    )

    result = runner.invoke(
        app,
        [
            "compare-control",
            "run",
            "--action",
            "subset_filter_patch",
            "--compare-field",
            "ai_model",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_selected_groups"


def test_compare_control_run_supports_insights_action(monkeypatch) -> None:
    monkeypatch.setattr(
        "cookimport.analytics.compare_control_engine.load_dashboard_records",
        lambda **_: _sample_records(),
    )

    result = runner.invoke(
        app,
        [
            "compare-control",
            "run",
            "--action",
            "insights",
            "--outcome-field",
            "strict_accuracy",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["result"]["profile"]["candidate_rows"] >= 1
    assert "highlights" in payload["result"]
    assert "suggested_queries" in payload["result"]


def test_compare_control_agent_handles_multiple_requests_and_bad_json(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "cookimport.analytics.compare_control_engine.load_dashboard_records",
        lambda **_: _sample_records(),
    )

    input_lines = "\n".join(
        [
            json.dumps({"id": "req-1", "action": "ping", "payload": {}}),
            json.dumps(
                {
                    "id": "req-2",
                    "action": "fields",
                    "payload": {
                        "filters": {
                            "quick_filters": {
                                "official_full_golden_only": False,
                                "exclude_ai_tests": False,
                            }
                        }
                    },
                }
            ),
            "not-json",
            json.dumps(
                {
                    "id": "req-3",
                    "action": "subset_filter_patch",
                    "payload": {
                        "compare_field": "ai_model",
                        "selected_groups": ["gpt-5"],
                    },
                }
            ),
            "",
        ]
    )

    result = runner.invoke(
        app,
        ["compare-control", "agent", "--output-root", str(tmp_path / "out")],
        input=input_lines,
    )

    assert result.exit_code == 0
    responses = [
        json.loads(line)
        for line in result.stdout.splitlines()
        if line.strip()
    ]

    assert responses[0]["id"] == "req-1"
    assert responses[0]["ok"] is True
    assert responses[0]["result"] == {"pong": True}

    assert responses[1]["id"] == "req-2"
    assert responses[1]["ok"] is True
    assert responses[1]["result"]["candidate_rows"] >= 1

    assert responses[2]["ok"] is False
    assert responses[2]["error"]["code"] == "invalid_json"

    assert responses[3]["id"] == "req-3"
    assert responses[3]["ok"] is True
    assert responses[3]["result"]["compare_field"] == "ai_model"


def test_compare_control_run_applies_discovery_preferences(monkeypatch) -> None:
    records = [
        {
            "strict_accuracy": 0.9,
            "driver_field": "A",
            "noise_id": "row-1",
        },
        {
            "strict_accuracy": 0.8,
            "driver_field": "A",
            "noise_id": "row-2",
        },
        {
            "strict_accuracy": 0.2,
            "driver_field": "B",
            "noise_id": "row-3",
        },
        {
            "strict_accuracy": 0.1,
            "driver_field": "B",
            "noise_id": "row-4",
        },
    ]
    monkeypatch.setattr(
        "cookimport.analytics.compare_control_engine.load_dashboard_records",
        lambda **_: records,
    )

    result = runner.invoke(
        app,
        [
            "compare-control",
            "run",
            "--action",
            "discover",
            "--outcome-field",
            "strict_accuracy",
            "--filters-json",
            '{"quick_filters":{"official_full_golden_only":false,"exclude_ai_tests":false}}',
            "--discover-exclude-field",
            "noise_id",
            "--discover-max-cards",
            "2",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    fields = [
        str(item.get("field") or "")
        for item in payload["result"]["analysis"]["items"]
    ]
    assert len(fields) <= 2
    assert "noise_id" not in fields


def test_compare_control_discovery_preferences_writes_dashboard_ui_state(
    tmp_path: Path,
) -> None:
    dashboard_dir = tmp_path / "dashboard"

    result = runner.invoke(
        app,
        [
            "compare-control",
            "discovery-preferences",
            "--dashboard-dir",
            str(dashboard_dir),
            "--exclude-field",
            "processed_report_path",
            "--prefer-field",
            "ai_model",
            "--demote-pattern",
            "hash",
            "--max-cards",
            "5",
        ],
    )

    assert result.exit_code == 0
    ui_state_path = dashboard_dir / "assets" / "dashboard_ui_state.json"
    assert ui_state_path.exists()
    payload = json.loads(ui_state_path.read_text(encoding="utf-8"))
    prefs = (
        payload["previous_runs"]["compare_control"]["discovery_preferences"]
    )
    assert prefs["exclude_fields"] == ["processed_report_path"]
    assert prefs["prefer_fields"] == ["ai_model"]
    assert prefs["demote_patterns"] == ["hash"]
    assert prefs["max_cards"] == 5


def test_compare_control_dashboard_state_writes_primary_set(
    tmp_path: Path,
) -> None:
    dashboard_dir = tmp_path / "dashboard"

    result = runner.invoke(
        app,
        [
            "compare-control",
            "dashboard-state",
            "--dashboard-dir",
            str(dashboard_dir),
            "--outcome-field",
            "strict_accuracy",
            "--compare-field",
            "ai_model",
            "--hold-constant-field",
            "source_name",
            "--split-field",
            "ai_effort",
        ],
    )

    assert result.exit_code == 0
    ui_state_path = dashboard_dir / "assets" / "dashboard_ui_state.json"
    assert ui_state_path.exists()
    payload = json.loads(ui_state_path.read_text(encoding="utf-8"))
    compare_control = payload["previous_runs"]["compare_control"]
    assert compare_control["outcome_field"] == "strict_accuracy"
    assert compare_control["compare_field"] == "ai_model"
    assert compare_control["view_mode"] == "raw"
    assert compare_control["hold_constant_fields"] == ["source_name"]
    assert compare_control["split_field"] == "ai_effort"
    assert payload["saved_at"]


def test_compare_control_dashboard_state_writes_secondary_set_layout(
    tmp_path: Path,
) -> None:
    dashboard_dir = tmp_path / "dashboard"

    result = runner.invoke(
        app,
        [
            "compare-control",
            "dashboard-state",
            "--dashboard-dir",
            str(dashboard_dir),
            "--set",
            "secondary",
            "--outcome-field",
            "strict_accuracy",
            "--compare-field",
            "ai_effort",
            "--view",
            "controlled",
            "--selected-group",
            "high",
            "--enable-second-set",
            "--chart-layout",
            "combined",
            "--combined-axis-mode",
            "dual",
        ],
    )

    assert result.exit_code == 0
    ui_state_path = dashboard_dir / "assets" / "dashboard_ui_state.json"
    payload = json.loads(ui_state_path.read_text(encoding="utf-8"))
    compare_control = payload["previous_runs"]["compare_control"]
    assert compare_control["second_set_enabled"] is True
    assert compare_control["chart_layout"] == "combined"
    assert compare_control["combined_axis_mode"] == "dual"
    second_set = compare_control["second_set"]
    assert second_set["outcome_field"] == "strict_accuracy"
    assert second_set["compare_field"] == "ai_effort"
    assert second_set["view_mode"] == "controlled"
    assert second_set["selected_groups"] == ["high"]
