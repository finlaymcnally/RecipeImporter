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
                "llm_recipe_pipeline": "codex-farm-3pass-v1",
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
