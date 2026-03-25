from __future__ import annotations

from pathlib import Path

from cookimport.cli_support.test_safety import should_skip_heavy_test_side_effects


def _runtime():
    from cookimport import cli_support as runtime

    return runtime


def _refresh_dashboard_after_history_write(
    *,
    csv_path: Path,
    output_root: Path | None = None,
    golden_root: Path | None = None,
    dashboard_out_dir: Path | None = None,
    reason: str | None = None,
) -> None:
    runtime = _runtime()
    if should_skip_heavy_test_side_effects():
        runtime.logger.info(
            "Skipping dashboard refresh during pytest-side-effect guard."
        )
        return
    resolved_csv_path = csv_path.expanduser()
    if not resolved_csv_path.exists():
        return
    resolved_output_root = output_root.expanduser() if output_root is not None else None
    resolved_dashboard_out_dir = (
        dashboard_out_dir.expanduser()
        if dashboard_out_dir is not None
        else (resolved_csv_path.parent / "dashboard")
    )
    if resolved_output_root is None:
        resolved_output_root = runtime._infer_output_root_from_history_csv(resolved_csv_path)
    reason_suffix = f" ({reason})" if reason else ""
    if resolved_output_root is None:
        runtime.logger.warning(
            "Dashboard refresh skipped%s: unable to infer output root for %s",
            reason_suffix,
            resolved_csv_path,
        )
        return
    try:
        from cookimport import cli as cli_module
        from cookimport.cli_commands import analytics as analytics_commands

        dashboard_runner = getattr(
            cli_module,
            "stats_dashboard",
            analytics_commands.stats_dashboard,
        )
        dashboard_runner(
            output_root=resolved_output_root,
            golden_root=golden_root or runtime.DEFAULT_GOLDEN,
            out_dir=resolved_dashboard_out_dir,
            open_browser=False,
            since_days=None,
            scan_reports=False,
            scan_benchmark_reports=False,
        )
    except Exception as exc:  # noqa: BLE001
        runtime.logger.warning("Dashboard refresh failed%s: %s", reason_suffix, exc)
