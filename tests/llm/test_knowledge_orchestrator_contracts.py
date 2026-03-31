from __future__ import annotations

from pathlib import Path

from cookimport.llm.codex_exec_runner import CodexExecLiveSnapshot
from cookimport.llm.codex_farm_knowledge_orchestrator import _preflight_knowledge_shard
from cookimport.llm.knowledge_stage import _shared as knowledge_stage_shared
from cookimport.llm.knowledge_stage.recovery import (
    _KNOWLEDGE_WORKSPACE_COMPLETION_QUIESCENCE_SECONDS,
    _build_knowledge_workspace_worker_prompt,
    _build_strict_json_watchdog_callback,
    _write_knowledge_worker_hint,
)
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1


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
    prompt = _build_knowledge_workspace_worker_prompt(
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
    assert (
        "Open `task.json`, read it once, edit only `/units/*/answer`, save the same file, and then run "
        "`python3 -m cookimport.llm.knowledge_same_session_handoff`." in prompt
    )
    assert "`task.json` is the whole job at each step." in prompt
    assert "- Start with `task.json`." in prompt
    assert "- Edit only the `answer` object inside each unit." in prompt
    assert (
        "- After each edit pass, run `python3 -m cookimport.llm.knowledge_same_session_handoff` "
        "from the workspace root." in prompt
    )
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
    assert "Do not invent queue advancement, control files, helper ledgers, or alternate output files." in prompt
    assert "This is the classification step." in prompt
    assert "Answer each unit with `category`, `reviewer_category`, `retrieval_concept`, and `grounding`." in prompt
    assert (
        "If `category` is `knowledge`, `retrieval_concept` must be a short standalone concept" in prompt
    )
    assert "Proposed tags are allowed only for real retrieval-grade concepts" in prompt
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

    assert "## Shard profile" in rendered
    assert "## Shard interpretation" in rendered
    assert "## Decision policy" in rendered
    assert "## Shard examples" in rendered
    assert "## Attention rows" in rendered
    assert "## How to use this task" not in rendered
    assert "## Packet summary" not in rendered
    assert "`examples/valid_heading_with_useful_body_packet.json`" in rendered
    assert "Nearby recipe guardrail block indices: `2, 3`." in rendered
    assert "gap_from_prev=14" in rendered
    assert "table_hint" in rendered
    assert rendered.count("## ") == 5


def test_knowledge_stage_shared_no_longer_imports_legacy_workspace_helper_surface() -> None:
    shared_source = Path(knowledge_stage_shared.__file__).read_text(encoding="utf-8")

    assert "knowledge_workspace_tools" not in shared_source


def test_knowledge_workspace_watchdog_completes_after_stable_outputs_without_queue_controller(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "out" / "book.ks0000.nr.json"
    callback = _build_strict_json_watchdog_callback(
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="workspace_worker_v1",
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
