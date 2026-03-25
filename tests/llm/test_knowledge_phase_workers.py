from __future__ import annotations

import json
from pathlib import Path

import pytest

from cookimport.core.models import ChunkLane, KnowledgeChunk
from cookimport.llm.codex_farm_knowledge_ingest import (
    read_validated_knowledge_outputs_from_proposals,
    validate_knowledge_shard_output,
)
from cookimport.llm.codex_farm_knowledge_jobs import build_knowledge_jobs
from cookimport.llm.fake_codex_farm_runner import FakeCodexFarmRunner
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1, run_phase_workers_v1
from cookimport.staging.nonrecipe_stage import NonRecipeSpan


def _semantic_packet_output(
    *,
    packet_id: str,
    chunk_id: str,
    block_index: int,
    snippet_block_index: int,
) -> dict[str, object]:
    return {
        "packet_id": packet_id,
        "chunk_results": [
            {
                "chunk_id": chunk_id,
                "is_useful": True,
                "block_decisions": [{"block_index": block_index, "category": "knowledge"}],
                "snippets": [
                    {
                        "body": "This should be rejected.",
                        "evidence": [{"block_index": snippet_block_index, "quote": "bad"}],
                    }
                ],
                "reason_code": "technique_or_mechanism",
            }
        ],
    }


def test_build_knowledge_jobs_emits_stable_shard_entries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id="chunk-0",
                lane=ChunkLane.KNOWLEDGE,
                title="Sauce Basics",
                text="Always whisk constantly when adding butter.",
                blockIds=[0],
            ),
            KnowledgeChunk(
                id="chunk-1",
                lane=ChunkLane.KNOWLEDGE,
                title="Seasoning",
                text="Salt in layers for better control.",
                blockIds=[1],
            ),
            KnowledgeChunk(
                id="chunk-2",
                lane=ChunkLane.KNOWLEDGE,
                title="Storage",
                text="Cool leftovers quickly before refrigeration.",
                blockIds=[2],
            ),
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    report = build_knowledge_jobs(
        full_blocks=[
            {"index": 0, "text": "Always whisk constantly when adding butter."},
            {"index": 1, "text": "Salt in layers for better control."},
            {"index": 2, "text": "Cool leftovers quickly before refrigeration."},
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id="nr.knowledge.0.3",
                category="knowledge",
                block_start_index=0,
                block_end_index=3,
                block_indices=[0, 1, 2],
                block_ids=["b0", "b1", "b2"],
            )
        ],
        recipe_spans=[],
        workbook_slug="book",
        source_hash="hash123",
        out_dir=tmp_path / "in",
        context_blocks=1,
        target_chunks_per_shard=2,
    )

    assert report.shards_written == 2
    assert [entry.shard_id for entry in report.shard_entries] == [
        "book.ks0000.nr",
        "book.ks0001.nr",
    ]
    assert report.shard_entries[0].owned_ids == ("book.c0000.nr", "book.c0001.nr")
    assert report.shard_entries[0].metadata["owned_block_indices"] == [0, 1]
    assert report.shard_entries[0].metadata["source_span_ids"] == ["nr.knowledge.0.3"]
    assert sorted(path.name for path in (tmp_path / "in").glob("*.json")) == [
        "book.ks0000.nr.json",
        "book.ks0001.nr.json",
    ]


def test_build_knowledge_jobs_uses_prompt_target_count_as_shard_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fake_chunks(_sequence, overrides=None):
        del overrides
        return [
            KnowledgeChunk(
                id=f"chunk-{index}",
                lane=ChunkLane.KNOWLEDGE,
                title=f"Topic {index}",
                text=f"Knowledge chunk {index}",
                blockIds=[index],
            )
            for index in range(5)
        ]

    monkeypatch.setattr(
        "cookimport.llm.codex_farm_knowledge_jobs.chunks_from_non_recipe_blocks",
        _fake_chunks,
    )

    report = build_knowledge_jobs(
        full_blocks=[
            {"index": index, "text": f"Knowledge chunk {index}"}
            for index in range(5)
        ],
        candidate_spans=[
            NonRecipeSpan(
                span_id="nr.knowledge.0.5",
                category="knowledge",
                block_start_index=0,
                block_end_index=5,
                block_indices=[0, 1, 2, 3, 4],
                block_ids=["b0", "b1", "b2", "b3", "b4"],
            )
        ],
        recipe_spans=[],
        workbook_slug="book",
        source_hash="hash123",
        out_dir=tmp_path / "in",
        context_blocks=1,
        prompt_target_count=2,
    )

    assert report.shards_written == 2
    assert [entry.owned_ids for entry in report.shard_entries] == [
        ("book.c0000.nr", "book.c0001.nr", "book.c0002.nr"),
        ("book.c0003.nr", "book.c0004.nr"),
    ]


def test_knowledge_phase_workers_reject_off_surface_outputs(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    runner = FakeCodexFarmRunner(
        output_builders={
            "recipe.knowledge.compact.v1": lambda shard_payload: _semantic_packet_output(
                packet_id=shard_payload["bid"],
                chunk_id=shard_payload["c"][0]["cid"],
                block_index=99,
                snippet_block_index=99,
            )
        }
    )

    manifest, reports = run_phase_workers_v1(
        phase_key="nonrecipe_knowledge_review",
        pipeline_id="recipe.knowledge.compact.v1",
        run_root=runtime_root,
        shards=[
            ShardManifestEntryV1(
                shard_id="book.ks0000.nr",
                owned_ids=("book.c0000.nr",),
                evidence_refs=("block:4",),
                input_payload={
                    "v": "2",
                    "bid": "book.ks0000.nr",
                    "c": [
                        {
                            "cid": "book.c0000.nr",
                            "b": [{"i": 4, "t": "Whisk constantly."}],
                        }
                    ],
                },
                metadata={"owned_block_indices": [4]},
            )
        ],
        runner=runner,
        worker_count=1,
        proposal_validator=validate_knowledge_shard_output,
    )

    outputs, payloads_by_shard_id = read_validated_knowledge_outputs_from_proposals(
        Path(manifest.run_root) / "proposals"
    )
    failures = json.loads((Path(manifest.run_root) / "failures.json").read_text(encoding="utf-8"))
    proposal = json.loads(
        (Path(manifest.run_root) / "proposals" / "book.ks0000.nr.json").read_text(
            encoding="utf-8"
        )
    )

    assert reports[0].failure_count == 1
    assert outputs == {}
    assert payloads_by_shard_id == {}
    assert failures == [
        {
            "reason": "proposal_validation_failed",
            "shard_id": "book.ks0000.nr",
            "validation_errors": [
                "block_decision_out_of_surface",
                "snippet_evidence_out_of_surface",
                "block_decision_coverage_mismatch",
                "snippet_evidence_wrong_chunk_surface",
            ],
            "worker_id": "worker-001",
        }
    ]
    assert proposal["validation_errors"] == [
        "block_decision_out_of_surface",
        "snippet_evidence_out_of_surface",
        "block_decision_coverage_mismatch",
        "snippet_evidence_wrong_chunk_surface",
    ]


def test_knowledge_phase_workers_reject_processing_error_fallback_with_out_of_surface_evidence(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    runner = FakeCodexFarmRunner(
        output_builders={
            "recipe.knowledge.compact.v1": lambda shard_payload: {
                "bundle_version": "2",
                "bundle_id": shard_payload["bid"],
                "chunk_results": [
                    {
                        "chunk_id": "processing_error",
                        "is_useful": False,
                        "block_decisions": [{"block_index": 4, "category": "other"}],
                        "snippets": [
                            {
                                "body": "Could not process.",
                                "evidence": [{"block_index": 0, "quote": "bad"}],
                            }
                        ],
                    }
                ],
            }
        }
    )

    manifest, reports = run_phase_workers_v1(
        phase_key="nonrecipe_knowledge_review",
        pipeline_id="recipe.knowledge.compact.v1",
        run_root=runtime_root,
        shards=[
            ShardManifestEntryV1(
                shard_id="book.ks0001.nr",
                owned_ids=("book.c0007.nr",),
                evidence_refs=("block:4",),
                input_payload={
                    "v": "2",
                    "bid": "book.ks0001.nr",
                    "c": [
                        {
                            "cid": "book.c0007.nr",
                            "b": [{"i": 4, "t": "Whisk constantly."}],
                        }
                    ],
                },
                metadata={"owned_block_indices": [4]},
            )
        ],
        runner=runner,
        worker_count=1,
        proposal_validator=validate_knowledge_shard_output,
    )

    outputs, payloads_by_shard_id = read_validated_knowledge_outputs_from_proposals(
        Path(manifest.run_root) / "proposals"
    )
    failures = json.loads((Path(manifest.run_root) / "failures.json").read_text(encoding="utf-8"))
    proposal = json.loads(
        (Path(manifest.run_root) / "proposals" / "book.ks0001.nr.json").read_text(
            encoding="utf-8"
        )
    )

    assert reports[0].failure_count == 1
    assert outputs == {}
    assert payloads_by_shard_id == {}
    assert failures == [
        {
            "reason": "proposal_validation_failed",
            "shard_id": "book.ks0001.nr",
            "validation_errors": ["schema_invalid"],
            "worker_id": "worker-001",
        }
    ]
    assert proposal["validation_errors"] == ["schema_invalid"]
