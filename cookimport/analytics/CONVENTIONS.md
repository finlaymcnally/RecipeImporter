# Analytics Conventions

Durable reporting/dashboard caveats for `cookimport/analytics/`.

## Analytics Caveats

- `perf_report.resolve_run_dir()` must accept both timestamp folder styles (`YYYY-MM-DD_HH.MM.SS` and legacy `YYYY-MM-DD-HH-MM-SS`) and choose the latest parsed run directory.
- Stage history append must target the actual chosen stage root's history sibling (`<stage --out parent>/.history/performance_history.csv`), not a hard-coded default output folder.
- Any CLI flow that writes `performance_history.csv` rows should trigger a best-effort dashboard refresh for the same history root; all-method benchmark internals should batch that refresh to once per source in serial-source mode and once at multi-source completion when source parallelism is enabled.
- CSV append paths in `cookimport/analytics/perf_report.py` (`append_history_csv` and `append_benchmark_csv`) must hold an inter-process file lock through schema-check + header decision + write so parallel benchmark rows cannot corrupt the shared history file.
- Dashboard `index.html` embeds dashboard JSON inline (in addition to `assets/dashboard_data.json`) so opening via `file://` works even when browser local `fetch()` is blocked.
- Dashboard timestamp ordering (recent runs/benchmarks and latest benchmark picks) must parse timestamps before sorting because history mixes `YYYY-MM-DDTHH:MM:SS` and `YYYY-MM-DD_HH.MM.SS` formats.
- Dashboard frontend timestamp parsing should explicitly parse timestamp components for those two canonical formats; avoid relying only on `Date.parse(...)` for local `file://` dashboards.
- Throughput dashboard should keep two complementary views: run/date history and file-over-time trend; file trend grouping key is `StageRecord.file_name`.
- Throughput run/date trend should default to p95-clamped rendering with explicit `Raw`/`Log` toggles so outliers do not flatten normal runs.
- Dashboard table collapse behavior should keep preview rows visible in reduced mode (`Show all` / `Show fewer`), not render zero-row collapsed tables.
- Benchmark dashboard enrichment should read `manifest.json` and `coverage.json` from either eval root or `prediction-run/`; `labelstudio-benchmark` co-locates prediction artifacts under `prediction-run/`.
- When combining benchmark rows from JSON + CSV, dedupe by eval artifact directory and merge fields; CSV timestamps can differ from eval-folder timestamps for the same run.
- Dashboard benchmark collection should ignore pytest temp eval artifact paths (`.../pytest-<n>/test_*/eval`) so local Python test runs do not pollute benchmark history.
- Dashboard benchmark collector must scan `eval_report.json` recursively under `golden_root` so nested all-method config runs (`.../all-method-benchmark/<source_slug>/config_*/eval_report.json`) appear in dashboard grouping/ranking.
- Dashboard `Recent Benchmarks` `Gold`/`Matched` columns are freeform span-eval counts (`gold_total`/`gold_matched`), not recipe totals; benchmark `recipes` is stored in CSV when available and can be backfilled from `processed_report_path`.
- Dashboard UX contract: every displayed metric must include a plain-English description (tooltips and/or an on-page help/glossary) that clarifies units and denominators (spans vs recipes, seconds vs ratios, etc.).
- Dashboard metrics contract is CSV-first: every stat shown in `stats-dashboard` must be written to `performance_history.csv`; JSON report scans are fallback/backfill only.
- Standalone dashboard pages for all-method sweeps must also remain CSV-first: group benchmark rows by `run_dir`/`artifact_dir` paths containing `all-method-benchmark/<source_slug>/config_*` and rank configs from those CSV-backed benchmark metrics.
- Dashboard should always emit an in-site all-method root page at `data/.history/dashboard/all-method-benchmark/index.html` (empty-state included), with one run-summary page per sweep at `all-method-benchmark/all-method-benchmark-run__<run_timestamp>.html`.
- All-method run-summary pages must aggregate configuration performance across all per-book jobs in the run folder and keep drilldown links to per-book pages (`all-method-benchmark/all-method-benchmark__<run_timestamp>__<source_slug>.html`).
- All-method run-summary/detail pages should expose sticky quick-nav links and collapsible section groups so long metric pages remain scannable without removing metrics.
- All-method detail pages should keep a compact stats-only summary block and per-metric bar-chart blocks ahead of the full ranked configuration table for quick scanability.
- Ranked all-method rows should expose explicit dimension fields (`Extractor`, `Parser`, `Skip HF`, `Preprocess`) so users can compare configuration differences without parsing slug strings.
- Run-config metrics contract is `run_config_hash` + `run_config_summary` + `run_config_json` in CSV. Dashboard UI should display summary/hash first and use JSON/report fallback only when CSV context is incomplete.
- Benchmark CSV `recipes` should be populated for all benchmark entrypoints (`labelstudio-benchmark`, `labelstudio-eval`, `bench run`) using pred-run manifest `recipe_count` first, then `processed_report_path` fallback.
- Benchmark CSV should also persist `gold_recipe_headers` from eval `recipe_counts.gold_recipe_headers`; all-method recipes charts must use `% identified` (`recipes / gold_recipe_headers`, clamped to 100%) on fixed 0-100% axes rather than max-relative recipe counts.
- If historical benchmark rows predate that persistence path, use `cookimport benchmark-csv-backfill` to patch CSV `recipes/report_path/file_name` from benchmark manifests before regenerating the dashboard.
