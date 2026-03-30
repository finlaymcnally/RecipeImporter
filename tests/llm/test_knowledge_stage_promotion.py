from __future__ import annotations

from cookimport.llm.codex_farm_knowledge_ingest import validate_knowledge_shard_output
from cookimport.llm.knowledge_stage.task_file_contracts import (
    build_knowledge_classification_task_file,
    combine_knowledge_task_file_outputs,
)
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1, WorkerAssignmentV1


def _assignment() -> WorkerAssignmentV1:
    return WorkerAssignmentV1(
        worker_id="worker-001",
        shard_ids=("book.ks0000.nr", "book.ks0001.nr"),
        workspace_root="/tmp/worker-001",
    )


def _shard(
    *,
    shard_id: str,
    blocks: list[tuple[int, str]],
) -> ShardManifestEntryV1:
    return ShardManifestEntryV1(
        shard_id=shard_id,
        owned_ids=(shard_id,),
        input_payload={
            "v": "1",
            "bid": shard_id,
            "b": [
                {"i": block_index, "id": f"{shard_id}:{block_index}", "t": text}
                for block_index, text in blocks
            ],
        },
        metadata={
            "owned_block_indices": [block_index for block_index, _text in blocks],
            "owned_block_count": len(blocks),
        },
    )


def test_promotion_combines_classification_and_grouping_into_final_packet_outputs() -> None:
    shards = [
        _shard(
            shard_id="book.ks0000.nr",
            blocks=[
                (10, "Balsamic Vinaigrette"),
                (11, "Acid brightens rich dishes by cutting heaviness."),
            ],
        ),
        _shard(
            shard_id="book.ks0001.nr",
            blocks=[(25, "Resting dough lets gluten relax so rolling gets easier.")],
        ),
    ]
    classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=shards,
    )

    outputs = combine_knowledge_task_file_outputs(
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id={
            "knowledge::10": {
                "category": "other",
                "reviewer_category": "other",
            },
            "knowledge::11": {
                "category": "knowledge",
                "reviewer_category": "knowledge",
            },
            "knowledge::25": {
                "category": "knowledge",
                "reviewer_category": "knowledge",
            },
        },
        grouping_answers_by_unit_id={
            "knowledge::11": {
                "group_key": "acid-balance",
                "topic_label": "Acid balance",
            },
            "knowledge::25": {
                "group_key": "dough-resting",
                "topic_label": "Dough resting",
            },
        },
        unit_to_shard_id=unit_to_shard_id,
    )

    assert outputs["book.ks0000.nr"] == {
        "packet_id": "book.ks0000.nr",
        "block_decisions": [
            {"block_index": 10, "category": "other", "reviewer_category": "other"},
            {
                "block_index": 11,
                "category": "knowledge",
                "reviewer_category": "knowledge",
            },
        ],
        "idea_groups": [
            {"group_id": "g01", "topic_label": "Acid balance", "block_indices": [11]}
        ],
    }
    assert outputs["book.ks0001.nr"] == {
        "packet_id": "book.ks0001.nr",
        "block_decisions": [
            {
                "block_index": 25,
                "category": "knowledge",
                "reviewer_category": "knowledge",
            }
        ],
        "idea_groups": [
            {"group_id": "g01", "topic_label": "Dough resting", "block_indices": [25]}
        ],
    }
    for shard in shards:
        valid, errors, metadata = validate_knowledge_shard_output(
            shard,
            outputs[shard.shard_id],
        )
        assert valid is True
        assert errors == ()
        assert metadata["knowledge_decision_count"] >= 0
