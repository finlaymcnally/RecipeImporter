# Scripts Notes

- `test-suite.sh`: standardized test runners for common agent loops.
  - `./scripts/test-suite.sh smoke`
  - `./scripts/test-suite.sh fast`
  - `./scripts/test-suite.sh domain <domain>`
  - `./scripts/test-suite.sh all-fast`
  - `./scripts/test-suite.sh full`
  - extra pytest args can be appended, for example `./scripts/test-suite.sh domain parsing --collect-only`
  - For agent workflows, prefer these `test-suite.sh` modes over raw `pytest` to avoid monolithic long-running runs.

- `interactive-with-codex-farm.sh`: launches interactive `cookimport` with Codex Farm env gate enabled for that process (`scripts/interactive-with-codex-farm.sh`).
- `with-codex-farm.sh`: one-shot opt-in wrapper that runs any command with `COOKIMPORT_ALLOW_CODEX_FARM=1` for that process only (`scripts/with-codex-farm.sh cookimport ...`).
- `markitdown_epub_smoke.py`: quick local smoke test for EPUB -> markdown conversion using MarkItDown (`python scripts/markitdown_epub_smoke.py <file.epub>`).
- `bench_sequence_matcher_impl.py`: quick local matcher timing/parity check for canonical eval across selectable modes (`python scripts/bench_sequence_matcher_impl.py --tokens 1400 --repeats 5 --modes stdlib,auto,dmp`).
- `quality_top_tier_tournament.py`: multi-seed QualitySuite tournament runner with fixed pass/fail gates for candidate settings (`python scripts/quality_top_tier_tournament.py --experiments-file ... --thresholds-file ...`). It uses `quality-run` auto experiment parallelism unless `--max-parallel-experiments` is provided, shares canonical/eval cache across folds by default, skips duplicate fold suites from gate aggregation, and prunes gate-impossible candidates between folds.
- `benchmark_cutdown_for_external_ai.py`: builds a benchmark package for external AI review (per-run summaries + sampled diagnostics + codex-vs-baseline comparison), then optionally flattens it to markdown (`python scripts/benchmark_cutdown_for_external_ai.py <benchmark_folder> --output-dir <cutdown_folder> --overwrite`). Each codex-enabled run now includes `full_prompt_log.jsonl` copied without sampling/truncation, while `codexfarm_prompt_log.dedup.txt` remains a convenience-only sampled view that is derived from `full_prompt_log.jsonl` when available (legacy text-log fallback). Prompt log input paths are resolved from `run_manifest.json` artifacts when available (with legacy path fallbacks). `process_manifest.json` now lists each run's `full_prompt_log.jsonl` path in `included_files` so downstream checks can assert full prompt payload presence directly. Without `--output-dir`, default naming is timestamp-driven from discovered run IDs (`<run_id>_cutdown` for one run, `<first>__to__<last>_cutdown` for multi-run). Set `--prompt-pairs-per-category 0` to keep all calls in the convenience file.
