from __future__ import annotations

import typer

from cookimport.cli_support import *  # noqa: F401,F403
from cookimport import cli_support as _cli

globals().update(
    {name: getattr(_cli, name) for name in dir(_cli) if not name.startswith("__")}
)


def register(app: typer.Typer) -> dict[str, object]:
    @app.command("perf-report")
    def perf_report(
        run_dir: Path | None = typer.Option(
            None,
            "--run-dir",
            help="Run folder to summarize (defaults to latest under --out-dir).",
        ),
        out_dir: Path = typer.Option(
            DEFAULT_OUTPUT,
            "--out-dir",
            help="Root output folder used to locate runs and history CSV.",
        ),
        write_csv: bool = typer.Option(
            True,
            "--write-csv/--no-csv",
            help="Append results to the performance history CSV.",
        ),
    ) -> None:
        """Summarize per-file performance metrics for a run."""
        from cookimport.analytics.perf_report import (
            append_history_csv,
            build_perf_summary,
            format_summary_line,
            history_path,
            resolve_run_dir,
        )

        resolved = resolve_run_dir(run_dir, out_dir)
        if resolved is None or not resolved.exists():
            _fail(f"No run folder found under {out_dir}.")

        summary = build_perf_summary(resolved)
        if not summary.rows:
            _fail(f"No conversion reports found in {resolved}.")

        typer.secho(f"Performance summary for {resolved}", fg=typer.colors.CYAN)
        for row in summary.rows:
            typer.echo(format_summary_line(row))

        if summary.total_outliers:
            outlier_names = ", ".join(row.file_name for row in summary.total_outliers)
            typer.secho(
                f"Outliers (total time > 3x median): {outlier_names}",
                fg=typer.colors.YELLOW,
            )
        if summary.parsing_outliers:
            outlier_names = ", ".join(row.file_name for row in summary.parsing_outliers)
            typer.secho(
                f"Outliers (parsing time > 3x median): {outlier_names}",
                fg=typer.colors.YELLOW,
            )
        if summary.writing_outliers:
            outlier_names = ", ".join(row.file_name for row in summary.writing_outliers)
            typer.secho(
                f"Outliers (writing time > 3x median): {outlier_names}",
                fg=typer.colors.YELLOW,
            )
        if summary.per_unit_outliers:
            outlier_names = ", ".join(row.file_name for row in summary.per_unit_outliers)
            typer.secho(
                f"Outliers (per-unit > 3x median): {outlier_names}",
                fg=typer.colors.YELLOW,
            )
        if summary.per_recipe_outliers:
            outlier_names = ", ".join(row.file_name for row in summary.per_recipe_outliers)
            typer.secho(
                "Outliers (per-recipe > 3x median, recipe-heavy only): " + outlier_names,
                fg=typer.colors.YELLOW,
            )
        if summary.knowledge_heavy:
            heavy_names = ", ".join(row.file_name for row in summary.knowledge_heavy)
            typer.secho(
                "Knowledge-heavy runs (topic candidates dominate): " + heavy_names,
                fg=typer.colors.CYAN,
            )

        if write_csv:
            csv_history_path = history_path(out_dir)
            append_history_csv(summary.rows, csv_history_path)
            _refresh_dashboard_after_history_write(
                csv_path=csv_history_path,
                output_root=out_dir,
                reason="perf-report history append",
            )

    @app.command("stats-dashboard")
    def stats_dashboard(
        output_root: Path = typer.Option(
            DEFAULT_OUTPUT,
            "--output-root",
            help="Root output folder for staged imports.",
        ),
        golden_root: Path = typer.Option(
            DEFAULT_GOLDEN,
            "--golden-root",
            help="Root folder for golden-set / benchmark data.",
        ),
        out_dir: Path = typer.Option(
            DEFAULT_HISTORY / "dashboard",
            "--out-dir",
            help="Directory where the dashboard will be written.",
        ),
        open_browser: bool = typer.Option(
            False,
            "--open",
            help="Open the generated dashboard in the default browser.",
        ),
        since_days: int | None = typer.Option(
            None,
            "--since-days",
            help="Only include runs from the last N days.",
        ),
        scan_reports: bool = typer.Option(
            False,
            "--scan-reports",
            help="Force scanning individual *.excel_import_report.json files.",
        ),
        scan_benchmark_reports: bool = typer.Option(
            False,
            "--scan-benchmark-reports",
            help="Force recursive benchmark eval_report.json scans under --golden-root.",
        ),
        serve: bool = typer.Option(
            False,
            "--serve",
            help=(
                "Serve the generated dashboard over HTTP and enable program-side UI-state "
                "persistence (assets/dashboard_ui_state.json) across browsers."
            ),
        ),
        host: str = typer.Option(
            "127.0.0.1",
            "--host",
            help="Host interface used when --serve is enabled.",
        ),
        port: int = typer.Option(
            8765,
            "--port",
            min=0,
            max=65535,
            help="Port used when --serve is enabled (0 picks a free port).",
        ),
    ) -> None:
        """Generate a static lifetime-stats dashboard (HTML)."""
        output_root = _unwrap_typer_option_default(output_root)
        golden_root = _unwrap_typer_option_default(golden_root)
        out_dir = _unwrap_typer_option_default(out_dir)
        open_browser = _unwrap_typer_option_default(open_browser)
        since_days = _unwrap_typer_option_default(since_days)
        scan_reports = _unwrap_typer_option_default(scan_reports)
        scan_benchmark_reports = _unwrap_typer_option_default(scan_benchmark_reports)
        serve = _unwrap_typer_option_default(serve)
        host = _unwrap_typer_option_default(host)
        port = _unwrap_typer_option_default(port)

        from cookimport.analytics.dashboard_collect import collect_dashboard_data
        from cookimport.analytics.dashboard_render import render_dashboard

        data = collect_dashboard_data(
            output_root=output_root,
            golden_root=golden_root,
            since_days=since_days,
            scan_reports=scan_reports,
            scan_benchmark_reports=scan_benchmark_reports,
        )

        html_path = render_dashboard(out_dir, data)

        if data.collector_warnings:
            typer.secho(
                f"Collector warnings ({len(data.collector_warnings)}):",
                fg=typer.colors.YELLOW,
            )
            for w in data.collector_warnings[:10]:
                typer.secho(f"  - {w}", fg=typer.colors.YELLOW)

        typer.secho(f"Wrote dashboard to {out_dir}", fg=typer.colors.GREEN)
        if serve:
            from cookimport.analytics.dashboard_state_server import start_dashboard_server

            try:
                server, dashboard_url = start_dashboard_server(
                    dashboard_dir=out_dir,
                    host=host,
                    port=port,
                )
            except (OSError, FileNotFoundError) as exc:
                _fail(f"Unable to serve dashboard: {exc}")

            typer.echo(f"Serving dashboard at:\n  {dashboard_url}")
            typer.echo("Program-side UI state file: assets/dashboard_ui_state.json")
            typer.echo("Press Ctrl+C to stop the server.")
            if open_browser:
                import webbrowser

                webbrowser.open(dashboard_url)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            return

        typer.echo(f"Open this file in your browser:\n  {html_path}")
        if open_browser:
            import webbrowser

            webbrowser.open(html_path.as_uri())

    @app.command("benchmark-csv-backfill")
    def benchmark_csv_backfill(
        out_dir: Path = typer.Option(
            DEFAULT_OUTPUT,
            "--out-dir",
            help="Output root used to resolve the default history CSV path.",
        ),
        history_csv: Path | None = typer.Option(
            None,
            "--history-csv",
            help="Explicit performance_history.csv path (overrides --out-dir).",
        ),
        dry_run: bool = typer.Option(
            False,
            "--dry-run",
            help="Show what would be patched without writing to disk.",
        ),
    ) -> None:
        """One-off patch for older benchmark CSV rows missing manifest-backed fields."""
        from cookimport.analytics.perf_report import (
            backfill_benchmark_history_csv,
            history_path,
        )

        csv_path = history_csv or history_path(out_dir)
        if not csv_path.exists():
            _fail(f"History CSV not found: {csv_path}")

        summary = backfill_benchmark_history_csv(csv_path, write=not dry_run)

        if dry_run:
            typer.secho(f"Dry run complete: {csv_path}", fg=typer.colors.CYAN)
        else:
            typer.secho(f"Backfill complete: {csv_path}", fg=typer.colors.GREEN)
        typer.echo(f"Benchmark rows scanned: {summary.benchmark_rows}")
        typer.echo(f"Rows updated: {summary.rows_updated}")
        typer.echo(f"Recipes filled: {summary.recipes_filled}")
        typer.echo(f"Report paths filled: {summary.report_paths_filled}")
        typer.echo(f"Source file fields filled: {summary.source_files_filled}")
        typer.echo(f"Run config fields filled: {summary.run_config_rows_filled}")
        typer.echo(f"Codex model fields filled: {summary.codex_models_filled}")
        typer.echo(f"Codex effort fields filled: {summary.codex_efforts_filled}")
        typer.echo(f"Token rows filled: {summary.token_rows_filled}")
        typer.echo(f"Token fields filled: {summary.token_fields_filled}")
        typer.echo(f"Rows still missing recipes: {summary.rows_still_missing_recipes}")

        if dry_run and summary.rows_updated > 0:
            typer.secho("Re-run without --dry-run to persist these patches.", fg=typer.colors.YELLOW)
        if not dry_run and summary.rows_updated > 0:
            default_history_csv = history_path(out_dir)
            refresh_output_root: Path | None = out_dir
            try:
                if csv_path.resolve() != default_history_csv.resolve():
                    refresh_output_root = None
            except OSError:
                if csv_path != default_history_csv:
                    refresh_output_root = None
            _refresh_dashboard_after_history_write(
                csv_path=csv_path,
                output_root=refresh_output_root,
                reason="benchmark-csv-backfill write",
            )

    return {
        "perf_report": perf_report,
        "stats_dashboard": stats_dashboard,
        "benchmark_csv_backfill": benchmark_csv_backfill,
    }
