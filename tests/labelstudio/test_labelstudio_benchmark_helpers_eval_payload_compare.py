from __future__ import annotations

import tests.labelstudio.benchmark_helper_support as _support

# Reuse shared imports/helpers from the benchmark helper support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})
def test_labelstudio_benchmark_direct_call_uses_real_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_cli_attr(monkeypatch, "_resolve_labelstudio_settings", lambda *_: ("http://example", "k"))
    _patch_cli_attr(monkeypatch, "_discover_freeform_gold_exports", lambda *_: [])
    with pytest.raises(cli.typer.Exit):
        cli.labelstudio_benchmark(output_dir=tmp_path / "empty-golden")

def test_labelstudio_benchmark_compare_payload_passes_with_required_debug_artifacts(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline"
    candidate_root = tmp_path / "candidate"

    _write_labelstudio_compare_multi_source_report(
        baseline_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.40,
                line_accuracy=0.50,
                ingredient_recall=0.30,
                variant_recall=0.10,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.45,
                line_accuracy=0.55,
                ingredient_recall=0.33,
                variant_recall=0.11,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
        ],
    )
    _write_labelstudio_compare_multi_source_report(
        candidate_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.50,
                line_accuracy=0.60,
                ingredient_recall=0.45,
                variant_recall=0.15,
                llm_recipe_pipeline="codex-recipe-shard-v1",
                codex_farm_recipe_mode="benchmark",
                write_required_llm_debug=True,
            ),
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.47,
                line_accuracy=0.56,
                ingredient_recall=0.34,
                variant_recall=0.12,
                llm_recipe_pipeline="codex-recipe-shard-v1",
                codex_farm_recipe_mode="benchmark",
                write_required_llm_debug=True,
            ),
        ],
    )

    payload = cli._build_labelstudio_benchmark_compare_payload(
        baseline_report_root=baseline_root,
        candidate_report_root=candidate_root,
    )

    assert payload["schema_version"] == "labelstudio_benchmark_compare.v1"
    assert payload["overall"]["verdict"] == "PASS"
    gates_by_name = {
        gate["name"]: gate
        for gate in payload["gates"]
        if isinstance(gate, dict) and gate.get("name")
    }
    assert gates_by_name["foodlab_debug_artifacts_present"]["passed"] is True
    assert gates_by_name["sea_debug_artifacts_present"]["passed"] is True
    assert gates_by_name["foodlab_variant_recall_nonzero"]["passed"] is True

def test_labelstudio_benchmark_compare_payload_fails_when_required_debug_artifacts_missing(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline"
    candidate_root = tmp_path / "candidate"

    _write_labelstudio_compare_multi_source_report(
        baseline_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.40,
                line_accuracy=0.50,
                ingredient_recall=0.30,
                variant_recall=0.10,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.45,
                line_accuracy=0.55,
                ingredient_recall=0.33,
                variant_recall=0.11,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
        ],
    )
    _write_labelstudio_compare_multi_source_report(
        candidate_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.50,
                line_accuracy=0.60,
                ingredient_recall=0.45,
                variant_recall=0.15,
                llm_recipe_pipeline="codex-recipe-shard-v1",
                codex_farm_recipe_mode="benchmark",
                write_required_llm_debug=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.47,
                line_accuracy=0.56,
                ingredient_recall=0.34,
                variant_recall=0.12,
                llm_recipe_pipeline="codex-recipe-shard-v1",
                codex_farm_recipe_mode="benchmark",
                write_required_llm_debug=True,
            ),
        ],
    )

    payload = cli._build_labelstudio_benchmark_compare_payload(
        baseline_report_root=baseline_root,
        candidate_report_root=candidate_root,
    )

    assert payload["overall"]["verdict"] == "FAIL"
    gates_by_name = {
        gate["name"]: gate
        for gate in payload["gates"]
        if isinstance(gate, dict) and gate.get("name")
    }
    assert gates_by_name["foodlab_debug_artifacts_present"]["passed"] is False

def test_labelstudio_benchmark_compare_payload_fails_when_benchmark_mode_metadata_is_missing(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline"
    candidate_root = tmp_path / "candidate"

    _write_labelstudio_compare_multi_source_report(
        baseline_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.40,
                line_accuracy=0.50,
                ingredient_recall=0.30,
                variant_recall=0.10,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.45,
                line_accuracy=0.55,
                ingredient_recall=0.33,
                variant_recall=0.11,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
        ],
    )
    _write_labelstudio_compare_multi_source_report(
        candidate_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.50,
                line_accuracy=0.60,
                ingredient_recall=0.45,
                variant_recall=0.15,
                llm_recipe_pipeline="codex-recipe-shard-v1",
                codex_farm_recipe_mode="benchmark",
                write_required_llm_debug=True,
                write_prompt_manifests=False,
                include_prediction_run_config=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.47,
                line_accuracy=0.56,
                ingredient_recall=0.34,
                variant_recall=0.12,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
        ],
    )

    payload = cli._build_labelstudio_benchmark_compare_payload(
        baseline_report_root=baseline_root,
        candidate_report_root=candidate_root,
    )

    assert payload["overall"]["verdict"] == "FAIL"
    gates_by_name = {
        gate["name"]: gate
        for gate in payload["gates"]
        if isinstance(gate, dict) and gate.get("name")
    }
    assert gates_by_name["foodlab_debug_artifacts_present"]["passed"] is False
    assert (
        "Missing required debug artifacts:"
        in str(gates_by_name["foodlab_debug_artifacts_present"]["reason"])
    )
    warnings = payload.get("warnings")
    assert isinstance(warnings, list)
    assert any(
        "inferred benchmark mode from artifacts (metadata missing)" in str(warning)
        for warning in warnings
    )

def test_labelstudio_benchmark_compare_payload_infers_benchmark_mode_from_artifacts_and_passes(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline"
    candidate_root = tmp_path / "candidate"

    _write_labelstudio_compare_multi_source_report(
        baseline_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.40,
                line_accuracy=0.50,
                ingredient_recall=0.30,
                variant_recall=0.10,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.45,
                line_accuracy=0.55,
                ingredient_recall=0.33,
                variant_recall=0.11,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
        ],
    )
    _write_labelstudio_compare_multi_source_report(
        candidate_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.50,
                line_accuracy=0.60,
                ingredient_recall=0.45,
                variant_recall=0.15,
                llm_recipe_pipeline="codex-recipe-shard-v1",
                codex_farm_recipe_mode="benchmark",
                write_required_llm_debug=True,
                include_prediction_run_config=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.47,
                line_accuracy=0.56,
                ingredient_recall=0.34,
                variant_recall=0.12,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
        ],
    )

    payload = cli._build_labelstudio_benchmark_compare_payload(
        baseline_report_root=baseline_root,
        candidate_report_root=candidate_root,
    )

    assert payload["overall"]["verdict"] == "PASS"
    warnings = payload.get("warnings")
    assert isinstance(warnings, list)
    assert any(
        (
            "Running benchmark-only debug checks for thefoodlabcutdown using "
            "inferred benchmark mode from artifacts (metadata missing)"
        ) in str(warning)
        for warning in warnings
    )
    foodlab_debug_gate = {
        gate["name"]: gate
        for gate in payload["gates"]
        if isinstance(gate, dict) and gate.get("name")
    }["foodlab_debug_artifacts_present"]
    assert foodlab_debug_gate["passed"] is True

def test_labelstudio_benchmark_compare_payload_skips_debug_checks_when_mode_unknown(
    tmp_path: Path,
) -> None:
    baseline_root = tmp_path / "baseline"
    candidate_root = tmp_path / "candidate"

    _write_labelstudio_compare_multi_source_report(
        baseline_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.40,
                line_accuracy=0.50,
                ingredient_recall=0.30,
                variant_recall=0.10,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=baseline_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.45,
                line_accuracy=0.55,
                ingredient_recall=0.33,
                variant_recall=0.11,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
            ),
        ],
    )
    _write_labelstudio_compare_multi_source_report(
        candidate_root,
        [
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="thefoodlabcutdown",
                practical_f1=0.50,
                line_accuracy=0.60,
                ingredient_recall=0.45,
                variant_recall=0.15,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
                include_prediction_run_config=False,
            ),
            _write_labelstudio_compare_source_row(
                run_root=candidate_root,
                source_key="seaandsmokecutdown",
                practical_f1=0.47,
                line_accuracy=0.56,
                ingredient_recall=0.34,
                variant_recall=0.12,
                llm_recipe_pipeline="off",
                codex_farm_recipe_mode="extract",
                write_required_llm_debug=False,
                include_prediction_run_config=False,
            ),
        ],
    )

    payload = cli._build_labelstudio_benchmark_compare_payload(
        baseline_report_root=baseline_root,
        candidate_report_root=candidate_root,
    )

    assert payload["overall"]["verdict"] == "PASS"
    warnings = payload.get("warnings")
    assert isinstance(warnings, list)
    assert any(
        "Could not confirm benchmark mode for seaandsmokecutdown: "
        "mode metadata is missing and artifact signals are not conclusive."
        in str(warning)
        for warning in warnings
    )
    source_row = payload["sources"]["seaandsmokecutdown"]
    assert isinstance(source_row, dict)
    candidate_context = source_row.get("candidate")
    assert isinstance(candidate_context, dict)
    debug_payload = candidate_context.get("debug_artifacts")
    assert isinstance(debug_payload, dict)
    assert debug_payload.get("required") is False
    foodlab_debug_gate = {
        gate["name"]: gate
        for gate in payload["gates"]
        if isinstance(gate, dict) and gate.get("name")
    }["sea_debug_artifacts_present"]
    assert foodlab_debug_gate["passed"] is True

def test_labelstudio_benchmark_action_compare_dispatches_to_compare_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    compare_out = tmp_path / "compare-out"
    captured: dict[str, object] = {}

    def fake_compare(**kwargs):
        captured.update(kwargs)
        return {"overall": {"verdict": "PASS"}}

    _patch_cli_attr(monkeypatch, "labelstudio_benchmark_compare", fake_compare)

    cli.labelstudio_benchmark(
        action="compare",
        baseline=baseline,
        candidate=candidate,
        compare_out=compare_out,
        fail_on_regression=True,
    )

    assert captured["baseline"] == baseline
    assert captured["candidate"] == candidate
    assert captured["out_dir"] == compare_out
    assert captured["fail_on_regression"] is True

def test_labelstudio_benchmark_compare_accepts_single_eval_report_inputs(
    tmp_path: Path,
) -> None:
    def _write_single_eval_run(
        run_dir: Path,
        *,
        source_file: str,
        practical_f1: float,
        line_accuracy: float,
        ingredient_recall: float,
        variant_recall: float,
    ) -> Path:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "aligned_prediction_blocks.jsonl").write_text("{}\n", encoding="utf-8")
        (run_dir / "prediction-run").mkdir(parents=True, exist_ok=True)
        (run_dir / "prediction-run" / "run_manifest.json").write_text(
            json.dumps(
                {
                    "run_config": {
                        "prediction_run_config": {
                            "llm_recipe_pipeline": "off",
                            "codex_farm_recipe_mode": "extract",
                        }
                    },
                    "artifacts": {},
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        (run_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "source": {"path": source_file},
                    "run_config": {
                        "llm_recipe_pipeline": "off",
                        "codex_farm_recipe_mode": "extract",
                        "prediction_run_config": {
                            "llm_recipe_pipeline": "off",
                            "codex_farm_recipe_mode": "extract",
                        },
                    },
                    "artifacts": {"artifact_root_dir": "prediction-run"},
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        report_path = run_dir / "eval_report.json"
        report_path.write_text(
            json.dumps(
                {
                    "source_file": source_file,
                    "practical_f1": practical_f1,
                    "overall_line_accuracy": line_accuracy,
                    "per_label": {
                        "INGREDIENT_LINE": {"recall": ingredient_recall},
                        "RECIPE_VARIANT": {"recall": variant_recall},
                    },
                    "artifacts": {
                        "aligned_prediction_blocks_jsonl": "aligned_prediction_blocks.jsonl",
                    },
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return report_path

    baseline_eval_report = _write_single_eval_run(
        tmp_path / "baseline-eval",
        source_file="data/input/thefoodlabCUTDOWN.epub",
        practical_f1=0.40,
        line_accuracy=0.50,
        ingredient_recall=0.30,
        variant_recall=0.10,
    )
    candidate_eval_report = _write_single_eval_run(
        tmp_path / "candidate-eval",
        source_file="data/input/thefoodlabCUTDOWN.epub",
        practical_f1=0.50,
        line_accuracy=0.60,
        ingredient_recall=0.35,
        variant_recall=0.15,
    )

    payload = cli.labelstudio_benchmark_compare(
        baseline=baseline_eval_report,
        candidate=candidate_eval_report,
        out_dir=tmp_path / "compare-out",
    )

    assert payload["comparison_mode"] == "single_eval_report"
    assert payload["overall"]["verdict"] == "PASS"
    gates = {
        gate["name"]: gate
        for gate in payload["gates"]
        if isinstance(gate, dict) and gate.get("name")
    }
    assert gates["practical_f1_no_regression"]["passed"] is True
    assert gates["overall_line_accuracy_no_regression"]["passed"] is True
    assert gates["debug_artifacts_present"]["passed"] is True
