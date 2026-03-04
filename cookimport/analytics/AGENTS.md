# Agent Guidelines — /cookimport/analytics

This folder owns dashboard/performance analytics contracts.

## CSV-first dashboard contract (mandatory)

- Any stat rendered by `stats-dashboard` must be persisted in canonical history CSV (`history_csv_for_output(...)`, default `<repo>/.history/performance_history.csv`).
- If you add/change a dashboard metric, update CSV write paths first (`perf_report` / benchmark CSV appenders), then collector/renderer.
- JSON report scanning (`*.excel_import_report.json`, benchmark manifests/eval reports) is fallback/backfill only, not the primary source of dashboard truth.
- Do not ship a dashboard metric that only exists in scanned JSON and is missing from CSV rows.
- Keep tests covering this contract: CSV persistence, collector mapping, and rendered output.
