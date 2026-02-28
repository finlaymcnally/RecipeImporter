# Scripts Notes

- `interactive-with-codex-farm.sh`: launches interactive `cookimport` with Codex Farm env gate enabled for that process (`scripts/interactive-with-codex-farm.sh`).
- `with-codex-farm.sh`: one-shot opt-in wrapper that runs any command with `COOKIMPORT_ALLOW_CODEX_FARM=1` for that process only (`scripts/with-codex-farm.sh cookimport ...`).
- `markitdown_epub_smoke.py`: quick local smoke test for EPUB -> markdown conversion using MarkItDown (`python scripts/markitdown_epub_smoke.py <file.epub>`).
- `bench_sequence_matcher_impl.py`: quick local matcher timing/parity check for canonical eval across selectable modes (`python scripts/bench_sequence_matcher_impl.py --tokens 1400 --repeats 5 --modes stdlib,auto,dmp`).
- `quality_top_tier_tournament.py`: multi-seed QualitySuite tournament runner with fixed pass/fail gates for candidate settings (`python scripts/quality_top_tier_tournament.py --experiments-file ... --thresholds-file ...`). It uses `quality-run` auto experiment parallelism unless `--max-parallel-experiments` is provided.
