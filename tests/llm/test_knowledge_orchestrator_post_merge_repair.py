from __future__ import annotations

import json
from pathlib import Path

import pytest

import cookimport.llm.knowledge_stage.workspace_run as knowledge_workspace_run
from cookimport.llm.codex_exec_runner import FakeCodexExecRunner
from tests.llm.knowledge_packet_test_support import (
    configure_runtime_codex_home,
    knowledge_span,
    make_runtime_pack_and_run_dirs,
    make_runtime_settings,
)
from tests.llm.test_knowledge_orchestrator_runtime_leasing import (
    _packet_result_from_base,
    _run_runtime_phase,
    _structured_classification_labels,
    _structured_grouping_groups,
)


class _WholeShardFinalRepairInlineRunner(FakeCodexExecRunner):
    def __init__(self) -> None:
        super().__init__(output_builder=lambda payload: {})
        self.final_repair_call_count = 0

    def run_packet_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
        base_result = super().run_packet_worker(*args, **kwargs)
        payload = dict(kwargs.get("input_payload") or {})
        packet_kind = str(payload.get("packet_kind") or "").strip()
        stage_key = str(payload.get("stage_key") or "").strip()
        if stage_key == "nonrecipe_classify":
            return _packet_result_from_base(
                base_result,
                response_text=json.dumps(
                    {"labels": _structured_classification_labels(payload)},
                    indent=2,
                    sort_keys=True,
                ),
            )
        if stage_key == "knowledge_group" and packet_kind in {"grouping_1", "grouping_2"}:
            return _packet_result_from_base(
                base_result,
                response_text=json.dumps(
                    {"groups": _structured_grouping_groups(payload, topic_label="Heat control")},
                    indent=2,
                    sort_keys=True,
                ),
            )
        if stage_key == "knowledge_group" and packet_kind == "grouping_final_repair":
            self.final_repair_call_count += 1
            return _packet_result_from_base(
                base_result,
                response_text=json.dumps(
                    {
                        "groups": _structured_grouping_groups(
                            payload,
                            topic_label="Unified heat control",
                        )
                    },
                    indent=2,
                    sort_keys=True,
                ),
            )
        return base_result


def test_knowledge_orchestrator_runs_whole_shard_grouping_repair_after_merge_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_runtime_codex_home(monkeypatch, tmp_path=tmp_path)
    pack_root, _run_root = make_runtime_pack_and_run_dirs(tmp_path)
    settings = make_runtime_settings(
        pack_root=pack_root,
        worker_count=1,
        knowledge_prompt_target_count=1,
        knowledge_codex_exec_style="inline-json-v1",
    ).model_copy(
        update={
            "knowledge_group_task_max_units": 1,
        }
    )
    runner = _WholeShardFinalRepairInlineRunner()
    real_validate = knowledge_workspace_run.validate_knowledge_shard_output
    validation_call_count = 0

    def _validate_once_then_pass(shard, payload):  # noqa: ANN001
        nonlocal validation_call_count
        validation_call_count += 1
        if validation_call_count == 1:
            return (
                False,
                ("knowledge_group_grounding_mismatch",),
                {
                    "knowledge_group_grounding_mismatch_blocks": [0, 1],
                },
            )
        return real_validate(shard, payload)

    monkeypatch.setattr(
        knowledge_workspace_run,
        "validate_knowledge_shard_output",
        _validate_once_then_pass,
    )

    fixture = _run_runtime_phase(
        monkeypatch,
        tmp_path,
        runner=runner,
        settings=settings,
        block_texts=[
            "Use medium heat to keep the pan under control.",
            "Stay with the pan so the heat stays even.",
        ],
        spans=[knowledge_span(0), knowledge_span(1)],
    )
    phase_dir = Path(fixture["phase_dir"])
    worker_root = Path(fixture["worker_root"])
    proposal = json.loads(
        (phase_dir / "proposals" / "book.ks0000.nr.json").read_text(encoding="utf-8")
    )
    worker_status = json.loads((worker_root / "status.json").read_text(encoding="utf-8"))
    final_repair_packet = json.loads(
        (
            worker_root
            / "shards"
            / "book.ks0000.nr"
            / "structured_session"
            / "grouping_final_repair_packet.json"
        ).read_text(encoding="utf-8")
    )

    assert proposal["payload"] is not None
    assert proposal["validation_errors"] == []
    assert proposal["validation_metadata"]["whole_shard_grouping_repair_attempted"] is True
    assert proposal["validation_metadata"]["whole_shard_grouping_repair_recovered"] is True
    assert runner.final_repair_call_count == 1
    assert final_repair_packet["packet_kind"] == "grouping_final_repair"
    assert final_repair_packet["repair_validation_summary"]["validation_errors"] == [
        "knowledge_group_grounding_mismatch"
    ]
    assert final_repair_packet["rows"] == [
        "r01 | 0 | Use medium heat to keep the pan under control.",
        "r02 | 1 | Stay with the pan so the heat stays even.",
    ]
    assert worker_status["telemetry"]["summary"]["prompt_input_mode_counts"] == {
        "structured_session_classification_initial": 1,
        "structured_session_grouping": 2,
        "structured_session_grouping_final_repair": 1,
    }
    assert (
        worker_status["repair_recovery_policy"]["worker_assignment"]["budgets"][
            "structured_repair_followup"
        ]["spent_attempts"]
        == 1
    )
