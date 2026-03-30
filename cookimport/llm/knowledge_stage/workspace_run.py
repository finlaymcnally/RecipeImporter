from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import _shared as _shared_module
from . import planning as _planning_module
from . import recovery as _recovery_module
from ..knowledge_phase_workspace_tools import (
    assemble_final_output,
    build_knowledge_workspace_shard_metadata,
    build_pass1_packet,
    build_pass1_repair_packet,
    build_pass2_packet,
    build_pass2_repair_packet,
    render_knowledge_packet_hint,
    validate_pass1_packet_result,
    validate_pass2_packet_result,
    write_knowledge_output_contract,
    write_knowledge_worker_examples,
)

for _module in (
    _shared_module,
    _planning_module,
    _recovery_module,
):
    globals().update(
        {
            name: value
            for name, value in vars(_module).items()
            if not name.startswith("__")
        }
    )


def _render_events_jsonl(events: tuple[dict[str, Any], ...]) -> str:
    if not events:
        return ""
    return "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)


def _load_json_dict_safely(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _render_validation_reason_detail(
    *,
    prefix: str,
    validation_errors: Sequence[str],
    validation_metadata: Mapping[str, Any],
) -> str:
    cleaned_errors = [
        str(error).strip() for error in validation_errors if str(error).strip()
    ]
    parse_error = str(validation_metadata.get("parse_error") or "").strip()
    unresolved_block_indices = [
        int(value)
        for value in (validation_metadata.get("unresolved_block_indices") or [])
        if value is not None
    ]
    detail_parts = [str(prefix).strip() or "validation blocked promotion"]
    if cleaned_errors:
        detail_parts.append("errors=" + ",".join(cleaned_errors))
    if unresolved_block_indices:
        detail_parts.append(
            "unresolved_block_indices=" + ",".join(str(value) for value in unresolved_block_indices)
        )
    if parse_error:
        detail_parts.append(f"parse_error={parse_error}")
    return "; ".join(part for part in detail_parts if part)


@dataclass(slots=True)
class _KnowledgeLeasedShardState:
    shard: ShardManifestEntryV1
    input_payload: dict[str, Any]
    hint_text: str
    pass1_result: dict[str, Any] | None = None
    pass2_result: dict[str, Any] | None = None
    packet_count: int = 0
    repair_packet_count: int = 0
    repair_attempted: bool = False
    repair_recovered: bool = False
    last_validation_errors: tuple[str, ...] = ()
    last_validation_metadata: dict[str, Any] = field(default_factory=dict)
    current_task_id: str | None = None
    current_packet_kind: str | None = None
    current_result_relpath: str | None = None
    current_packet_state: str = "pending"
    current_result_observed: bool = False
    promotion_attempted: bool = False
    promotion_succeeded: bool = False
    last_runtime_action: str = "pending"
    terminal_status: str = "pending"
    terminal_reason_code: str | None = None
    terminal_reason_detail: str | None = None


@dataclass(slots=True)
class _KnowledgePacketLeaseController:
    worker_root: Path
    shard_states: dict[str, _KnowledgeLeasedShardState]
    shard_order: tuple[str, ...]
    current_packet: dict[str, Any] | None = None
    current_result_relpath: str | None = None
    current_shard_id_value: str | None = None
    current_validation_errors: tuple[str, ...] = ()
    queue_complete: bool = False
    completed_shard_ids: set[str] = field(default_factory=set)
    failed_shard_ids: set[str] = field(default_factory=set)
    packet_history_path: Path | None = None

    def __post_init__(self) -> None:
        if self.packet_history_path is None:
            self.packet_history_path = self.worker_root / "packet_history.jsonl"
        self._advance_to_next_pending_shard()

    @property
    def total_task_count(self) -> int:
        return len(self.shard_order)

    @property
    def validated_task_count(self) -> int:
        return len(self.completed_shard_ids)

    def is_complete(self) -> bool:
        return self.queue_complete

    def current_task_id(self) -> str | None:
        return (
            str(self.current_packet.get("task_id") or "").strip()
            if isinstance(self.current_packet, Mapping)
            else None
        ) or None

    def status_payload(self) -> dict[str, Any]:
        return {
            "queue_total_task_count": self.total_task_count,
            "queue_validated_task_count": self.validated_task_count,
            "queue_failed_task_count": len(self.failed_shard_ids),
            "queue_remaining_task_count": max(
                self.total_task_count
                - self.validated_task_count
                - len(self.failed_shard_ids),
                0,
            ),
            "queue_complete": self.is_complete(),
            "current_task_id": self.current_task_id(),
            "current_shard_id": self.current_shard_id_value,
            "current_packet_kind": (
                str(self.current_packet.get("packet_kind") or "").strip()
                if isinstance(self.current_packet, Mapping)
                else None
            ),
            "current_validation_errors": list(self.current_validation_errors),
        }

    def shard_summary(self, shard_id: str) -> dict[str, Any]:
        state = self.shard_states[str(shard_id)]
        return {
            "packet_count": state.packet_count,
            "repair_packet_count": state.repair_packet_count,
            "repair_attempted": state.repair_attempted,
            "repair_recovered": state.repair_recovered,
            "current_task_id": state.current_task_id,
            "current_packet_kind": state.current_packet_kind,
            "current_result_relpath": state.current_result_relpath,
            "current_packet_state": state.current_packet_state,
            "current_result_observed": state.current_result_observed,
            "promotion_attempted": state.promotion_attempted,
            "promotion_succeeded": state.promotion_succeeded,
            "last_runtime_action": state.last_runtime_action,
            "terminal_status": state.terminal_status,
            "terminal_reason_code": state.terminal_reason_code,
            "terminal_reason_detail": state.terminal_reason_detail,
            "last_validation_errors": list(state.last_validation_errors),
            "last_validation_metadata": dict(state.last_validation_metadata),
        }

    def observe_current_output(self) -> dict[str, Any]:
        previous_task_id = self.current_task_id()
        previous_complete = self.queue_complete
        previous_completed_count = len(self.completed_shard_ids) + len(self.failed_shard_ids)

        current_output_present = False
        if self.current_result_relpath:
            current_result_path = self.worker_root / self.current_result_relpath
            current_output_present = current_result_path.exists() and current_result_path.is_file()
            if current_output_present:
                shard_id = str(
                    (self.current_packet or {}).get("shard_id")
                    or self.current_shard_id_value
                    or ""
                ).strip()
                if shard_id and shard_id in self.shard_states:
                    self.shard_states[shard_id].current_result_observed = True
                self._consume_current_result(current_result_path)
        current_task_id = self.current_task_id()
        return {
            "current_task_id": current_task_id,
            "current_output_present": current_output_present,
            "advanced": (
                previous_task_id != current_task_id
                or previous_complete != self.queue_complete
                or previous_completed_count
                != (len(self.completed_shard_ids) + len(self.failed_shard_ids))
            ),
            "valid": self.queue_complete or current_output_present,
            "validation_errors": self.current_validation_errors,
            "queue_complete": self.queue_complete,
        }

    def _consume_current_result(self, result_path: Path) -> None:
        packet = dict(self.current_packet or {})
        shard_id = str(packet.get("shard_id") or self.current_shard_id_value or "").strip()
        if not shard_id:
            return
        state = self.shard_states[shard_id]
        try:
            loaded_payload = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            self._handle_invalid_packet(
                state=state,
                packet=packet,
                validation_errors=("response_json_invalid",),
                validation_metadata={"parse_error": str(exc)},
            )
            return
        if not isinstance(loaded_payload, Mapping):
            self._handle_invalid_packet(
                state=state,
                packet=packet,
                validation_errors=("response_not_json_object",),
                validation_metadata={},
            )
            return

        packet_kind = str(packet.get("packet_kind") or "").strip()
        if packet_kind == "pass1":
            normalized_payload, validation_errors, validation_metadata = (
                validate_pass1_packet_result(
                    packet_payload=packet,
                    result_payload=dict(loaded_payload),
                )
            )
        else:
            normalized_payload, validation_errors, validation_metadata = (
                validate_pass2_packet_result(
                    packet_payload=packet,
                    result_payload=dict(loaded_payload),
                )
            )
        if validation_errors:
            self._handle_invalid_packet(
                state=state,
                packet=packet,
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
            )
            return
        result_path.unlink(missing_ok=True)
        if packet_kind == "pass1":
            state.pass1_result = normalized_payload
            self._install_pass1(state)
            return
        state.pass2_result = normalized_payload
        self._install_pass2(state)

    def _install_pass1(self, state: _KnowledgeLeasedShardState) -> None:
        assert state.pass1_result is not None
        if state.repair_attempted:
            state.repair_recovered = True
        knowledge_rows = [
            dict(row)
            for row in (state.pass1_result.get("rows") or [])
            if isinstance(row, Mapping)
            and str(row.get("category") or "").strip() == "knowledge"
        ]
        if not knowledge_rows:
            final_payload = assemble_final_output(
                shard_id=state.shard.shard_id,
                pass1_result=state.pass1_result,
                pass2_result={"rows": []},
            )
            self._install_final_payload(state=state, final_payload=final_payload)
            return
        next_packet = build_pass2_packet(
            shard_id=state.shard.shard_id,
            task_id=f"{state.shard.shard_id}.pass2",
            input_payload=state.input_payload,
            pass1_rows=knowledge_rows,
        )
        self._write_current_packet(state=state, packet=next_packet)

    def _install_pass2(self, state: _KnowledgeLeasedShardState) -> None:
        assert state.pass1_result is not None
        assert state.pass2_result is not None
        final_payload = assemble_final_output(
            shard_id=state.shard.shard_id,
            pass1_result=state.pass1_result,
            pass2_result=state.pass2_result,
        )
        self._install_final_payload(state=state, final_payload=final_payload)

    def _install_final_payload(
        self,
        *,
        state: _KnowledgeLeasedShardState,
        final_payload: Mapping[str, Any],
    ) -> None:
        valid, validation_errors, validation_metadata = validate_knowledge_shard_output(
            state.shard,
            dict(final_payload),
        )
        state.promotion_attempted = True
        if not valid:
            self._mark_failed(
                state=state,
                reason_code=(
                    "repair_packet_exhausted"
                    if state.repair_attempted
                    else "packet_result_validation_blocked"
                ),
                reason_detail=_render_validation_reason_detail(
                    prefix=(
                        "repair packet was exhausted without a promotable final output"
                        if state.repair_attempted
                        else "packet result existed but structural validation blocked promotion"
                    ),
                    validation_errors=validation_errors,
                    validation_metadata=validation_metadata,
                ),
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
            )
            return
        _write_json(
            dict(final_payload),
            self.worker_root / "out" / f"{state.shard.shard_id}.json",
        )
        state.current_packet_state = "validated"
        state.current_result_observed = True
        state.promotion_succeeded = True
        state.last_runtime_action = "shard_validated"
        state.terminal_status = "validated"
        state.terminal_reason_code = "validated"
        state.terminal_reason_detail = None
        self.completed_shard_ids.add(state.shard.shard_id)
        self.current_validation_errors = ()
        self._append_packet_history(
            {
                "event": "shard_validated",
                "shard_id": state.shard.shard_id,
                "packet_count": state.packet_count,
                "repair_packet_count": state.repair_packet_count,
            }
        )
        self._advance_to_next_pending_shard()

    def _handle_invalid_packet(
        self,
        *,
        state: _KnowledgeLeasedShardState,
        packet: Mapping[str, Any],
        validation_errors: Sequence[str],
        validation_metadata: Mapping[str, Any],
    ) -> None:
        state.last_validation_errors = tuple(validation_errors)
        state.last_validation_metadata = dict(validation_metadata or {})
        state.current_packet_state = "validation_blocked"
        state.current_result_observed = True
        state.last_runtime_action = "validation_blocked"
        self.current_validation_errors = tuple(validation_errors)
        packet_kind = str(packet.get("packet_kind") or "").strip()
        repair_payload = _coerce_dict(packet.get("repair"))
        repair_attempt = bool(repair_payload)
        if repair_attempt:
            self._mark_failed(
                state=state,
                reason_code="repair_packet_exhausted",
                reason_detail=_render_validation_reason_detail(
                    prefix="repair packet was exhausted without a promotable final output",
                    validation_errors=validation_errors,
                    validation_metadata=validation_metadata,
                ),
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
            )
            return

        state.repair_attempted = True
        if packet_kind == "pass1":
            repair_packet = build_pass1_repair_packet(
                packet_payload=packet,
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
                accepted_rows=[
                    dict(row)
                    for row in ((state.pass1_result or {}).get("rows") or [])
                    if isinstance(row, Mapping)
                ],
            )
        else:
            repair_packet = build_pass2_repair_packet(
                packet_payload=packet,
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
                accepted_rows=[
                    dict(row)
                    for row in ((state.pass2_result or {}).get("rows") or [])
                    if isinstance(row, Mapping)
                ],
            )
        repair_packet["task_id"] = (
            f"{state.shard.shard_id}.{packet_kind}.repair{state.repair_packet_count + 1:02d}"
        )
        self._write_current_packet(state=state, packet=repair_packet, repair_packet=True)

    def _mark_failed(
        self,
        *,
        state: _KnowledgeLeasedShardState,
        reason_code: str,
        reason_detail: str | None,
        validation_errors: Sequence[str],
        validation_metadata: Mapping[str, Any],
    ) -> None:
        state.current_packet_state = "failed"
        state.last_runtime_action = "shard_failed"
        state.terminal_status = "failed"
        state.terminal_reason_code = str(reason_code).strip() or "validation_failed"
        state.terminal_reason_detail = str(reason_detail or "").strip() or None
        state.last_validation_errors = tuple(validation_errors)
        state.last_validation_metadata = dict(validation_metadata or {})
        self.failed_shard_ids.add(state.shard.shard_id)
        self._append_packet_history(
            {
                "event": "shard_failed",
                "shard_id": state.shard.shard_id,
                "reason_code": state.terminal_reason_code,
                "reason_detail": state.terminal_reason_detail,
                "validation_errors": list(validation_errors),
                "validation_metadata": dict(validation_metadata or {}),
            }
        )
        self._advance_to_next_pending_shard()

    def _advance_to_next_pending_shard(self) -> None:
        next_shard_id = next(
            (
                shard_id
                for shard_id in self.shard_order
                if shard_id not in self.completed_shard_ids
                and shard_id not in self.failed_shard_ids
            ),
            None,
        )
        if next_shard_id is None:
            self.queue_complete = True
            self.current_packet = None
            self.current_result_relpath = None
            self.current_shard_id_value = None
            self._write_queue_complete_status()
            return
        state = self.shard_states[next_shard_id]
        next_packet = build_pass1_packet(
            shard_id=state.shard.shard_id,
            task_id=f"{state.shard.shard_id}.pass1",
            input_payload=state.input_payload,
        )
        self._write_current_packet(state=state, packet=next_packet)

    def _write_current_packet(
        self,
        *,
        state: _KnowledgeLeasedShardState,
        packet: Mapping[str, Any],
        repair_packet: bool = False,
    ) -> None:
        self.queue_complete = False
        self.current_packet = dict(packet)
        self.current_shard_id_value = state.shard.shard_id
        self.current_validation_errors = ()
        state.packet_count += 1
        if repair_packet:
            state.repair_packet_count += 1
        task_id = str(packet.get("task_id") or "").strip()
        self.current_result_relpath = str(Path("scratch") / f"{task_id}.json")
        state.current_task_id = task_id
        state.current_packet_kind = str(packet.get("packet_kind") or "").strip() or None
        state.current_result_relpath = self.current_result_relpath
        state.current_packet_state = "leased"
        state.current_result_observed = False
        state.promotion_attempted = False
        state.promotion_succeeded = False
        state.last_runtime_action = "repair_packet_leased" if repair_packet else "lease_started"
        _write_json(self.current_packet, self.worker_root / "current_packet.json")
        (self.worker_root / "current_result_path.txt").write_text(
            self.current_result_relpath + "\n",
            encoding="utf-8",
        )
        (self.worker_root / "current_hint.md").write_text(
            render_knowledge_packet_hint(
                packet_payload=self.current_packet,
                shard_hint_text=state.hint_text,
                result_path=self.current_result_relpath,
            ),
            encoding="utf-8",
        )
        _write_json(
            {
                "schema_version": "knowledge_packet_lease_status.v1",
                "worker_state": "leased_current_packet",
                "last_runtime_action": state.last_runtime_action,
                "current_task_id": task_id,
                "current_shard_id": state.shard.shard_id,
                "packet_kind": packet.get("packet_kind"),
                "current_packet_state": state.current_packet_state,
                "current_result_relpath": self.current_result_relpath,
                "current_result_observed": state.current_result_observed,
                "promotion_attempted": state.promotion_attempted,
                "promotion_succeeded": state.promotion_succeeded,
                "current_validation_errors": list(state.last_validation_errors),
                "current_validation_metadata": dict(state.last_validation_metadata),
                "packet_count_total": state.packet_count,
                "repair_packet_count": state.repair_packet_count,
                "completed_shard_count": len(self.completed_shard_ids),
                "failed_shard_count": len(self.failed_shard_ids),
                "queue_total_shard_count": len(self.shard_order),
                "shard_statuses": {
                    shard_id: self.shard_summary(shard_id)
                    for shard_id in self.shard_order
                },
            },
            self.worker_root / "packet_lease_status.json",
        )
        self._append_packet_history(
            {
                "event": "lease_started",
                "task_id": task_id,
                "shard_id": state.shard.shard_id,
                "packet_kind": packet.get("packet_kind"),
                "repair_packet": repair_packet,
                "result_path": self.current_result_relpath,
            }
        )

    def _write_queue_complete_status(self) -> None:
        for relative_path in (
            "current_packet.json",
            "current_hint.md",
            "current_result_path.txt",
        ):
            (self.worker_root / relative_path).unlink(missing_ok=True)
        for state in self.shard_states.values():
            if state.terminal_status == "pending":
                state.current_packet_state = "queue_completed_without_terminal_output"
                state.last_runtime_action = "queue_completed"
            state.current_task_id = None
            state.current_packet_kind = None
            state.current_result_relpath = None
        _write_json(
            {
                "schema_version": "knowledge_packet_lease_status.v1",
                "worker_state": "queue_completed",
                "completed_shard_count": len(self.completed_shard_ids),
                "failed_shard_count": len(self.failed_shard_ids),
                "queue_total_shard_count": len(self.shard_order),
                "last_runtime_action": "queue_completed",
                "shard_statuses": {
                    shard_id: self.shard_summary(shard_id)
                    for shard_id in self.shard_order
                },
            },
            self.worker_root / "packet_lease_status.json",
        )

    def _append_packet_history(self, payload: Mapping[str, Any]) -> None:
        history_path = self.packet_history_path or (self.worker_root / "packet_history.jsonl")
        history_path.parent.mkdir(parents=True, exist_ok=True)
        with history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(payload), sort_keys=True))
            handle.write("\n")


def _evaluate_knowledge_output_file(
    *,
    shard: ShardManifestEntryV1,
    response_text: str | None,
) -> tuple[dict[str, Any] | None, tuple[str, ...], dict[str, Any], str]:
    if response_text is None or not str(response_text).strip():
        return None, ("missing_output_file",), {}, "no_final_output"
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        return None, ("response_json_invalid",), {}, "invalid"
    if not isinstance(payload, Mapping):
        return None, ("response_not_json_object",), {}, "invalid"
    normalized_payload, normalization_metadata = normalize_knowledge_worker_payload(dict(payload))
    valid, validation_errors, validation_metadata = validate_knowledge_shard_output(
        shard,
        normalized_payload,
    )
    combined_metadata = {
        **dict(validation_metadata or {}),
        **normalization_metadata,
    }
    if not valid:
        combined_metadata["failure_classification"] = classify_knowledge_validation_failure(
            validation_errors=validation_errors,
            validation_metadata=combined_metadata,
        )
        return None, tuple(validation_errors), combined_metadata, "invalid"
    return normalized_payload, (), combined_metadata, "validated"


def _classify_missing_packet_result(
    *,
    worker_root: Path,
    shard: ShardManifestEntryV1,
    run_result: CodexExecRunResult,
    shard_summary: Mapping[str, Any] | None = None,
) -> tuple[str, str | None, dict[str, Any]]:
    live_status = _load_json_dict_safely(worker_root / "live_status.json")
    workspace_manifest = _load_json_dict_safely(worker_root / "workspace_manifest.json")
    lease_status = _load_json_dict_safely(worker_root / "packet_lease_status.json")
    shard_statuses = lease_status.get("shard_statuses")
    lease_shard_summary = (
        dict(shard_statuses.get(shard.shard_id))
        if isinstance(shard_statuses, Mapping)
        and isinstance(shard_statuses.get(shard.shard_id), Mapping)
        else {}
    )
    summary = {
        **lease_shard_summary,
        **dict(shard_summary or {}),
    }
    metadata = {
        "live_status": live_status,
        "workspace_manifest": workspace_manifest,
        "packet_lease_status": lease_status,
        "lease_shard_summary": lease_shard_summary,
    }
    supervision_reason_code = str(run_result.supervision_reason_code or "").strip()
    supervision_reason_detail = str(run_result.supervision_reason_detail or "").strip() or None
    if (
        supervision_reason_code
        and str(run_result.supervision_state or "").strip() == "watchdog_killed"
    ):
        return supervision_reason_code, supervision_reason_detail, metadata

    current_task_id = str(summary.get("current_task_id") or "").strip()
    current_packet_kind = str(summary.get("current_packet_kind") or "").strip()
    current_packet_state = str(summary.get("current_packet_state") or "").strip()
    current_result_relpath = str(summary.get("current_result_relpath") or "").strip()
    current_result_observed = bool(summary.get("current_result_observed"))
    promotion_attempted = bool(summary.get("promotion_attempted"))
    repair_attempted = bool(summary.get("repair_attempted"))
    validation_errors = [
        str(error).strip()
        for error in (summary.get("last_validation_errors") or [])
        if str(error).strip()
    ]
    validation_metadata = _coerce_dict(summary.get("last_validation_metadata"))
    terminal_reason_code = str(summary.get("terminal_reason_code") or "").strip()
    terminal_reason_detail = str(summary.get("terminal_reason_detail") or "").strip() or None
    worker_state = str(lease_status.get("worker_state") or "").strip()

    if terminal_reason_code == "repair_packet_exhausted":
        return terminal_reason_code, terminal_reason_detail, metadata
    if terminal_reason_code == "packet_result_validation_blocked":
        return terminal_reason_code, terminal_reason_detail, metadata

    if current_packet_state == "failed" and repair_attempted:
        return (
            "repair_packet_exhausted",
            terminal_reason_detail
            or _render_validation_reason_detail(
                prefix="repair packet was exhausted without a promotable final output",
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
            ),
            metadata,
        )
    if current_packet_state in {"failed", "validation_blocked"} and (
        current_result_observed or promotion_attempted or validation_errors
    ):
        return (
            "packet_result_validation_blocked",
            terminal_reason_detail
            or _render_validation_reason_detail(
                prefix="packet result existed but structural validation blocked promotion",
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
            ),
            metadata,
        )
    if current_packet_state == "leased" or (
        worker_state == "leased_current_packet" and current_task_id
    ):
        detail = (
            "worker exited while the current packet was still leased"
            f" (task_id={current_task_id or '[unknown]'}, "
            f"packet_kind={current_packet_kind or '[unknown]'}, "
            f"result_path={current_result_relpath or '[unknown]'})"
        )
        return "worker_exited_with_packet_still_leased", detail, metadata
    if worker_state == "queue_completed":
        return (
            "queue_completed_without_promoted_output",
            "queue controller recorded completion without a promotable shard output for this packet",
            metadata,
        )
    return (
        "process_exited_without_final_packet_state",
        "worker exited without a promotable shard output and without enough lease-state evidence for a stronger classification",
        metadata,
    )


def _run_phase_knowledge_worker_assignment_v1(
    *,
    run_root: Path,
    assignment: WorkerAssignmentV1,
    artifacts: Mapping[str, str],
    shard_by_id: Mapping[str, ShardManifestEntryV1],
    runner: CodexExecRunner,
    pipeline_id: str,
    env: Mapping[str, str],
    model: str | None,
    reasoning_effort: str | None,
    cohort_watchdog_state: _KnowledgeCohortWatchdogState,
    shard_completed_callback: Callable[..., None] | None,
    progress_state: _KnowledgePhaseProgressState | None,
    task_status_tracker: _KnowledgeTaskStatusTracker | None,
) -> _DirectKnowledgeWorkerResult:
    worker_root = Path(assignment.workspace_root)
    in_dir = worker_root / "in"
    hints_dir = worker_root / "hints"
    logs_dir = worker_root / "logs"
    out_dir = worker_root / "out"
    scratch_dir = worker_root / "scratch"
    for path in (in_dir, hints_dir, logs_dir, out_dir, scratch_dir):
        path.mkdir(parents=True, exist_ok=True)
    requested_shards = [shard_by_id[shard_id] for shard_id in assignment.shard_ids]

    worker_failure_count = 0
    worker_proposal_count = 0
    worker_failures: list[dict[str, Any]] = []
    worker_proposals: list[ShardProposalV1] = []
    worker_runner_results: list[dict[str, Any]] = []
    stage_rows: list[dict[str, Any]] = []
    assigned_shards: list[ShardManifestEntryV1] = []

    for shard in requested_shards:
        preflight_failure = _preflight_knowledge_shard(shard)
        if preflight_failure is None:
            assigned_shards.append(shard)
            continue
        proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
        reason_code = str(preflight_failure.get("reason_code") or "preflight_rejected")
        reason_detail = str(preflight_failure.get("reason_detail") or "")
        _write_json(
            {
                "shard_id": shard.shard_id,
                "worker_id": assignment.worker_id,
                "payload": None,
                "validation_errors": [reason_code],
                "validation_metadata": {},
            },
            proposal_path,
        )
        worker_failure_count += 1
        worker_failures.append(
            {
                "worker_id": assignment.worker_id,
                "shard_id": shard.shard_id,
                "reason": "preflight_rejected",
                "validation_errors": [reason_code],
                "state": "preflight_rejected",
                "reason_code": reason_code,
            }
        )
        worker_proposals.append(
            ShardProposalV1(
                shard_id=shard.shard_id,
                worker_id=assignment.worker_id,
                status="preflight_rejected",
                proposal_path=_relative_path(run_root, proposal_path),
                payload=None,
                validation_errors=(reason_code,),
                metadata={},
            )
        )
        if task_status_tracker is not None:
            task_status_tracker.mark_terminal(
                task_id=shard.shard_id,
                worker_id=assignment.worker_id,
                terminal_state="preflight_rejected",
                attempt_type="preflight",
                proposal_status="preflight_rejected",
                validation_errors=(reason_code,),
                metadata={"reason_detail": reason_detail},
                terminal_reason_code=reason_code,
                terminal_reason_detail=reason_detail,
            )
        if progress_state is not None:
            progress_state.mark_task_packet_terminal(
                worker_id=assignment.worker_id,
                task_id=shard.shard_id,
            )
        if shard_completed_callback is not None:
            shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)

    assigned_shard_rows: list[dict[str, Any]] = []
    shard_states: dict[str, _KnowledgeLeasedShardState] = {}
    for shard in assigned_shards:
        shard_id = str(shard.shard_id).strip()
        input_relpath = str(Path("in") / f"{shard_id}.json")
        hint_relpath = str(Path("hints") / f"{shard_id}.md")
        result_relpath = str(Path("out") / f"{shard_id}.json")
        shard_row = {
            "shard_id": shard_id,
            "owned_ids": list(shard.owned_ids),
            "metadata": build_knowledge_workspace_shard_metadata(
                shard_id=shard_id,
                input_payload=shard.input_payload,
                input_path=input_relpath,
                hint_path=hint_relpath,
                result_path=result_relpath,
            ),
        }
        assigned_shard_rows.append(shard_row)
        _write_worker_input(
            path=in_dir / f"{shard_id}.json",
            payload=shard.input_payload,
            input_text=shard.input_text,
        )
        _write_knowledge_worker_hint(path=hints_dir / f"{shard_id}.md", shard=shard)
        hint_text = (hints_dir / f"{shard_id}.md").read_text(encoding="utf-8")
        shard_states[shard_id] = _KnowledgeLeasedShardState(
            shard=shard,
            input_payload=dict(shard.input_payload or {}),
            hint_text=hint_text,
        )
    _write_json(assigned_shard_rows, worker_root / "assigned_shards.json")
    write_knowledge_worker_examples(worker_root=worker_root)
    write_knowledge_output_contract(worker_root=worker_root)

    if not assigned_shards:
        _write_json(
            {"worker_state": "queue_completed", "queue_total_shard_count": 0},
            worker_root / "packet_lease_status.json",
        )
        worker_runner_payload = _aggregate_worker_runner_payload(
            pipeline_id=pipeline_id,
            worker_runs=worker_runner_results,
            stage_rows=stage_rows,
        )
        _write_json(worker_runner_payload, worker_root / "status.json")
        return _DirectKnowledgeWorkerResult(
            report=WorkerExecutionReportV1(
                worker_id=assignment.worker_id,
                shard_ids=assignment.shard_ids,
                workspace_root=_relative_path(run_root, worker_root),
                status="ok" if worker_failure_count == 0 else "partial_failure",
                proposal_count=worker_proposal_count,
                failure_count=worker_failure_count,
                runtime_mode_audit={
                    "mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                    "status": "ok",
                    "output_schema_enforced": False,
                    "tool_affordances_requested": True,
                },
                runner_result=worker_runner_payload,
                metadata={
                    "in_dir": _relative_path(run_root, in_dir),
                    "hints_dir": _relative_path(run_root, hints_dir),
                    "out_dir": _relative_path(run_root, out_dir),
                    "scratch_dir": _relative_path(run_root, scratch_dir),
                },
            ),
            proposals=tuple(worker_proposals),
            failures=tuple(worker_failures),
            stage_rows=tuple(stage_rows),
            worker_runner_payload=worker_runner_payload,
        )

    if task_status_tracker is not None:
        for shard in assigned_shards:
            task_status_tracker.start_attempt(
                task_id=shard.shard_id,
                worker_id=assignment.worker_id,
                attempt_type="main_worker",
                metadata={
                    "input_path": str(Path("in") / f"{shard.shard_id}.json"),
                    "hint_path": str(Path("hints") / f"{shard.shard_id}.md"),
                    "workspace_processing_contract": "knowledge_packet_lease_v1",
                },
            )

    worker_prompt_text = _build_knowledge_workspace_worker_prompt(shards=assigned_shards)
    worker_prompt_path = worker_root / "prompt.txt"
    worker_prompt_path.write_text(worker_prompt_text, encoding="utf-8")
    packet_lease_controller = _KnowledgePacketLeaseController(
        worker_root=worker_root,
        shard_states=shard_states,
        shard_order=tuple(str(shard.shard_id) for shard in assigned_shards),
    )
    run_result = runner.run_workspace_worker(
        prompt_text=worker_prompt_text,
        working_dir=worker_root,
        env=env,
        model=model,
        reasoning_effort=reasoning_effort,
        workspace_task_label="knowledge packet lease worker session",
        supervision_callback=_build_strict_json_watchdog_callback(
            live_status_path=worker_root / "live_status.json",
            allow_workspace_commands=True,
            execution_workspace_root=worker_root,
            expected_workspace_output_paths=[
                out_dir / f"{shard.shard_id}.json" for shard in assigned_shards
            ],
            task_queue_controller=packet_lease_controller,
            workspace_output_observer=(
                None
                if progress_state is None
                else lambda present_count, expected_count, _worker_id=assignment.worker_id: (
                    progress_state.observe_workspace_outputs(
                        worker_id=_worker_id,
                        present_count=present_count,
                        expected_count=expected_count,
                    )
                )
            ),
        ),
    )
    _finalize_live_status(
        worker_root / "live_status.json",
        run_result=run_result,
        watchdog_policy="workspace_worker_v1",
    )
    (worker_root / "events.jsonl").write_text(
        _render_events_jsonl(run_result.events),
        encoding="utf-8",
    )
    _write_json({"text": run_result.response_text}, worker_root / "last_message.json")
    _write_json(dict(run_result.usage or {}), worker_root / "usage.json")
    _write_json(run_result.workspace_manifest(), worker_root / "workspace_manifest.json")
    _write_optional_text(worker_root / "stdout.txt", run_result.stdout_text)
    _write_optional_text(worker_root / "stderr.txt", run_result.stderr_text)

    task_total = len(assigned_shards)
    for task_index, shard in enumerate(assigned_shards):
        response_path = out_dir / f"{shard.shard_id}.json"
        response_text = (
            response_path.read_text(encoding="utf-8")
            if response_path.exists()
            else None
        )
        shard_summary = packet_lease_controller.shard_summary(shard.shard_id)
        runner_payload = _build_knowledge_workspace_task_runner_payload(
            pipeline_id=pipeline_id,
            worker_id=assignment.worker_id,
            shard_id=shard.shard_id,
            runtime_task_id=shard.shard_id,
            run_result=run_result,
            model=model,
            reasoning_effort=reasoning_effort,
            request_input_file=in_dir / f"{shard.shard_id}.json",
            worker_prompt_path=worker_prompt_path,
            worker_root=worker_root,
            task_count=task_total,
            task_index=task_index,
        )
        runner_payload["packet_lease"] = dict(shard_summary)
        worker_runner_results.append(dict(runner_payload))
        runner_rows = (
            runner_payload.get("telemetry", {}).get("rows")
            if isinstance(runner_payload.get("telemetry"), Mapping)
            else None
        )
        if isinstance(runner_rows, list):
            for row_payload in runner_rows:
                if isinstance(row_payload, Mapping):
                    stage_row = dict(row_payload)
                    stage_row.update(
                        {
                            "workspace_packet_count": int(shard_summary.get("packet_count") or 0),
                            "workspace_repair_packet_count": int(
                                shard_summary.get("repair_packet_count") or 0
                            ),
                            "owned_row_count": int(
                                (shard.metadata or {}).get("owned_block_count") or 0
                            ),
                        }
                    )
                    stage_rows.append(stage_row)
        payload, validation_errors, validation_metadata, proposal_status = (
            _evaluate_knowledge_output_file(
                shard=shard,
                response_text=response_text,
            )
        )
        explicit_terminal_reason_code: str | None = None
        explicit_terminal_reason_detail: str | None = None
        explicit_terminal_reason_metadata: dict[str, Any] = {}
        if proposal_status == "no_final_output":
            (
                explicit_terminal_reason_code,
                explicit_terminal_reason_detail,
                explicit_terminal_reason_metadata,
            ) = _classify_missing_packet_result(
                worker_root=worker_root,
                shard=shard,
                run_result=run_result,
                shard_summary=shard_summary,
            )
        validation_metadata = {
            **dict(validation_metadata or {}),
            **dict(shard_summary),
            **dict(explicit_terminal_reason_metadata or {}),
        }
        if explicit_terminal_reason_code:
            validation_metadata["terminal_reason_code"] = explicit_terminal_reason_code
            validation_metadata["terminal_reason_detail"] = explicit_terminal_reason_detail
        proposal_path = run_root / artifacts["proposals_dir"] / f"{shard.shard_id}.json"
        _write_json(
            {
                "shard_id": shard.shard_id,
                "worker_id": assignment.worker_id,
                "payload": payload,
                "validation_errors": list(validation_errors),
                "validation_metadata": dict(validation_metadata or {}),
            },
            proposal_path,
        )
        worker_proposals.append(
            ShardProposalV1(
                shard_id=shard.shard_id,
                worker_id=assignment.worker_id,
                status=proposal_status,
                proposal_path=_relative_path(run_root, proposal_path),
                payload=payload,
                validation_errors=tuple(validation_errors),
                metadata=dict(validation_metadata or {}),
            )
        )
        worker_proposal_count += 1
        if proposal_status != "validated":
            worker_failure_count += 1
            worker_failures.append(
                {
                    "worker_id": assignment.worker_id,
                    "shard_id": shard.shard_id,
                    "reason": (
                        str(explicit_terminal_reason_code or "").strip()
                        or str(shard_summary.get("terminal_reason_code") or "").strip()
                        or _failure_reason_from_run_result(
                            run_result=run_result,
                            proposal_status=proposal_status,
                        )
                    ),
                    "validation_errors": list(validation_errors),
                    "state": run_result.supervision_state or "completed",
                    "reason_code": (
                        str(explicit_terminal_reason_code or "").strip()
                        or str(shard_summary.get("terminal_reason_code") or "").strip()
                        or run_result.supervision_reason_code
                    ),
                }
            )
        else:
            cohort_watchdog_state.record_validated_result(
                duration_ms=run_result.duration_ms,
                example_payload=_build_knowledge_watchdog_example(
                    shard=shard,
                    payload=payload,
                ),
            )
        if progress_state is not None:
            progress_state.mark_task_packet_terminal(
                worker_id=assignment.worker_id,
                task_id=shard.shard_id,
            )
        if task_status_tracker is not None:
            terminal_reason_code, terminal_reason_detail = _terminal_reason_for_knowledge_task(
                proposal_status=proposal_status,
                validation_errors=validation_errors,
                validation_metadata=validation_metadata,
                run_result=run_result,
                repair_skip_reason_code=(
                    str(explicit_terminal_reason_code or "").strip()
                    or str(shard_summary.get("terminal_reason_code") or "").strip()
                    or None
                ),
                repair_skip_reason_detail=(
                    str(explicit_terminal_reason_detail or "").strip()
                    or str(shard_summary.get("terminal_reason_detail") or "").strip()
                    or None
                ),
            )
            task_status_tracker.mark_terminal(
                task_id=shard.shard_id,
                worker_id=assignment.worker_id,
                terminal_state=_terminal_knowledge_task_state(
                    proposal_status=proposal_status,
                    supervision_state=run_result.supervision_state,
                    terminal_reason_code=terminal_reason_code,
                ),
                attempt_type="main_worker",
                proposal_status=proposal_status,
                validation_errors=validation_errors,
                metadata=dict(validation_metadata or {}),
                terminal_reason_code=terminal_reason_code,
                terminal_reason_detail=terminal_reason_detail,
            )
        if shard_completed_callback is not None:
            shard_completed_callback(worker_id=assignment.worker_id, shard_id=shard.shard_id)

    worker_runner_payload = _aggregate_worker_runner_payload(
        pipeline_id=pipeline_id,
        worker_runs=worker_runner_results,
        stage_rows=stage_rows,
    )
    _write_json(worker_runner_payload, worker_root / "status.json")
    return _DirectKnowledgeWorkerResult(
        report=WorkerExecutionReportV1(
            worker_id=assignment.worker_id,
            shard_ids=assignment.shard_ids,
            workspace_root=_relative_path(run_root, worker_root),
            status="ok" if worker_failure_count == 0 else "partial_failure",
            proposal_count=worker_proposal_count,
            failure_count=worker_failure_count,
            runtime_mode_audit={
                "mode": DIRECT_CODEX_EXEC_RUNTIME_MODE_V1,
                "status": "ok",
                "output_schema_enforced": False,
                "tool_affordances_requested": True,
            },
            runner_result=worker_runner_payload,
            metadata={
                "in_dir": _relative_path(run_root, in_dir),
                "hints_dir": _relative_path(run_root, hints_dir),
                "out_dir": _relative_path(run_root, out_dir),
                "scratch_dir": _relative_path(run_root, scratch_dir),
                "packet_history_path": _relative_path(
                    run_root,
                    worker_root / "packet_history.jsonl",
                ),
            },
        ),
        proposals=tuple(worker_proposals),
        failures=tuple(worker_failures),
        stage_rows=tuple(stage_rows),
        worker_runner_payload=worker_runner_payload,
    )
