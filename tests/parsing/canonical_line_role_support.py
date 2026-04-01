from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from copy import deepcopy
from pathlib import Path

import pytest

import cookimport.llm.canonical_line_role_prompt as canonical_line_role_prompt_module
from cookimport.config.run_settings import RunSettings
from cookimport.core.progress_messages import parse_stage_progress
from cookimport.llm.canonical_line_role_prompt import (
    build_canonical_line_role_file_prompt,
    build_line_role_shared_contract_block,
)
from cookimport.llm.codex_exec_runner import (
    CodexExecLiveSnapshot,
    CodexExecRecentCommandCompletion,
    CodexExecRunResult,
    FakeCodexExecRunner,
)
from cookimport.llm.codex_farm_runner import CodexFarmRunnerError
from cookimport.llm.editable_task_file import load_task_file, write_task_file
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1
from cookimport.parsing import canonical_line_roles as canonical_line_roles_module
from cookimport.parsing.canonical_line_roles import _preflight_line_role_shard, label_atomic_lines
from cookimport.parsing.canonical_line_roles.runtime import (
    _expand_line_role_task_file_outputs,
    _line_role_recovery_guidance_for_diagnosis,
)
from cookimport.parsing.canonical_line_roles.same_session_handoff import (
    advance_line_role_same_session_handoff,
)
from cookimport.parsing.recipe_block_atomizer import (
    AtomicLineCandidate,
    atomize_blocks,
    build_atomic_index_lookup,
)
from tests.paths import FIXTURES_DIR


def _completed_line_role_helper_command() -> CodexExecRecentCommandCompletion:
    return CodexExecRecentCommandCompletion(
        command=(
            "/bin/bash -lc "
            "'python3 -m cookimport.parsing.canonical_line_roles.same_session_handoff'"
        ),
        exit_code=0,
        status="completed",
        python_module="cookimport.parsing.canonical_line_roles.same_session_handoff",
        parsed_output={
            "completed": True,
            "final_status": "completed",
            "status": "completed",
        },
        reported_completed=True,
        reported_final_status="completed",
    )


def _completed_task_file_summary_command() -> CodexExecRecentCommandCompletion:
    return CodexExecRecentCommandCompletion(
        command="/bin/bash -lc 'python3 -m cookimport.llm.editable_task_file --summary'",
        exit_code=0,
        status="completed",
        python_module="cookimport.llm.editable_task_file",
        parsed_output={"answered_units": 1},
        reported_completed=False,
        reported_final_status=None,
    )


def _load_fixture(name: str) -> dict[str, object]:
    fixture_path = FIXTURES_DIR / "canonical_labeling" / name
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def _settings(mode: str = "off", **kwargs):
    return RunSettings(line_role_pipeline=mode, **kwargs)


@pytest.fixture(autouse=True)
def _isolate_default_line_role_runtime_root(tmp_path, monkeypatch) -> None:
    original = canonical_line_roles_module._resolve_line_role_codex_farm_workspace_root
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(
        "COOKIMPORT_CODEX_FARM_CODEX_HOME",
        str(codex_home),
    )

    def _patched(*, settings):
        resolved = original(settings=settings)
        if resolved is not None:
            return resolved
        return tmp_path / "line-role-runtime-workspace"

    monkeypatch.setattr(
        canonical_line_roles_module,
        "_resolve_line_role_codex_farm_workspace_root",
        _patched,
    )


def _progress_messages_as_text(messages: list[str]) -> list[str]:
    rows: list[str] = []
    for message in messages:
        payload = parse_stage_progress(message)
        if payload is not None:
            rows.append(str(payload.get("message") or "").strip())
        else:
            rows.append(str(message).strip())
    return rows


def _line_role_runner(
    label_by_atomic_index: dict[int, str] | None = None,
    *,
    output_builder=None,
):
    def _default_builder(payload):
        rows = payload.get("rows") if isinstance(payload, dict) else []
        atomic_indices: list[int] = []
        for row in rows:
            value = None
            if isinstance(row, dict):
                value = row.get("atomic_index")
            elif isinstance(row, list | tuple) and row:
                value = row[0]
            if value is not None:
                atomic_indices.append(int(value))
        if not atomic_indices:
            prompt_text = payload if isinstance(payload, str) else json.dumps(payload, sort_keys=True)
            atomic_indices = [
                int(value)
                for value in re.findall(r'"atomic_index"\s*:\s*(\d+)', prompt_text)
            ]
        if not atomic_indices:
            atomic_indices = [
                int(value) for value in re.findall(r"(?m)^(\d+)\|", prompt_text)
            ]
        return {
            "rows": [
                {
                    "atomic_index": atomic_index,
                    "label": (
                        label_by_atomic_index or {}
                    ).get(atomic_index, "NONRECIPE_CANDIDATE"),
                }
                for atomic_index in atomic_indices
            ]
        }

    return FakeCodexExecRunner(
        output_builder=output_builder or _default_builder
    )


def _gold_label_counts_for_book(source_slug: str) -> dict[str, int]:
    path = (
        Path("/home/mcnal/projects/recipeimport/data/golden/pulled-from-labelstudio")
        / source_slug
        / "exports"
        / "canonical_span_labels.jsonl"
    )
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        label = str(row.get("label") or "").strip().upper()
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1
    return counts


def _load_preserved_line_role_packet_rows(
    *,
    worker_id: str,
    task_id: str,
) -> list[dict[str, object]]:
    path = (
        Path("/home/mcnal/projects/recipeimport/data/output/2026-03-21_14.53.27")
        / "single-book-benchmark"
        / "saltfatacidheatcutdown"
        / "codexfarm"
        / "2026-03-21_14.54.14"
        / "line-role-pipeline"
        / "runtime"
        / "line_role"
        / "workers"
        / worker_id
        / "debug"
        / f"{task_id}.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("rows") or [])


def test_expand_line_role_task_file_outputs_recovers_answers_despite_immutable_drift(
    tmp_path: Path,
) -> None:
    original_task_file = {
        "schema_version": "editable_task_file.v1",
        "stage_key": "line_role",
        "assignment_id": "worker-003",
        "worker_id": "worker-003",
        "mode": "initial",
        "editable_json_pointers": ["/units/0/answer", "/units/1/answer"],
        "units": [
            {
                "unit_id": "line::589",
                "owned_id": "589",
                "evidence": {
                    "atomic_index": 589,
                    "block_id": "b877",
                    "text": "Original line 589",
                },
                "answer": {},
            },
            {
                "unit_id": "line::590",
                "owned_id": "590",
                "evidence": {
                    "atomic_index": 590,
                    "block_id": "b878",
                    "text": "Original line 590",
                },
                "answer": {},
            },
        ],
    }
    edited_task_file = {
        **original_task_file,
        "units": [
            {
                "unit_id": "line::589",
                "owned_id": "589",
                "evidence": {
                    "atomic_index": 123456,
                    "block_id": "b589",
                    "text": "Corrupted replacement text",
                },
                "answer": {"label": "INSTRUCTION_LINE"},
            },
            {
                "unit_id": "line::590",
                "owned_id": "590",
                "evidence": {
                    "atomic_index": 999999,
                    "block_id": "b590",
                    "text": "More corrupted text",
                },
                "answer": {"label": "NONRECIPE_CANDIDATE"},
            },
        ],
    }
    task_file_path = tmp_path / "task.json"
    task_file_path.write_text(json.dumps(edited_task_file, indent=2) + "\n", encoding="utf-8")

    outputs = _expand_line_role_task_file_outputs(
        original_task_file=original_task_file,
        task_file_path=task_file_path,
        unit_to_shard_id={
            "line::589": "line-role-canonical-0003-a000589-a000590",
            "line::590": "line-role-canonical-0003-a000589-a000590",
        },
    )

    assert outputs == {
        "line-role-canonical-0003-a000589-a000590": {
            "rows": [
                {"atomic_index": 589, "label": "INSTRUCTION_LINE"},
                {"atomic_index": 590, "label": "NONRECIPE_CANDIDATE"},
            ]
        }
    }


class _NoFinalWorkspaceMessageRunner(FakeCodexExecRunner):
    def run_workspace_worker(self, **kwargs) -> CodexExecRunResult:  # noqa: ANN003
        result = super().run_workspace_worker(**kwargs)
        return CodexExecRunResult(
            command=list(result.command),
            subprocess_exit_code=result.subprocess_exit_code,
            output_schema_path=result.output_schema_path,
            prompt_text=result.prompt_text,
            response_text=None,
            turn_failed_message=result.turn_failed_message,
            events=tuple(
                event
                for event in result.events
                if event.get("item", {}).get("type") != "agent_message"
            ),
            usage=dict(result.usage or {}),
            stderr_text=result.stderr_text,
            stdout_text=result.stdout_text,
            source_working_dir=result.source_working_dir,
            execution_working_dir=result.execution_working_dir,
            execution_agents_path=result.execution_agents_path,
            duration_ms=result.duration_ms,
            started_at_utc=result.started_at_utc,
            finished_at_utc=result.finished_at_utc,
            workspace_mode=result.workspace_mode,
            supervision_state=result.supervision_state,
            supervision_reason_code=result.supervision_reason_code,
            supervision_reason_detail=result.supervision_reason_detail,
            supervision_retryable=result.supervision_retryable,
        )


class _FreshSessionLineRoleRunner(FakeCodexExecRunner):
    def __init__(self, *, hard_boundary: bool = False) -> None:
        super().__init__(
            output_builder=lambda payload: {
                "rows": [
                    {"atomic_index": int(row[0]), "label": "NONRECIPE_CANDIDATE"}
                    for row in (dict(payload or {}).get("rows") or [])
                    if isinstance(row, (list, tuple)) and row
                ]
            }
        )
        self.workspace_run_calls = 0
        self.hard_boundary = hard_boundary

    def run_workspace_worker(self, **kwargs) -> CodexExecRunResult:  # noqa: ANN003
        self.workspace_run_calls += 1
        working_dir = Path(kwargs.get("working_dir"))
        if self.workspace_run_calls == 1:
            task_file = load_task_file(working_dir / "task.json")
            edited = deepcopy(task_file)
            for unit in edited["units"]:
                unit["answer"] = {"label": "NONRECIPE_CANDIDATE"}
            write_task_file(path=working_dir / "task.json", payload=edited)
            return CodexExecRunResult(
                command=["codex", "exec"],
                subprocess_exit_code=0,
                output_schema_path=None,
                prompt_text=str(kwargs.get("prompt_text") or ""),
                response_text='{"status":"session_exhausted"}',
                turn_failed_message=None,
                usage={
                    "input_tokens": 1,
                    "cached_input_tokens": 0,
                    "output_tokens": 1,
                    "reasoning_tokens": 0,
                },
                source_working_dir=str(working_dir),
                execution_working_dir=str(working_dir),
                execution_agents_path=None,
                duration_ms=1,
                started_at_utc="2026-01-01T00:00:00Z",
                finished_at_utc="2026-01-01T00:00:00Z",
                workspace_mode="workspace_worker",
                supervision_state="watchdog_killed" if self.hard_boundary else "completed",
                supervision_reason_code=(
                    "watchdog_command_execution_forbidden" if self.hard_boundary else None
                ),
            )
        return super().run_workspace_worker(**kwargs)


class _TimeoutThenRecoveredLineRoleRunner(FakeCodexExecRunner):
    def __init__(self, *, fail_worker_ids: set[str] | None = None) -> None:
        super().__init__(
            output_builder=lambda payload: {
                "rows": [
                    {"atomic_index": int(row[0]), "label": "NONRECIPE_CANDIDATE"}
                    for row in (dict(payload or {}).get("rows") or [])
                    if isinstance(row, (list, tuple)) and row
                ]
            }
        )
        self.workspace_run_calls = 0
        self.calls_by_worker_id: dict[str, int] = {}
        self.fail_worker_ids = set(fail_worker_ids or {"worker-001"})
        self._lock = threading.Lock()

    def run_workspace_worker(self, **kwargs) -> CodexExecRunResult:  # noqa: ANN003
        working_dir = Path(kwargs.get("working_dir"))
        worker_id = working_dir.name
        with self._lock:
            self.workspace_run_calls += 1
            call_count = self.calls_by_worker_id.get(worker_id, 0) + 1
            self.calls_by_worker_id[worker_id] = call_count
        if worker_id in self.fail_worker_ids and call_count == 1:
            raise CodexFarmRunnerError("codex exec timed out after 600 seconds.")

        task_file = load_task_file(working_dir / "task.json")
        edited = deepcopy(task_file)
        for unit in edited["units"]:
            unit["answer"] = {"label": "NONRECIPE_CANDIDATE"}
        write_task_file(path=working_dir / "task.json", payload=edited)
        state_path = Path(
            str(kwargs.get("env", {}).get("RECIPEIMPORT_LINE_ROLE_SAME_SESSION_STATE_PATH"))
        )
        helper_result = advance_line_role_same_session_handoff(
            workspace_root=working_dir,
            state_path=state_path,
        )
        assert helper_result["status"] == "completed"
        return CodexExecRunResult(
            command=["codex", "exec"],
            subprocess_exit_code=0,
            output_schema_path=None,
            prompt_text=str(kwargs.get("prompt_text") or ""),
            response_text='{"status":"completed"}',
            turn_failed_message=None,
            usage={
                "input_tokens": 1,
                "cached_input_tokens": 0,
                "output_tokens": 1,
                "reasoning_tokens": 0,
            },
            source_working_dir=str(working_dir),
            execution_working_dir=str(working_dir),
            execution_agents_path=None,
            duration_ms=1,
            started_at_utc="2026-01-01T00:00:00Z",
            finished_at_utc="2026-01-01T00:00:00Z",
            workspace_mode="workspace_worker",
            supervision_state="completed",
            supervision_reason_code=None,
            supervision_reason_detail=None,
            supervision_retryable=False,
        )


class _FinalMessageMissingOutputRunner(FakeCodexExecRunner):
    def __init__(
        self,
        *,
        set_answers_before_exit: bool,
        spend_retry_budget: bool = False,
    ) -> None:
        super().__init__(
            output_builder=lambda payload: {
                "rows": [
                    {"atomic_index": int(row[0]), "label": "NONRECIPE_CANDIDATE"}
                    for row in (dict(payload or {}).get("rows") or [])
                    if isinstance(row, (list, tuple)) and row
                ]
            }
        )
        self.workspace_run_calls = 0
        self.set_answers_before_exit = set_answers_before_exit
        self.spend_retry_budget = spend_retry_budget

    def run_workspace_worker(self, **kwargs) -> CodexExecRunResult:  # noqa: ANN003
        self.workspace_run_calls += 1
        working_dir = Path(kwargs.get("working_dir"))
        if self.workspace_run_calls == 1:
            grace_seconds = float(
                canonical_line_roles_module._LINE_ROLE_FINAL_MESSAGE_MISSING_OUTPUT_GRACE_SECONDS  # noqa: SLF001
            )
            task_file_path = working_dir / "task.json"
            if self.set_answers_before_exit:
                task_file = load_task_file(task_file_path)
                edited = deepcopy(task_file)
                for unit in edited["units"]:
                    unit["answer"] = {"label": "NONRECIPE_CANDIDATE"}
                write_task_file(path=task_file_path, payload=edited)
            state_path = Path(
                str(kwargs.get("env", {}).get("RECIPEIMPORT_LINE_ROLE_SAME_SESSION_STATE_PATH"))
            )
            if self.spend_retry_budget and state_path.exists():
                state_payload = json.loads(state_path.read_text(encoding="utf-8"))
                state_payload["fresh_session_retry_count"] = 1
                state_payload["fresh_session_retry_status"] = "completed"
                state_payload["fresh_session_retry_limit"] = 1
                state_path.write_text(
                    json.dumps(state_payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            callback = kwargs.get("supervision_callback")
            assert callback is not None
            first = callback(
                CodexExecLiveSnapshot(
                    elapsed_seconds=0.1,
                    last_event_seconds_ago=0.0,
                    event_count=2,
                    command_execution_count=0,
                    reasoning_item_count=0,
                    last_command=None,
                    last_command_repeat_count=0,
                    has_final_agent_message=True,
                    agent_message_count=1,
                    timeout_seconds=kwargs.get("timeout_seconds"),
                )
            )
            assert first is None
            decision = callback(
                CodexExecLiveSnapshot(
                    elapsed_seconds=0.2 + grace_seconds + 0.1,
                    last_event_seconds_ago=0.0,
                    event_count=3,
                    command_execution_count=0,
                    reasoning_item_count=0,
                    last_command=None,
                    last_command_repeat_count=0,
                    has_final_agent_message=True,
                    agent_message_count=1,
                    timeout_seconds=kwargs.get("timeout_seconds"),
                )
            )
            assert decision is None
            decision = callback(
                CodexExecLiveSnapshot(
                    elapsed_seconds=0.2 + grace_seconds + 0.2,
                    last_event_seconds_ago=0.0,
                    event_count=4,
                    command_execution_count=0,
                    reasoning_item_count=0,
                    last_command=None,
                    last_command_repeat_count=0,
                    has_final_agent_message=True,
                    agent_message_count=1,
                    timeout_seconds=kwargs.get("timeout_seconds"),
                )
            )
            assert decision is not None
            return CodexExecRunResult(
                command=["codex", "exec"],
                subprocess_exit_code=0,
                output_schema_path=None,
                prompt_text=str(kwargs.get("prompt_text") or ""),
                response_text='{"status":"worker_completed"}',
                turn_failed_message=None,
                usage={
                    "input_tokens": 1,
                    "cached_input_tokens": 0,
                    "output_tokens": 1,
                    "reasoning_tokens": 0,
                },
                source_working_dir=str(working_dir),
                execution_working_dir=str(working_dir),
                execution_agents_path=None,
                duration_ms=1,
                started_at_utc="2026-01-01T00:00:00Z",
                finished_at_utc="2026-01-01T00:00:00Z",
                workspace_mode="workspace_worker",
                supervision_state=decision.supervision_state,
                supervision_reason_code=decision.reason_code,
                supervision_reason_detail=decision.reason_detail,
                supervision_retryable=decision.retryable,
            )
        return super().run_workspace_worker(**kwargs)


class _ProgressSummaryAnswersFileRunner(FakeCodexExecRunner):
    def __init__(self) -> None:
        super().__init__(
            output_builder=lambda payload: {
                "rows": [
                    {"atomic_index": int(row[0]), "label": "NONRECIPE_CANDIDATE"}
                    for row in (dict(payload or {}).get("rows") or [])
                    if isinstance(row, (list, tuple)) and row
                ]
            }
        )
        self.workspace_run_calls = 0

    def run_workspace_worker(self, **kwargs) -> CodexExecRunResult:  # noqa: ANN003
        self.workspace_run_calls += 1
        working_dir = Path(kwargs.get("working_dir"))
        if self.workspace_run_calls == 1:
            task_file = load_task_file(working_dir / "task.json")
            answers_by_unit_id: dict[str, dict[str, str]] = {}
            for index, unit in enumerate(task_file["units"]):
                unit_id = str(unit.get("unit_id") or "").strip()
                if not unit_id:
                    continue
                if index < 2:
                    answers_by_unit_id[unit_id] = {"label": "NONRECIPE_CANDIDATE"}
            (working_dir / "answers.json").write_text(
                json.dumps({"answers_by_unit_id": answers_by_unit_id}, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            callback = kwargs.get("supervision_callback")
            assert callback is not None
            decision = callback(
                CodexExecLiveSnapshot(
                    elapsed_seconds=0.3,
                    last_event_seconds_ago=0.0,
                    event_count=6,
                    command_execution_count=2,
                    reasoning_item_count=1,
                    last_command="/bin/bash -lc 'task-show-unanswered --limit 5'",
                    last_command_repeat_count=1,
                    has_final_agent_message=True,
                    agent_message_count=1,
                    timeout_seconds=kwargs.get("timeout_seconds"),
                    final_agent_message_text=(
                        "- I reviewed the first chunk and recorded labels in `answers.json`.\n"
                        "- The rest of the shard still needs labeling, and I haven't run "
                        "`task-apply answers.json` or `task-handoff` yet.\n\n"
                        "1. Keep moving through the ledger.\n"
                        "2. After batching more edits, run `task-apply answers.json`, then `task-handoff`."
                    ),
                )
            )
            assert decision is not None
            assert decision.reason_code == "workspace_final_message_incomplete_progress"
            return CodexExecRunResult(
                command=["codex", "exec"],
                subprocess_exit_code=0,
                output_schema_path=None,
                prompt_text=str(kwargs.get("prompt_text") or ""),
                response_text=(
                    "- I reviewed the first chunk and recorded labels in `answers.json`.\n"
                    "- The rest of the shard still needs labeling, and I haven't run "
                    "`task-apply answers.json` or `task-handoff` yet."
                ),
                turn_failed_message=None,
                usage={
                    "input_tokens": 1,
                    "cached_input_tokens": 0,
                    "output_tokens": 1,
                    "reasoning_tokens": 0,
                },
                source_working_dir=str(working_dir),
                execution_working_dir=str(working_dir),
                execution_agents_path=None,
                duration_ms=1,
                started_at_utc="2026-01-01T00:00:00Z",
                finished_at_utc="2026-01-01T00:00:00Z",
                workspace_mode="workspace_worker",
                supervision_state=decision.supervision_state,
                supervision_reason_code=decision.reason_code,
                supervision_reason_detail=decision.reason_detail,
                supervision_retryable=decision.retryable,
            )

        task_file = load_task_file(working_dir / "task.json")
        edited = deepcopy(task_file)
        for unit in edited["units"]:
            unit["answer"] = {"label": "NONRECIPE_CANDIDATE"}
        write_task_file(path=working_dir / "task.json", payload=edited)
        state_path = Path(
            str(kwargs.get("env", {}).get("RECIPEIMPORT_LINE_ROLE_SAME_SESSION_STATE_PATH"))
        )
        helper_result = advance_line_role_same_session_handoff(
            workspace_root=working_dir,
            state_path=state_path,
        )
        assert helper_result["status"] == "completed"
        return CodexExecRunResult(
            command=["codex", "exec"],
            subprocess_exit_code=0,
            output_schema_path=None,
            prompt_text=str(kwargs.get("prompt_text") or ""),
            response_text='{"status":"completed"}',
            turn_failed_message=None,
            usage={
                "input_tokens": 1,
                "cached_input_tokens": 0,
                "output_tokens": 1,
                "reasoning_tokens": 0,
            },
            source_working_dir=str(working_dir),
            execution_working_dir=str(working_dir),
            execution_agents_path=None,
            duration_ms=1,
            started_at_utc="2026-01-01T00:00:00Z",
            finished_at_utc="2026-01-01T00:00:00Z",
            workspace_mode="workspace_worker",
            supervision_state="completed",
            supervision_reason_code=None,
            supervision_reason_detail=None,
            supervision_retryable=False,
        )


class _KilledAfterHelperCompletionRunner(FakeCodexExecRunner):
    def __init__(self) -> None:
        super().__init__(
            output_builder=lambda payload: {
                "rows": [
                    {"atomic_index": int(row[0]), "label": "NONRECIPE_CANDIDATE"}
                    for row in (dict(payload or {}).get("rows") or [])
                    if isinstance(row, (list, tuple)) and row
                ]
            }
        )
        self.workspace_run_calls = 0

    def run_workspace_worker(self, **kwargs) -> CodexExecRunResult:  # noqa: ANN003
        self.workspace_run_calls += 1
        working_dir = Path(kwargs.get("working_dir"))
        task_file = load_task_file(working_dir / "task.json")
        edited = deepcopy(task_file)
        for unit in edited["units"]:
            unit["answer"] = {"label": "NONRECIPE_CANDIDATE"}
        write_task_file(path=working_dir / "task.json", payload=edited)

        state_path = Path(
            str(kwargs.get("env", {}).get("RECIPEIMPORT_LINE_ROLE_SAME_SESSION_STATE_PATH"))
        )
        helper_result = advance_line_role_same_session_handoff(
            workspace_root=working_dir,
            state_path=state_path,
        )
        assert helper_result["status"] == "completed"

        return CodexExecRunResult(
            command=["codex", "exec"],
            subprocess_exit_code=0,
            output_schema_path=None,
            prompt_text=str(kwargs.get("prompt_text") or ""),
            response_text='{"status":"worker_completed"}',
            turn_failed_message=None,
            usage={
                "input_tokens": 1,
                "cached_input_tokens": 0,
                "output_tokens": 1,
                "reasoning_tokens": 0,
            },
            source_working_dir=str(working_dir),
            execution_working_dir=str(working_dir),
            execution_agents_path=None,
            duration_ms=1,
            started_at_utc="2026-01-01T00:00:00Z",
            finished_at_utc="2026-01-01T00:00:00Z",
            workspace_mode="workspace_worker",
            supervision_state="watchdog_killed",
            supervision_reason_code="workspace_final_message_missing_output",
            supervision_reason_detail=(
                "workspace worker emitted a final agent message but the required output files "
                "were still missing after 15.0 seconds: line-role-canonical-0001-a000000-a000000.json"
            ),
            supervision_retryable=True,
        )


class _AuthoritativeCompletionRunner(FakeCodexExecRunner):
    def __init__(self, *, emit_shell_drift: bool = False) -> None:
        super().__init__(
            output_builder=lambda payload: {
                "rows": [
                    {"atomic_index": int(row[0]), "label": "NONRECIPE_CANDIDATE"}
                    for row in (dict(payload or {}).get("rows") or [])
                    if isinstance(row, (list, tuple)) and row
                ]
            }
        )
        self.workspace_run_calls = 0
        self.emit_shell_drift = emit_shell_drift

    def run_workspace_worker(self, **kwargs) -> CodexExecRunResult:  # noqa: ANN003
        self.workspace_run_calls += 1
        working_dir = Path(kwargs.get("working_dir"))
        callback = kwargs.get("supervision_callback")
        assert callback is not None
        quiescence_seconds = float(
            canonical_line_roles_module._LINE_ROLE_WORKSPACE_COMPLETION_QUIESCENCE_SECONDS  # noqa: SLF001
        )

        if self.emit_shell_drift:
            warning_decision = callback(
                CodexExecLiveSnapshot(
                    elapsed_seconds=0.1,
                    last_event_seconds_ago=0.0,
                    event_count=2,
                    command_execution_count=1,
                    reasoning_item_count=0,
                    last_command="/bin/bash -lc 'cat task.json'",
                    last_command_repeat_count=1,
                    has_final_agent_message=False,
                    timeout_seconds=kwargs.get("timeout_seconds"),
                )
            )
            assert warning_decision is None

        task_file = load_task_file(working_dir / "task.json")
        edited = deepcopy(task_file)
        for unit in edited["units"]:
            unit["answer"] = {"label": "NONRECIPE_CANDIDATE"}
        write_task_file(path=working_dir / "task.json", payload=edited)

        state_path = Path(
            str(kwargs.get("env", {}).get("RECIPEIMPORT_LINE_ROLE_SAME_SESSION_STATE_PATH"))
        )
        helper_result = advance_line_role_same_session_handoff(
            workspace_root=working_dir,
            state_path=state_path,
        )
        assert helper_result["status"] == "completed"

        first = callback(
            CodexExecLiveSnapshot(
                elapsed_seconds=0.3,
                last_event_seconds_ago=0.0,
                event_count=4,
                command_execution_count=(
                    1 if self.emit_shell_drift else 0
                ),
                reasoning_item_count=0,
                last_command=(
                    "/bin/bash -lc 'cat task.json'" if self.emit_shell_drift else None
                ),
                last_command_repeat_count=1 if self.emit_shell_drift else 0,
                has_final_agent_message=True,
                agent_message_count=1,
                timeout_seconds=kwargs.get("timeout_seconds"),
            )
        )
        assert first is None

        decision = callback(
            CodexExecLiveSnapshot(
                elapsed_seconds=0.6 + quiescence_seconds + 0.1,
                last_event_seconds_ago=quiescence_seconds + 0.1,
                event_count=5,
                command_execution_count=(
                    1 if self.emit_shell_drift else 0
                ),
                reasoning_item_count=0,
                last_command=(
                    "/bin/bash -lc 'cat task.json'" if self.emit_shell_drift else None
                ),
                last_command_repeat_count=1 if self.emit_shell_drift else 0,
                has_final_agent_message=True,
                agent_message_count=1,
                timeout_seconds=kwargs.get("timeout_seconds"),
            )
        )
        assert decision is not None
        assert decision.supervision_state == "completed"

        return CodexExecRunResult(
            command=["codex", "exec"],
            subprocess_exit_code=0,
            output_schema_path=None,
            prompt_text=str(kwargs.get("prompt_text") or ""),
            response_text='{"status":"completed"}',
            turn_failed_message=None,
            usage={
                "input_tokens": 1,
                "cached_input_tokens": 0,
                "output_tokens": 1,
                "reasoning_tokens": 0,
            },
            source_working_dir=str(working_dir),
            execution_working_dir=str(working_dir),
            execution_agents_path=None,
            duration_ms=1,
            started_at_utc="2026-01-01T00:00:00Z",
            finished_at_utc="2026-01-01T00:00:00Z",
            workspace_mode="workspace_worker",
            supervision_state=decision.supervision_state,
            supervision_reason_code=decision.reason_code,
            supervision_reason_detail=decision.reason_detail,
            supervision_retryable=decision.retryable,
        )


class _HelperCompletionVisibilityLagRunner(FakeCodexExecRunner):
    def __init__(self) -> None:
        super().__init__(
            output_builder=lambda payload: {
                "rows": [
                    {"atomic_index": int(row[0]), "label": "NONRECIPE_CANDIDATE"}
                    for row in (dict(payload or {}).get("rows") or [])
                    if isinstance(row, (list, tuple)) and row
                ]
            }
        )
        self.workspace_run_calls = 0

    def run_workspace_worker(self, **kwargs) -> CodexExecRunResult:  # noqa: ANN003
        self.workspace_run_calls += 1
        working_dir = Path(kwargs.get("working_dir"))
        callback = kwargs.get("supervision_callback")
        assert callback is not None
        quiescence_seconds = float(
            canonical_line_roles_module._LINE_ROLE_WORKSPACE_COMPLETION_QUIESCENCE_SECONDS  # noqa: SLF001
        )

        task_file = load_task_file(working_dir / "task.json")
        edited = deepcopy(task_file)
        for unit in edited["units"]:
            unit["answer"] = {"label": "NONRECIPE_CANDIDATE"}
        write_task_file(path=working_dir / "task.json", payload=edited)

        helper_summary = _completed_line_role_helper_command()
        summary_command = _completed_task_file_summary_command()
        first = callback(
            CodexExecLiveSnapshot(
                elapsed_seconds=0.3,
                last_event_seconds_ago=0.0,
                event_count=4,
                command_execution_count=2,
                reasoning_item_count=0,
                last_command=summary_command.command,
                last_command_repeat_count=1,
                has_final_agent_message=True,
                agent_message_count=1,
                timeout_seconds=kwargs.get("timeout_seconds"),
                last_completed_command=summary_command,
                last_completed_stage_helper_command=helper_summary,
            )
        )
        assert first is None

        state_path = Path(
            str(kwargs.get("env", {}).get("RECIPEIMPORT_LINE_ROLE_SAME_SESSION_STATE_PATH"))
        )
        advance_result = advance_line_role_same_session_handoff(
            workspace_root=working_dir,
            state_path=state_path,
        )
        assert advance_result["status"] == "completed"

        second = callback(
            CodexExecLiveSnapshot(
                elapsed_seconds=0.6,
                last_event_seconds_ago=0.0,
                event_count=5,
                command_execution_count=2,
                reasoning_item_count=0,
                last_command=summary_command.command,
                last_command_repeat_count=1,
                has_final_agent_message=True,
                agent_message_count=1,
                timeout_seconds=kwargs.get("timeout_seconds"),
                last_completed_command=summary_command,
                last_completed_stage_helper_command=helper_summary,
            )
        )
        assert second is None

        decision = callback(
            CodexExecLiveSnapshot(
                elapsed_seconds=0.6 + quiescence_seconds + 0.1,
                last_event_seconds_ago=quiescence_seconds + 0.1,
                event_count=6,
                command_execution_count=2,
                reasoning_item_count=0,
                last_command=summary_command.command,
                last_command_repeat_count=1,
                has_final_agent_message=True,
                agent_message_count=1,
                timeout_seconds=kwargs.get("timeout_seconds"),
                last_completed_command=summary_command,
                last_completed_stage_helper_command=helper_summary,
            )
        )
        assert decision is not None
        assert decision.supervision_state == "completed"

        return CodexExecRunResult(
            command=["codex", "exec"],
            subprocess_exit_code=0,
            output_schema_path=None,
            prompt_text=str(kwargs.get("prompt_text") or ""),
            response_text='{"status":"completed"}',
            turn_failed_message=None,
            events=(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_27",
                        "type": "command_execution",
                        "command": helper_summary.command,
                        "exit_code": 0,
                        "status": "completed",
                        "aggregated_output": (
                            '{"completed": true, "final_status": "completed", "status": "completed"}\n'
                        ),
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_29",
                        "type": "command_execution",
                        "command": summary_command.command,
                        "exit_code": 0,
                        "status": "completed",
                        "aggregated_output": '{"answered_units": 1}\n',
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_30",
                        "type": "agent_message",
                        "text": "Completed for shard `line-role-canonical-0001-a000000-a000000`.",
                    },
                },
            ),
            usage={
                "input_tokens": 1,
                "cached_input_tokens": 0,
                "output_tokens": 1,
                "reasoning_tokens": 0,
            },
            source_working_dir=str(working_dir),
            execution_working_dir=str(working_dir),
            execution_agents_path=None,
            duration_ms=1,
            started_at_utc="2026-01-01T00:00:00Z",
            finished_at_utc="2026-01-01T00:00:00Z",
            workspace_mode="workspace_worker",
            supervision_state=decision.supervision_state,
            supervision_reason_code=decision.reason_code,
            supervision_reason_detail=decision.reason_detail,
            supervision_retryable=decision.retryable,
        )


def _run_line_role_cohort_outlier_warning_fixture(
    tmp_path,
    monkeypatch,
) -> dict[str, object]:
    monkeypatch.setattr(
        canonical_line_roles_module,
        "_LINE_ROLE_COHORT_WATCHDOG_MIN_ELAPSED_MS",
        10,
    )
    monkeypatch.setattr(
        canonical_line_roles_module,
        "_LINE_ROLE_COHORT_WATCHDOG_MEDIAN_FACTOR",
        2.0,
    )

    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:outlier:{atomic_index}",
            block_index=atomic_index,
            atomic_index=atomic_index,
            text=f"Ambiguous line {atomic_index}",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
        for atomic_index in range(4)
    ]

    class _OutlierRetryRunner(FakeCodexExecRunner):
        @staticmethod
        def _first_atomic_index_for_workspace(working_dir) -> int:  # noqa: ANN001
            worker_root = Path(str(working_dir))
            assigned_shards_path = worker_root / "assigned_shards.json"
            if not assigned_shards_path.exists():
                return -1
            assigned_shards = json.loads(assigned_shards_path.read_text(encoding="utf-8"))
            if not isinstance(assigned_shards, list) or not assigned_shards:
                return -1
            shard_row = assigned_shards[0]
            if not isinstance(shard_row, dict):
                return -1
            shard_id = str(shard_row.get("shard_id") or "").strip()
            if not shard_id:
                return -1
            input_path = worker_root / "in" / f"{shard_id}.json"
            if not input_path.exists():
                return -1
            payload = json.loads(input_path.read_text(encoding="utf-8"))
            rows = payload.get("rows") if isinstance(payload, dict) else []
            if not isinstance(rows, list) or not rows:
                return -1
            first_row = rows[0]
            return int(first_row[0]) if isinstance(first_row, list) and first_row else -1

        def run_structured_prompt(self, *args, **kwargs):  # noqa: ANN002, ANN003
            payload = dict(kwargs.get("input_payload") or {})
            rows = payload.get("rows") or []
            first_atomic_index = int(rows[0][0]) if rows else -1
            if payload.get("retry_mode") == "line_role_watchdog":
                return super().run_structured_prompt(*args, **kwargs)
            if first_atomic_index == 3:
                supervision_callback = kwargs.get("supervision_callback")
                if supervision_callback is not None:
                    for _ in range(40):
                        time.sleep(0.05)
                        decision = supervision_callback(
                            CodexExecLiveSnapshot(
                                elapsed_seconds=0.2,
                                last_event_seconds_ago=0.05,
                                event_count=0,
                                command_execution_count=0,
                                reasoning_item_count=0,
                                last_command=None,
                                last_command_repeat_count=0,
                                has_final_agent_message=False,
                                timeout_seconds=kwargs.get("timeout_seconds"),
                            )
                        )
                        assert decision is None
            return super().run_structured_prompt(*args, **kwargs)

        def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            first_atomic_index = self._first_atomic_index_for_workspace(kwargs.get("working_dir"))
            if first_atomic_index == 3:
                supervision_callback = kwargs.get("supervision_callback")
                if supervision_callback is not None:
                    for _ in range(40):
                        time.sleep(0.05)
                        decision = supervision_callback(
                            CodexExecLiveSnapshot(
                                elapsed_seconds=0.2,
                                last_event_seconds_ago=0.05,
                                event_count=0,
                                command_execution_count=0,
                                reasoning_item_count=0,
                                last_command=None,
                                last_command_repeat_count=0,
                                has_final_agent_message=False,
                                timeout_seconds=kwargs.get("timeout_seconds"),
                            )
                        )
                        assert decision is None
            return super().run_workspace_worker(*args, **kwargs)

    predictions = label_atomic_lines(
        candidates,
        _settings(
            "codex-line-role-route-v2",
            line_role_worker_count=4,
            line_role_prompt_target_count=4,
        ),
        artifact_root=tmp_path,
        codex_batch_size=1,
        codex_runner=_OutlierRetryRunner(
            output_builder=lambda payload: {
                "rows": [
                    {"atomic_index": int(row[0]), "label": "RECIPE_NOTES"}
                    for row in (payload.get("rows") or [])
                ]
            }
        ),
        live_llm_allowed=True,
    )

    telemetry_payload = json.loads(
        (tmp_path / "line-role-pipeline" / "telemetry_summary.json").read_text(
            encoding="utf-8"
        )
    )
    failures = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "failures.json"
        ).read_text(encoding="utf-8")
    )
    warning_live_status = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in (tmp_path / "line-role-pipeline" / "runtime").rglob("live_status.json")
        if json.loads(path.read_text(encoding="utf-8")).get("warning_count")
    )
    return {
        "predictions": predictions,
        "telemetry_payload": telemetry_payload,
        "failures": failures,
        "warning_live_status": warning_live_status,
    }


def _run_single_prompt_surface_fixture(tmp_path: Path) -> dict[str, object]:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:compact:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous line 0",
            within_recipe_span=None,
            rule_tags=[],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_batch_size=1,
        codex_runner=_line_role_runner({0: "NONRECIPE_CANDIDATE"}),
        live_llm_allowed=True,
    )
    return {
        "predictions": predictions,
        "prompt_root": tmp_path / "line-role-pipeline",
    }
