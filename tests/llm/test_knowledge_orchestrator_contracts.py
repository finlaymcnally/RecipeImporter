from __future__ import annotations

from cookimport.llm.codex_farm_knowledge_orchestrator import _preflight_knowledge_shard
from cookimport.llm.knowledge_stage.recovery import _build_knowledge_workspace_worker_prompt
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1, TaskManifestEntryV1


def test_preflight_knowledge_shard_accepts_packet_payload() -> None:
    shard = ShardManifestEntryV1(
        shard_id="book.kp0000.nr",
        owned_ids=("book.kp0000.nr",),
        input_payload={
            "v": "1",
            "bid": "book.kp0000.nr",
            "b": [{"i": 4, "t": "Whisk constantly."}],
        },
    )

    assert _preflight_knowledge_shard(shard) is None


def test_preflight_knowledge_shard_rejects_missing_packet_id() -> None:
    shard = ShardManifestEntryV1(
        shard_id="book.kp0000.nr",
        owned_ids=("book.kp0000.nr",),
        input_payload={
            "v": "1",
            "b": [{"i": 4, "t": "Whisk constantly."}],
        },
    )

    assert _preflight_knowledge_shard(shard) == {
        "reason_code": "preflight_invalid_shard_payload",
        "reason_detail": "knowledge shard is missing `bid`",
    }


def test_worker_prompt_describes_packet_contract() -> None:
    prompt = _build_knowledge_workspace_worker_prompt(
        tasks=[
            TaskManifestEntryV1(
                task_id="book.kp0000.nr",
                task_kind="knowledge_review_packet_task",
                parent_shard_id="book.kp0000.nr",
                owned_ids=("book.kp0000.nr",),
                input_payload={
                    "v": "1",
                    "bid": "book.kp0000.nr",
                    "b": [{"i": 4, "t": "Whisk constantly."}],
                },
                input_text="{}",
                metadata={},
            )
        ]
    )

    assert "Top level keys: `packet_id`, `block_decisions`, `idea_groups`." in prompt
    assert "Each task owns exactly one authoritative packet." in prompt
    assert "Every `knowledge` block must appear in exactly one idea group." in prompt
    assert "chunk_results" not in prompt
    assert "`reason_code` must be one of" not in prompt
