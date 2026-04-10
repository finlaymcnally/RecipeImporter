from __future__ import annotations

import json
from pathlib import Path

from cookimport.llm.codex_exec_runner import CodexExecLiveSnapshot
from cookimport.llm.codex_farm_knowledge_orchestrator import _preflight_knowledge_shard
from cookimport.llm.editable_task_file import (
    build_repair_task_file,
    summarize_task_file,
    write_task_file,
)
from cookimport.llm.knowledge_stage import _shared as knowledge_stage_shared
from cookimport.llm.knowledge_stage.recovery import (
    _KNOWLEDGE_WORKSPACE_COMPLETION_QUIESCENCE_SECONDS,
    _build_knowledge_taskfile_prompt,
    _build_strict_json_watchdog_callback,
    _write_knowledge_worker_hint,
)
from cookimport.llm.knowledge_stage.task_file_contracts import (
    build_knowledge_classification_task_file,
)
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1, WorkerAssignmentV1


def test_preflight_knowledge_shard_accepts_shard_payload() -> None:
    shard = ShardManifestEntryV1(
        shard_id="book.ks0000.nr",
        owned_ids=("book.ks0000.nr",),
        input_payload={
            "v": "1",
            "bid": "book.ks0000.nr",
            "b": [{"i": 4, "t": "Whisk constantly."}],
        },
    )

    assert _preflight_knowledge_shard(shard) is None


def test_preflight_knowledge_shard_rejects_missing_bundle_id() -> None:
    shard = ShardManifestEntryV1(
        shard_id="book.ks0000.nr",
        owned_ids=("book.ks0000.nr",),
        input_payload={"v": "1", "b": [{"i": 4, "t": "Whisk constantly."}]},
    )

    assert _preflight_knowledge_shard(shard) == {
        "reason_code": "preflight_invalid_shard_payload",
        "reason_detail": "knowledge shard is missing `bid`",
    }


def test_worker_prompt_describes_task_file_contract() -> None:
    prompt = _build_knowledge_taskfile_prompt(
        stage_key="nonrecipe_classify",
        shards=[
            ShardManifestEntryV1(
                shard_id="book.ks0000.nr",
                owned_ids=("book.ks0000.nr",),
                input_payload={
                    "v": "1",
                    "bid": "book.ks0000.nr",
                    "b": [{"i": 4, "t": "Whisk constantly."}],
                },
                input_text=None,
                metadata={},
            )
        ]
    )

    assert "task.json" in prompt
    assert "Open `task.json` directly" in prompt
    assert "`task.json` is the whole job at each step." in prompt
    assert "- Start with `task.json`." in prompt
    assert "- Edit only the `answer` object inside each unit." in prompt
    assert "- After each edit pass, run `task-handoff` from the workspace root." in prompt
    assert (
        "- After the helper returns, trust the current `task.json` as the new whole job." in prompt
    )
    assert (
        "- If the helper reports `repair_required` or `advance_to_grouping`, reopen the rewritten "
        "`task.json` immediately and continue in the same session." in prompt
    )
    assert (
        "- Stop only after the helper reports `completed_without_grouping` or "
        "`completed_with_grouping`." in prompt
    )
    assert "Harmless local retries are not the point of failure here." in prompt
    assert "Ordinary local reads of `task.json` and `AGENTS.md` are allowed." in prompt
    assert "Do not invent queue advancement, control files, helper ledgers, or alternate output files." in prompt
    assert "This is the classification step." in prompt
    assert "Read the full classification file once" in prompt
    assert "Answer each unit with `category` and `grounding`." in prompt
    assert "You are doing close semantic review, not building a heuristic classifier" in prompt
    assert "Treat heading shape and packet position as weak hints only" in prompt
    assert "If you feel tempted to invent a rule that covers many rows at once" in prompt
    assert "If `category` is `knowledge`, `grounding` must include at least one existing `tag_key`" in prompt
    assert "personal story with an embedded cooking lesson is still usually `other`" in prompt
    assert "Praise, endorsement, foreword, thesis, manifesto" in prompt
    assert "A heading alone is not enough for `knowledge`." in prompt
    assert "Short conceptual headings can still be `knowledge`" in prompt
    assert "unsupported by reusable explanatory body text in the owned packet" in prompt
    assert "Proposed tags are allowed only for real retrieval-grade concepts" in prompt
    assert "Do not compress the packet into one global keep/drop rule" in prompt
    assert "Do not invent `group_key`, `topic_label`, packet summaries, or cross-unit grouping notes in this step." in prompt
    assert "Do not return shard outputs in your final message." in prompt
    assert "Assigned shard ids represented in this task file: `book.ks0000.nr`." in prompt
    assert "current_packet.json" not in prompt
    assert "current_hint.md" not in prompt
    assert "current_result_path.txt" not in prompt
    assert "packet_lease_status.json" not in prompt
    assert "CURRENT_PHASE.md" not in prompt
    assert "check-phase" not in prompt
    assert "install-phase" not in prompt


def test_knowledge_worker_hint_stays_compact_and_keeps_high_signal_sections(
    tmp_path: Path,
) -> None:
    hint_path = tmp_path / "hint.md"
    shard = ShardManifestEntryV1(
        shard_id="book.ks0000.nr",
        owned_ids=("book.ks0000.nr",),
        input_payload={
            "v": "1",
            "bid": "book.ks0000.nr",
            "b": [
                {"i": 4, "t": "WHAT IS ACID?", "hl": 2},
                {
                    "i": 18,
                    "t": "Acid brightens food because it balances richness and sharpens flavor perception across the whole dish.",
                },
                {
                    "i": 40,
                    "t": "Conversion table row",
                    "th": {"id": "tbl-1", "c": "Conversions", "r": 0},
                },
            ],
            "g": {"r": [2, 3]},
        },
        input_text=None,
        metadata={},
    )

    _write_knowledge_worker_hint(path=hint_path, shard=shard)
    rendered = hint_path.read_text(encoding="utf-8")

    assert "## Packet summary" in rendered
    assert "## Shard interpretation" in rendered
    assert "## Decision policy" in rendered
    assert "## Shard examples" in rendered
    assert "## Attention rows" in rendered
    assert "## How to use this task" not in rendered
    assert "## Shard profile" not in rendered
    assert "`examples/valid_heading_with_useful_body_packet.json`" in rendered
    assert "Nearby recipe guardrail block indices: `2, 3`." in rendered
    assert "gap_from_prev=14" in rendered
    assert "table_hint" in rendered
    assert "Do not turn heading shape or packet profile into a bulk heuristic" in rendered
    assert "If a short heading feels ambiguous, ask whether it introduces portable cooking knowledge and is supported by reusable body text" in rendered
    assert "Memoir, praise, endorsement, foreword, and thesis-like framing are usually `other`" in rendered
    assert rendered.count("## ") == 5


def test_knowledge_stage_shared_no_longer_imports_legacy_workspace_helper_surface() -> None:
    shared_source = Path(knowledge_stage_shared.__file__).read_text(encoding="utf-8")

    assert "knowledge_workspace_tools" not in shared_source


def test_knowledge_task_file_summary_surfaces_semantic_review_contract() -> None:
    task_file, _unit_to_shard = build_knowledge_classification_task_file(
        assignment=WorkerAssignmentV1(
            worker_id="worker-001",
            shard_ids=("book.ks0000.nr",),
            workspace_root="/tmp/worker-001",
        ),
        shards=[
            ShardManifestEntryV1(
                shard_id="book.ks0000.nr",
                owned_ids=("book.ks0000.nr",),
                input_payload={
                    "v": "1",
                    "bid": "book.ks0000.nr",
                    "b": [{"i": 4, "t": "Heat control matters for browning."}],
                },
                input_text=None,
                metadata={},
            )
        ],
    )

    review_contract = task_file.get("review_contract")
    assert isinstance(review_contract, dict)
    assert review_contract.get("mode") == "semantic_review"
    assert "close semantic review" in str(review_contract.get("worker_role") or "")
    assert "candidate tags" not in " ".join(review_contract.get("anti_patterns") or []).lower()
    assert any(
        "heading alone is not enough" in row.lower()
        for row in (review_contract.get("decision_policy") or [])
    )

    summary = summarize_task_file(payload=task_file)
    summary_contract = summary.get("review_contract")
    assert isinstance(summary_contract, dict)
    assert summary_contract.get("mode") == "semantic_review"
    assert "standalone cooking concept" in str(
        summary_contract.get("primary_question") or ""
    )
    assert any(
        "weak hints" in row.lower()
        for row in (summary_contract.get("decision_policy") or [])
    )
    assert any(
        "local runs of adjacent rows" in row.lower()
        for row in (summary_contract.get("decision_policy") or [])
    )
    assert any(
        "decide by local span, emit by row" in row.lower()
        for row in (summary_contract.get("decision_policy") or [])
    )
    assert any(
        "many rows at once" in row.lower()
        for row in (summary_contract.get("anti_patterns") or [])
    )
    assert any(
        "manifesto" in row.lower()
        for row in (summary_contract.get("anti_patterns") or [])
    )


def test_knowledge_repair_task_file_preserves_semantic_review_contract() -> None:
    original_task_file, _unit_to_shard = build_knowledge_classification_task_file(
        assignment=WorkerAssignmentV1(
            worker_id="worker-001",
            shard_ids=("book.ks0000.nr",),
            workspace_root="/tmp/worker-001",
        ),
        shards=[
            ShardManifestEntryV1(
                shard_id="book.ks0000.nr",
                owned_ids=("book.ks0000.nr",),
                input_payload={
                    "v": "1",
                    "bid": "book.ks0000.nr",
                    "b": [{"i": 4, "t": "Heat control matters for browning."}],
                },
                input_text=None,
                metadata={},
            )
        ],
    )

    repair_task_file = build_repair_task_file(
        original_task_file=original_task_file,
        failed_unit_ids=["knowledge::4"],
        previous_answers_by_unit_id={
            "knowledge::4": {
                "category": "knowledge",
                "grounding": {
                    "tag_keys": [],
                    "category_keys": [],
                    "proposed_tags": [
                        {
                            "key": "heat-control",
                            "display_name": "Heat control",
                            "category_key": "techniques",
                        }
                    ],
                },
            }
        },
        validation_feedback_by_unit_id={
            "knowledge::4": {"validation_errors": ["example_feedback"]}
        },
    )

    assert repair_task_file.get("review_contract") == original_task_file.get("review_contract")
    summary = summarize_task_file(payload=repair_task_file)
    assert summary.get("review_contract", {}).get("mode") == "semantic_review"


def test_knowledge_workspace_watchdog_completes_after_stable_outputs_without_queue_controller(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "out" / "book.ks0000.nr.json"
    callback = _build_strict_json_watchdog_callback(
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="taskfile_v1",
        allow_workspace_commands=True,
        expected_workspace_output_paths=[output_path],
    )

    first = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.1,
            last_event_seconds_ago=0.0,
            event_count=3,
            command_execution_count=1,
            reasoning_item_count=0,
            agent_message_count=0,
            turn_completed_count=0,
            last_command="/bin/bash -lc 'cat task.json'",
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text('{"ok": true}\n', encoding="utf-8")
    second = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.2,
            last_event_seconds_ago=0.0,
            event_count=6,
            command_execution_count=2,
            reasoning_item_count=0,
            agent_message_count=0,
            turn_completed_count=0,
            last_command="/bin/bash -lc 'python3 -m cookimport.llm.knowledge_same_session_handoff'",
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )
    third = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.2 + _KNOWLEDGE_WORKSPACE_COMPLETION_QUIESCENCE_SECONDS + 0.1,
            last_event_seconds_ago=0.0,
            event_count=9,
            command_execution_count=2,
            reasoning_item_count=0,
            agent_message_count=0,
            turn_completed_count=0,
            last_command="/bin/bash -lc 'python3 -m cookimport.llm.knowledge_same_session_handoff'",
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert first is None
    assert second is None
    assert third is not None
    assert third.supervision_state == "completed"
    assert third.reason_code == "workspace_expected_outputs_completed"

    live_status = (tmp_path / "live_status.json").read_text(encoding="utf-8")
    assert "workspace_output_complete" in live_status
    assert "workspace_completion_waiting_for_exit" in live_status


def test_knowledge_workspace_watchdog_warns_on_egregious_single_file_shell_transform(
    tmp_path: Path,
) -> None:
    task_file, _unit_to_shard = build_knowledge_classification_task_file(
        assignment=WorkerAssignmentV1(
            worker_id="worker-001",
            shard_ids=("book.ks0000.nr",),
            workspace_root=str(tmp_path),
        ),
        shards=[
            ShardManifestEntryV1(
                shard_id="book.ks0000.nr",
                owned_ids=("book.ks0000.nr",),
                input_payload={
                    "v": "1",
                    "bid": "book.ks0000.nr",
                    "b": [{"i": 4, "t": "Whisk constantly."}],
                },
                input_text=None,
                metadata={},
            )
        ],
    )
    write_task_file(path=tmp_path / "task.json", payload=task_file)
    callback = _build_strict_json_watchdog_callback(
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="taskfile_v1",
        allow_workspace_commands=True,
        execution_workspace_root=tmp_path,
    )

    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.2,
            last_event_seconds_ago=0.0,
            event_count=4,
            command_execution_count=1,
            reasoning_item_count=0,
            agent_message_count=0,
            turn_completed_count=0,
            last_command="/bin/bash -lc \"python3 -c 'from pathlib import Path; Path(\\\"task.json\\\").write_text(\\\"{}\\\")'\"",
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert decision is None
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["state"] == "running_with_warnings"
    assert live_status["warning_codes"] == ["single_file_shell_drift"]
    assert live_status["last_command_policy"] == "single_file_task_ad_hoc_transform"
