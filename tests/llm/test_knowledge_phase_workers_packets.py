from __future__ import annotations

import json
from pathlib import Path

from cookimport.llm.codex_farm_knowledge_ingest import (
    read_validated_knowledge_outputs_from_proposals,
    validate_knowledge_shard_output,
)
from cookimport.llm.codex_farm_knowledge_jobs import build_knowledge_jobs
from cookimport.llm.fake_codex_farm_runner import FakeCodexFarmRunner
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1, run_phase_workers_v1
from cookimport.staging.nonrecipe_stage import NonRecipeSpan


def test_build_knowledge_jobs_emits_shard_entries(tmp_path: Path) -> None:
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
        out_dir=tmp_path / "in",
        context_blocks=1,
    )

    assert report.shards_written == 1
    assert [entry.shard_id for entry in report.shard_entries] == ["book.ks0000.nr"]
    assert report.shard_entries[0].owned_ids == ("book.ks0000.nr",)
    payload = json.loads((tmp_path / "in" / "book.ks0000.nr.json").read_text(encoding="utf-8"))
    assert payload["bid"] == "book.ks0000.nr"
    assert [row["i"] for row in payload["b"]] == [0, 1, 2]


def test_knowledge_phase_workers_reject_off_surface_group_outputs(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    runner = FakeCodexFarmRunner(
        output_builders={
            "recipe.knowledge.packet.v1": lambda shard_payload: {
                "packet_id": shard_payload["bid"],
                "block_decisions": [
                    {
                        "block_index": 4,
                        "category": "knowledge",
                        "reviewer_category": "knowledge",
                        "retrieval_concept": "Keep the emulsion stable",
                        "grounding": {
                            "tag_keys": ["emulsify"],
                            "category_keys": ["techniques"],
                            "proposed_tags": [],
                        },
                    }
                ],
                "idea_groups": [
                    {
                        "group_id": "g01",
                        "topic_label": "bad",
                        "block_indices": [4, 99],
                    }
                ],
            }
        }
    )

    manifest, reports = run_phase_workers_v1(
        phase_key="nonrecipe_finalize",
        pipeline_id="recipe.knowledge.packet.v1",
        run_root=runtime_root,
        shards=[
            ShardManifestEntryV1(
                shard_id="book.ks0000.nr",
                owned_ids=("book.ks0000.nr",),
                evidence_refs=("block:4",),
                input_payload={
                    "v": "1",
                    "bid": "book.ks0000.nr",
                    "b": [{"i": 4, "t": "Whisk constantly."}],
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
            "validation_errors": ["group_contains_other_block"],
            "worker_id": "worker-001",
        }
    ]
    assert proposal["validation_errors"] == ["group_contains_other_block"]


def test_knowledge_phase_workers_accept_valid_shard_outputs(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    runner = FakeCodexFarmRunner()

    manifest, reports = run_phase_workers_v1(
        phase_key="nonrecipe_finalize",
        pipeline_id="recipe.knowledge.packet.v1",
        run_root=runtime_root,
        shards=[
            ShardManifestEntryV1(
                shard_id="book.ks0000.nr",
                owned_ids=("book.ks0000.nr",),
                evidence_refs=("block:4",),
                input_payload={
                    "v": "1",
                    "bid": "book.ks0000.nr",
                    "b": [{"i": 4, "t": "Whisk constantly."}],
                },
                metadata={"owned_block_indices": [4]},
            )
        ],
        runner=runner,
        worker_count=1,
        proposal_validator=validate_knowledge_shard_output,
    )

    proposal = json.loads(
        (Path(manifest.run_root) / "proposals" / "book.ks0000.nr.json").read_text(
            encoding="utf-8"
        )
    )

    assert reports[0].failure_count == 0
    assert proposal["validation_errors"] == []
    assert proposal["payload"]["packet_id"] == "book.ks0000.nr"
    assert proposal["validation_metadata"]["bundle_id"] == "book.ks0000.nr"
