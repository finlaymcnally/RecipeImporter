---
summary: "Cross-cutting convention index pointing to code-adjacent convention docs."
read_when:
  - "When looking for hidden rules; start here to find the code-local convention file"
  - "When adding a new convention and deciding where it should live"
---

# Important Conventions

Most durable conventions now live next to the code they govern.
This file is now an index, not a long rule dump.

## Code-Adjacent Convention Files

- `cookimport/CONVENTIONS.md` — CLI discovery/runtime behavior and dependency-resolution notes.
- `cookimport/config/CONVENTIONS.md` — Run-settings source-of-truth and propagation contracts.
- `cookimport/labelstudio/CONVENTIONS.md` — Label Studio prelabel/task/export contracts.
- `cookimport/staging/CONVENTIONS.md` — Stage report and section-artifact output contracts.
- `cookimport/plugins/CONVENTIONS.md` — Ingestion split/merge and extractor contracts.
- `cookimport/bench/CONVENTIONS.md` — Benchmark scoring/orchestration contracts.
- `cookimport/analytics/CONVENTIONS.md` — Analytics/dashboard caveats and history contracts.
- `tests/CONVENTIONS.md` — Test modularity and low-noise pytest contracts.

## Recent Cross-Cutting Update

- Benchmark scoring now uses stage block evidence manifests (`.bench/<workbook_slug>/stage_block_predictions.json`) rather than pipeline chunk span overlap. See `cookimport/bench/CONVENTIONS.md` and `cookimport/staging/CONVENTIONS.md`.
- `labelstudio-benchmark` now supports `stage-blocks` and `canonical-text` eval modes; interactive benchmark modes (`single_offline` and `all_method`) run `canonical-text` so extractor permutations can share one freeform gold export. See `cookimport/bench/CONVENTIONS.md`.
- Stage-block benchmark gold now allows multi-label blocks, and missing predicted-block gold rows default to `OTHER`; evaluator logs both diagnostics in `gold_conflicts.jsonl`. See `cookimport/bench/CONVENTIONS.md`.
- Stage-block benchmark quality depends on extractor/blockization parity between gold-generation and benchmark-prediction runs; matching source hash alone is not sufficient to avoid block-index drift. See `cookimport/bench/CONVENTIONS.md`.
- Stage-block evaluator now fails fast with `gold_prediction_blockization_mismatch` when blockization profiles disagree and missing-gold drift is severe, preventing misleading benchmark metrics from extractor mismatch runs. See `cookimport/bench/CONVENTIONS.md`.
- Stage block evidence `KNOWLEDGE` labels now prefer pass4 snippets and fall back to deterministic chunk lanes when snippets are absent. See `cookimport/staging/CONVENTIONS.md`.
- Label Studio import/export/eval are freeform-only (`freeform-spans`); legacy `pipeline` and `canonical-blocks` scopes are rejected in current workflows. See `cookimport/CONVENTIONS.md` and `cookimport/labelstudio/CONVENTIONS.md`.
- EPUB extractor race mode is retired from both interactive and direct CLI commands; EPUB debug support remains via `cookimport epub inspect|dump|unpack|blocks|candidates|validate`. See `cookimport/CONVENTIONS.md` and `docs/02-cli/02-cli_README.md`.
- Race-only parsing modules (`parsing/epub_auto_select.py`, `parsing/extraction_quality.py`) are removed, and compatibility fields (`epubAutoSelection`, `epubAutoSelectedScore`, `epub_auto_selected_score`) are removed from reports/manifests/history/dashboard contracts.
- All-method scheduler heavy-slot utilization/idle-gap metrics describe split-convert slot usage, not canonical evaluation runtime; long eval tails can dominate config duration even when heavy slots are mostly idle. See `cookimport/bench/CONVENTIONS.md` and `docs/understandings/2026-02-25_23.02.58-all-method-canonical-eval-runtime-hotspot.md`.
- Canonical-text eval runtime is currently dominated by full-book `difflib.SequenceMatcher` alignment in `cookimport/bench/eval_canonical_text.py`; optimize/bound alignment before expecting scheduler-only changes to fix slow runs. See `cookimport/bench/CONVENTIONS.md` and `docs/understandings/2026-02-25_23.15.51-canonical-eval-sequencematcher-profile.md`.
- Canonical-text eval now enforces legacy full-book `SequenceMatcher` alignment for correctness; fast bounded alignment is deprecated due to accuracy risk and should remain disabled unless policy changes. See `cookimport/bench/CONVENTIONS.md`.
- All-method smart scheduler now has an explicit eval-tail cap (`all_method_max_eval_tail_pipelines`) so extra inflight workers are granted primarily when configs are in evaluate phase; keep split slots and wing backlog tuned separately from eval tail. See `cookimport/bench/CONVENTIONS.md` and `docs/07-bench/07-bench_README.md`.
- Benchmark evaluators now emit `evaluation_telemetry` (subphase timers, resource deltas, work-unit counts), and benchmark timing checkpoints mirror those values with `evaluate_*` keys so eval hotspots can be diagnosed from reports/history without rerunning profiling.
- Canonical-text benchmark telemetry now includes alignment micro-subphases and text-size checkpoints, and `labelstudio-benchmark` can emit opt-in slow-eval profiles (`eval_profile.pstats`, `eval_profile_top.txt`) via `COOKIMPORT_BENCHMARK_EVAL_PROFILE_MIN_SECONDS`.

## Adding New Conventions

When you discover a new durable rule:

1. Write it in the nearest code folder (`<folder>/CONVENTIONS.md`) first.
2. Add that folder-level conventions file if it does not exist yet.
3. Update this index only if a new conventions file/path should be discoverable here.
