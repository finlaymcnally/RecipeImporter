from __future__ import annotations

from copy import deepcopy

from cookimport.llm.knowledge_stage.task_file_contracts import (
    KNOWLEDGE_GROUP_SCHEMA_VERSION,
    KNOWLEDGE_GROUP_STAGE_KEY,
    build_knowledge_classification_task_file,
    build_knowledge_grouping_task_file,
    build_knowledge_grouping_task_files,
    canonicalize_knowledge_grouping_answer_ids,
    validate_knowledge_grouping_task_file,
)
from cookimport.llm.knowledge_stage.structured_session_contract import (
    build_knowledge_edited_task_file_from_grouping_response,
)
from cookimport.llm.knowledge_tag_catalog import load_knowledge_tag_catalog
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1, WorkerAssignmentV1


def _assignment() -> WorkerAssignmentV1:
    return WorkerAssignmentV1(
        worker_id="worker-001",
        shard_ids=("book.ks0000.nr",),
        workspace_root="/tmp/worker-001",
    )


def _shard(*, block_index: int, text: str) -> ShardManifestEntryV1:
    return ShardManifestEntryV1(
        shard_id="book.ks0000.nr",
        owned_ids=("book.ks0000.nr",),
        input_payload={
            "v": "1",
            "bid": "book.ks0000.nr",
            "b": [{"i": block_index, "id": f"book.ks0000.nr:{block_index}", "t": text}],
        },
        metadata={"owned_block_indices": [block_index], "owned_block_count": 1},
    )


def _group_answer(
    *,
    group_id: str,
    topic_label: str,
    tag_keys: list[str] | None = None,
    proposed_tags: list[dict[str, str]] | None = None,
    why_no_existing_tag: str | None = None,
    retrieval_query: str | None = None,
) -> dict[str, object]:
    catalog = load_knowledge_tag_catalog()
    categories = [
        catalog.tag_by_key[tag_key].category_key
        for tag_key in (tag_keys or [])
        if tag_key in catalog.tag_by_key
    ]
    if proposed_tags:
        categories.extend(
            str(tag.get("category_key") or "").strip()
            for tag in proposed_tags
            if str(tag.get("category_key") or "").strip()
        )
    return {
        "group_id": group_id,
        "topic_label": topic_label,
        "grounding": {
            "tag_keys": list(tag_keys or []),
            "category_keys": categories,
            "proposed_tags": list(proposed_tags or []),
        },
        "why_no_existing_tag": why_no_existing_tag,
        "retrieval_query": retrieval_query,
    }


def _group_span(
    *,
    group_id: str,
    start_row_id: str,
    end_row_id: str,
    topic_label: str,
    tag_keys: list[str] | None = None,
    proposed_tags: list[dict[str, str]] | None = None,
    why_no_existing_tag: str | None = None,
    retrieval_query: str | None = None,
) -> dict[str, object]:
    answer = _group_answer(
        group_id=group_id,
        topic_label=topic_label,
        tag_keys=tag_keys,
        proposed_tags=proposed_tags,
        why_no_existing_tag=why_no_existing_tag,
        retrieval_query=retrieval_query,
    )
    return {
        "group_id": answer["group_id"],
        "start_row_id": start_row_id,
        "end_row_id": end_row_id,
        "topic_label": answer["topic_label"],
        "grounding": answer["grounding"],
        "why_no_existing_tag": answer["why_no_existing_tag"],
        "retrieval_query": answer["retrieval_query"],
    }


def test_grouping_task_file_only_contains_kept_rows() -> None:
    classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(block_index=5, text="Balsamic Vinaigrette"),
            _shard(block_index=6, text="Use low heat and whisk steadily."),
        ],
    )

    grouping_task_file, grouping_unit_to_shard_id = build_knowledge_grouping_task_file(
        assignment_id="worker-001",
        worker_id="worker-001",
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id={
            "knowledge::5": {"category": "other"},
            "knowledge::6": {"category": "keep_for_review"},
        },
        unit_to_shard_id=unit_to_shard_id,
    )

    assert grouping_task_file["schema_version"] == KNOWLEDGE_GROUP_SCHEMA_VERSION
    assert grouping_task_file["stage_key"] == KNOWLEDGE_GROUP_STAGE_KEY
    assert [unit["unit_id"] for unit in grouping_task_file["units"]] == ["knowledge::6"]
    assert grouping_unit_to_shard_id == {"knowledge::6": "book.ks0000.nr"}


def test_grouping_validator_accepts_existing_tag_group_grounding() -> None:
    classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[_shard(block_index=8, text="Use low heat and whisk steadily.")],
    )
    grouping_task_file, _ = build_knowledge_grouping_task_file(
        assignment_id="worker-001",
        worker_id="worker-001",
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id={"knowledge::8": {"category": "keep_for_review"}},
        unit_to_shard_id=unit_to_shard_id,
    )
    edited = deepcopy(grouping_task_file)
    edited["units"][0]["answer"] = _group_answer(
        group_id="g01",
        topic_label="Heat control",
        tag_keys=["saute"],
    )

    answers_by_unit_id, errors, metadata = validate_knowledge_grouping_task_file(
        original_task_file=grouping_task_file,
        edited_task_file=edited,
    )

    assert errors == ()
    assert metadata["failed_unit_ids"] == []
    assert answers_by_unit_id == {
        "knowledge::8": {
            "group_id": "g01",
            "topic_label": "Heat control",
            "grounding": {
                "tag_keys": ["saute"],
                "category_keys": ["cooking-method"],
                "proposed_tags": [],
            },
            "why_no_existing_tag": None,
            "retrieval_query": None,
        }
    }


def test_grouping_validator_requires_tag_story_and_group_consistency() -> None:
    classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(block_index=11, text="Rest dough before rolling."),
            _shard(block_index=12, text="Resting relaxes the gluten."),
        ],
    )
    grouping_task_file, _ = build_knowledge_grouping_task_file(
        assignment_id="worker-001",
        worker_id="worker-001",
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id={
            "knowledge::11": {"category": "keep_for_review"},
            "knowledge::12": {"category": "keep_for_review"},
        },
        unit_to_shard_id=unit_to_shard_id,
    )

    invalid = deepcopy(grouping_task_file)
    invalid["units"][0]["answer"] = _group_answer(
        group_id="g01",
        topic_label="Dough resting",
        tag_keys=["rest"],
    )
    invalid["units"][1]["answer"] = _group_answer(
        group_id="g01",
        topic_label="Dough resting",
        proposed_tags=[
            {
                "key": "dough-resting",
                "display_name": "Dough resting",
                "category_key": "techniques",
            }
        ],
        why_no_existing_tag="No existing tag fits the dough-resting concept.",
        retrieval_query="why rest dough before rolling",
    )

    answers_by_unit_id, errors, metadata = validate_knowledge_grouping_task_file(
        original_task_file=grouping_task_file,
        edited_task_file=invalid,
    )

    assert answers_by_unit_id is None
    assert "knowledge_group_mixed_tag_story" in errors
    assert sorted(metadata["failed_unit_ids"]) == ["knowledge::11", "knowledge::12"]


def test_grouping_answer_id_canonicalization_recovers_repair_subset_collisions() -> None:
    classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(block_index=51, text="Buy whole spices and grind them just before use."),
            _shard(block_index=52, text="Fresh grinding releases aromatic oils."),
            _shard(block_index=53, text="Salt improves dessert flavor."),
            _shard(block_index=54, text="Desserts need a pinch of salt too."),
            _shard(block_index=55, text="Finish cookie dough with flaky salt."),
        ],
    )
    grouping_task_file, _ = build_knowledge_grouping_task_file(
        assignment_id="worker-001",
        worker_id="worker-001",
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id={
            "knowledge::51": {"category": "keep_for_review"},
            "knowledge::52": {"category": "keep_for_review"},
            "knowledge::53": {"category": "keep_for_review"},
            "knowledge::54": {"category": "keep_for_review"},
            "knowledge::55": {"category": "keep_for_review"},
        },
        unit_to_shard_id=unit_to_shard_id,
    )

    merged_answers = {
        "knowledge::51": _group_answer(
            group_id="g01",
            topic_label="Fresh-ground spices",
            proposed_tags=[
                {
                    "key": "fresh-ground-spices",
                    "display_name": "Fresh-ground spices",
                    "category_key": "techniques",
                }
            ],
            why_no_existing_tag="No existing tag covers grinding whole spices right before use.",
            retrieval_query="whole spices grind before use aromatic oils",
        ),
        "knowledge::52": _group_answer(
            group_id="g01",
            topic_label="Fresh-ground spices",
            proposed_tags=[
                {
                    "key": "fresh-ground-spices",
                    "display_name": "Fresh-ground spices",
                    "category_key": "techniques",
                }
            ],
            why_no_existing_tag="No existing tag covers grinding whole spices right before use.",
            retrieval_query="whole spices grind before use aromatic oils",
        ),
        "knowledge::53": _group_answer(
            group_id="g01",
            topic_label="Salt in desserts",
            tag_keys=["sweet", "dessert"],
        ),
        "knowledge::54": _group_answer(
            group_id="g01",
            topic_label="Salt in desserts",
            tag_keys=["sweet", "dessert"],
        ),
        "knowledge::55": _group_answer(
            group_id="g01",
            topic_label="Salt in desserts",
            tag_keys=["sweet", "dessert"],
        ),
    }

    invalid = deepcopy(grouping_task_file)
    for unit in invalid["units"]:
        unit_id = str(unit.get("unit_id") or "")
        if unit_id in merged_answers:
            unit["answer"] = deepcopy(merged_answers[unit_id])

    answers_by_unit_id, errors, metadata = validate_knowledge_grouping_task_file(
        original_task_file=grouping_task_file,
        edited_task_file=invalid,
    )

    assert answers_by_unit_id is None
    assert errors == ("knowledge_group_mixed_tag_story",)
    assert sorted(metadata["failed_unit_ids"]) == [
        "knowledge::51",
        "knowledge::52",
        "knowledge::53",
        "knowledge::54",
        "knowledge::55",
    ]

    canonical_answers = canonicalize_knowledge_grouping_answer_ids(
        original_task_file=grouping_task_file,
        answers_by_unit_id=merged_answers,
    )
    repaired = deepcopy(grouping_task_file)
    for unit in repaired["units"]:
        unit_id = str(unit.get("unit_id") or "")
        if unit_id in canonical_answers:
            unit["answer"] = deepcopy(canonical_answers[unit_id])

    repaired_answers_by_unit_id, repaired_errors, repaired_metadata = (
        validate_knowledge_grouping_task_file(
            original_task_file=grouping_task_file,
            edited_task_file=repaired,
        )
    )

    assert repaired_errors == ()
    assert repaired_metadata["failed_unit_ids"] == []
    assert repaired_answers_by_unit_id is not None
    assert repaired_answers_by_unit_id["knowledge::51"]["group_id"] == "g01"
    assert repaired_answers_by_unit_id["knowledge::52"]["group_id"] == "g01"
    assert repaired_answers_by_unit_id["knowledge::53"]["group_id"] == "g02"
    assert repaired_answers_by_unit_id["knowledge::54"]["group_id"] == "g02"
    assert repaired_answers_by_unit_id["knowledge::55"]["group_id"] == "g02"


def test_grouping_structured_response_maps_group_fields_and_reports_missing_rows() -> None:
    classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(block_index=21, text="Use gentle heat for eggs."),
            _shard(block_index=22, text="Rest dough before rolling."),
        ],
    )
    grouping_task_file, _ = build_knowledge_grouping_task_file(
        assignment_id="worker-001",
        worker_id="worker-001",
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id={
            "knowledge::21": {"category": "keep_for_review"},
            "knowledge::22": {"category": "keep_for_review"},
        },
        unit_to_shard_id=unit_to_shard_id,
    )

    edited, errors, metadata = build_knowledge_edited_task_file_from_grouping_response(
        original_task_file=grouping_task_file,
        response_text='{"groups":[{"group_id":"g01","start_row_id":"r01","end_row_id":"r01","topic_label":"Heat control","grounding":{"tag_keys":["saute"],"category_keys":["cooking-method"],"proposed_tags":[]},"why_no_existing_tag":null,"retrieval_query":null}]}',
    )

    assert edited is not None
    assert errors == ("knowledge_missing_response_rows",)
    assert metadata["failed_unit_ids"] == ["knowledge::22"]
    assert edited["units"][0]["answer"] == {
            "group_id": "g01",
            "topic_label": "Heat control",
            "grounding": {
                "tag_keys": ["saute"],
                "category_keys": ["cooking-method"],
                "proposed_tags": [],
        },
        "why_no_existing_tag": "",
        "retrieval_query": "",
    }
    assert "answer" not in edited["units"][1]


def test_grouping_validator_rejects_noncontiguous_group_runs() -> None:
    classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=[
            _shard(block_index=31, text="Use gentle heat for eggs."),
            _shard(block_index=32, text="Let dough rest before rolling."),
            _shard(block_index=33, text="Return to gentle heat before serving."),
        ],
    )
    grouping_task_file, _ = build_knowledge_grouping_task_file(
        assignment_id="worker-001",
        worker_id="worker-001",
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id={
            "knowledge::31": {"category": "keep_for_review"},
            "knowledge::32": {"category": "keep_for_review"},
            "knowledge::33": {"category": "keep_for_review"},
        },
        unit_to_shard_id=unit_to_shard_id,
    )

    invalid = deepcopy(grouping_task_file)
    invalid["units"][0]["answer"] = _group_answer(
        group_id="g01",
        topic_label="Heat control",
        tag_keys=["saute"],
    )
    invalid["units"][1]["answer"] = _group_answer(
        group_id="g02",
        topic_label="Dough resting",
        proposed_tags=[
            {
                "key": "dough-resting",
                "display_name": "Dough resting",
                "category_key": "techniques",
            }
        ],
        why_no_existing_tag="No existing tag fits the dough-resting concept.",
        retrieval_query="why rest dough before rolling",
    )
    invalid["units"][2]["answer"] = _group_answer(
        group_id="g01",
        topic_label="Heat control",
        tag_keys=["saute"],
    )

    answers_by_unit_id, errors, metadata = validate_knowledge_grouping_task_file(
        original_task_file=grouping_task_file,
        edited_task_file=invalid,
    )

    assert answers_by_unit_id is None
    assert "knowledge_group_noncontiguous_span" in errors
    assert sorted(metadata["failed_unit_ids"]) == [
        "knowledge::31",
        "knowledge::33",
    ]
    assert metadata["knowledge_group_noncontiguous_blocks"] == [31, 33]


def test_grouping_batches_stay_partitioned_for_large_kept_sets() -> None:
    shards = [
        _shard(block_index=index, text=f"Technique note {index}")
        for index in range(40, 46)
    ]
    classification_task_file, unit_to_shard_id = build_knowledge_classification_task_file(
        assignment=_assignment(),
        shards=shards,
    )
    task_files, _unit_to_shard, batch_unit_ids = build_knowledge_grouping_task_files(
        assignment_id="worker-001",
        worker_id="worker-001",
        classification_task_file=classification_task_file,
        classification_answers_by_unit_id={
            f"knowledge::{index}": {"category": "keep_for_review"}
            for index in range(40, 46)
        },
        unit_to_shard_id=unit_to_shard_id,
        max_units_per_batch=2,
        max_evidence_chars_per_batch=10_000,
    )

    assert len(task_files) == 3
    assert batch_unit_ids == [
        ["knowledge::40", "knowledge::41"],
        ["knowledge::42", "knowledge::43"],
        ["knowledge::44", "knowledge::45"],
    ]
