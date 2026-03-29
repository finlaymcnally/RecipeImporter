from __future__ import annotations

import sys

runtime = sys.modules["cookimport.parsing.canonical_line_roles"]
globals().update(
    {
        name: value
        for name, value in vars(runtime).items()
        if not name.startswith("__")
    }
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


def _build_line_role_book_context(
    *,
    candidates: Sequence[AtomicLineCandidate],
) -> dict[str, Any]:
    by_atomic_index = {
        int(candidate.atomic_index): candidate for candidate in candidates
    }
    evidence_count = sum(
        1
        for candidate in candidates
        if _has_recipe_local_howto_support(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    )
    if evidence_count >= 3:
        availability = "available"
        policy = (
            "`HOWTO_SECTION` is available in this book, but it remains a high-evidence label tied to local recipe structure."
        )
    elif evidence_count >= 1:
        availability = "sparse"
        policy = (
            "`HOWTO_SECTION` appears sparse in this book. Prefer non-structural labels unless the local heading clearly splits one recipe into components or step families."
        )
    else:
        availability = "absent_or_unproven"
        policy = (
            "This book may legitimately use zero `HOWTO_SECTION` labels. Treat the label as optional and require strong local recipe evidence before using it."
        )
    return {
        "howto_section_availability": availability,
        "howto_section_evidence_count": evidence_count,
        "howto_section_policy": policy,
    }


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
    book_context = _build_line_role_book_context(candidates=ordered_candidates)
    prompt_format = _resolve_line_role_prompt_format()
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
            book_context=book_context,
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
                debug_rows=list(debug_input_payload.get("rows") or []),
                by_atomic_index=by_atomic_index,
                book_context=book_context,
            ),
            metadata={
                "phase_key": "line_role",
                "prompt_index": prompt_index,
                "prompt_stem": "line_role_prompt",
                "first_atomic_index": first_atomic_index,
                "last_atomic_index": last_atomic_index,
                "owned_row_count": len(shard_candidates),
                "prompt_format": prompt_format,
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
    for row in rows:
        if isinstance(row, (list, tuple)):
            rendered_rows.append(json.dumps(list(row), ensure_ascii=False))
        elif isinstance(row, Mapping):
            rendered_rows.append(
                json.dumps(dict(row), ensure_ascii=False, sort_keys=True)
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
        work_path=f"work/{shard.shard_id}.json",
        result_path=f"out/{shard.shard_id}.json",
        repair_path=f"repair/{shard.shard_id}.json",
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
                "deterministic_label": str(row.get("deterministic_label") or "OTHER").strip()
                or "OTHER",
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

def _resolve_line_role_prompt_format() -> LineRolePromptFormat:
    return "compact_v1"


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


def _build_line_role_workspace_worker_prompt(
    *,
    shards: Sequence[ShardManifestEntryV1],
) -> str:
    assignments = "\n".join(
        f"- `{shard.shard_id}`: read `hints/{shard.shard_id}.md`, edit `work/{shard.shard_id}.json`, validate with `check-phase`, then install to `out/{shard.shard_id}.json`"
        for shard in shards
    )
    return (
        "You are processing canonical line-role shards inside one local worker workspace. Each shard owns one ordered row ledger.\n\n"
        "Worker contract:\n"
        "- The current working directory is already the workspace root.\n"
        "- Start by opening `worker_manifest.json`, then `CURRENT_PHASE.md`, then `OUTPUT_CONTRACT.md`. Open `current_phase.json` when you need the exact metadata fields or file paths.\n"
        "- The normal path is repo-written already: open the current work ledger named in `current_phase.json`, then `hints/<shard_id>.md`; open `in/<shard_id>.json` only when the work ledger or hint is insufficient.\n"
        "- Run `python3 tools/line_role_worker.py check-phase` after editing the work ledger. If `CURRENT_PHASE_FEEDBACK.md` names a repair file, fix only those unresolved rows in the existing work ledger.\n"
        "- Run `python3 tools/line_role_worker.py install-phase` only after the current work ledger validates cleanly. Installing advances the phase surface to the next shard when one remains.\n"
        "- There is no separate repo-owned repair model pass for line-role. The active workspace ledger is the authoritative fix loop.\n"
        "- Accepted rows are meant to stay frozen. Do not reopen already-installed shard ledgers just to hunt for novelty.\n"
        "- After the last shard is installed, send one brief completion message naming the finished outputs and then stop.\n"
        "- If `tools/line_role_worker.py` exists, use it as the paved road before inventing ad hoc shell helpers.\n"
        "- `python3 tools/line_role_worker.py overview`, `show <shard_id>`, and `scaffold <shard_id> --dest <path>` are fallback/debug tools, not the default starting path.\n"
        "- Long handwritten `jq` transforms are unnecessary here because the helper can already expand the deterministic label codes into the correct output shape.\n"
        "- Prefer opening the named files directly. If you still need shell helpers, keep them narrow and grounded on the named local files only.\n"
        "- Stay inside this workspace: do not inspect parent directories or the repository, keep every visible path local, and do not use repo/network/package-manager commands such as `git`, `curl`, or `npm`.\n"
        "- Treat `CURRENT_PHASE.md` as the cheapest repo-written first read. Use `current_phase.json` only for the exact metadata and named file paths.\n"
        "- Use `assigned_shards.json` only for ordered ownership/progress context.\n"
        "- For each assigned shard, start from the prewritten work ledger and hint before reopening the raw input ledger.\n"
        "- Treat `hints/<shard_id>.md` as guidance and `in/<shard_id>.json` as the authoritative shard input for the active phase.\n"
        "- Treat each shard ledger's deterministic label code as a weak hint only. Recompute from the shard rows, hint, and local context; do not preserve or prefer a label just because it came from the deterministic seed.\n"
        "- If `OUTPUT_CONTRACT.md` or `examples/` exists, use those repo-written files as the authoritative output-shape reference.\n"
        "- If `examples/*.md` exists, use those contrast examples for calibration only; do not copy them into outputs.\n"
        "- Write and revise the active shard only in `work/<shard_id>.json`. The helper installs the validated ledger to `out/<shard_id>.json`.\n"
        "- If `out/<shard_id>.json` already exists and is complete, leave it alone and continue.\n"
        "- Do not modify files under `in/`, `debug/`, or `hints/`.\n"
        "- Stay inside this workspace; do not inspect parent directories or the repository.\n"
        "- Keep working through the assigned shard files until all of them are handled or you truly cannot proceed.\n\n"
        "Each shard input file has this shape:\n"
        '{"v":1,"shard_id":"line-role-canonical-0001-a000123-a000456","rows":[[123,"L4","1 cup flour"],[124,"L2","Stir well."]]}\n\n'
        "Each work/install ledger must have this shape:\n"
        '{"rows":[{"atomic_index":123,"label":"INGREDIENT_LINE"}]}\n\n'
        "Rules:\n"
        "- Use only the keys `rows`, `atomic_index`, `label`, and optional `review_exclusion_reason` in each ledger.\n"
        "- Return one result for every owned input row in `rows`, in the same order.\n"
        "- Convert `label_code` into the correct full label string. The seeded work ledger already does this deterministically.\n"
        "- `INGREDIENT_LINE`: quantity/unit ingredients and bare ingredient items in ingredient lists.\n"
        "- `INSTRUCTION_LINE`: recipe-local imperative action sentences, even when they include time.\n"
        "- `TIME_LINE`: stand-alone timing or temperature lines, not full instruction sentences.\n"
        "- `HOWTO_SECTION`: recipe-internal subsection headings such as `FOR THE SAUCE`, `TO FINISH`, or `FOR SERVING`.\n"
        "- `HOWTO_SECTION` is book-optional: some books legitimately use zero of them, so emit it only with immediate recipe-local support.\n"
        "- `RECIPE_VARIANT`: alternate recipe names or variant headers inside a recipe.\n"
        "- `KNOWLEDGE`: keep this for recipe-local explanatory/reference prose only; outside recipes, useful prose should stay `OTHER` for the later knowledge stage.\n"
        "- `OTHER`: navigation, memoir, marketing, dedications, table of contents, or decorative matter.\n"
        "- Never label a quantity ingredient line as `KNOWLEDGE`.\n"
        "- Never label an imperative recipe step as `KNOWLEDGE`.\n"
        "- Do not use `INSTRUCTION_LINE` for generic culinary advice or cookbook teaching prose.\n"
        "- Generic cooking advice that spans many dishes belongs in review-eligible `OTHER` here, not `INSTRUCTION_LINE`.\n"
        "- Do not use `HOWTO_SECTION` for chapter, topic, or cookbook-lesson headings such as `Salt and Pepper`, `Cooking Acids`, or `Starches`.\n"
        "- A heading by itself is weak evidence. Keep topic headings such as `Balancing Fat` or `WHAT IS ACID?` as review-eligible `OTHER` unless nearby rows prove recipe-local structure.\n"
        "- First-person narrative or memoir prose is usually `OTHER`, not recipe structure.\n\n"
        "Do not return row labels in your final message. The authoritative results are the installed `out/<shard_id>.json` files.\n\n"
        "Assigned shard files:\n"
        f"{assignments}\n"
    )


def _write_line_role_worker_examples(*, worker_root: Path) -> list[str]:
    examples_dir = worker_root / "examples"
    examples_dir.mkdir(parents=True, exist_ok=True)
    written_files: list[str] = []
    for filename, content in (
        *_LINE_ROLE_PACKET_EXAMPLE_FILES,
        *_LINE_ROLE_OUTPUT_EXAMPLE_FILES,
    ):
        (examples_dir / filename).write_text(content, encoding="utf-8")
        written_files.append(filename)
    return written_files


def _write_line_role_output_contract(*, worker_root: Path) -> None:
    (worker_root / "OUTPUT_CONTRACT.md").write_text(
        LINE_ROLE_OUTPUT_CONTRACT_MARKDOWN,
        encoding="utf-8",
    )


def _write_line_role_worker_tools(*, worker_root: Path) -> list[str]:
    tools_dir = worker_root / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    tool_path = tools_dir / LINE_ROLE_WORKER_TOOL_FILENAME
    tool_path.write_text(render_line_role_worker_script(), encoding="utf-8")
    return [LINE_ROLE_WORKER_TOOL_FILENAME]


def _write_line_role_worker_hint(
    *,
    path: Path,
    shard: ShardManifestEntryV1,
    debug_payload: Any,
) -> None:
    input_rows = list(_coerce_mapping_dict(shard.input_payload).get("rows") or [])
    debug_rows = list(_coerce_mapping_dict(debug_payload).get("rows") or [])
    input_row_by_atomic_index: dict[int, tuple[str, str, str]] = {}
    ordered_atomic_indices: list[int] = []
    code_by_label = build_line_role_label_code_by_label()
    label_by_code = {str(code): str(label) for label, code in code_by_label.items()}
    for row in input_rows:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        try:
            atomic_index = int(row[0])
        except (TypeError, ValueError):
            continue
        input_row_by_atomic_index[atomic_index] = (
            atomic_index,
            str(row[1]),
            str(row[2]),
        )
        ordered_atomic_indices.append(atomic_index)
    order_lookup = {atomic_index: idx for idx, atomic_index in enumerate(ordered_atomic_indices)}

    label_counts: dict[str, int] = {}
    flagged_count = 0
    span_inside = 0
    span_outside = 0
    span_unknown = 0
    attention_lines: list[str] = []
    shard_context = _build_line_role_shard_context(rows=debug_rows)
    for row in debug_rows:
        if not isinstance(row, Mapping):
            continue
        try:
            atomic_index = int(row.get("atomic_index"))
        except (TypeError, ValueError):
            continue
        deterministic_label = str(row.get("deterministic_label") or "OTHER").strip() or "OTHER"
        label_counts[deterministic_label] = label_counts.get(deterministic_label, 0) + 1
        within_recipe_span = row.get("within_recipe_span")
        if within_recipe_span is True:
            span_inside += 1
        elif within_recipe_span is False:
            span_outside += 1
        else:
            span_unknown += 1
        rule_tags = [
            str(tag).strip()
            for tag in row.get("rule_tags") or []
            if str(tag).strip()
        ]
        escalation_reasons = [
            str(reason).strip()
            for reason in row.get("escalation_reasons") or []
            if str(reason).strip()
        ]
        if escalation_reasons or rule_tags:
            flagged_count += 1
        if len(attention_lines) >= 12 or (not escalation_reasons and not rule_tags):
            continue
        current_line = str(row.get("current_line") or "").strip()
        input_code = input_row_by_atomic_index.get(atomic_index, ("", "", ""))[1]
        row_index = order_lookup.get(atomic_index)
        prev_line = "[start]"
        next_line = "[end]"
        if row_index is not None:
            if row_index > 0:
                prev_atomic_index = ordered_atomic_indices[row_index - 1]
                prev_line = input_row_by_atomic_index.get(prev_atomic_index, ("", "", ""))[2]
            if row_index < (len(ordered_atomic_indices) - 1):
                next_atomic_index = ordered_atomic_indices[row_index + 1]
                next_line = input_row_by_atomic_index.get(next_atomic_index, ("", "", ""))[2]
        attention_lines.append(
            f"`{atomic_index}` `{preview_text(current_line, max_chars=90)}` -> deterministic `{deterministic_label}`, input code `{input_code}` ({label_by_code.get(input_code, 'unknown')}), tags `{', '.join(rule_tags) or 'none'}`, escalation `{', '.join(escalation_reasons) or 'none'}`, prev `{preview_text(prev_line, max_chars=60)}`, next `{preview_text(next_line, max_chars=60)}`"
        )

    shard_profile = [
        f"Owned rows: {len(input_row_by_atomic_index)}.",
        f"Deterministic label mix: {', '.join(f'{label}={count}' for label, count in sorted(label_counts.items())) or 'none'}.",
        f"Rows with rule tags or escalation reasons: {flagged_count}.",
        f"Recipe-span status mix: inside={span_inside}, outside={span_outside}, unknown={span_unknown}.",
        "Use this file to decode compact rows quickly, then rely on `in/<shard_id>.json` for the full owned row list.",
    ]
    legend_lines = [
        f"`{code}` = `{label}`"
        for label, code in sorted(code_by_label.items(), key=lambda item: item[1])
    ]
    shard_interpretation = [
        str(shard_context.get("shard_summary") or "No shard summary available."),
        (
            "Confidence: "
            f"{str(shard_context.get('context_confidence') or 'low')}. "
            f"Shard mode: {str(shard_context.get('shard_mode') or 'mixed_boundaries')}."
        ),
        str(shard_context.get("default_posture") or "Make conservative shard-local corrections."),
    ]
    decision_policy = list(shard_context.get("flip_policy") or [])
    decision_policy.extend(
        f"Strong signal: {value}"
        for value in list(shard_context.get("strong_signals") or [])
    )
    decision_policy.extend(
        f"Weak signal: {value}"
        for value in list(shard_context.get("weak_signals") or [])
    )
    shard_examples = [
        f"`examples/{filename}`"
        for filename in list(shard_context.get("example_files") or [])
    ] or ["Worker-local examples are not available for this shard."]
    if not attention_lines:
        attention_lines = [
            "No special attention rows were flagged. Read the authoritative rows in order and use nearby neighbors for disambiguation."
        ]
    write_worker_hint_markdown(
        path,
        title=f"Canonical line-role hints for {shard.shard_id}",
        summary_lines=[
            "This sidecar is worker guidance only.",
            "Open this file first, then open the authoritative `in/<shard_id>.json` file.",
            "Use nearby rows to disambiguate front matter, lesson prose, headings, and recipe-local structure.",
        ],
        sections=[
            ("Shard profile", shard_profile),
            ("Shard interpretation", shard_interpretation),
            ("Decision policy", decision_policy),
            ("Shard examples", shard_examples),
            ("Label code legend", legend_lines),
            ("Attention rows", attention_lines),
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
    by_atomic_index = build_atomic_index_lookup(candidates)
    payload: list[dict[str, Any]] = []
    for candidate in candidates:
        prev_text, next_text = get_atomic_line_neighbor_texts(
            candidate,
            by_atomic_index=by_atomic_index,
        )
        payload.append(
            {
                "recipe_id": candidate.recipe_id,
                "block_id": candidate.block_id,
                "block_index": candidate.block_index,
                "atomic_index": candidate.atomic_index,
                "text": candidate.text,
                "within_recipe_span": candidate.within_recipe_span,
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
