from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import cookimport.cli as cli
from tests.labelstudio.benchmark_helper_support import _patch_cli_attr

def test_labelstudio_eval_run_config_threads_line_role_knobs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pred_run = tmp_path / "pred-run"
    pred_run.mkdir(parents=True, exist_ok=True)
    gold_spans = tmp_path / "gold.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    output_dir = tmp_path / "eval"

    _patch_cli_attr(monkeypatch, "load_predicted_labeled_ranges",
        lambda *_args, **_kwargs: [],
    )
    _patch_cli_attr(monkeypatch, "load_gold_freeform_ranges",
        lambda *_args, **_kwargs: [],
    )
    _patch_cli_attr(monkeypatch, "evaluate_predicted_vs_freeform",
        lambda *_args, **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                }
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    _patch_cli_attr(monkeypatch, "format_freeform_eval_report_md",
        lambda *_args, **_kwargs: "# report\n",
    )
    _patch_cli_attr(monkeypatch, "_load_pred_run_recipe_context",
        lambda *_args, **_kwargs: SimpleNamespace(
            recipes=0,
            source_file="demo.epub",
            source_hash="hash-demo",
            processed_report_path=None,
            run_config={
                "llm_recipe_pipeline": "codex-recipe-shard-v1",
                "atomic_block_splitter": "atomic-v1",
                "line_role_pipeline": "deterministic-route-v2",
            },
            run_config_hash="cfg-hash",
            run_config_summary="cfg-summary",
        ),
    )
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.append_benchmark_csv",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "cookimport.analytics.perf_report.history_path",
        lambda *_args, **_kwargs: tmp_path / "history.csv",
    )
    _patch_cli_attr(monkeypatch, "_refresh_dashboard_after_history_write",
        lambda **_kwargs: None,
    )
    captured_manifest: dict[str, object] = {}

    def _capture_manifest(*_args, **kwargs) -> None:
        captured_manifest["run_config"] = kwargs.get("run_config")
        captured_manifest["artifacts"] = kwargs.get("artifacts")

    _patch_cli_attr(monkeypatch, "_write_eval_run_manifest", _capture_manifest)

    cli.labelstudio_eval(
        pred_run=pred_run,
        gold_spans=gold_spans,
        output_dir=output_dir,
        llm_recipe_pipeline="off",
        atomic_block_splitter="off",
        line_role_pipeline="off",
    )

    run_config = captured_manifest.get("run_config")
    assert isinstance(run_config, dict)
    assert run_config["llm_recipe_pipeline"] == "off"
    assert run_config["atomic_block_splitter"] == "off"
    assert run_config["line_role_pipeline"] == "off"

    artifacts = captured_manifest.get("artifacts")
    assert isinstance(artifacts, dict)
    assert artifacts["artifact_root_dir"] == str(pred_run)
    assert "pred_run_dir" not in artifacts
