---
summary: "Retained benchmark architecture/build/fix chronology for active benchmark features."
read_when:
  - When benchmark behavior debugging is looping and you need prior decisions
  - When changing active benchmark contracts (stage-block, canonical-text, all-method, speed suite)
  - When validating why current benchmark constraints exist
---

# Bench Log: Architecture, Builds, and Fix Attempts

This log was pruned to retain only history that still maps to active benchmark features.
Entries tied to removed benchmark surfaces were retired from this file.

## 1. 2026-02-19_15.49.31 README/Log split marker

Decision retained:
- `docs/07-bench/07-bench_README.md` is the current-state benchmark contract.
- `docs/07-bench/07-bench_log.md` is chronology + anti-loop context.

## 2. 2026-02-25 stage-block benchmark contract rollout

Problem addressed:
- Legacy benchmark scoring could diverge from stage outputs and produced misleading label outcomes.

Durable decisions:
- Primary prediction surface is `stage_block_predictions.json` (stage evidence), not pipeline-task artifacts.
- `labelstudio-benchmark` and `bench run` require both:
  - `stage_block_predictions.json`
  - `extracted_archive.json`
- Stage-block evaluation is block classification and reports:
  - `overall_block_accuracy`
  - `macro_f1_excluding_other`
  - `worst_label_recall`

Anti-loop note:
- Missing stage-block artifacts is an artifact-generation/fixture contract issue, not scorer-math drift.

## 3. 2026-02-25 multi-label gold + mismatch guard hardening

Problems addressed:
- Freeform gold can contain multiple labels for one block.
- Gold/prediction extractor drift can silently produce invalid block-level comparisons.

Durable decisions:
- Multi-label gold per block is valid; prediction is correct when label is in allowed set.
- Missing-gold predicted blocks default to `OTHER` and are logged in `gold_conflicts.jsonl`.
- Evaluator fingerprints blockization metadata and fails with `gold_prediction_blockization_mismatch` when severe drift is detected.

Anti-loop note:
- If metrics look impossible, verify blockization parity and mismatch diagnostics before changing precision/recall logic.

## 4. 2026-02-26 canonical-text all-method default and eval visibility

Problems addressed:
- All-method extractor permutations are not valid under stage-block index parity.
- Long canonical eval phases looked frozen without evaluation-phase status.

Durable decisions:
- Interactive benchmark modes (`single_offline`, `all_method`) use `canonical-text`.
- Non-suppressed benchmark runs keep visible evaluation status.
- Canonical-text exists specifically to score extractor permutations in canonical line space.

## 5. 2026-02-26 canonical alignment safety boundary

Problem addressed:
- Fast canonical alignment introduced scoring-risk ambiguity.

Durable decisions:
- Canonical scoring enforces legacy global alignment semantics.
- `COOKIMPORT_CANONICAL_ALIGNMENT_STRATEGY=auto|fast` is treated as deprecated request and forced to legacy.
- Reports/telemetry keep explicit deprecation and alignment strategy fields.

## 6. 2026-02-26 to 2026-02-27 matcher selection surface

Problems addressed:
- Need benchmark runtime acceleration without changing scoring semantics.
- Need clear requested-vs-effective matcher observability.

Durable decisions:
- Matcher selector contract is `COOKIMPORT_BENCHMARK_SEQUENCE_MATCHER`:
  - `fallback|stdlib|cydifflib|cdifflib|dmp|multilayer`
  - legacy `auto` alias maps to `fallback`
- Fallback chain is deterministic (`cydifflib -> cdifflib -> dmp -> multilayer -> stdlib`) and telemetry records requested/effective/forced mode.
- `multilayer` can be explicitly forced, and fallback reaches it only after higher-priority accelerators are unavailable.

Anti-loop note:
- Byte-parity checks across matcher implementations should use `aligned_prediction_blocks.jsonl`, not `eval_report.json`.

## 7. 2026-02-27 canonical alignment cache reliability updates

Problems addressed:
- Canonical eval tails were dominated by repeated miss-path alignment work.
- Dead-owner lock files could stall progress under age-only stale lock checks.

Durable decisions:
- All-method uses shared per-source canonical cache roots.
- Cache keys include canonical text hash, prediction text hash, and boundary signature.
- Dead-owner lock reclamation checks PID liveness first, then falls back to age-based stale handling for malformed lock metadata.

Evidence retained:
- Miss->hit runs showed matcher-time and wall-time drops while preserving quality metrics.

Anti-loop note:
- When cache benefit is absent, inspect `evaluation_telemetry.alignment_cache_key` equality before changing cache policy.

## 8. 2026-02-27 speed1-4 benchmark stage/replay contract closeout

Problems addressed:
- Replay/evaluate-only paths were under-specified.
- Pipelined mode needed explicit producer/consumer boundary behavior.

Durable decisions:
- Runtime boundary functions are explicit:
  - `predict_stage(...)`
  - `evaluate_stage(...)`
  - `run_legacy(...)`
  - `run_pipelined(...)`
- `--predictions-out` emits per-block prediction records (`schema_kind=stage-block.v1`).
- `--predictions-in` evaluate-only accepts both:
  - per-block records
  - legacy run-pointer records
- `pipelined` mode is true producer/consumer replay overlap while evaluators remain path-based.

## 9. 2026-02-27 speed1-5 artifact-write controls

Problem addressed:
- Non-scoring artifact writes (markdown/tasks jsonl) added runtime cost and needed deterministic toggles.

Durable decisions:
- Stage and benchmark support write toggles:
  - `--write-markdown/--no-write-markdown`
  - `--write-labelstudio-tasks/--no-write-labelstudio-tasks` (offline paths)
- Intentional task-jsonl skips are explicit in manifests (`tasks_jsonl_status`).
- Prediction-surface no-drift checks were added for markdown-toggle variations.

## 10. 2026-02-27 all-method scheduler/runtime interpretation contracts

Problems addressed:
- Operators misread heavy-slot counters and live fail counters.
- Throughput tails on multi-source runs were sensitive to source ordering and caps.

Durable decisions:
- `scheduler heavy X/Y` represents split-active occupancy only.
- Live queue fail counters are attempt-level; final truth is per-source report status after retries/timeouts.
- Scheduler runtime contract includes configured/effective eval-tail fields and explicit admission ceiling.
- Source-level orchestration includes bounded parallelism, source scheduling strategy, and optional heavy-source sharding.

Anti-loop note:
- Low late-run CPU can be structurally normal on final-source canonical tails; use scheduler events, CPU, and cache-lock health before declaring stalls.

## 11. 2026-02-27 speed-suite baseline/candidate workflow

Problem addressed:
- Quality benchmark runs are not enough for deterministic runtime regression gating.

Durable decisions:
- Introduced `bench speed-discover`, `bench speed-run`, `bench speed-compare` as a dedicated speed-regression lane.
- Shared target matching contract uses source-hint fallback order:
  1. `manifest.json` `source_file`
  2. `run_manifest.json` `source.path`
  3. first `source_file` in `freeform_span_labels.jsonl`
  4. first `source_file` in `freeform_segment_manifest.jsonl`

## 12. 2026-02-27 direct-call compatibility boundary for bench CLI helpers

Problem addressed:
- Direct Python calls to bench command helpers could receive Typer `OptionInfo` defaults and fail matcher normalization.

Durable decision:
- Bench command helpers unwrap Typer defaults at function entry before validation/normalization.

Anti-loop note:
- Treat direct-call behavior as a compatibility contract for tests/internal invocations, not incidental CLI-only behavior.

## 13. 2026-02-28 benchmark docs code-map completeness sync

Problem addressed:
- `docs/07-bench/07-bench_README.md` code map had drifted and omitted active helper modules/artifacts still used by benchmark flows.

Durable decisions:
- README now enumerates all active `cookimport/bench/*.py` modules with one-line responsibilities.
- README now calls out suite/sweep/speed/prediction-record artifact families (including trace, noise, cost, iteration packet, and replay artifacts).
- Matcher-history wording in this log now matches the actual fallback chain and multilayer behavior in code.

Anti-loop note:
- If benchmark docs feel incomplete, diff README code-map entries against `cookimport/bench/*.py` before assuming a module is retired.

## 14. Retired History Notice

The following legacy surfaces were intentionally removed from this log to keep it relevant:
- pipeline-task span-IoU benchmark scoring chronology
- upload-first interactive benchmark flow chronology
- fast canonical alignment as a production scoring path

Older artifacts referencing those surfaces are historical context only and should not be used as current contract guidance.

## 15. 2026-02-27 merged understanding ledger (all-method tail, matcher, and doc coverage)

### 2026-02-27_19.21.15 all-method 91/91 retry/eval tail semantics

Durable findings:
- `config N/N` completion reflects first pass only; retries can continue after spinner reaches `N/N`.
- Retry + canonical eval tail can keep run active with apparently frozen per-source counters.

### 2026-02-27_19.23.51 fallback chain includes multilayer before stdlib

Durable findings:
- Effective fallback order is `cydifflib -> cdifflib -> dmp -> multilayer -> stdlib`.
- Multilayer must be ahead of final stdlib fallback to ever be selected.

### 2026-02-27_19.24.31 stopping in-flight retries without killing parent

Durable findings:
- Terminating active worker child PIDs can short-circuit retry tails while preserving final report emission.

### 2026-02-27_19.31.54 canonical cache scope and lock wait behavior

Durable findings:
- Cache hit telemetry does not imply low wall time when lock waits dominate.
- Run-local cache prevents recompute but cross-run persistence gives larger rerun wins.

### 2026-02-27_19.34.53 benchmark-vs-golden config signal

Durable findings:
- This run favored stable unstructured-v1 configs for reliability/runtime trade-off.
- Large-source instability was observed in v2/non-unstructured variants in this sample.

### 2026-02-27_19.42.47 all-method EPUB extractor default scope

Durable findings:
- Default variants are `unstructured` + `beautifulsoup`; markdown extractors are opt-in.

### 2026-02-27_19.47.10 all-method evaluation dedupe hook points

Durable findings:
- Integration point for predict/eval split is `_run_all_method_benchmark(...)` orchestration, not evaluator internals.

### 2026-02-27_19.49.45 tail-throughput plan audit

Durable findings:
- Source planning/sharding/tail-pair and shared cache-dir wiring landed in code/tests/docs.
- Remaining validation gap noted: fresh wall-clock baseline-vs-candidate confirmation was not captured in that audit.

### 2026-02-27_19.51.07 bench docs code-map completeness audit

Durable findings:
- README code map must track all active `cookimport/bench/*.py` runtime modules and artifact families.

Anti-loop summary:
- Distinguish retry/eval tail from deadlock before changing scheduler logic.
- Treat matcher fallback ordering and cache-lock behavior as first-line diagnostics for canonical-text slowness.
