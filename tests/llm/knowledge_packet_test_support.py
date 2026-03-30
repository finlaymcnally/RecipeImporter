from __future__ import annotations

from pathlib import Path

from cookimport.config.run_settings import RunSettings
from cookimport.core.models import ConversionReport, ConversionResult, RawArtifact
from cookimport.staging.nonrecipe_stage import NonRecipeSpan, NonRecipeStageResult
from tests.nonrecipe_stage_helpers import (
    make_authority_result,
    make_candidate_status_result,
    make_routing_result,
    make_seed_result,
    make_stage_result,
)


def configure_runtime_codex_home(
    monkeypatch,
    *,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("cookimport.llm.codex_exec_runner.Path.home", lambda: tmp_path)
    monkeypatch.setattr(
        "cookimport.llm.codex_exec_runner._resolve_recipeimport_codex_home",
        lambda explicit_env=None: str(tmp_path / ".codex-recipe"),
    )


def make_runtime_pack_and_run_dirs(tmp_path: Path) -> tuple[Path, Path]:
    pack_root = tmp_path / "pack"
    for name in ("pipelines", "prompts", "schemas"):
        (pack_root / name).mkdir(parents=True, exist_ok=True)
    run_root = tmp_path / "run"
    run_root.mkdir(parents=True, exist_ok=True)
    return pack_root, run_root


def make_runtime_settings(
    *,
    pack_root: Path,
    worker_count: int,
    context_blocks: int | None = None,
) -> RunSettings:
    payload: dict[str, object] = {
        "llm_knowledge_pipeline": "codex-knowledge-candidate-v2",
        "knowledge_worker_count": worker_count,
        "codex_farm_cmd": "codex-farm",
        "codex_farm_root": str(pack_root),
        "codex_farm_pipeline_knowledge": "recipe.knowledge.packet.v1",
    }
    if context_blocks is not None:
        payload["codex_farm_knowledge_context_blocks"] = context_blocks
    return RunSettings.model_validate(payload)


def make_runtime_conversion_result(block_texts: list[str]) -> ConversionResult:
    return ConversionResult(
        recipes=[],
        nonRecipeBlocks=[
            {"index": index, "text": text}
            for index, text in enumerate(block_texts)
        ],
        rawArtifacts=[
            RawArtifact(
                importer="text",
                sourceHash="hash123",
                locationId="full_text",
                extension="json",
                content={
                    "blocks": [
                        {"index": index, "text": text}
                        for index, text in enumerate(block_texts)
                    ]
                },
                metadata={},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbookPath="book.txt",
    )


def knowledge_span(*block_indices: int) -> NonRecipeSpan:
    ordered = [int(index) for index in block_indices]
    start = ordered[0]
    end = ordered[-1] + 1
    return NonRecipeSpan(
        span_id=f"nr.candidate.{start}.{end}",
        category="candidate",
        block_start_index=start,
        block_end_index=end,
        block_indices=ordered,
        block_ids=[f"b{index}" for index in ordered],
    )


def make_runtime_nonrecipe_stage_result(
    *,
    spans: list[NonRecipeSpan],
) -> NonRecipeStageResult:
    block_category_by_index = {
        int(block_index): "candidate"
        for span in spans
        for block_index in span.block_indices
    }
    return make_stage_result(
        seed=make_seed_result(
            block_category_by_index,
            nonrecipe_spans=spans,
            candidate_spans=spans,
            excluded_spans=[],
        ),
        routing=make_routing_result(
            candidate_block_indices=sorted(block_category_by_index),
        ),
        authority=make_authority_result({}),
        candidate_status=make_candidate_status_result(
            finalized_candidate_block_indices=[],
            unresolved_candidate_route_by_index=block_category_by_index,
        ),
    )
