Performance reporting utilities live here.

- Reads per-run conversion reports and prints one-line, per-file timing summaries.
- Appends run history to `data/output/.history/performance_history.csv` for easy trending.
- Invoked by `cookimport perf-report` and auto-runs after `cookimport stage`.

Outliers are flagged across multiple metrics (total, parsing, writing, per-unit) and
per-recipe only when the run is recipe-heavy (to avoid knowledge-heavy false positives).
