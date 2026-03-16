from __future__ import annotations

import tests.labelstudio.benchmark_helper_support as _support

# Reuse shared imports/helpers from the benchmark helper support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})
def test_single_offline_comparison_markdown_table_columns_are_width_aligned() -> None:
    payload = {
        "schema_version": "codex_vs_vanilla_comparison.v2",
        "run_timestamp": "2026-03-02_21.25.24",
        "source_file": "book.epub",
        "variants": {
            "codexfarm": {"eval_output_dir": "codex"},
            "vanilla": {"eval_output_dir": "vanilla"},
        },
        "metrics": {
            "codexfarm": {
                "strict_accuracy": 0.438589,
                "macro_f1_excluding_other": 0.295998,
            },
            "vanilla": {
                "strict_accuracy": 0.399915,
                "macro_f1_excluding_other": 0.290594,
            },
        },
        "deltas": {
            "codex_minus_vanilla": {
                "strict_accuracy": 0.038674,
                "macro_f1_excluding_other": 0.005404,
            }
        },
        "metadata": {},
    }

    markdown = cli._format_single_offline_comparison_markdown(payload)
    table_lines = [line for line in markdown.splitlines() if line.startswith("|")]
    assert len(table_lines) == 4

    expected_pipes = [idx for idx, char in enumerate(table_lines[0]) if char == "|"]
    assert len(expected_pipes) == 5
    for line in table_lines[1:]:
        assert [idx for idx, char in enumerate(line) if char == "|"] == expected_pipes

    assert table_lines[0] == "| Metric                     | CodexFarm |  Vanilla | Codex - Vanilla |"
    assert table_lines[2] == "| `strict_accuracy`          |  0.438589 | 0.399915 |        0.038674 |"
    assert table_lines[3] == "| `macro_f1_excluding_other` |  0.295998 | 0.290594 |        0.005404 |"
    assert "Compatibility aliases in eval JSON" not in markdown

def test_single_offline_comparison_markdown_includes_per_label_breakdown() -> None:
    payload = {
        "schema_version": "codex_vs_vanilla_comparison.v2",
        "run_timestamp": "2026-03-02_21.25.24",
        "source_file": "book.epub",
        "variants": {
            "codexfarm": {"eval_output_dir": "codex"},
            "vanilla": {"eval_output_dir": "vanilla"},
        },
        "metrics": {},
        "deltas": {"codex_minus_vanilla": {}},
        "metadata": {
            "per_label_breakdown": {
                "schema_version": "single_offline_per_label_breakdown.v1",
                "run_timestamp": "2026-03-02_21.25.24",
                "eval_count": 2,
                "rows": [
                    {
                        "label": "RECIPE_TITLE",
                        "precision": 0.811111,
                        "recall": 0.598361,
                        "gold_total": 122,
                        "pred_total": 90,
                    },
                    {
                        "label": "INGREDIENT_LINE",
                        "precision": 0.745341,
                        "recall": 0.137300,
                        "gold_total": 874,
                        "pred_total": 161,
                    },
                ],
            }
        },
    }

    markdown = cli._format_single_offline_comparison_markdown(payload)
    assert "## Per-Label Breakdown (2026-03-02_21.25.24, 2 evals)" in markdown
    assert (
        "Per label: precision answers false alarms, recall answers misses."
        in markdown
    )
    assert "| Label           | Precision | Recall | Gold | Pred |" in markdown
    assert "| INGREDIENT_LINE |    0.7453 | 0.1373 |  874 |  161 |" in markdown
    assert "| RECIPE_TITLE    |    0.8111 | 0.5984 |  122 |   90 |" in markdown

def test_single_offline_comparison_artifacts_include_per_label_breakdown(
    tmp_path: Path,
) -> None:
    session_root = tmp_path / "session"
    codex_eval_output_dir = session_root / "codexfarm"
    vanilla_eval_output_dir = session_root / "vanilla"
    codex_eval_output_dir.mkdir(parents=True, exist_ok=True)
    vanilla_eval_output_dir.mkdir(parents=True, exist_ok=True)

    (codex_eval_output_dir / "eval_report.json").write_text(
        json.dumps(
            {
                "precision": 0.5,
                "recall": 0.6,
                "f1": 0.55,
                "per_label": {
                    "RECIPE_TITLE": {
                        "precision": 1.0,
                        "recall": 0.5,
                        "gold_total": 10,
                        "pred_total": 5,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (vanilla_eval_output_dir / "eval_report.json").write_text(
        json.dumps(
            {
                "precision": 0.4,
                "recall": 0.5,
                "f1": 0.45,
                "per_label": {
                    "RECIPE_TITLE": {
                        "precision": 0.5,
                        "recall": 1.0,
                        "gold_total": 4,
                        "pred_total": 8,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    written = cli._write_single_offline_comparison_artifacts(
        run_timestamp="2026-03-02_21.25.24",
        session_root=session_root,
        source_file="book.epub",
        codex_eval_output_dir=codex_eval_output_dir,
        vanilla_eval_output_dir=vanilla_eval_output_dir,
        write_markdown=True,
    )

    assert written is not None
    comparison_json_path, comparison_md_path = written
    payload = json.loads(comparison_json_path.read_text(encoding="utf-8"))
    per_label_breakdown = payload["metadata"]["per_label_breakdown"]
    assert per_label_breakdown["schema_version"] == "single_offline_per_label_breakdown.v1"
    assert per_label_breakdown["run_timestamp"] == "2026-03-02_21.25.24"
    assert per_label_breakdown["eval_count"] == 2
    assert len(per_label_breakdown["rows"]) == 1
    row = per_label_breakdown["rows"][0]
    assert row["label"] == "RECIPE_TITLE"
    assert row["precision"] == pytest.approx(9 / 13)
    assert row["recall"] == pytest.approx(9 / 14)
    assert row["gold_total"] == 14
    assert row["pred_total"] == 13

    assert comparison_md_path is not None
    markdown = comparison_md_path.read_text(encoding="utf-8")
    assert "## Per-Label Breakdown (2026-03-02_21.25.24, 2 evals)" in markdown
    assert "| RECIPE_TITLE |    0.6923 | 0.6429 |   14 |   13 |" in markdown

def test_single_offline_comparison_artifacts_include_variant_diagnostics(
    tmp_path: Path,
) -> None:
    session_root = tmp_path / "session"
    codex_eval_output_dir = session_root / "codexfarm"
    vanilla_eval_output_dir = session_root / "vanilla"
    codex_eval_output_dir.mkdir(parents=True, exist_ok=True)
    vanilla_eval_output_dir.mkdir(parents=True, exist_ok=True)

    (codex_eval_output_dir / "eval_report.json").write_text(
        json.dumps(
            {
                "overall_block_accuracy": 0.80,
                "macro_f1_excluding_other": 0.60,
                "segmentation": {"boundaries": {"overall_micro": {"f1": 0.75, "fp": 4, "fn": 6}}},
                "diagnostics": {
                    "gold_adaptation": {
                        "mode": "auto",
                        "coverage_ratio": 0.91,
                        "ambiguous_gold_blocks": 2,
                        "unresolved_gold_blocks": 5,
                        "confidence_counts": {"high": 10, "medium": 8, "low": 2},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (vanilla_eval_output_dir / "eval_report.json").write_text(
        json.dumps(
            {
                "overall_block_accuracy": 0.74,
                "macro_f1_excluding_other": 0.58,
                "segmentation": {"boundaries": {"overall_micro": {"f1": 0.81, "fp": 2, "fn": 5}}},
                "diagnostics": {
                    "gold_adaptation": {
                        "mode": "auto",
                        "coverage_ratio": 0.95,
                        "ambiguous_gold_blocks": 1,
                        "unresolved_gold_blocks": 3,
                        "confidence_counts": {"high": 12, "medium": 7, "low": 1},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    written = cli._write_single_offline_comparison_artifacts(
        run_timestamp="2026-03-04_11.00.00",
        session_root=session_root,
        source_file="book.epub",
        codex_eval_output_dir=codex_eval_output_dir,
        vanilla_eval_output_dir=vanilla_eval_output_dir,
        write_markdown=True,
    )
    assert written is not None
    comparison_json_path, comparison_md_path = written
    payload = json.loads(comparison_json_path.read_text(encoding="utf-8"))
    diagnostics = payload["metadata"]["variant_diagnostics"]
    assert diagnostics["schema_version"] == "single_offline_variant_diagnostics.v1"
    assert diagnostics["likely_driver"] in {
        "segmentation_driven",
        "classification_driven",
        "mixed",
        "no_material_change",
    }
    codex_row = diagnostics["variants"]["codexfarm"]
    vanilla_row = diagnostics["variants"]["vanilla"]
    assert codex_row["gold_adaptation"]["coverage_ratio"] == pytest.approx(0.91)
    assert vanilla_row["gold_adaptation"]["coverage_ratio"] == pytest.approx(0.95)
    assert diagnostics["deltas"]["gold_adaptation_coverage_ratio_delta"] == pytest.approx(
        -0.04
    )
    assert diagnostics["deltas"]["gold_adaptation_confidence_count_deltas"]["high"] == -2

    assert comparison_md_path is not None
    markdown = comparison_md_path.read_text(encoding="utf-8")
    assert "## Delta Attribution" in markdown
    assert "gold_adaptation_coverage_ratio" in markdown

def test_single_offline_comparison_artifacts_markdown_toggle(tmp_path: Path) -> None:
    session_root = tmp_path / "session"
    codex_eval_output_dir = session_root / "codexfarm"
    vanilla_eval_output_dir = session_root / "vanilla"
    codex_eval_output_dir.mkdir(parents=True, exist_ok=True)
    vanilla_eval_output_dir.mkdir(parents=True, exist_ok=True)

    (codex_eval_output_dir / "eval_report.json").write_text(
        json.dumps({"precision": 0.50, "recall": 0.60, "f1": 0.55}),
        encoding="utf-8",
    )
    (vanilla_eval_output_dir / "eval_report.json").write_text(
        json.dumps({"precision": 0.40, "recall": 0.50, "f1": 0.45}),
        encoding="utf-8",
    )

    comparison_paths = cli._write_single_offline_comparison_artifacts(
        run_timestamp="2026-03-02_12.34.56",
        session_root=session_root,
        source_file="book.epub",
        codex_eval_output_dir=codex_eval_output_dir,
        vanilla_eval_output_dir=vanilla_eval_output_dir,
        write_markdown=False,
    )

    assert comparison_paths is not None
    comparison_json_path, comparison_md_path = comparison_paths
    assert comparison_json_path.exists()
    assert comparison_md_path is None
    assert not (session_root / "codex_vs_vanilla_comparison.md").exists()

    comparison_paths_markdown = cli._write_single_offline_comparison_artifacts(
        run_timestamp="2026-03-02_12.34.56",
        session_root=session_root,
        source_file="book.epub",
        codex_eval_output_dir=codex_eval_output_dir,
        vanilla_eval_output_dir=vanilla_eval_output_dir,
        write_markdown=True,
    )
    assert comparison_paths_markdown is not None
    _, comparison_md_path_markdown = comparison_paths_markdown
    assert comparison_md_path_markdown is not None
    assert comparison_md_path_markdown.exists()

def test_single_offline_comparison_artifacts_trigger_starter_pack(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session_root = tmp_path / "session"
    codex_eval_output_dir = session_root / "codexfarm"
    vanilla_eval_output_dir = session_root / "vanilla"
    codex_eval_output_dir.mkdir(parents=True, exist_ok=True)
    vanilla_eval_output_dir.mkdir(parents=True, exist_ok=True)

    (codex_eval_output_dir / "eval_report.json").write_text(
        json.dumps({"precision": 0.50, "recall": 0.60, "f1": 0.55}),
        encoding="utf-8",
    )
    (vanilla_eval_output_dir / "eval_report.json").write_text(
        json.dumps({"precision": 0.40, "recall": 0.50, "f1": 0.45}),
        encoding="utf-8",
    )

    starter_calls: list[Path] = []

    def _fake_starter_pack_writer(*, session_root: Path) -> Path:
        starter_calls.append(session_root)
        starter_dir = session_root / "starter_pack_v1"
        starter_dir.mkdir(parents=True, exist_ok=True)
        (session_root / "benchmark_summary.md").write_text(
            "# Flattened benchmark summary\n",
            encoding="utf-8",
        )
        return starter_dir

    monkeypatch.setattr(cli, "_write_single_offline_starter_pack", _fake_starter_pack_writer)

    comparison_paths = cli._write_single_offline_comparison_artifacts(
        run_timestamp="2026-03-02_12.34.56",
        session_root=session_root,
        source_file="book.epub",
        codex_eval_output_dir=codex_eval_output_dir,
        vanilla_eval_output_dir=vanilla_eval_output_dir,
        write_markdown=False,
        write_starter_pack=True,
    )

    assert comparison_paths is not None
    comparison_json_path, _ = comparison_paths
    payload = json.loads(comparison_json_path.read_text(encoding="utf-8"))
    metadata = payload.get("metadata")
    assert isinstance(metadata, dict)
    starter_metadata = metadata.get("starter_pack_v1")
    assert isinstance(starter_metadata, dict)
    assert starter_metadata.get("relative_path") == "starter_pack_v1"
    assert starter_metadata.get("manifest_file") == "starter_pack_v1/10_process_manifest.json"
    flattened_metadata = metadata.get("flattened_summary")
    assert isinstance(flattened_metadata, dict)
    assert flattened_metadata.get("relative_path") == "benchmark_summary.md"
    assert starter_calls == [session_root]

def test_single_offline_starter_pack_fallback_loader_registers_module(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session_root = tmp_path / "session"
    session_root.mkdir(parents=True, exist_ok=True)
    helper_script_path = tmp_path / "fake_benchmark_helper.py"
    helper_script_path.write_text(
        "\n".join(
            [
                "from dataclasses import dataclass",
                "",
                "@dataclass",
                "class _DataclassProbe:",
                "    value: int = 1",
                "",
                "def build_starter_pack_for_existing_runs(*, input_dir, output_dir, write_flattened_summary=False):",
                "    starter_dir = output_dir / 'starter_pack_v1'",
                "    starter_dir.mkdir(parents=True, exist_ok=True)",
                "    if write_flattened_summary:",
                "        (output_dir / 'benchmark_summary.md').write_text('# summary\\n', encoding='utf-8')",
                "    return {'ok': True}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # type: ignore[no-untyped-def]
        if name == "scripts.benchmark_cutdown_for_external_ai":
            raise ModuleNotFoundError("No module named 'scripts'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    real_spec_from_file_location = cli.importlib.util.spec_from_file_location

    def _fake_spec_from_file_location(name, location, *args, **kwargs):  # type: ignore[no-untyped-def]
        return real_spec_from_file_location(name, helper_script_path, *args, **kwargs)

    monkeypatch.setattr(
        cli.importlib.util,
        "spec_from_file_location",
        _fake_spec_from_file_location,
    )

    starter_dir = cli._write_single_offline_starter_pack(session_root=session_root)

    assert starter_dir == session_root / "starter_pack_v1"
    assert (session_root / "starter_pack_v1").is_dir()
    assert (session_root / "benchmark_summary.md").is_file()

def test_single_offline_comparison_includes_codex_runtime_from_llm_manifest_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli, "default_codex_reasoning_effort", lambda cmd=None: "high")

    session_root = tmp_path / "single-offline-benchmark"
    codex_eval_output_dir = session_root / "codexfarm"
    vanilla_eval_output_dir = session_root / "vanilla"
    codex_eval_output_dir.mkdir(parents=True, exist_ok=True)
    vanilla_eval_output_dir.mkdir(parents=True, exist_ok=True)

    (codex_eval_output_dir / "eval_report.json").write_text(
        json.dumps({"precision": 0.40, "recall": 0.32, "f1": 0.35}),
        encoding="utf-8",
    )
    (vanilla_eval_output_dir / "eval_report.json").write_text(
        json.dumps({"precision": 0.38, "recall": 0.30, "f1": 0.33}),
        encoding="utf-8",
    )
    (vanilla_eval_output_dir / "run_manifest.json").write_text(
        json.dumps({"source": {"path": str(tmp_path / "book.epub")}}),
        encoding="utf-8",
    )
    (codex_eval_output_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "source": {"path": str(tmp_path / "book.epub")},
                "run_config": {
                    "llm_recipe_pipeline": "codex-farm-single-correction-v1",
                    "codex_farm_model": None,
                    "codex_farm_reasoning_effort": None,
                },
                "artifacts": {"artifact_root_dir": "prediction-run"},
            }
        ),
        encoding="utf-8",
    )

    llm_manifest_path = (
        codex_eval_output_dir
        / "prediction-run"
        / "raw"
        / "llm"
        / "book"
        / cli.RECIPE_MANIFEST_FILE_NAME
    )
    llm_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    llm_manifest_path.write_text(
        json.dumps(
            {
                "codex_farm_model": None,
                "codex_farm_reasoning_effort": None,
                "process_runs": {
                    "pass1": {
                        "process_payload": {
                            "codex_model": "gpt-5.3-codex-spark",
                            "codex_reasoning_effort": None,
                        },
                        "telemetry_report": {
                            "insights": {
                                "model_reasoning_breakdown": [
                                    {
                                        "model": "gpt-5.3-codex-spark",
                                        "reasoning_effort": "<default>",
                                    }
                                ]
                            }
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    written = cli._write_single_offline_comparison_artifacts(
        run_timestamp="2026-03-02_12.34.56",
        session_root=session_root,
        source_file=str(tmp_path / "book.epub"),
        codex_eval_output_dir=codex_eval_output_dir,
        vanilla_eval_output_dir=vanilla_eval_output_dir,
    )

    assert written is not None
    comparison_json_path = written[0]
    payload = json.loads(comparison_json_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["codex_farm_runtime"]["codex_model"] == "gpt-5.3-codex-spark"
    assert (
        payload["metadata"]["codex_farm_runtime"]["codex_reasoning_effort"]
        == "high"
    )
