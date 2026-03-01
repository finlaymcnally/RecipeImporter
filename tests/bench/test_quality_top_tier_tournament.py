from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_tournament_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "quality_top_tier_tournament.py"
    spec = importlib.util.spec_from_file_location(
        "quality_top_tier_tournament",
        script_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_resolve_seed_plan_prefers_explicit_cli_inputs() -> None:
    module = _load_tournament_module()
    seed_plan = module._resolve_seed_plan(
        threshold_seeds=[42, 314, 2718, 4242],
        quick_parsing=True,
        max_seeds=None,
        seed_values=[2718, 42],
        seed_list_raw="42,4242,2718",
    )

    assert seed_plan["seed_source"] == "explicit_cli"
    assert seed_plan["resolved_seeds"] == [2718, 42, 4242]
    assert seed_plan["max_seeds_effective"] is None


def test_resolve_seed_plan_caps_explicit_cli_inputs_with_max_seeds() -> None:
    module = _load_tournament_module()
    seed_plan = module._resolve_seed_plan(
        threshold_seeds=[42, 314, 2718, 4242],
        quick_parsing=False,
        max_seeds=2,
        seed_values=[2718, 42, 42],
        seed_list_raw="314",
    )

    assert seed_plan["seed_source"] == "explicit_cli"
    assert seed_plan["resolved_seeds"] == [2718, 42]
    assert seed_plan["max_seeds_effective"] == 2
    assert seed_plan["seed_resolution"]["max_seeds_applied_to"] == "explicit_cli"


def test_resolve_seed_plan_quick_mode_defaults_to_three_threshold_seeds() -> None:
    module = _load_tournament_module()
    seed_plan = module._resolve_seed_plan(
        threshold_seeds=[42, 314, 2718, 4242],
        quick_parsing=True,
        max_seeds=None,
        seed_values=[],
        seed_list_raw="",
    )

    assert seed_plan["seed_source"] == "thresholds"
    assert seed_plan["resolved_seeds"] == [42, 314, 2718]
    assert seed_plan["max_seeds_effective"] == 3


def test_resolve_seed_plan_rejects_malformed_seed_list() -> None:
    module = _load_tournament_module()
    with pytest.raises(ValueError, match="Invalid --seed-list token"):
        module._resolve_seed_plan(
            threshold_seeds=[42, 314, 2718, 4242],
            quick_parsing=False,
            max_seeds=None,
            seed_values=[],
            seed_list_raw="42,nope,2718",
        )


def test_recommend_phase_b_candidates_clear_winner_prefers_single() -> None:
    module = _load_tournament_module()
    recommendation = module._recommend_phase_b_candidates(
        candidate_rows={
            "cand_a": {"mean_practical_f1_delta": 0.010, "mean_strict_f1_delta": 0.009},
            "cand_b": {"mean_practical_f1_delta": 0.006, "mean_strict_f1_delta": 0.005},
        },
        fold_rows=[
            {
                "comparisons": {
                    "cand_a": {"completed": True, "practical_f1_delta": 0.011},
                    "cand_b": {"completed": True, "practical_f1_delta": 0.004},
                }
            },
            {
                "comparisons": {
                    "cand_a": {"completed": True, "practical_f1_delta": 0.009},
                    "cand_b": {"completed": True, "practical_f1_delta": 0.003},
                }
            },
        ],
    )

    assert recommendation["selected_candidate_ids"] == ["cand_a"]
    assert recommendation["reason_code"] == "clear_winner_or_tied_top_all_unique_folds"
    assert recommendation["evaluated_unique_folds"] == 2
    assert recommendation["top_candidate_winner_or_tied_top_folds"] == 2


def test_recommend_phase_b_candidates_close_top_two_selects_both() -> None:
    module = _load_tournament_module()
    recommendation = module._recommend_phase_b_candidates(
        candidate_rows={
            "cand_a": {"mean_practical_f1_delta": 0.010, "mean_strict_f1_delta": 0.009},
            "cand_b": {"mean_practical_f1_delta": 0.0085, "mean_strict_f1_delta": 0.008},
            "cand_c": {"mean_practical_f1_delta": 0.001, "mean_strict_f1_delta": 0.001},
        },
        fold_rows=[],
    )

    assert recommendation["selected_candidate_ids"] == ["cand_a", "cand_b"]
    assert recommendation["reason_code"] == "top_two_close_mean_practical_delta"
    assert recommendation["top_two_mean_practical_delta_gap"] == pytest.approx(0.0015)


def test_resolve_auto_candidate_selection_from_summary_directory(
    tmp_path: Path,
) -> None:
    module = _load_tournament_module()
    source_dir = tmp_path / "source_tournament"
    _write_json(
        source_dir / "summary.json",
        {
            "baseline_experiment_id": "baseline",
            "candidates": {
                "cand_a": {"mean_practical_f1_delta": 0.010, "mean_strict_f1_delta": 0.009},
                "cand_b": {"mean_practical_f1_delta": 0.006, "mean_strict_f1_delta": 0.005},
            },
            "total_folds": 2,
        },
    )
    _write_json(
        source_dir / "folds.json",
        {
            "folds": [
                {
                    "included_in_gates": True,
                    "comparisons": {
                        "cand_a": {"completed": True, "practical_f1_delta": 0.011},
                        "cand_b": {"completed": True, "practical_f1_delta": 0.003},
                    },
                },
                {
                    "included_in_gates": True,
                    "comparisons": {
                        "cand_a": {"completed": True, "practical_f1_delta": 0.010},
                        "cand_b": {"completed": True, "practical_f1_delta": 0.002},
                    },
                },
            ]
        },
    )

    selection = module._resolve_auto_candidate_selection(
        auto_candidates_from_summary=str(source_dir),
        auto_candidates_from_latest_in="",
        all_experiment_ids=["baseline", "cand_a", "cand_b"],
        baseline_experiment_id="baseline",
    )

    assert selection is not None
    assert selection["mode"] == "summary_path"
    assert selection["selected_candidate_ids"] == ["cand_a"]
    assert selection["recommendation"]["reason_code"] == (
        "clear_winner_or_tied_top_all_unique_folds"
    )


def test_resolve_auto_candidate_selection_from_latest_root(tmp_path: Path) -> None:
    module = _load_tournament_module()
    root = tmp_path / "tournaments"
    older = root / "2026-03-01_09.00.00"
    newer = root / "2026-03-01_09.05.00"
    _write_json(
        older / "summary.json",
        {
            "baseline_experiment_id": "baseline",
            "candidates": {"cand_a": {"mean_practical_f1_delta": 0.005}},
        },
    )
    _write_json(
        newer / "summary.json",
        {
            "baseline_experiment_id": "baseline",
            "candidates": {"cand_b": {"mean_practical_f1_delta": 0.007}},
        },
    )

    selection = module._resolve_auto_candidate_selection(
        auto_candidates_from_summary="",
        auto_candidates_from_latest_in=str(root),
        all_experiment_ids=["baseline", "cand_a", "cand_b"],
        baseline_experiment_id="baseline",
    )

    assert selection is not None
    assert selection["mode"] == "latest_in"
    assert selection["resolved_tournament_dir"] == str(newer)
    assert selection["selected_candidate_ids"] == ["cand_b"]


def test_resolve_max_parallel_experiments_plan_precedence() -> None:
    module = _load_tournament_module()
    cli_plan = module._resolve_max_parallel_experiments_plan(
        cli_value=6,
        threshold_default_value=4,
    )
    threshold_plan = module._resolve_max_parallel_experiments_plan(
        cli_value=None,
        threshold_default_value=4,
    )
    auto_plan = module._resolve_max_parallel_experiments_plan(
        cli_value=None,
        threshold_default_value=None,
    )

    assert cli_plan["effective"] == 6
    assert cli_plan["source"] == "cli"
    assert threshold_plan["effective"] == 4
    assert threshold_plan["source"] == "thresholds_default"
    assert auto_plan["effective"] is None
    assert auto_plan["source"] == "quality_run_auto"


def test_run_quality_run_with_subprogress_reports_checkpoint_updates(
    tmp_path: Path,
) -> None:
    module = _load_tournament_module()
    run_out_dir = tmp_path / "quality_runs"
    worker_script = tmp_path / "fake_quality_worker.py"
    worker_script.write_text(
        """
import json
import pathlib
import sys
import time

run_out_dir = pathlib.Path(sys.argv[1])
run_dir = run_out_dir / "2026-03-01_00.00.00"
run_dir.mkdir(parents=True, exist_ok=True)
(run_dir / "experiments_resolved.json").write_text("{}", encoding="utf-8")

def write_progress(completed: int) -> None:
    total = 3
    pending = [f"exp-{i}" for i in range(max(0, total - completed))]
    checkpoint = {
        "experiment_count_total": total,
        "experiment_count_completed": completed,
        "pending_experiment_ids": pending,
        "status": "complete" if completed >= total else "in_progress",
    }
    (run_dir / "checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")
    (run_dir / "summary.partial.json").write_text(
        json.dumps({"experiment_count": completed}),
        encoding="utf-8",
    )

write_progress(0)
time.sleep(0.15)
write_progress(2)
time.sleep(0.15)
write_progress(3)
""".strip()
        + "\n",
        encoding="utf-8",
    )

    observed_rows: list[dict[str, object]] = []
    run_dir = module._run_quality_run_with_subprogress(
        cmd=[sys.executable, str(worker_script), str(run_out_dir)],
        dry_run=False,
        env=None,
        fold_index=1,
        configured_folds=4,
        run_out_dir=run_out_dir,
        resume_run_dir=None,
        progress_callback=observed_rows.append,
        poll_seconds=0.05,
    )

    assert run_dir is not None
    assert run_dir.name == "2026-03-01_00.00.00"
    completed_values = [int(row["experiment_count_completed"]) for row in observed_rows]
    assert completed_values[0] == 0
    assert 2 in completed_values
    assert completed_values[-1] == 3
