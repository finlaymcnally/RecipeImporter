from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from cookimport.llm.knowledge_phase_workspace_tools import (
    build_final_output,
    build_knowledge_seed_output,
    build_pass1_semantic_audit,
    build_pass1_work_ledger,
    build_pass2_input_ledger,
    build_pass2_work_ledger,
    render_knowledge_current_phase_brief,
    render_knowledge_current_phase_feedback,
    render_knowledge_worker_script,
    validate_pass1_work_ledger,
    validate_pass2_work_ledger,
)


def test_build_knowledge_seed_output_defaults_every_block_to_other() -> None:
    payload = build_knowledge_seed_output(
        {
            "bid": "book.ks0000.nr",
            "b": [{"i": 1, "t": "PRAISE"}, {"i": 2, "t": "Use low heat."}],
        }
    )

    assert payload == {
        "packet_id": "book.ks0000.nr",
        "block_decisions": [
            {"block_index": 1, "category": "other", "reviewer_category": "other"},
            {"block_index": 2, "category": "other", "reviewer_category": "other"},
        ],
        "idea_groups": [],
    }


def test_pass1_and_pass2_ledgers_round_trip_into_final_output() -> None:
    input_payload = {
        "bid": "book.ks0000.nr",
        "b": [
            {"i": 7, "t": "Marketing."},
            {"i": 8, "t": "Use low heat and whisk steadily."},
        ],
    }
    pass1 = {
        "phase": "pass1",
        "rows": [
            {"block_index": 7, "category": "other"},
            {"block_index": 8, "category": "knowledge"},
        ],
    }
    pass2_input = build_pass2_input_ledger(input_payload=input_payload, pass1_payload=pass1)
    pass2 = {
        "phase": "pass2",
        "rows": [
            {
                "block_index": 8,
                "category": "knowledge",
                "text": "Use low heat and whisk steadily.",
                "group_key": "heat-control",
                "topic_label": "Heat control",
            },
        ],
    }
    final_output = build_final_output(
        shard_id="book.ks0000.nr",
        pass1_payload=pass1,
        pass2_payload=pass2,
    )

    assert pass2_input == {
        "phase": "pass2",
        "rows": [
            {
                "block_index": 8,
                "category": "knowledge",
                "text": "Use low heat and whisk steadily.",
            }
        ],
    }
    assert final_output == {
        "packet_id": "book.ks0000.nr",
        "block_decisions": [
            {"block_index": 7, "category": "other", "reviewer_category": "other"},
            {"block_index": 8, "category": "knowledge", "reviewer_category": "knowledge"},
        ],
        "idea_groups": [
            {"group_id": "g01", "topic_label": "Heat control", "block_indices": [8]}
        ],
    }


def test_pass1_validator_rejects_missing_rows() -> None:
    errors, metadata = validate_pass1_work_ledger(
        input_payload={"b": [{"i": 4, "t": "Whisk"}, {"i": 5, "t": "Cool"}]},
        payload={"phase": "pass1", "rows": [{"block_index": 4, "category": "knowledge"}]},
    )

    assert errors == ("missing_owned_block_decisions",)
    assert metadata["missing_owned_block_indices"] == [5]


def test_pass2_validator_rejects_blank_topic_labels() -> None:
    pass2_input = {"phase": "pass2", "rows": [{"block_index": 4, "text": "Whisk"}]}
    errors, metadata = validate_pass2_work_ledger(
        pass2_input_payload=pass2_input,
        payload={"phase": "pass2", "rows": [{"block_index": 4, "group_id": "g01", "topic_label": ""}]},
    )

    assert errors == ("knowledge_block_missing_group",)
    assert metadata["knowledge_blocks_missing_group"] == [4]


def test_render_knowledge_phase_sidecars_reference_current_phase_loop() -> None:
    phase_row = {
        "status": "active",
        "phase": "pass1",
        "shard_id": "book.ks0000.nr",
        "hint_path": "hints/book.ks0000.nr.md",
        "input_path": "in/book.ks0000.nr.json",
        "work_path": "work/book.ks0000.nr.pass1.json",
        "repair_path": "repair/book.ks0000.nr.pass1.json",
        "semantic_audit_path": "shards/book.ks0000.nr/semantic_audit.json",
        "result_path": "out/book.ks0000.nr.json",
    }

    brief = render_knowledge_current_phase_brief(phase_row)
    feedback = render_knowledge_current_phase_feedback(phase_row=phase_row)

    assert "first-authority semantic judgment" in brief
    assert "Active work ledger: `work/book.ks0000.nr.pass1.json`" in brief
    assert "Preferred loop" in brief
    assert "Open `hints/book.ks0000.nr.md` before `in/book.ks0000.nr.json`." in brief
    assert "Open `in/book.ks0000.nr.json` only if the phase brief, feedback, hint, and work ledger are still insufficient." in brief
    assert "The repo does not know the `knowledge` versus `other` answer ahead of time." in brief
    assert "python3 tools/knowledge_worker.py check-phase" in brief
    assert "Next command: `python3 tools/knowledge_worker.py install-phase`." in feedback
    assert "Install target" in feedback


def test_render_knowledge_phase_feedback_names_repair_loop() -> None:
    phase_row = {
        "status": "active",
        "phase": "pass1",
        "shard_id": "book.ks0000.nr",
        "hint_path": "hints/book.ks0000.nr.md",
        "input_path": "in/book.ks0000.nr.json",
        "work_path": "work/book.ks0000.nr.pass1.json",
        "repair_path": "repair/book.ks0000.nr.pass1.json",
        "semantic_audit_path": "shards/book.ks0000.nr/semantic_audit.json",
        "result_path": "out/book.ks0000.nr.json",
    }

    feedback = render_knowledge_current_phase_feedback(
        phase_row=phase_row,
        validation_errors=("missing_owned_block_decisions",),
        validation_metadata={
            "unresolved_block_indices": [11],
            "frozen_block_indices": [10],
        },
    )

    assert "Edit only `work/book.ks0000.nr.pass1.json`." in feedback
    assert "Repair request: `repair/book.ks0000.nr.pass1.json`" in feedback
    assert "Next command after fixes: `python3 tools/knowledge_worker.py check-phase`." in feedback


def test_build_pass1_semantic_audit_flags_high_signal_keep_and_drop_rows() -> None:
    audit = build_pass1_semantic_audit(
        shard_id="book.ks0000.nr",
        input_payload={
            "bid": "book.ks0000.nr",
            "b": [
                {"i": 10, "t": "WHEN I COOK BEANS", "hl": 2},
                {"i": 11, "t": "Use low heat so the butter does not break."},
            ],
        },
        pass1_payload={
            "phase": "pass1",
            "rows": [
                {"block_index": 10, "category": "knowledge"},
                {"block_index": 11, "category": "other"},
            ],
        },
    )

    assert audit["status"] == "repair_required"
    assert audit["flagged_block_indices"] == [10, 11]
    assert {flag["code"] for flag in audit["flags"]} == {
        "guidance_like_other",
        "heading_like_keep_without_supported_body",
        "memoir_like_keep",
    }


def test_render_knowledge_phase_feedback_shows_semantic_audit_evidence() -> None:
    phase_row = {
        "status": "active",
        "phase": "pass1",
        "shard_id": "book.ks0000.nr",
        "hint_path": "hints/book.ks0000.nr.md",
        "input_path": "in/book.ks0000.nr.json",
        "work_path": "work/book.ks0000.nr.pass1.json",
        "repair_path": "repair/book.ks0000.nr.pass1.json",
        "semantic_audit_path": "shards/book.ks0000.nr/semantic_audit.json",
        "result_path": "out/book.ks0000.nr.json",
    }

    feedback = render_knowledge_current_phase_feedback(
        phase_row=phase_row,
        validation_errors=("semantic_suspicion_requires_repair",),
        validation_metadata={
            "unresolved_block_indices": [10],
            "frozen_block_indices": [11],
            "semantic_audit_path": "shards/book.ks0000.nr/semantic_audit.json",
            "semantic_audit_flags": [
                {
                    "block_index": 10,
                    "code": "heading_like_keep_without_supported_body",
                    "evidence": "short heading-like row was marked knowledge without an adjacent kept explanatory body",
                }
            ],
        },
    )

    assert "semantic suspicion audit flagged rows" in feedback
    assert "Semantic audit file: `shards/book.ks0000.nr/semantic_audit.json`" in feedback
    assert "`heading_like_keep_without_supported_body`" in feedback


def test_generated_knowledge_worker_script_uses_phase_contract() -> None:
    script = render_knowledge_worker_script()

    assert "check-phase" in script
    assert "install-phase" in script
    assert "current_phase.json" in script
    assert "CURRENT_PHASE.md" in script
    assert "idea_groups" in script


def test_build_pass2_work_ledger_carries_forward_kept_rows_without_final_ids() -> None:
    payload = build_pass2_work_ledger(
        {
            "phase": "pass2",
            "rows": [
                {"block_index": 4, "category": "knowledge", "text": "Whisk"},
                {"block_index": 5, "category": "knowledge", "text": "Rest"},
            ],
        }
    )

    assert payload["phase"] == "pass2"
    assert payload["rows"] == [
        {
            "block_index": 4,
            "category": "knowledge",
            "text": "Whisk",
            "group_key": "",
            "topic_label": "",
        },
        {
            "block_index": 5,
            "category": "knowledge",
            "text": "Rest",
            "group_key": "",
            "topic_label": "",
        },
    ]


def test_build_pass1_work_ledger_scaffolds_raw_owned_rows_without_semantic_default() -> None:
    payload = build_pass1_work_ledger({"b": [{"i": 4, "t": "Whisk"}, {"i": 5, "t": "Rest"}]})

    assert payload == {
        "phase": "pass1",
        "rows": [
            {"block_index": 4, "text": "Whisk", "category": ""},
            {"block_index": 5, "text": "Rest", "category": ""},
        ],
    }


def _write_workspace_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _make_workspace(
    tmp_path: Path,
    *,
    input_payload: dict[str, object],
) -> Path:
    workspace_root = tmp_path / "knowledge-worker"
    for name in ("in", "work", "repair", "out", "hints", "tools"):
        (workspace_root / name).mkdir(parents=True, exist_ok=True)
    shard_id = str(input_payload["bid"])
    _write_workspace_json(workspace_root / "assigned_shards.json", [{"shard_id": shard_id}])
    _write_workspace_json(workspace_root / "in" / f"{shard_id}.json", input_payload)
    _write_workspace_json(
        workspace_root / "current_phase.json",
        {
            "status": "active",
            "phase": "pass1",
            "shard_id": shard_id,
            "input_path": f"in/{shard_id}.json",
            "work_path": f"work/{shard_id}.pass1.json",
            "repair_path": f"repair/{shard_id}.pass1.json",
            "semantic_audit_path": f"shards/{shard_id}/semantic_audit.json",
            "result_path": f"out/{shard_id}.json",
            "hint_path": f"hints/{shard_id}.md",
        },
    )
    worker_path = workspace_root / "tools" / "knowledge_worker.py"
    worker_path.write_text(render_knowledge_worker_script(), encoding="utf-8")
    worker_path.chmod(0o755)
    return workspace_root


def _run_worker_command(workspace_root: Path, command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/knowledge_worker.py", command],
        cwd=workspace_root,
        text=True,
        capture_output=True,
        check=False,
    )


def test_generated_knowledge_worker_script_round_trips_pass1_to_pass2_same_session(
    tmp_path: Path,
) -> None:
    workspace_root = _make_workspace(
        tmp_path,
        input_payload={
            "bid": "book.ks0000.nr",
            "b": [
                {"i": 10, "t": "Praise."},
                {"i": 11, "t": "Use low heat and whisk steadily."},
            ],
        },
    )
    _write_workspace_json(
        workspace_root / "work" / "book.ks0000.nr.pass1.json",
        {
            "phase": "pass1",
            "rows": [
                {"block_index": 10, "category": "other"},
                {"block_index": 11, "category": "knowledge"},
            ],
        },
    )

    check_pass1 = _run_worker_command(workspace_root, "check-phase")
    install_pass1 = _run_worker_command(workspace_root, "install-phase")

    assert check_pass1.returncode == 0, check_pass1.stderr or check_pass1.stdout
    assert install_pass1.returncode == 0, install_pass1.stderr or install_pass1.stdout
    assert json.loads(
        (workspace_root / "in" / "book.ks0000.nr.pass2.json").read_text(encoding="utf-8")
    ) == {
        "phase": "pass2",
        "rows": [
            {
                "block_index": 11,
                "category": "knowledge",
                "text": "Use low heat and whisk steadily.",
            }
        ],
    }
    assert json.loads(
        (workspace_root / "current_phase.json").read_text(encoding="utf-8")
    )["phase"] == "pass2"

    _write_workspace_json(
        workspace_root / "work" / "book.ks0000.nr.pass2.json",
        {
            "phase": "pass2",
            "rows": [
                {
                    "block_index": 11,
                    "category": "knowledge",
                    "text": "Use low heat and whisk steadily.",
                    "group_key": "heat-control",
                    "topic_label": "Heat control",
                },
            ],
        },
    )

    check_pass2 = _run_worker_command(workspace_root, "check-phase")
    install_pass2 = _run_worker_command(workspace_root, "install-phase")

    assert check_pass2.returncode == 0, check_pass2.stderr or check_pass2.stdout
    assert install_pass2.returncode == 0, install_pass2.stderr or install_pass2.stdout
    assert json.loads(
        (workspace_root / "current_phase.json").read_text(encoding="utf-8")
    )["status"] == "completed"
    assert json.loads(
        (workspace_root / "out" / "book.ks0000.nr.json").read_text(encoding="utf-8")
    ) == {
        "packet_id": "book.ks0000.nr",
        "block_decisions": [
            {"block_index": 10, "category": "other", "reviewer_category": "other"},
            {"block_index": 11, "category": "knowledge", "reviewer_category": "knowledge"},
        ],
        "idea_groups": [
            {"group_id": "g01", "topic_label": "Heat control", "block_indices": [11]}
        ],
    }


def test_generated_knowledge_worker_script_requires_same_session_semantic_repair(
    tmp_path: Path,
) -> None:
    workspace_root = _make_workspace(
        tmp_path,
        input_payload={
            "bid": "book.ks0000.nr",
            "b": [
                {"i": 10, "t": "WHAT IS ACID?", "hl": 2},
                {"i": 11, "t": "Use low heat so the butter does not break."},
            ],
        },
    )
    _write_workspace_json(
        workspace_root / "work" / "book.ks0000.nr.pass1.json",
        {
            "phase": "pass1",
            "rows": [
                {"block_index": 10, "category": "knowledge"},
                {"block_index": 11, "category": "other"},
            ],
        },
    )

    first_check = _run_worker_command(workspace_root, "check-phase")

    assert first_check.returncode == 1
    repair_payload = json.loads(
        (workspace_root / "repair" / "book.ks0000.nr.pass1.json").read_text(encoding="utf-8")
    )
    audit_payload = json.loads(
        (workspace_root / "shards" / "book.ks0000.nr" / "semantic_audit.json").read_text(
            encoding="utf-8"
        )
    )
    assert repair_payload["repair_request_kind"] == "semantic_suspicion"
    assert repair_payload["unresolved_block_indices"] == [10, 11]
    assert audit_payload["status"] == "repair_required"

    _write_workspace_json(
        workspace_root / "work" / "book.ks0000.nr.pass1.json",
        {
            "phase": "pass1",
            "rows": [
                {"block_index": 10, "category": "other"},
                {"block_index": 11, "category": "knowledge"},
            ],
        },
    )

    second_check = _run_worker_command(workspace_root, "check-phase")

    assert second_check.returncode == 0
    cleared_audit_payload = json.loads(
        (workspace_root / "shards" / "book.ks0000.nr" / "semantic_audit.json").read_text(
            encoding="utf-8"
        )
    )
    feedback = (workspace_root / "CURRENT_PHASE_FEEDBACK.md").read_text(encoding="utf-8")
    assert cleared_audit_payload["status"] == "passed_after_repair"
    assert cleared_audit_payload["repair_cleared"] is True
    assert "Previous semantic suspicion flags were cleared in this same session." in feedback


def test_generated_knowledge_worker_script_freezes_accepted_rows_across_rechecks(
    tmp_path: Path,
) -> None:
    workspace_root = _make_workspace(
        tmp_path,
        input_payload={
            "bid": "book.ks0000.nr",
            "b": [
                {"i": 1, "t": "Whisk."},
                {"i": 2, "t": "Rest."},
            ],
        },
    )
    _write_workspace_json(
        workspace_root / "work" / "book.ks0000.nr.pass1.json",
        {
            "phase": "pass1",
            "rows": [
                {"block_index": 1, "category": "knowledge"},
                {"block_index": 2, "category": ""},
            ],
        },
    )

    first_check = _run_worker_command(workspace_root, "check-phase")
    repair_payload = json.loads(
        (workspace_root / "repair" / "book.ks0000.nr.pass1.json").read_text(encoding="utf-8")
    )
    phase_payload = json.loads(
        (workspace_root / "current_phase.json").read_text(encoding="utf-8")
    )

    assert first_check.returncode == 1
    assert repair_payload["frozen_rows"] == [{"block_index": 1, "category": "knowledge"}]
    assert phase_payload["frozen_rows"] == [{"block_index": 1, "category": "knowledge"}]

    _write_workspace_json(
        workspace_root / "work" / "book.ks0000.nr.pass1.json",
        {
            "phase": "pass1",
            "rows": [
                {"block_index": 1, "category": "other"},
                {"block_index": 2, "category": ""},
            ],
        },
    )

    second_check = _run_worker_command(workspace_root, "check-phase")
    second_repair_payload = json.loads(
        (workspace_root / "repair" / "book.ks0000.nr.pass1.json").read_text(encoding="utf-8")
    )

    assert second_check.returncode == 1
    assert "frozen_row_modified:1" in second_check.stdout
    assert second_repair_payload["unresolved_block_indices"] == [1, 2]
    assert second_repair_payload["frozen_rows"] == [{"block_index": 1, "category": "knowledge"}]


def test_generated_knowledge_worker_script_names_rows_for_order_only_mismatches(
    tmp_path: Path,
) -> None:
    workspace_root = _make_workspace(
        tmp_path,
        input_payload={
            "bid": "book.ks0000.nr",
            "b": [
                {"i": 4, "t": "Whisk."},
                {"i": 5, "t": "Rest."},
            ],
        },
    )
    _write_workspace_json(
        workspace_root / "work" / "book.ks0000.nr.pass1.json",
        {
            "phase": "pass1",
            "rows": [
                {"block_index": 5, "category": "other"},
                {"block_index": 4, "category": "knowledge"},
            ],
        },
    )

    check_result = _run_worker_command(workspace_root, "check-phase")
    repair_payload = json.loads(
        (workspace_root / "repair" / "book.ks0000.nr.pass1.json").read_text(encoding="utf-8")
    )

    assert check_result.returncode == 1
    assert repair_payload["unresolved_block_indices"] == [4, 5]
    assert repair_payload["rows"] == [
        {"block_index": 4, "text": "Whisk.", "category": ""},
        {"block_index": 5, "text": "Rest.", "category": ""},
    ]


def test_generated_knowledge_worker_script_reseeds_invalid_pass1_shape(
    tmp_path: Path,
) -> None:
    workspace_root = _make_workspace(
        tmp_path,
        input_payload={
            "bid": "book.ks0000.nr",
            "b": [
                {"i": 4, "t": "Whisk."},
                {"i": 5, "t": "Rest."},
            ],
        },
    )
    _write_workspace_json(
        workspace_root / "work" / "book.ks0000.nr.pass1.json",
        {
            "packet_id": "book.ks0000.nr",
            "block_decisions": [
                {"block_index": 4, "category": "knowledge", "reviewer_category": "knowledge"},
                {"block_index": 5, "category": "other", "reviewer_category": "other"},
            ],
            "idea_groups": [],
        },
    )

    scaffold_result = _run_worker_command(workspace_root, "scaffold-phase")
    reseeded_payload = json.loads(
        (workspace_root / "work" / "book.ks0000.nr.pass1.json").read_text(encoding="utf-8")
    )
    check_result = _run_worker_command(workspace_root, "check-phase")

    assert scaffold_result.returncode == 0, scaffold_result.stderr or scaffold_result.stdout
    assert reseeded_payload == {
        "phase": "pass1",
        "rows": [
            {"block_index": 4, "text": "Whisk.", "category": ""},
            {"block_index": 5, "text": "Rest.", "category": ""},
        ],
    }
    assert check_result.returncode == 1
