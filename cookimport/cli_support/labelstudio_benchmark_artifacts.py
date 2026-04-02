from __future__ import annotations

from cookimport.cli_support import Any, Path, shutil, typer


def prune_benchmark_outputs(
    *,
    eval_output_dir: Path,
    processed_run_root: Path | None,
    suppress_summary: bool,
    suppress_output_prune: bool,
) -> None:
    """Drop transient benchmark artifacts after CSV metrics are persisted."""
    from cookimport.analytics.dashboard_collect import (
        _is_excluded_benchmark_artifact,
        _is_pytest_temp_eval_artifact,
    )

    if suppress_output_prune:
        return
    eval_root = eval_output_dir.expanduser()
    if _is_pytest_temp_eval_artifact(eval_root):
        return
    if not _is_excluded_benchmark_artifact(eval_root):
        return

    candidate_targets: list[Path] = [eval_root]
    if processed_run_root is not None:
        candidate_targets.append(processed_run_root.expanduser())

    targets: list[Path] = []
    seen: set[Path] = set()
    for path in candidate_targets:
        if path in seen:
            continue
        seen.add(path)
        if not path.exists() or not path.is_dir():
            continue
        targets.append(path)
    if not targets:
        return

    removed: list[Path] = []
    failed: list[tuple[Path, str]] = []
    for path in targets:
        try:
            shutil.rmtree(path)
            removed.append(path)
        except OSError as exc:
            failed.append((path, str(exc)))

    if suppress_summary:
        return
    if removed:
        typer.secho(
            "Pruned transient benchmark artifacts after CSV metric append:",
            fg=typer.colors.YELLOW,
        )
        for path in removed:
            typer.secho(f"  - {path}", fg=typer.colors.YELLOW)
    if failed:
        typer.secho(
            "Failed to prune some transient benchmark artifacts:",
            fg=typer.colors.YELLOW,
        )
        for path, reason in failed:
            typer.secho(f"  - {path} ({reason})", fg=typer.colors.YELLOW)


def benchmark_selective_retry_manifest_summary(
    run_config: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(run_config, dict):
        return {}
    summary_fields = (
        "selective_retry_attempted",
        "selective_retry_recipe_correction_attempts",
        "selective_retry_recipe_correction_recovered",
        "selective_retry_final_recipe_attempts",
        "selective_retry_final_recipe_recovered",
    )
    return {
        field: run_config[field]
        for field in summary_fields
        if field in run_config
    }
