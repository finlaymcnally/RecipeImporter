from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

from cookimport.bench.upload_bundle_v1_existing_output import (
    ExistingOutputAdapterHelpers,
    build_upload_bundle_source_model_from_existing_root,
)
from cookimport.bench.upload_bundle_v1_model import UploadBundleSourceModel
from cookimport.bench.upload_bundle_v1_render import (
    build_recipe_pipeline_context_from_model,
    build_stage_separated_comparison_from_model,
)
from cookimport.config.run_settings import RECIPE_CODEX_FARM_PIPELINE_SHARD_V1


def _coerce_int(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _source_key(source_hash: str | None, source_file: str | None) -> str:
    if source_hash:
        return source_hash
    return str(source_file or "unknown")


def test_existing_output_adapter_prefers_root_summaries(tmp_path: Path) -> None:
    source_root = tmp_path / "session"
    source_root.mkdir(parents=True, exist_ok=True)

    def _load_json_object(path: Path) -> dict[str, object]:
        name = path.name
        if name == "run_index.json":
            return {
                "runs": [
                    {
                        "run_id": "root-codex",
                        "output_subdir": "root-codex",
                        "source_file": "book.epub",
                        "source_hash": "book-hash",
                        "source_key": "book-hash",
                        "llm_recipe_pipeline": RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
                    }
                ]
            }
        if name == "comparison_summary.json":
            return {
                "pairs": [
                    {
                        "source_key": "book-hash",
                        "codex_run": {"run_id": "root-codex"},
                        "baseline_run": {"run_id": "root-vanilla"},
                    }
                ],
                "changed_lines_total": 1,
            }
        if name == "process_manifest.json":
            return {"schema_version": "manifest.v1"}
        if name == "per_recipe_or_per_span_breakdown.json":
            return {"pairs": [{"source_key": "book-hash"}]}
        if name == "10_process_manifest.json":
            return {"schema_version": "starter_pack_manifest.v1"}
        return {}

    def _iter_jsonl(path: Path) -> list[dict[str, object]]:
        if path.name == "changed_lines.codex_vs_vanilla.jsonl":
            return [{"source_key": "book-hash", "line_index": 1}]
        if path.name == "02_call_inventory.jsonl":
            return [{"run_id": "root-codex"}]
        if path.name == "06_selected_recipe_packets.jsonl":
            return [{"recipe_id": "recipe:c0"}]
        return []

    helpers = ExistingOutputAdapterHelpers(
        load_json_object=_load_json_object,
        iter_jsonl=_iter_jsonl,
        load_recipe_triage_rows=lambda _path: [{"recipe_id": "recipe:c0"}],
        discover_run_dirs=lambda _path: [],
        build_run_record_from_existing_run=lambda _path: None,
        build_comparison_summary=lambda **_kwargs: ({}, [], [], [], [], [], []),
        coerce_int=_coerce_int,
        source_file_name=lambda value: str(value or ""),
        source_key=_source_key,
        select_starter_pack_recipe_cases=lambda rows: rows,
        build_selected_recipe_packets=lambda **_kwargs: [],
    )
    model = build_upload_bundle_source_model_from_existing_root(
        source_root=source_root,
        helpers=helpers,
    )

    assert model.run_rows[0]["run_id"] == "root-codex"
    assert model.comparison_pairs[0]["source_key"] == "book-hash"
    assert model.changed_line_rows[0]["line_index"] == 1
    assert model.adapter_metadata["uses_root_run_rows"] is True
    assert model.adapter_metadata["uses_root_pairs"] is True


def test_existing_output_adapter_falls_back_to_discovered_runs(tmp_path: Path) -> None:
    source_root = tmp_path / "session"
    source_root.mkdir(parents=True, exist_ok=True)
    discovered = [source_root / "codexfarm", source_root / "vanilla"]
    for run_dir in discovered:
        run_dir.mkdir(parents=True, exist_ok=True)

    def _load_json_object(path: Path) -> dict[str, object]:
        if path.name == "run_index.json":
            return {"runs": []}
        if path.name == "comparison_summary.json":
            return {"pairs": [], "changed_lines_total": 0}
        if path.name == "per_recipe_or_per_span_breakdown.json":
            return {"pairs": []}
        return {}

    def _build_run_record(path: Path) -> SimpleNamespace:
        if path.name == "codexfarm":
            return SimpleNamespace(
                run_timestamp=None,
                run_id="codexfarm",
                run_dir=path,
                output_subdir="codexfarm",
                source_key="book-hash",
                source_file="book.epub",
                source_hash="book-hash",
                metric_overall_line_accuracy=0.60,
                metric_macro_f1_excluding_other=0.60,
                metric_practical_f1=0.60,
                full_prompt_log_status="complete",
                full_prompt_log_rows=3,
                line_role_pipeline="codex-line-role-shard-v1",
                llm_recipe_pipeline=RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
            )
        return SimpleNamespace(
            run_timestamp=None,
            run_id="vanilla",
            run_dir=path,
            output_subdir="vanilla",
            source_key="book-hash",
            source_file="book.epub",
            source_hash="book-hash",
            metric_overall_line_accuracy=0.70,
            metric_macro_f1_excluding_other=0.70,
            metric_practical_f1=0.70,
            full_prompt_log_status="not_applicable",
            full_prompt_log_rows=0,
            line_role_pipeline="off",
            llm_recipe_pipeline="off",
        )

    def _build_comparison_summary(**_kwargs: object) -> tuple[object, ...]:
        return (
            {
                "pairs": [
                    {
                        "source_key": "book-hash",
                        "codex_run": {"run_id": "codexfarm"},
                        "baseline_run": {"run_id": "vanilla"},
                    }
                ]
            },
            [{"source_key": "book-hash", "line_index": 1}],
            [{"source_key": "book-hash"}],
            [],
            [{"recipe_id": "recipe:c0"}],
            [{"run_id": "codexfarm"}],
            [],
        )

    helpers = ExistingOutputAdapterHelpers(
        load_json_object=_load_json_object,
        iter_jsonl=lambda _path: [],
        load_recipe_triage_rows=lambda _path: [],
        discover_run_dirs=lambda _path: list(discovered),
        build_run_record_from_existing_run=_build_run_record,
        build_comparison_summary=_build_comparison_summary,
        coerce_int=_coerce_int,
        source_file_name=lambda value: str(value or ""),
        source_key=_source_key,
        select_starter_pack_recipe_cases=lambda rows: rows,
        build_selected_recipe_packets=lambda **_kwargs: [],
    )
    model = build_upload_bundle_source_model_from_existing_root(
        source_root=source_root,
        helpers=helpers,
    )

    assert len(model.run_rows) == 2
    assert model.run_rows[0]["source_key"] == "book-hash"
    assert len(model.comparison_pairs) == 1
    assert model.adapter_metadata["uses_root_run_rows"] is False
    assert model.adapter_metadata["discovered_run_count"] == 2
    assert model.topology["codex_recipe_pipelines"] == [
        RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
    ]
    assert model.topology["recipe_topology_key"] == "single_correction"
    assert model.topology["observed_recipe_stage_call_counts"] == {
        "build_intermediate_det": 0,
        "recipe_llm_correct_and_link": 0,
        "build_final_recipe": 0,
    }
    assert model.topology["recipe_stages"] == [
        {
            "stage_key": "build_intermediate_det",
            "stage_label": "Build Intermediate Recipe",
        },
        {
            "stage_key": "recipe_llm_correct_and_link",
            "stage_label": "Recipe LLM Correction",
        },
        {
            "stage_key": "build_final_recipe",
            "stage_label": "Build Final Recipe",
        },
    ]
    assert model.topology["runtime_runs"] == [
        {
            "output_subdir": "codexfarm",
            "run_id": "codexfarm",
            "runtime_stages": {},
            "source_key": "book-hash",
        },
        {
            "output_subdir": "vanilla",
            "run_id": "vanilla",
            "runtime_stages": {},
            "source_key": "book-hash",
        },
    ]


def test_stage_renderer_accepts_synthetic_alternate_topology_model() -> None:
    model = UploadBundleSourceModel(
        source_root=Path("/tmp/fake"),
        run_index_payload={},
        comparison_summary_payload={},
        process_manifest_payload={},
        per_recipe_payload={},
        starter_manifest_payload={},
        starter_pack_present=False,
        run_rows=[],
        comparison_pairs=[],
        changed_line_rows=[],
        pair_breakdown_rows=[],
        recipe_triage_rows=[],
        call_inventory_rows=[],
        selected_packets=[],
        run_dir_by_id={},
        run_dirs_by_id={},
        run_dir_by_output_subdir={},
        discovered_run_dirs=[],
        advertised_counts={},
        topology={
            "recipe_topology_key": "alternate_topology",
            "recipe_stages": [
                {"stage_key": "extract_family", "stage_label": "Observed Extract Family"},
                {"stage_key": "repair_family", "stage_label": "Observed Repair Family"},
            ],
        },
    )

    recipe_pipeline_context = build_recipe_pipeline_context_from_model(model=model)
    rendered = build_stage_separated_comparison_from_model(
        model=model,
        per_label_metrics=[],
        pass_stage_per_label_metrics={},
    )

    assert recipe_pipeline_context["recipe_topology_key"] == "alternate_topology"
    assert recipe_pipeline_context["recipe_stages"][0]["stage_key"] == "extract_family"
    assert recipe_pipeline_context["runtime_runs"] == []
    assert rendered["pair_count"] == 0
    assert rendered["recipe_topology_key"] == "alternate_topology"
    assert rendered["recipe_stages"][1]["stage_label"] == "Observed Repair Family"
