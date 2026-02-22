from __future__ import annotations

import json
from pathlib import Path

import pytest

from cookimport.bench.runner import run_suite
from cookimport.bench.suite import BenchItem, BenchSuite
from cookimport.bench.sweep import run_sweep


def _fake_eval_result() -> dict[str, object]:
    return {
        "report": {
            "counts": {
                "gold_total": 1,
                "pred_total": 1,
                "gold_matched": 1,
                "pred_matched": 1,
                "gold_missed": 0,
                "pred_false_positive": 0,
            },
            "recall": 1.0,
            "precision": 1.0,
            "prediction_density": 1.0,
            "per_label": {},
        },
        "missed_gold": [],
        "false_positive_preds": [],
    }


def test_run_suite_progress_messages_include_item_counters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_alpha = tmp_path / "input" / "alpha.epub"
    source_beta = tmp_path / "input" / "beta.epub"
    source_alpha.parent.mkdir(parents=True, exist_ok=True)
    source_alpha.write_text("alpha", encoding="utf-8")
    source_beta.write_text("beta", encoding="utf-8")

    suite = BenchSuite(
        name="progress-suite",
        items=[
            BenchItem(item_id="alpha", source_path="input/alpha.epub", gold_dir="gold/alpha"),
            BenchItem(item_id="beta", source_path="input/beta.epub", gold_dir="gold/beta"),
        ],
    )

    def _fake_build_pred_run_for_source(
        source_path: Path,
        out_dir: Path,
        *,
        config: dict | None = None,
        progress_callback=None,
        **_: object,
    ) -> Path:
        run_root = out_dir / f"{source_path.stem}_pred_run"
        run_root.mkdir(parents=True, exist_ok=True)
        (run_root / "label_studio_tasks.jsonl").write_text("{}\n", encoding="utf-8")
        (run_root / "manifest.json").write_text(
            json.dumps({"source_file": str(source_path), "source_hash": "abc123"}),
            encoding="utf-8",
        )
        if progress_callback is not None:
            progress_callback("Converting source...")
        return run_root

    monkeypatch.setattr(
        "cookimport.bench.runner.build_pred_run_for_source",
        _fake_build_pred_run_for_source,
    )
    monkeypatch.setattr("cookimport.bench.runner.load_gold_freeform_ranges", lambda _path: [])
    monkeypatch.setattr("cookimport.bench.runner.load_predicted_labeled_ranges", lambda _path: [])
    monkeypatch.setattr(
        "cookimport.bench.runner.evaluate_predicted_vs_freeform",
        lambda *_args, **_kwargs: _fake_eval_result(),
    )

    progress_messages: list[str] = []
    run_suite(
        suite,
        tmp_path / "runs",
        repo_root=tmp_path,
        progress_callback=progress_messages.append,
    )

    assert "item 1/2 [alpha] Processing..." in progress_messages
    assert "item 1/2 [alpha] Converting source..." in progress_messages
    assert any(msg.startswith("item 2/2 [beta] Done. recall=") for msg in progress_messages)


def test_run_sweep_progress_messages_include_config_and_nested_item_counters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    suite = BenchSuite(
        name="progress-sweep",
        items=[
            BenchItem(item_id="alpha", source_path="input/alpha.epub", gold_dir="gold/alpha"),
        ],
    )

    def _fake_run_suite(
        _suite: BenchSuite,
        out_dir: Path,
        *,
        repo_root: Path,
        config: dict | None = None,
        progress_callback=None,
        **_: object,
    ) -> tuple[Path, dict[str, float]]:
        if progress_callback is not None:
            progress_callback("item 1/1 [alpha] Evaluating...")
        run_root = out_dir / "run"
        run_root.mkdir(parents=True, exist_ok=True)
        return run_root, {"recall": 0.6, "precision": 0.6}

    monkeypatch.setattr("cookimport.bench.sweep.run_suite", _fake_run_suite)

    progress_messages: list[str] = []
    run_sweep(
        suite,
        tmp_path / "sweep_runs",
        repo_root=tmp_path,
        budget=2,
        seed=7,
        progress_callback=progress_messages.append,
    )

    assert any(msg.startswith("config 1/2: ") for msg in progress_messages)
    assert "config 1/2 | item 1/1 [alpha] Evaluating..." in progress_messages
    assert "config 2/2 | item 1/1 [alpha] Evaluating..." in progress_messages
    assert any(
        msg.startswith("Sweep complete. Best score=") and "config 1/2" in msg
        for msg in progress_messages
    )
