from __future__ import annotations

import json
from pathlib import Path

import typer

from cookimport.bench.followup_bundle import (
    write_ablation_matrix,
    write_case_export,
    write_followup_pack,
    write_followup_request_packet,
    write_followup_request_template,
    write_structure_report,
    write_line_role_audit,
    write_page_context,
    write_knowledge_audit,
    write_prompt_link_audit,
    write_selector_manifest,
    write_uncertainty_export,
)
from cookimport.core.slug import slugify_name
from cookimport.llm.prompt_preview import write_prompt_preview_for_existing_run


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Deterministic follow-up exporters and audits for benchmark upload bundles.",
)


@app.command("request-template")
def request_template(
    bundle: Path = typer.Option(..., "--bundle", exists=True, file_okay=False, dir_okay=True),
    out: Path = typer.Option(..., "--out"),
) -> None:
    write_followup_request_template(bundle_dir=bundle, out_path=out)
    typer.echo(str(out))


def _select_cases_command_text(
    *,
    bundle: Path,
    out: Path,
    top_neg: int,
    top_pos: int,
    outside_span: int,
    stage: list[str],
    include_case_id: list[str],
    include_recipe_id: list[str],
    include_line_range: list[str],
    include_knowledge_source_key: list[str],
    include_knowledge_output_subdir: list[str],
) -> str:
    parts = [
        "cf-debug",
        "select-cases",
        "--bundle",
        str(bundle),
        "--out",
        str(out),
        "--top-neg",
        str(top_neg),
        "--top-pos",
        str(top_pos),
        "--outside-span",
        str(outside_span),
    ]
    for value in stage:
        parts.extend(["--stage", value])
    for value in include_case_id:
        parts.extend(["--include-case-id", value])
    for value in include_recipe_id:
        parts.extend(["--include-recipe-id", value])
    for value in include_line_range:
        parts.extend(["--include-line-range", value])
    for value in include_knowledge_source_key:
        parts.extend(["--include-knowledge-source-key", value])
    for value in include_knowledge_output_subdir:
        parts.extend(["--include-knowledge-output-subdir", value])
    return " ".join(parts)


@app.command("select-cases")
def select_cases(
    bundle: Path = typer.Option(..., "--bundle", exists=True, file_okay=False, dir_okay=True),
    out: Path = typer.Option(..., "--out"),
    top_neg: int = typer.Option(0, "--top-neg", min=0),
    top_pos: int = typer.Option(0, "--top-pos", min=0),
    outside_span: int = typer.Option(0, "--outside-span", min=0),
    stage: list[str] | None = typer.Option(None, "--stage"),
    include_case_id: list[str] | None = typer.Option(None, "--include-case-id"),
    include_recipe_id: list[str] | None = typer.Option(None, "--include-recipe-id"),
    include_line_range: list[str] | None = typer.Option(None, "--include-line-range"),
    include_knowledge_source_key: list[str] | None = typer.Option(None, "--include-knowledge-source-key"),
    include_knowledge_output_subdir: list[str] | None = typer.Option(
        None,
        "--include-knowledge-output-subdir",
    ),
) -> None:
    stage_values = stage or []
    include_case_values = include_case_id or []
    include_recipe_values = include_recipe_id or []
    include_line_range_values = include_line_range or []
    include_knowledge_source_values = include_knowledge_source_key or []
    include_knowledge_output_values = include_knowledge_output_subdir or []
    write_selector_manifest(
        bundle_dir=bundle,
        out_path=out,
        command=_select_cases_command_text(
            bundle=bundle,
            out=out,
            top_neg=top_neg,
            top_pos=top_pos,
            outside_span=outside_span,
            stage=stage_values,
            include_case_id=include_case_values,
            include_recipe_id=include_recipe_values,
            include_line_range=include_line_range_values,
            include_knowledge_source_key=include_knowledge_source_values,
            include_knowledge_output_subdir=include_knowledge_output_values,
        ),
        stage_filters=stage_values,
        top_neg=top_neg,
        top_pos=top_pos,
        outside_span=outside_span,
        include_case_ids=include_case_values,
        include_recipe_ids=include_recipe_values,
        include_line_ranges=include_line_range_values,
        include_knowledge_source_keys=include_knowledge_source_values,
        include_knowledge_output_subdirs=include_knowledge_output_values,
    )
    typer.echo(str(out))


@app.command("build-followup")
def build_followup(
    bundle: Path = typer.Option(..., "--bundle", exists=True, file_okay=False, dir_okay=True),
    request: Path = typer.Option(..., "--request", exists=True, file_okay=True, dir_okay=False),
    out: Path = typer.Option(..., "--out"),
    readme: bool = typer.Option(True, "--readme/--no-readme"),
) -> None:
    write_followup_request_packet(
        bundle_dir=bundle,
        request_path=request,
        out_dir=out,
        include_readme=readme,
    )
    typer.echo(str(out))


@app.command("export-cases")
def export_cases(
    bundle: Path = typer.Option(..., "--bundle", exists=True, file_okay=False, dir_okay=True),
    selectors: Path = typer.Option(..., "--selectors", exists=True, file_okay=True, dir_okay=False),
    out: Path = typer.Option(..., "--out"),
) -> None:
    write_case_export(bundle_dir=bundle, selectors_path=selectors, out_dir=out)
    typer.echo(str(out))


@app.command("structure-report")
def structure_report(
    bundle: Path = typer.Option(..., "--bundle", exists=True, file_okay=False, dir_okay=True),
    out: Path = typer.Option(..., "--out"),
) -> None:
    write_structure_report(bundle_dir=bundle, out_path=out)
    typer.echo(str(out))


@app.command("audit-line-role")
def audit_line_role(
    bundle: Path = typer.Option(..., "--bundle", exists=True, file_okay=False, dir_okay=True),
    selectors: Path = typer.Option(..., "--selectors", exists=True, file_okay=True, dir_okay=False),
    out: Path = typer.Option(..., "--out"),
) -> None:
    write_line_role_audit(bundle_dir=bundle, selectors_path=selectors, out_path=out)
    typer.echo(str(out))


@app.command("audit-prompt-links")
def audit_prompt_links(
    bundle: Path = typer.Option(..., "--bundle", exists=True, file_okay=False, dir_okay=True),
    selectors: Path = typer.Option(..., "--selectors", exists=True, file_okay=True, dir_okay=False),
    out: Path = typer.Option(..., "--out"),
) -> None:
    write_prompt_link_audit(bundle_dir=bundle, selectors_path=selectors, out_path=out)
    typer.echo(str(out))


@app.command("audit-knowledge")
def audit_knowledge(
    bundle: Path = typer.Option(..., "--bundle", exists=True, file_okay=False, dir_okay=True),
    selectors: Path = typer.Option(..., "--selectors", exists=True, file_okay=True, dir_okay=False),
    out: Path = typer.Option(..., "--out"),
) -> None:
    write_knowledge_audit(bundle_dir=bundle, selectors_path=selectors, out_path=out)
    typer.echo(str(out))


@app.command("export-page-context")
def export_page_context(
    bundle: Path = typer.Option(..., "--bundle", exists=True, file_okay=False, dir_okay=True),
    selectors: Path = typer.Option(..., "--selectors", exists=True, file_okay=True, dir_okay=False),
    out: Path = typer.Option(..., "--out"),
) -> None:
    write_page_context(bundle_dir=bundle, selectors_path=selectors, out_path=out)
    typer.echo(str(out))


@app.command("export-uncertainty")
def export_uncertainty(
    bundle: Path = typer.Option(..., "--bundle", exists=True, file_okay=False, dir_okay=True),
    selectors: Path = typer.Option(..., "--selectors", exists=True, file_okay=True, dir_okay=False),
    out: Path = typer.Option(..., "--out"),
) -> None:
    write_uncertainty_export(
        bundle_dir=bundle,
        selectors_path=selectors,
        out_path=out,
    )
    typer.echo(str(out))


@app.command("pack")
def pack(
    bundle: Path = typer.Option(..., "--bundle", exists=True, file_okay=False, dir_okay=True),
    selectors: Path = typer.Option(..., "--selectors", exists=True, file_okay=True, dir_okay=False),
    out: Path = typer.Option(..., "--out"),
    readme: bool = typer.Option(True, "--readme/--no-readme"),
) -> None:
    write_followup_pack(
        bundle_dir=bundle,
        selectors_path=selectors,
        out_dir=out,
        include_readme=readme,
    )
    typer.echo(str(out))


@app.command("ablate")
def ablate(
    bundle: Path = typer.Option(..., "--bundle", exists=True, file_okay=False, dir_okay=True),
    out: Path = typer.Option(..., "--out"),
) -> None:
    write_ablation_matrix(bundle_dir=bundle, out_path=out)
    typer.echo(str(out))


@app.command("preview-prompts")
def preview_prompts(
    run: Path = typer.Option(..., "--run", exists=True, file_okay=True, dir_okay=True),
    out: Path = typer.Option(..., "--out"),
    llm_recipe_pipeline: str = typer.Option(
        "codex-recipe-shard-v1",
        "--llm-recipe-pipeline",
    ),
    llm_knowledge_pipeline: str = typer.Option(
        "codex-knowledge-shard-v1",
        "--llm-knowledge-pipeline",
    ),
    line_role_pipeline: str = typer.Option(
        "codex-line-role-shard-v1",
        "--line-role-pipeline",
    ),
    codex_farm_root: Path | None = typer.Option(None, "--codex-farm-root"),
    codex_farm_model: str | None = typer.Option(None, "--codex-farm-model"),
    codex_farm_reasoning_effort: str | None = typer.Option(
        None,
        "--codex-farm-reasoning-effort",
    ),
    codex_farm_context_blocks: int = typer.Option(30, "--codex-farm-context-blocks", min=0),
    codex_farm_knowledge_context_blocks: int = typer.Option(
        0,
        "--codex-farm-knowledge-context-blocks",
        min=0,
    ),
    atomic_block_splitter: str = typer.Option("off", "--atomic-block-splitter"),
    recipe_worker_count: int | None = typer.Option(None, "--recipe-worker-count", min=1),
    recipe_prompt_target_count: int | None = typer.Option(
        None,
        "--recipe-prompt-target-count",
        min=1,
    ),
    knowledge_prompt_target_count: int | None = typer.Option(
        None,
        "--knowledge-prompt-target-count",
        min=1,
    ),
    knowledge_worker_count: int | None = typer.Option(None, "--knowledge-worker-count", min=1),
    line_role_worker_count: int | None = typer.Option(None, "--line-role-worker-count", min=1),
    line_role_prompt_target_count: int | None = typer.Option(
        None,
        "--line-role-prompt-target-count",
        min=1,
    ),
    line_role_shard_target_lines: int | None = typer.Option(
        None,
        "--line-role-shard-target-lines",
        min=1,
    ),
) -> None:
    manifest_path = write_prompt_preview_for_existing_run(
        run_path=run,
        out_dir=out,
        repo_root=Path(__file__).resolve().parents[1],
        llm_recipe_pipeline=llm_recipe_pipeline,
        llm_knowledge_pipeline=llm_knowledge_pipeline,
        line_role_pipeline=line_role_pipeline,
        codex_farm_root=codex_farm_root,
        codex_farm_model=codex_farm_model,
        codex_farm_reasoning_effort=codex_farm_reasoning_effort,
        codex_farm_context_blocks=codex_farm_context_blocks,
        codex_farm_knowledge_context_blocks=codex_farm_knowledge_context_blocks,
        atomic_block_splitter=atomic_block_splitter,
        recipe_worker_count=recipe_worker_count,
        recipe_prompt_target_count=recipe_prompt_target_count,
        knowledge_prompt_target_count=knowledge_prompt_target_count,
        knowledge_worker_count=knowledge_worker_count,
        line_role_worker_count=line_role_worker_count,
        line_role_prompt_target_count=line_role_prompt_target_count,
        line_role_shard_target_lines=line_role_shard_target_lines,
    )
    try:
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        manifest_payload = {}
    warnings = manifest_payload.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings:
            if not isinstance(warning, dict):
                continue
            message = str(warning.get("message") or "").strip()
            if not message:
                continue
            severity = str(warning.get("severity") or "").strip().lower()
            color = typer.colors.YELLOW
            if severity == "danger":
                color = typer.colors.RED
            typer.secho(message, fg=color, err=True)
    typer.echo(str(manifest_path))


@app.command("actual-costs")
def actual_costs(
    run: Path = typer.Option(..., "--run", exists=True, file_okay=True, dir_okay=True),
) -> None:
    summary_path = _resolve_actual_costs_summary_path(run)
    typer.echo(str(summary_path))


def _resolve_actual_costs_summary_path(run_path: Path) -> Path:
    candidate = run_path.expanduser().resolve(strict=False)
    if candidate.is_file() and candidate.name == "prompt_budget_summary.json":
        return candidate
    if candidate.is_dir():
        for direct_candidate in (
            candidate / "prompt_budget_summary.json",
            candidate / "prediction-run" / "prompt_budget_summary.json",
        ):
            if direct_candidate.is_file():
                return direct_candidate
    for manifest_path in _candidate_manifest_paths(root=candidate):
        payload = _read_json(manifest_path)
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, dict):
            continue
        for key in ("actual_costs_json", "prompt_budget_summary_json"):
            raw_path = artifacts.get(key)
            if not isinstance(raw_path, str) or not raw_path.strip():
                continue
            resolved = _resolve_manifest_artifact_path(
                manifest_path=manifest_path,
                raw_path=raw_path.strip(),
            )
            if resolved.is_file():
                return resolved
    raise ValueError(
        f"Could not find an actual-costs summary from {run_path}. "
        "Actual costs are a post-run artifact; look for prompt_budget_summary.json on the finished run."
    )


def _candidate_manifest_paths(*, root: Path) -> list[Path]:
    rows: list[Path] = []
    if root.is_file() and root.name in {"run_manifest.json", "manifest.json"}:
        return [root]
    if root.is_dir():
        for pattern in ("**/run_manifest.json", "**/manifest.json"):
            rows.extend(sorted(root.glob(pattern)))
    return rows


def _resolve_manifest_artifact_path(*, manifest_path: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    return (manifest_path.parent.resolve(strict=False) / raw_path).resolve(strict=False)


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_shard_sweep_experiments(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        experiments = payload.get("experiments")
        if isinstance(experiments, list):
            return [entry for entry in experiments if isinstance(entry, dict)]
    if isinstance(payload, list):
        return [entry for entry in payload if isinstance(entry, dict)]
    raise typer.BadParameter("Expected a JSON list or {'experiments': [...]} payload.")


def _phase_plan_summary_row(phase_plan: dict[str, object]) -> dict[str, object]:
    return {
        "stage_key": str(phase_plan.get("stage_key") or ""),
        "stage_label": str(phase_plan.get("stage_label") or ""),
        "worker_count": int(phase_plan.get("worker_count") or 0),
        "shard_count": int(phase_plan.get("shard_count") or 0),
        "interaction_count": int(phase_plan.get("interaction_count") or 0),
        "owned_ids_per_shard_avg": float(
            ((phase_plan.get("owned_ids_per_shard") or {}) if isinstance(phase_plan.get("owned_ids_per_shard"), dict) else {}).get("avg")
            or 0.0
        ),
        "first_turn_payload_chars_avg": float(
            ((phase_plan.get("first_turn_payload_chars") or {}) if isinstance(phase_plan.get("first_turn_payload_chars"), dict) else {}).get("avg")
            or 0.0
        ),
    }


@app.command("preview-shard-sweep")
def preview_shard_sweep(
    run: Path = typer.Option(..., "--run", exists=True, file_okay=True, dir_okay=True),
    experiment_file: Path = typer.Option(
        ...,
        "--experiment-file",
        exists=True,
        file_okay=True,
        dir_okay=False,
    ),
    out: Path = typer.Option(..., "--out"),
    llm_recipe_pipeline: str = typer.Option(
        "codex-recipe-shard-v1",
        "--llm-recipe-pipeline",
    ),
    llm_knowledge_pipeline: str = typer.Option(
        "codex-knowledge-shard-v1",
        "--llm-knowledge-pipeline",
    ),
    line_role_pipeline: str = typer.Option(
        "codex-line-role-shard-v1",
        "--line-role-pipeline",
    ),
    codex_farm_root: Path | None = typer.Option(None, "--codex-farm-root"),
    codex_farm_model: str | None = typer.Option(None, "--codex-farm-model"),
    codex_farm_reasoning_effort: str | None = typer.Option(
        None,
        "--codex-farm-reasoning-effort",
    ),
    codex_farm_context_blocks: int = typer.Option(30, "--codex-farm-context-blocks", min=0),
    codex_farm_knowledge_context_blocks: int = typer.Option(
        0,
        "--codex-farm-knowledge-context-blocks",
        min=0,
    ),
    atomic_block_splitter: str = typer.Option("off", "--atomic-block-splitter"),
) -> None:
    experiments = _load_shard_sweep_experiments(experiment_file)
    if not experiments:
        raise typer.BadParameter("Experiment file did not contain any experiment objects.")

    out.mkdir(parents=True, exist_ok=True)
    experiment_rows: list[dict[str, object]] = []
    for index, experiment in enumerate(experiments, start=1):
        raw_name = str(experiment.get("name") or f"experiment-{index:02d}").strip()
        experiment_name = raw_name or f"experiment-{index:02d}"
        experiment_slug = slugify_name(experiment_name) or f"experiment_{index:02d}"
        experiment_out = out / "experiments" / experiment_slug
        manifest_path = write_prompt_preview_for_existing_run(
            run_path=run,
            out_dir=experiment_out,
            repo_root=Path(__file__).resolve().parents[1],
            llm_recipe_pipeline=str(
                experiment.get("llm_recipe_pipeline") or llm_recipe_pipeline
            ),
            llm_knowledge_pipeline=str(
                experiment.get("llm_knowledge_pipeline") or llm_knowledge_pipeline
            ),
            line_role_pipeline=str(
                experiment.get("line_role_pipeline") or line_role_pipeline
            ),
            codex_farm_root=codex_farm_root,
            codex_farm_model=codex_farm_model,
            codex_farm_reasoning_effort=codex_farm_reasoning_effort,
            codex_farm_context_blocks=codex_farm_context_blocks,
            codex_farm_knowledge_context_blocks=codex_farm_knowledge_context_blocks,
            atomic_block_splitter=str(
                experiment.get("atomic_block_splitter") or atomic_block_splitter
            ),
            recipe_worker_count=(
                int(experiment["recipe_worker_count"])
                if experiment.get("recipe_worker_count") is not None
                else None
            ),
            recipe_prompt_target_count=(
                int(experiment["recipe_prompt_target_count"])
                if experiment.get("recipe_prompt_target_count") is not None
                else None
            ),
            knowledge_prompt_target_count=(
                int(experiment["knowledge_prompt_target_count"])
                if experiment.get("knowledge_prompt_target_count") is not None
                else None
            ),
            knowledge_worker_count=(
                int(experiment["knowledge_worker_count"])
                if experiment.get("knowledge_worker_count") is not None
                else None
            ),
            line_role_worker_count=(
                int(experiment["line_role_worker_count"])
                if experiment.get("line_role_worker_count") is not None
                else None
            ),
            line_role_prompt_target_count=(
                int(experiment["line_role_prompt_target_count"])
                if experiment.get("line_role_prompt_target_count") is not None
                else None
            ),
            line_role_shard_target_lines=(
                int(experiment["line_role_shard_target_lines"])
                if experiment.get("line_role_shard_target_lines") is not None
                else None
            ),
        )
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        budget_payload = json.loads(
            (experiment_out / "prompt_preview_budget_summary.json").read_text(encoding="utf-8")
        )
        phase_plans = manifest_payload.get("phase_plans")
        if not isinstance(phase_plans, dict):
            phase_plans = {}
        experiment_rows.append(
            {
                "name": experiment_name,
                "slug": experiment_slug,
                "manifest_path": str(manifest_path.relative_to(out)),
                "preview_dir": str(experiment_out.relative_to(out)),
                "estimated_total_tokens": (
                    ((budget_payload.get("totals") or {}) if isinstance(budget_payload.get("totals"), dict) else {}).get("estimated_total_tokens")
                ),
                "warnings": manifest_payload.get("warnings") or [],
                "phases": [
                    _phase_plan_summary_row(phase_plan)
                    for phase_plan in sorted(
                        [value for value in phase_plans.values() if isinstance(value, dict)],
                        key=lambda row: (int(row.get("stage_order") or 999), str(row.get("stage_key") or "")),
                    )
                ],
                "experiment": dict(experiment),
            }
        )

    sweep_manifest = {
        "schema_version": "prompt_preview_shard_sweep.v1",
        "run": str(run),
        "experiment_file": str(experiment_file),
        "experiments": experiment_rows,
    }
    manifest_path = out / "shard_sweep_manifest.json"
    manifest_path.write_text(
        json.dumps(sweep_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Shard Sweep Preview",
        "",
        f"- Run: `{run}`",
        f"- Experiment file: `{experiment_file}`",
        "",
    ]
    for experiment in experiment_rows:
        lines.append(f"## {experiment['name']}")
        lines.append("")
        lines.append(f"- Preview dir: `{experiment['preview_dir']}`")
        estimated_total_tokens = experiment.get("estimated_total_tokens")
        if estimated_total_tokens is None:
            lines.append("- Estimated total tokens: `unavailable`")
        else:
            lines.append(f"- Estimated total tokens: `~{int(estimated_total_tokens):,}`")
        warnings = experiment.get("warnings")
        if isinstance(warnings, list) and warnings:
            lines.append("- Warnings:")
            for warning in warnings:
                if isinstance(warning, dict):
                    lines.append(f"  - {str(warning.get('message') or '').strip()}")
        phases = experiment.get("phases")
        if isinstance(phases, list) and phases:
            lines.append("")
            lines.append("| Stage | Workers | Shards | Interactions | Owned IDs / Shard | First-Turn Chars / Shard |")
            lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
            for phase in phases:
                if not isinstance(phase, dict):
                    continue
                lines.append(
                    "| "
                    + f"{str(phase.get('stage_label') or phase.get('stage_key') or '')} | "
                    + f"{int(phase.get('worker_count') or 0):,} | "
                    + f"{int(phase.get('shard_count') or 0):,} | "
                    + f"{int(phase.get('interaction_count') or 0):,} | "
                    + f"{float(phase.get('owned_ids_per_shard_avg') or 0.0):.2f} | "
                    + f"{float(phase.get('first_turn_payload_chars_avg') or 0.0):.1f} |"
                )
        lines.append("")
    (out / "shard_sweep_summary.md").write_text(
        "\n".join(lines).rstrip() + "\n",
        encoding="utf-8",
    )
    typer.echo(str(manifest_path))
