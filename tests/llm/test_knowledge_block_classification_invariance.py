from __future__ import annotations

from copy import deepcopy

from cookimport.llm.editable_task_file import build_repair_task_file
from cookimport.llm.knowledge_stage.task_file_contracts import (
    build_knowledge_classification_task_file,
    validate_knowledge_classification_task_file,
)
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1, WorkerAssignmentV1

# These cases come from the March 30, 2026 knowledge overreach failure described in the ExecPlan.
_TARGET_CASES = {
    "balsamic_vinaigrette": {
        "text": "Balsamic Vinaigrette",
        "answer": {
            "category": "other",
            "reviewer_category": "chapter_taxonomy",
            "retrieval_concept": None,
            "grounding": {"tag_keys": [], "category_keys": [], "proposed_tags": []},
        },
    },
    "generic_advice": {
        "text": (
            "Instead, once you've chosen a recipe, don't let your own intimate knowledge "
            "of your own ingredients and kitchen and, most important, your own taste be "
            "overridden by what you're reading. Be present. Stir, taste, adjust."
        ),
        "answer": {
            "category": "other",
            "reviewer_category": "other",
            "retrieval_concept": None,
            "grounding": {"tag_keys": [], "category_keys": [], "proposed_tags": []},
        },
    },
    "durable_knowledge": {
        "text": (
            "Acid brightens rich food because it balances heaviness and sharpens flavor "
            "perception across the whole dish."
        ),
        "answer": {
            "category": "knowledge",
            "reviewer_category": "knowledge",
            "retrieval_concept": "Balance richness with acid",
            "grounding": {
                "tag_keys": ["bright"],
                "category_keys": ["flavor-profile"],
                "proposed_tags": [],
            },
        },
    },
}


def _assignment() -> WorkerAssignmentV1:
    return WorkerAssignmentV1(
        worker_id="worker-001",
        shard_ids=("book.ks0000.nr",),
        workspace_root="/tmp/worker-001",
    )


def _shard(*, shard_id: str, blocks: list[tuple[int, str]]) -> ShardManifestEntryV1:
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
            "x": {
                "p": [{"i": 1, "t": "Local heading context."}],
                "n": [{"i": 999, "t": "Local following context."}],
            },
        },
        metadata={
            "owned_block_indices": [block_index for block_index, _text in blocks],
            "owned_block_count": len(blocks),
        },
    )


def _answers_for_task_file(task_file: dict) -> dict[str, dict[str, str]]:
    answers: dict[str, dict[str, str]] = {}
    for unit in task_file["units"]:
        text = unit["evidence"]["text"]
        for fixture in _TARGET_CASES.values():
            if fixture["text"] == text:
                answers[unit["unit_id"]] = dict(fixture["answer"])
                break
        else:
            answers[unit["unit_id"]] = {
                "category": "other",
                "reviewer_category": "other",
            }
    return answers


def _edited_task_file(task_file: dict) -> dict:
    edited = deepcopy(task_file)
    answers = _answers_for_task_file(task_file)
    for unit in edited["units"]:
        unit["answer"] = dict(answers[unit["unit_id"]])
    return edited


def _target_unit(task_file: dict, target_text: str) -> dict:
    return next(unit for unit in task_file["units"] if unit["evidence"]["text"] == target_text)


def test_target_block_evidence_and_answer_surface_stay_invariant_across_packings() -> None:
    target_text = _TARGET_CASES["balsamic_vinaigrette"]["text"]
    alone_task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[_shard(shard_id="book.ks0000.nr", blocks=[(10, target_text)])],
    )
    mixed_task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(
                shard_id="book.ks0000.nr",
                blocks=[
                    (10, target_text),
                    (30, _TARGET_CASES["generic_advice"]["text"]),
                    (50, _TARGET_CASES["durable_knowledge"]["text"]),
                ],
            )
        ],
    )
    reordered_task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(
                shard_id="book.ks0000.nr",
                blocks=[
                    (50, _TARGET_CASES["durable_knowledge"]["text"]),
                    (10, target_text),
                    (30, _TARGET_CASES["generic_advice"]["text"]),
                ],
            )
        ],
    )

    target_evidence = _target_unit(alone_task_file, target_text)["evidence"]
    assert _target_unit(mixed_task_file, target_text)["evidence"] == target_evidence
    assert _target_unit(reordered_task_file, target_text)["evidence"] == target_evidence
    assert "group_key" not in _target_unit(mixed_task_file, target_text)["answer"]
    assert "topic_label" not in _target_unit(mixed_task_file, target_text)["answer"]
    assert mixed_task_file["ontology"] == alone_task_file["ontology"]


def test_expected_classifications_survive_alone_mixed_reordered_and_repair_shapes() -> None:
    task_file, _ = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(
                shard_id="book.ks0000.nr",
                blocks=[
                    (10, _TARGET_CASES["balsamic_vinaigrette"]["text"]),
                    (30, _TARGET_CASES["generic_advice"]["text"]),
                    (50, _TARGET_CASES["durable_knowledge"]["text"]),
                ],
            )
        ],
    )
    edited = _edited_task_file(task_file)
    answers_by_unit_id, errors, metadata = validate_knowledge_classification_task_file(
        original_task_file=task_file,
        edited_task_file=edited,
    )

    assert errors == ()
    assert answers_by_unit_id is not None
    assert answers_by_unit_id["knowledge::10"] == _TARGET_CASES["balsamic_vinaigrette"]["answer"]
    assert answers_by_unit_id["knowledge::30"] == _TARGET_CASES["generic_advice"]["answer"]
    assert answers_by_unit_id["knowledge::50"] == _TARGET_CASES["durable_knowledge"]["answer"]

    repair_task_file = build_repair_task_file(
        original_task_file=task_file,
        failed_unit_ids=["knowledge::10"],
        previous_answers_by_unit_id=_answers_for_task_file(task_file),
        validation_feedback_by_unit_id={
            "knowledge::10": {"validation_errors": ["knowledge_reviewer_category_mismatch"]}
        },
    )
    repair_edited = _edited_task_file(repair_task_file)
    repair_answers, repair_errors, repair_metadata = validate_knowledge_classification_task_file(
        original_task_file=repair_task_file,
        edited_task_file=repair_edited,
    )

    assert repair_errors == ()
    assert repair_metadata["failed_unit_ids"] == []
    assert repair_answers == {
        "knowledge::10": _TARGET_CASES["balsamic_vinaigrette"]["answer"]
    }
