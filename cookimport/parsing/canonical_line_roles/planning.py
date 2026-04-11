from __future__ import annotations

import hashlib
import json
import os
import cookimport.parsing.canonical_line_roles as runtime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from cookimport.config.prediction_identity import build_line_role_cache_identity_payload
from cookimport.config.run_settings import RunSettings, normalize_line_role_pipeline_value
from cookimport.llm.canonical_line_role_prompt import (
    build_canonical_line_role_file_prompt,
    build_line_role_shared_contract_block,
)
from cookimport.llm.codex_exec_runner import CodexExecRunResult
from cookimport.llm.phase_worker_runtime import (
    ShardManifestEntryV1,
    ShardProposalV1,
    WorkerExecutionReportV1,
    resolve_phase_worker_count,
)
from cookimport.llm.taskfile_prompt_contract import render_taskfile_prompt, section
from cookimport.llm.shard_prompt_targets import (
    partition_contiguous_items,
    resolve_shard_count,
)
from cookimport.llm.worker_hint_sidecars import write_worker_hint_markdown
from cookimport.parsing.line_role_workspace_tools import (
    build_line_role_workspace_shard_metadata,
)
from cookimport.parsing.recipe_block_atomizer import (
    AtomicLineCandidate,
    build_atomic_index_lookup,
    get_atomic_line_neighbor_texts,
)

from . import (
    _CODEX_EXECUTABLES,
    _LINE_ROLE_CACHE_ROOT_ENV,
    _LINE_ROLE_CACHE_SCHEMA_VERSION,
    _LINE_ROLE_CODEX_EXEC_DEFAULT_CMD,
    _LINE_ROLE_CODEX_FARM_PIPELINE_ID,
    _LINE_ROLE_CODEX_MAX_INFLIGHT_DEFAULT,
    _LINE_ROLE_CODEX_MAX_INFLIGHT_ENV,
)
from .contracts import CanonicalLineRolePrediction
from .policy import (
    build_line_role_debug_input_payload,
    build_line_role_model_input_payload,
)


def _runtime_attr(name: str, default: Any) -> Any:
    return getattr(runtime, name, default)


@dataclass(frozen=True)
class _LineRoleShardPlan:
    phase_key: str
    phase_label: str
    runtime_pipeline_id: str
    prompt_stem: str
    shard_id: str
    prompt_index: int
    candidates: tuple[AtomicLineCandidate, ...]
    baseline_predictions: tuple[CanonicalLineRolePrediction, ...]
    debug_input_payload: dict[str, Any]
    manifest_entry: ShardManifestEntryV1


@dataclass(frozen=True)
class _LineRolePhaseRuntimeResult:
    phase_key: str
    phase_label: str
    shard_plans: tuple[_LineRoleShardPlan, ...]
    worker_reports: tuple[WorkerExecutionReportV1, ...]
    runner_results_by_shard_id: dict[str, dict[str, Any]]
    response_payloads_by_shard_id: dict[str, dict[str, Any]]
    proposal_metadata_by_shard_id: dict[str, dict[str, Any]]
    invalid_shard_count: int
    missing_output_shard_count: int
    runtime_root: Path | None


@dataclass(frozen=True)
class _LineRoleRuntimeResult:
    predictions_by_atomic_index: dict[int, CanonicalLineRolePrediction]
    phase_results: tuple[_LineRolePhaseRuntimeResult, ...]


@dataclass(frozen=True)
class _DirectLineRoleWorkerResult:
    report: WorkerExecutionReportV1
    proposals: tuple[ShardProposalV1, ...]
    failures: tuple[dict[str, Any], ...]
    stage_rows: tuple[dict[str, Any], ...]
    task_status_rows: tuple[dict[str, Any], ...]
    runner_results_by_shard_id: dict[str, dict[str, Any]]


def _coerce_mapping_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _build_line_role_canonical_plans(
    *,
    ordered_candidates: Sequence[AtomicLineCandidate],
    deterministic_baseline: dict[int, CanonicalLineRolePrediction],
    settings: RunSettings,
    codex_batch_size: int,
) -> tuple[_LineRoleShardPlan, ...]:
    if not ordered_candidates:
        return ()
    requested_shard_count = _resolve_line_role_requested_shard_count(
        settings=settings,
        codex_batch_size=codex_batch_size,
        total_candidates=len(ordered_candidates),
    )
    by_atomic_index = build_atomic_index_lookup(ordered_candidates)
    plans: list[_LineRoleShardPlan] = []
    for prompt_index, shard_candidates in enumerate(
        partition_contiguous_items(
            ordered_candidates,
            shard_count=requested_shard_count,
        ),
        start=1,
    ):
        if not shard_candidates:
            continue
        baseline_batch = tuple(
            deterministic_baseline[int(candidate.atomic_index)]
            for candidate in shard_candidates
        )
        first_atomic_index = int(shard_candidates[0].atomic_index)
        last_atomic_index = int(shard_candidates[-1].atomic_index)
        shard_id = (
            f"line-role-canonical-{prompt_index:04d}-"
            f"a{first_atomic_index:06d}-a{last_atomic_index:06d}"
        )
        debug_input_payload = build_line_role_debug_input_payload(
            shard_id=shard_id,
            candidates=shard_candidates,
            deterministic_baseline=deterministic_baseline,
            by_atomic_index=by_atomic_index,
        )
        manifest_entry = ShardManifestEntryV1(
            shard_id=shard_id,
            owned_ids=tuple(
                str(int(candidate.atomic_index)) for candidate in shard_candidates
            ),
            evidence_refs=tuple(
                dict.fromkeys(str(candidate.block_id) for candidate in shard_candidates)
            ),
            input_payload=build_line_role_model_input_payload(
                shard_id=shard_id,
                candidates=shard_candidates,
                deterministic_baseline=deterministic_baseline,
                by_atomic_index=by_atomic_index,
            ),
            metadata={
                "phase_key": "line_role",
                "prompt_index": prompt_index,
                "prompt_stem": "line_role_prompt",
                "first_atomic_index": first_atomic_index,
                "last_atomic_index": last_atomic_index,
                "owned_row_count": len(shard_candidates),
            },
        )
        plans.append(
            _LineRoleShardPlan(
                phase_key="line_role",
                phase_label="Canonical Line Role",
                runtime_pipeline_id=_LINE_ROLE_CODEX_FARM_PIPELINE_ID,
                prompt_stem="line_role_prompt",
                shard_id=shard_id,
                prompt_index=prompt_index,
                candidates=tuple(shard_candidates),
                baseline_predictions=baseline_batch,
                debug_input_payload=debug_input_payload,
                manifest_entry=manifest_entry,
            )
        )
    return tuple(plans)


def _line_role_execution_plan_phase(
    shard_plans: Sequence[_LineRoleShardPlan],
) -> dict[str, Any]:
    if not shard_plans:
        return {
            "phase_key": None,
            "phase_label": None,
            "runtime_pipeline_id": None,
            "planned_shard_count": 0,
            "planned_candidate_count": 0,
            "shards": [],
        }
    return {
        "phase_key": shard_plans[0].phase_key,
        "phase_label": shard_plans[0].phase_label,
        "runtime_pipeline_id": shard_plans[0].runtime_pipeline_id,
        "planned_shard_count": len(shard_plans),
        "planned_candidate_count": sum(len(plan.candidates) for plan in shard_plans),
        "shards": [
            {
                "shard_id": plan.shard_id,
                "prompt_index": plan.prompt_index,
                "candidate_count": len(plan.candidates),
                "atomic_indices": [int(candidate.atomic_index) for candidate in plan.candidates],
                "owned_ids": list(plan.manifest_entry.owned_ids),
                "rows": list(plan.debug_input_payload.get("rows") or []),
            }
            for plan in shard_plans
        ],
    }


def _resolve_line_role_requested_shard_count(
    *,
    settings: RunSettings,
    codex_batch_size: int,
    total_candidates: int | None = None,
) -> int:
    if total_candidates is not None and total_candidates > 0:
        return resolve_shard_count(
            total_items=total_candidates,
            prompt_target_count=getattr(settings, "line_role_prompt_target_count", None),
            items_per_shard=getattr(settings, "line_role_shard_target_lines", None),
            default_items_per_shard=codex_batch_size,
        )
    configured = getattr(settings, "line_role_shard_target_lines", None)
    resolved = getattr(configured, "value", configured)
    if resolved is not None:
        try:
            return 1
        except (TypeError, ValueError):
            pass
    prompt_target = getattr(settings, "line_role_prompt_target_count", None)
    resolved_prompt_target = getattr(prompt_target, "value", prompt_target)
    if resolved_prompt_target is not None:
        try:
            return max(1, int(resolved_prompt_target))
        except (TypeError, ValueError):
            pass
    return 1


def _resolve_line_role_worker_count(
    *,
    settings: RunSettings,
    codex_max_inflight: int | None,
    shard_count: int,
) -> int:
    if codex_max_inflight is not None:
        return resolve_phase_worker_count(
            requested_worker_count=_normalize_line_role_codex_max_inflight_value(
                codex_max_inflight
            ),
            shard_count=shard_count,
        )
    configured = getattr(settings, "line_role_worker_count", None)
    resolved = getattr(configured, "value", configured)
    if resolved is not None:
        try:
            return resolve_phase_worker_count(
                requested_worker_count=max(1, min(int(resolved), 256)),
                shard_count=shard_count,
            )
        except (TypeError, ValueError):
            pass
    raw_env = str(os.getenv(_LINE_ROLE_CODEX_MAX_INFLIGHT_ENV) or "").strip()
    if raw_env:
        return resolve_phase_worker_count(
            requested_worker_count=_normalize_line_role_codex_max_inflight_value(raw_env),
            shard_count=shard_count,
        )
    return resolve_phase_worker_count(
        requested_worker_count=None,
        shard_count=shard_count,
    )

def _render_line_role_authoritative_rows(shard: ShardManifestEntryV1) -> str:
    rows = list((_coerce_mapping_dict(shard.input_payload)).get("rows") or [])
    rendered_rows: list[str] = []
    for index, row in enumerate(rows):
        if isinstance(row, (list, tuple)):
            block_index = int(row[1]) if len(row) >= 3 else int(row[0])
            text = str((row[2] if len(row) >= 3 else row[1]) or "")
            rendered_rows.append(
                json.dumps(f"r{index + 1:02d} | {block_index} | {text}", ensure_ascii=False)
            )
        elif isinstance(row, Mapping):
            row_dict = dict(row)
            block_index = int(
                row_dict.get("block_index")
                or row_dict.get("source_block_index")
                or row_dict.get("atomic_index")
                or index
            )
            text = str(
                row_dict.get("current_line")
                or row_dict.get("text")
                or ""
            )
            rendered_rows.append(
                json.dumps(f"r{index + 1:02d} | {block_index} | {text}", ensure_ascii=False)
            )
    return "\n".join(rendered_rows) if rendered_rows else "[no shard rows available]"


def _build_line_role_worker_shard_row(
    *,
    shard: ShardManifestEntryV1,
) -> dict[str, Any]:
    metadata = build_line_role_workspace_shard_metadata(
        shard_id=shard.shard_id,
        input_payload=_coerce_mapping_dict(shard.input_payload),
        input_path=f"in/{shard.shard_id}.json",
        hint_path=f"hints/{shard.shard_id}.md",
        result_path=f"out/{shard.shard_id}.json",
    )
    return {
        "shard_id": shard.shard_id,
        "owned_ids": [str(value).strip() for value in shard.owned_ids if str(value).strip()],
        "metadata": {
            **_coerce_mapping_dict(shard.metadata),
            **metadata,
        },
    }

def _build_line_role_canonical_line_table_rows(
    *,
    debug_payload_by_shard_id: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows_by_atomic_index: dict[int, dict[str, Any]] = {}
    for shard_id, debug_payload in debug_payload_by_shard_id.items():
        payload_rows = list(_coerce_mapping_dict(debug_payload).get("rows") or [])
        for row in payload_rows:
            if not isinstance(row, Mapping):
                continue
            try:
                atomic_index = int(row.get("atomic_index"))
            except (TypeError, ValueError):
                continue
            rows_by_atomic_index[atomic_index] = {
                "line_id": str(atomic_index),
                "atomic_index": atomic_index,
                "block_id": str(row.get("block_id") or ""),
                "block_index": int(row.get("block_index") or 0),
                "recipe_id": row.get("recipe_id"),
                "within_recipe_span": row.get("within_recipe_span"),
                "current_line": str(row.get("current_line") or ""),
                "rule_tags": [
                    str(tag).strip()
                    for tag in row.get("rule_tags") or []
                    if str(tag).strip()
                ],
                "escalation_reasons": [
                    str(reason).strip()
                    for reason in row.get("escalation_reasons") or []
                    if str(reason).strip()
                ],
                "source_shard_id": str(shard_id),
            }
    return [rows_by_atomic_index[key] for key in sorted(rows_by_atomic_index)]


def _find_line_role_existing_output_path(
    *,
    run_root: Path,
    preferred_worker_root: Path,
    shard_id: str,
) -> Path | None:
    candidate_paths: list[Path] = []
    preferred_path = preferred_worker_root / "out" / f"{shard_id}.json"
    if preferred_path.exists():
        candidate_paths.append(preferred_path)
    candidate_paths.extend(
        path
        for path in sorted(run_root.glob(f"workers/*/out/{shard_id}.json"))
        if path != preferred_path
    )
    for path in candidate_paths:
        if path.exists():
            return path
    return None

def _looks_like_codex_exec_command(command_text: str) -> bool:
    tokens = str(command_text or "").strip().split()
    if not tokens:
        return False
    executable = Path(tokens[0]).name.lower()
    return executable in _CODEX_EXECUTABLES


def _resolve_line_role_codex_exec_cmd(
    *,
    settings: RunSettings,
    codex_cmd_override: str | None,
) -> str:
    override = str(codex_cmd_override or "").strip()
    if override:
        return override
    configured = str(getattr(settings, "codex_farm_cmd", "") or "").strip()
    if configured and _looks_like_codex_exec_command(configured):
        return configured
    if configured and Path(configured).name == "fake-codex-farm.py":
        return configured
    return _LINE_ROLE_CODEX_EXEC_DEFAULT_CMD


def _resolve_line_role_codex_farm_root(*, settings: RunSettings) -> Path:
    configured = str(getattr(settings, "codex_farm_root", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[3] / "llm_pipelines"


def _resolve_line_role_codex_farm_workspace_root(
    *,
    settings: RunSettings,
) -> Path | None:
    configured = str(getattr(settings, "codex_farm_workspace_root", "") or "").strip()
    if not configured:
        return None
    return Path(configured).expanduser()


def _resolve_line_role_codex_farm_model(*, settings: RunSettings) -> str | None:
    configured = str(getattr(settings, "codex_farm_model", "") or "").strip()
    return configured or None


def _resolve_line_role_codex_farm_reasoning_effort(
    *,
    settings: RunSettings,
) -> str | None:
    raw_value = getattr(settings, "codex_farm_reasoning_effort", None)
    if raw_value is None:
        return None
    resolved = getattr(raw_value, "value", raw_value)
    cleaned = str(resolved or "").strip()
    return cleaned or None

def _build_line_role_runner_payload(
    *,
    pipeline_id: str,
    worker_id: str,
    shard_id: str,
    run_result: CodexExecRunResult,
    model: str | None,
    reasoning_effort: str | None,
    request_input_file: Path | None,
    debug_input_file: Path | None,
) -> dict[str, Any]:
    payload = run_result.to_payload(worker_id=worker_id, shard_id=shard_id)
    payload["pipeline_id"] = pipeline_id
    request_input_file_str = (
        str(request_input_file)
        if request_input_file is not None
        else None
    )
    request_input_file_bytes = (
        request_input_file.stat().st_size
        if request_input_file is not None and request_input_file.exists()
        else None
    )
    debug_input_file_str = (
        str(debug_input_file)
        if debug_input_file is not None
        else None
    )
    telemetry = payload.get("telemetry")
    row_payloads = telemetry.get("rows") if isinstance(telemetry, dict) else None
    if isinstance(row_payloads, list):
        for row_payload in row_payloads:
            if not isinstance(row_payload, dict):
                continue
            row_payload["prompt_input_mode"] = "inline"
            row_payload["request_input_file"] = request_input_file_str
            row_payload["request_input_file_bytes"] = request_input_file_bytes
            row_payload["debug_input_file"] = debug_input_file_str
    summary_payload = telemetry.get("summary") if isinstance(telemetry, dict) else None
    if isinstance(summary_payload, dict):
        summary_payload["prompt_input_mode"] = "inline"
        summary_payload["request_input_file_bytes_total"] = request_input_file_bytes
    payload["process_payload"] = {
        "pipeline_id": pipeline_id,
        "status": "done" if run_result.subprocess_exit_code == 0 else "failed",
        "codex_model": model,
        "codex_reasoning_effort": reasoning_effort,
        "prompt_input_mode": "inline",
        "request_input_file": request_input_file_str,
        "request_input_file_bytes": request_input_file_bytes,
        "debug_input_file": debug_input_file_str,
    }
    return payload


def _build_line_role_file_prompt_for_shard(
    *,
    input_path: Path,
    input_payload: Mapping[str, Any] | None,
) -> str:
    return build_canonical_line_role_file_prompt(
        input_path=input_path,
        input_payload=input_payload,
    )


def _build_line_role_taskfile_prompt(
    *,
    shards: Sequence[ShardManifestEntryV1],
    fresh_session_resume: bool = False,
) -> str:
    assignments = "\n".join(
        f"- `{shard.shard_id}`"
        for shard in shards
    )
    start_instruction = (
        "- Resume from the existing `task.json` and current workspace state.\n"
        if fresh_session_resume
        else "- Open `task.json` directly, read the full shard in order, fill every `answer.label`, save the same file, and run `task-handoff`.\n"
    )
    shared_contract = build_line_role_shared_contract_block()
    return render_taskfile_prompt(
        section(
            "You are processing canonical line-role shards inside one local worker workspace. Each shard owns one ordered row ledger.",
        ),
        section(
            "- The current working directory is already the workspace root.",
            start_instruction.strip(),
            "- `task.json` already contains the full assignment. You do not need extra control state, helper ledgers, or hidden context before editing it.",
            "- This is an execution task, not a planning or status-report task.",
            "- Do not invent phase ledgers, install loops, queue-control files, or alternate output files.",
            "- Title, variant, yield, and section calls are sequence-sensitive. For ambiguous lines, read the nearby rows directly in the ordered `task.json` ledger before labeling.",
            "- If you need orientation first, run `task-status`.",
            "- If the workspace feels inconsistent, run `task-doctor` before inventing shell scripts.",
            "- If a narrow local ambiguity remains after reading the file directly, `task-show-unit <unit_id>` and `task-show-unanswered --limit 5` exist as fallback-only helpers.",
            "- Ordinary local reads of `task.json` and `AGENTS.md` are allowed. Do not turn them into shell schedulers or scripted rewrites.",
            "- After each edit pass, run `task-handoff` from the workspace root.",
            "- If the helper reports `repair_required`, reopen the rewritten `task.json` immediately, fix only the named issues, and run the helper again.",
            "- Do not stop to summarize partial progress, list next steps, mention time limits, or say that you have not run `task-handoff` yet.",
            "- Do not emit todo lists, progress recaps, or “keep going from here” messages. Continue the assignment instead.",
            "- Stop only after the helper reports `completed`.",
            "- If you briefly reread part of the file or make a small local false start, correct it and continue.",
            "- Stay inside this workspace: do not inspect parent directories or the repository, keep every visible path local, and do not use repo/network/package-manager commands such as `git`, `curl`, or `npm`.",
            "- The task file already contains the immutable row evidence and the editable answer slots.",
            "- Do not modify immutable evidence fields.",
            heading="Worker contract",
        ),
        section(
            "- Set `answer.label` for every unit.",
            heading="Task-file answer rules",
        ),
        section(*shared_contract.splitlines(), heading="Shared labeling contract"),
        section(
            "Do not return row labels in your final message. The authoritative result is the edited `task.json` file.",
        ),
        section(assignments, heading="Assigned shard ids represented in this task file"),
    )

def _write_line_role_worker_hint(
    *,
    path: Path,
    shard: ShardManifestEntryV1,
    debug_payload: Any,
) -> None:
    input_rows = list(_coerce_mapping_dict(shard.input_payload).get("rows") or [])
    debug_rows = list(_coerce_mapping_dict(debug_payload).get("rows") or [])
    owned_row_count = 0
    for row in debug_rows:
        if not isinstance(row, Mapping):
            continue
        owned_row_count += 1

    write_worker_hint_markdown(
        path,
        title=f"Canonical line-role hints for {shard.shard_id}",
        summary_lines=[
            "This sidecar is worker guidance only.",
            "Open the authoritative `in/<shard_id>.json` file and label the owned rows directly from the text.",
            "Use nearby rows only as boundary context; they are reference-only and never belong in output JSON.",
        ],
        sections=[
            (
                "Worker flow",
                [
                    "Read the shard in order.",
                    "Label every owned row once.",
                    "Edit only the required answer surface for this workspace.",
                    "Finish with the normal handoff command for this workspace.",
                ],
            ),
        ],
    )


def _distribute_line_role_session_value(
    total: int | None, parts: int
) -> list[int | None]:
    normalized_parts = max(1, int(parts))
    if total is None:
        return [None for _ in range(normalized_parts)]
    normalized_total = max(0, int(total))
    base, remainder = divmod(normalized_total, normalized_parts)
    return [base + (1 if index < remainder else 0) for index in range(normalized_parts)]

def _resolve_line_role_codex_max_inflight() -> int:
    raw_value = str(os.getenv(_LINE_ROLE_CODEX_MAX_INFLIGHT_ENV) or "").strip()
    if not raw_value:
        return _LINE_ROLE_CODEX_MAX_INFLIGHT_DEFAULT
    return _normalize_line_role_codex_max_inflight_value(raw_value)


def _normalize_line_role_codex_max_inflight_value(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return _LINE_ROLE_CODEX_MAX_INFLIGHT_DEFAULT
    return max(1, min(parsed, 32))


def _resolve_line_role_cache_path(
    *,
    source_hash: str | None,
    settings: RunSettings,
    ordered_candidates: Sequence[AtomicLineCandidate],
    artifact_root: Path | None,
    cache_root: Path | None,
    codex_timeout_seconds: int,
    codex_batch_size: int,
) -> Path | None:
    normalized_source_hash = str(source_hash or "").strip()
    if not normalized_source_hash:
        return None
    resolved_root = _resolve_line_role_cache_root(
        artifact_root=artifact_root,
        cache_root=cache_root,
    )
    if resolved_root is None:
        return None
    candidate_fingerprint = _canonical_candidate_fingerprint(ordered_candidates)
    key_payload = {
        "schema_version": _LINE_ROLE_CACHE_SCHEMA_VERSION,
        "source_hash": normalized_source_hash,
        "line_role_identity": build_line_role_cache_identity_payload(settings),
        "candidate_fingerprint": candidate_fingerprint,
        "codex_timeout_seconds": int(codex_timeout_seconds),
        "codex_batch_size": int(codex_batch_size),
    }
    digest = hashlib.sha256(
        json.dumps(
            key_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    return resolved_root / digest[:2] / f"{digest}.json"


def _resolve_line_role_cache_root(
    *,
    artifact_root: Path | None,
    cache_root: Path | None,
) -> Path | None:
    if cache_root is not None:
        return cache_root.expanduser()
    override = str(os.getenv(_LINE_ROLE_CACHE_ROOT_ENV) or "").strip()
    if override:
        return Path(override).expanduser()
    if artifact_root is None:
        return None
    resolved_artifact_root = artifact_root.expanduser().resolve()
    for parent in (resolved_artifact_root, *resolved_artifact_root.parents):
        if parent.name in {"benchmark-vs-golden", "sent-to-labelstudio"}:
            return parent / ".cache" / "canonical_line_role"
    return resolved_artifact_root / ".cache" / "canonical_line_role"


def _canonical_candidate_fingerprint(
    candidates: Sequence[AtomicLineCandidate],
) -> str:
    sanitized_candidates = runtime.sanitize_pre_grouping_line_role_candidates(candidates)
    by_atomic_index = build_atomic_index_lookup(sanitized_candidates)
    payload: list[dict[str, Any]] = []
    for candidate in sanitized_candidates:
        prev_text, next_text = get_atomic_line_neighbor_texts(
            candidate,
            by_atomic_index=by_atomic_index,
        )
        payload.append(
            {
                "block_id": candidate.block_id,
                "block_index": candidate.block_index,
                "atomic_index": candidate.atomic_index,
                "text": candidate.text,
                "prev_text": prev_text,
                "next_text": next_text,
                "rule_tags": list(candidate.rule_tags),
            }
        )
    canonical_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _load_cached_predictions(
    *,
    cache_path: Path,
    expected_candidates: Sequence[AtomicLineCandidate],
) -> tuple[list[CanonicalLineRolePrediction], list[CanonicalLineRolePrediction]] | None:
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != _LINE_ROLE_CACHE_SCHEMA_VERSION:
        return None
    raw_predictions = payload.get("predictions")
    if not isinstance(raw_predictions, list):
        return None
    raw_baseline_predictions = payload.get("baseline_predictions")
    if raw_baseline_predictions is None:
        raw_baseline_predictions = raw_predictions
    if not isinstance(raw_baseline_predictions, list):
        return None
    predictions: list[CanonicalLineRolePrediction] = []
    baseline_predictions: list[CanonicalLineRolePrediction] = []
    try:
        for row in raw_predictions:
            predictions.append(CanonicalLineRolePrediction.model_validate(row))
        for row in raw_baseline_predictions:
            baseline_predictions.append(CanonicalLineRolePrediction.model_validate(row))
    except Exception:
        return None
    if (
        len(predictions) != len(expected_candidates)
        or len(baseline_predictions) != len(expected_candidates)
    ):
        return None
    for candidate, prediction in zip(expected_candidates, predictions):
        if int(candidate.atomic_index) != int(prediction.atomic_index):
            return None
        if str(candidate.text) != str(prediction.text):
            return None
    return predictions, baseline_predictions


def _write_cached_predictions(
    *,
    cache_path: Path | None,
    predictions: Sequence[CanonicalLineRolePrediction],
    baseline_predictions: Sequence[CanonicalLineRolePrediction],
) -> None:
    if cache_path is None:
        return
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": _LINE_ROLE_CACHE_SCHEMA_VERSION,
            "predictions": [row.model_dump(mode="json") for row in predictions],
            "baseline_predictions": [
                row.model_dump(mode="json") for row in baseline_predictions
            ],
        }
        tmp_path = cache_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(cache_path)
    except OSError:
        return


def _line_role_pipeline_name(settings: RunSettings) -> str:
    value = getattr(settings, "line_role_pipeline", "off")
    return normalize_line_role_pipeline_value(value)
