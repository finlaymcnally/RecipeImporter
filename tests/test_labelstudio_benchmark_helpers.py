from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

import cookimport.cli as cli


def test_discover_freeform_gold_exports_orders_newest_first(tmp_path: Path) -> None:
    older = tmp_path / "2026-01-01-000000" / "labelstudio" / "book" / "exports"
    newer = tmp_path / "2026-01-02-000000" / "labelstudio" / "book" / "exports"
    older.mkdir(parents=True, exist_ok=True)
    newer.mkdir(parents=True, exist_ok=True)
    older_path = older / "freeform_span_labels.jsonl"
    newer_path = newer / "freeform_span_labels.jsonl"
    older_path.write_text("{}\n", encoding="utf-8")
    newer_path.write_text("{}\n", encoding="utf-8")

    discovered = cli._discover_freeform_gold_exports(tmp_path)
    assert discovered[0] == newer_path
    assert discovered[1] == older_path


def test_discover_freeform_gold_exports_includes_golden_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_root = tmp_path / "output"
    golden_root = tmp_path / "golden"
    exports = golden_root / "sample" / "freeform" / "2026-02-10_20:36:41" / "labelstudio" / "book" / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    golden_path = exports / "freeform_span_labels.jsonl"
    golden_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(cli, "DEFAULT_GOLDEN", golden_root)

    discovered = cli._discover_freeform_gold_exports(output_root)
    assert golden_path in discovered


def test_display_gold_export_path_relative_to_golden_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_root = tmp_path / "output"
    golden_root = tmp_path / "golden"
    path = golden_root / "sample" / "freeform" / "exports" / "freeform_span_labels.jsonl"
    monkeypatch.setattr(cli, "DEFAULT_GOLDEN", golden_root)

    display = cli._display_gold_export_path(path, output_root)
    assert display == "sample/freeform/exports/freeform_span_labels.jsonl"


def test_discover_prediction_runs_orders_newest_first(tmp_path: Path) -> None:
    older = tmp_path / "2026-01-01-000000" / "labelstudio" / "book-a"
    newer = tmp_path / "2026-01-02-000000" / "labelstudio" / "book-b"
    older.mkdir(parents=True, exist_ok=True)
    newer.mkdir(parents=True, exist_ok=True)
    older_marker = older / "label_studio_tasks.jsonl"
    newer_marker = newer / "label_studio_tasks.jsonl"
    older_marker.write_text("{}\n", encoding="utf-8")
    newer_marker.write_text("{}\n", encoding="utf-8")

    discovered = cli._discover_prediction_runs(tmp_path)
    assert discovered[0] == newer
    assert discovered[1] == older


def test_infer_source_file_from_manifest_path(tmp_path: Path) -> None:
    source = tmp_path / "data" / "input" / "book.epub"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("x", encoding="utf-8")
    run_root = tmp_path / "run"
    exports = run_root / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    gold_path = exports / "freeform_span_labels.jsonl"
    gold_path.write_text("{}\n", encoding="utf-8")
    (run_root / "manifest.json").write_text(
        json.dumps({"source_file": str(source)}), encoding="utf-8"
    )

    inferred = cli._infer_source_file_from_freeform_gold(gold_path)
    assert inferred == source


def test_infer_source_file_from_gold_row_uses_default_input(
    tmp_path: Path, monkeypatch
) -> None:
    input_root = tmp_path / "data" / "input"
    input_root.mkdir(parents=True, exist_ok=True)
    source = input_root / "book.epub"
    source.write_text("x", encoding="utf-8")
    monkeypatch.setattr(cli, "DEFAULT_INPUT", input_root)

    run_root = tmp_path / "run"
    exports = run_root / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    gold_path = exports / "freeform_span_labels.jsonl"
    gold_path.write_text(
        json.dumps({"source_file": "book.epub", "label": "NOTES"}) + "\n",
        encoding="utf-8",
    )

    inferred = cli._infer_source_file_from_freeform_gold(gold_path)
    assert inferred == source


def test_labelstudio_benchmark_direct_call_uses_real_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_resolve_labelstudio_settings", lambda *_: ("http://example", "k"))
    monkeypatch.setattr(cli, "_discover_freeform_gold_exports", lambda *_: [])
    with pytest.raises(cli.typer.Exit):
        cli.labelstudio_benchmark(output_dir=tmp_path / "empty-golden")


def test_labelstudio_commands_default_output_roots() -> None:
    import_param = inspect.signature(cli.labelstudio_import).parameters["output_dir"]
    export_param = inspect.signature(cli.labelstudio_export).parameters["output_dir"]
    benchmark_param = inspect.signature(cli.labelstudio_benchmark).parameters["output_dir"]

    assert getattr(import_param.default, "default", None) == cli.DEFAULT_GOLDEN
    assert getattr(export_param.default, "default", None) == cli.DEFAULT_GOLDEN
    assert benchmark_param.default == cli.DEFAULT_GOLDEN


def test_co_locate_prediction_run_for_benchmark_moves_into_eval_dir(tmp_path: Path) -> None:
    timestamp_root = tmp_path / "output" / "2026-02-10_21:09:52"
    pred_run = timestamp_root / "labelstudio" / "book"
    pred_run.mkdir(parents=True, exist_ok=True)
    marker = pred_run / "label_studio_tasks.jsonl"
    marker.write_text("{}\n", encoding="utf-8")
    eval_output_dir = tmp_path / "golden" / "sample" / "freeform" / "eval-vs-pipeline" / "2026-02-10_21:09:52"
    eval_output_dir.mkdir(parents=True, exist_ok=True)

    moved = cli._co_locate_prediction_run_for_benchmark(pred_run, eval_output_dir)

    assert moved == eval_output_dir / "prediction-run"
    assert moved.exists()
    assert (moved / "label_studio_tasks.jsonl").exists()
    assert not pred_run.exists()
    assert not (timestamp_root / "labelstudio").exists()
    assert not timestamp_root.exists()


def test_co_locate_prediction_run_for_benchmark_overwrites_existing_target(tmp_path: Path) -> None:
    pred_run = tmp_path / "output" / "2026-02-10_21:09:52" / "labelstudio" / "book"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "new.txt").write_text("new\n", encoding="utf-8")

    eval_output_dir = tmp_path / "golden" / "sample" / "freeform" / "eval-vs-pipeline" / "2026-02-10_21:09:52"
    existing_target = eval_output_dir / "prediction-run"
    existing_target.mkdir(parents=True, exist_ok=True)
    (existing_target / "old.txt").write_text("old\n", encoding="utf-8")

    moved = cli._co_locate_prediction_run_for_benchmark(pred_run, eval_output_dir)

    assert moved.exists()
    assert (moved / "new.txt").exists()
    assert not (moved / "old.txt").exists()


def test_interactive_labelstudio_freeform_scope_routes_to_freeform_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selected_file = tmp_path / "book.epub"
    selected_file.write_text("dummy", encoding="utf-8")

    menu_answers = iter(["labelstudio", selected_file, "freeform-spans"])

    def fake_menu_select(*_args, **_kwargs):
        return next(menu_answers)

    text_answers = iter(["", "42", "6"])

    class _Prompt:
        def __init__(self, value: str | bool):
            self._value = value

        def ask(self):
            return self._value

    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [selected_file])
    monkeypatch.setattr(cli, "_load_settings", lambda: {})
    monkeypatch.setattr(cli, "_menu_select", fake_menu_select)
    monkeypatch.setattr(cli, "DEFAULT_GOLDEN", tmp_path / "golden")
    monkeypatch.setattr(cli, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key"))
    monkeypatch.setenv("LABEL_STUDIO_URL", "http://localhost:8080")
    monkeypatch.setenv("LABEL_STUDIO_API_KEY", "key")
    monkeypatch.setattr(
        cli.questionary,
        "text",
        lambda *args, **kwargs: _Prompt(next(text_answers)),
    )
    confirm_answers = iter([False, True])
    monkeypatch.setattr(
        cli.questionary,
        "confirm",
        lambda *args, **kwargs: _Prompt(next(confirm_answers)),
    )

    captured: dict[str, object] = {}

    def fake_run_labelstudio_import(**kwargs):
        captured.update(kwargs)
        return {
            "project_name": "book",
            "project_id": 1,
            "tasks_total": 10,
            "tasks_uploaded": 10,
            "run_root": tmp_path / "out",
        }

    monkeypatch.setattr(cli, "run_labelstudio_import", fake_run_labelstudio_import)

    cli._interactive_mode()

    assert captured["task_scope"] == "freeform-spans"
    assert captured["chunk_level"] == "both"
    assert captured["segment_blocks"] == 42
    assert captured["segment_overlap"] == 6
    assert captured["output_dir"] == tmp_path / "golden"


def test_interactive_benchmark_uses_golden_output_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured_output = tmp_path / "custom-output"
    golden_root = tmp_path / "golden"
    menu_answers = iter(["labelstudio_benchmark"])

    monkeypatch.setattr(cli, "_menu_select", lambda *_args, **_kwargs: next(menu_answers))
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [])
    monkeypatch.setattr(cli, "_load_settings", lambda: {"output_dir": str(configured_output)})
    monkeypatch.setattr(cli, "DEFAULT_GOLDEN", golden_root)
    monkeypatch.setattr(
        cli.questionary,
        "confirm",
        lambda *args, **kwargs: type("_Prompt", (), {"ask": lambda self: True})(),
    )

    captured: dict[str, object] = {}

    def fake_labelstudio_benchmark(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli, "labelstudio_benchmark", fake_labelstudio_benchmark)

    cli._interactive_mode()

    assert captured["output_dir"] == golden_root
    eval_output_dir = captured["eval_output_dir"]
    assert isinstance(eval_output_dir, Path)
    assert eval_output_dir.parent == golden_root / "eval-vs-pipeline"


def test_interactive_benchmark_eval_only_uses_existing_prediction_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    golden_root = tmp_path / "golden"
    pred_run = golden_root / "some-run" / "prediction-run"
    pred_run.mkdir(parents=True, exist_ok=True)
    (pred_run / "label_studio_tasks.jsonl").write_text("{}\n", encoding="utf-8")
    gold_spans = golden_root / "some-run" / "exports" / "freeform_span_labels.jsonl"
    gold_spans.parent.mkdir(parents=True, exist_ok=True)
    gold_spans.write_text("{}\n", encoding="utf-8")

    menu_answers = iter(["labelstudio_benchmark", "eval-only", gold_spans, pred_run])
    monkeypatch.setattr(cli, "_menu_select", lambda *_args, **_kwargs: next(menu_answers))
    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [])
    monkeypatch.setattr(cli, "_load_settings", lambda: {})
    monkeypatch.setattr(cli, "DEFAULT_GOLDEN", golden_root)

    def _unexpected_confirm(*_args, **_kwargs):
        raise AssertionError("Upload confirm should not be shown in eval-only mode")

    monkeypatch.setattr(cli.questionary, "confirm", _unexpected_confirm)
    monkeypatch.setattr(cli, "_discover_freeform_gold_exports", lambda *_: [gold_spans])
    monkeypatch.setattr(cli, "_discover_prediction_runs", lambda *_: [pred_run])

    captured: dict[str, object] = {}

    def fake_labelstudio_eval(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli, "labelstudio_eval", fake_labelstudio_eval)

    cli._interactive_mode()

    assert captured["scope"] == "freeform-spans"
    assert captured["pred_run"] == pred_run
    assert captured["gold_spans"] == gold_spans
    eval_output_dir = captured["output_dir"]
    assert isinstance(eval_output_dir, Path)
    assert eval_output_dir.parent == golden_root / "eval-vs-pipeline"


def test_interactive_labelstudio_export_routes_to_export_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selected_output = tmp_path / "golden"
    menu_answers = iter(["labelstudio_export", "freeform-spans"])

    def fake_menu_select(*_args, **_kwargs):
        return next(menu_answers)

    class _Prompt:
        def __init__(self, value: str):
            self._value = value

        def ask(self):
            return self._value

    monkeypatch.setattr(cli, "_list_importable_files", lambda *_: [])
    monkeypatch.setattr(cli, "_load_settings", lambda: {})
    monkeypatch.setattr(cli, "_menu_select", fake_menu_select)
    monkeypatch.setattr(cli, "DEFAULT_GOLDEN", selected_output)
    monkeypatch.setattr(cli, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key"))
    monkeypatch.setenv("LABEL_STUDIO_URL", "http://localhost:8080")
    monkeypatch.setenv("LABEL_STUDIO_API_KEY", "key")
    monkeypatch.setattr(
        cli.questionary,
        "text",
        lambda *args, **kwargs: _Prompt("Bench Project"),
    )

    captured: dict[str, object] = {}

    def fake_run_labelstudio_export(**kwargs):
        captured.update(kwargs)
        return {"summary_path": selected_output / "summary.json"}

    monkeypatch.setattr(cli, "run_labelstudio_export", fake_run_labelstudio_export)

    cli._interactive_mode()

    assert captured["project_name"] == "Bench Project"
    assert captured["export_scope"] == "freeform-spans"
    assert captured["output_dir"] == selected_output


def test_labelstudio_benchmark_passes_processed_output_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_file = tmp_path / "book.epub"
    source_file.write_text("dummy", encoding="utf-8")
    gold_spans = tmp_path / "freeform_span_labels.jsonl"
    gold_spans.write_text("{}\n", encoding="utf-8")
    prediction_run = tmp_path / "pred-run"
    prediction_run.mkdir(parents=True, exist_ok=True)
    (prediction_run / "label_studio_tasks.jsonl").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        cli, "_resolve_labelstudio_settings", lambda *_: ("http://example", "api-key")
    )
    monkeypatch.setattr(
        cli,
        "_co_locate_prediction_run_for_benchmark",
        lambda _pred_run, _eval_dir: prediction_run,
    )
    monkeypatch.setattr(cli, "load_predicted_labeled_ranges", lambda *_: [])
    monkeypatch.setattr(cli, "load_gold_freeform_ranges", lambda *_: [])
    monkeypatch.setattr(
        cli,
        "evaluate_predicted_vs_freeform",
        lambda *_args, **_kwargs: {
            "report": {
                "counts": {
                    "gold_total": 0,
                    "pred_total": 0,
                    "gold_matched": 0,
                    "pred_matched": 0,
                    "gold_missed": 0,
                    "pred_false_positive": 0,
                },
                "recall": 0.0,
                "precision": 0.0,
                "boundary": {"correct": 0, "over": 0, "under": 0, "partial": 0},
                "per_label": {},
            },
            "missed_gold": [],
            "false_positive_preds": [],
        },
    )
    monkeypatch.setattr(cli, "format_freeform_eval_report_md", lambda *_: "report")
    monkeypatch.setattr(cli, "write_jsonl", lambda *_: None)

    captured: dict[str, object] = {}

    def fake_run_labelstudio_import(**kwargs):
        captured.update(kwargs)
        return {
            "project_name": "book",
            "project_id": 1,
            "tasks_total": 1,
            "tasks_uploaded": 1,
            "run_root": prediction_run,
            "processed_run_root": tmp_path / "processed" / "2026-02-11-00-00-00",
        }

    monkeypatch.setattr(cli, "run_labelstudio_import", fake_run_labelstudio_import)

    processed_root = tmp_path / "output"
    eval_root = tmp_path / "eval"
    cli.labelstudio_benchmark(
        gold_spans=gold_spans,
        source_file=source_file,
        output_dir=tmp_path / "golden",
        processed_output_dir=processed_root,
        eval_output_dir=eval_root,
        allow_labelstudio_write=True,
    )

    assert captured["processed_output_root"] == processed_root
