---
summary: "Current benchmark-suite reference for cookimport bench and related benchmark flows."
read_when:
  - When running or modifying cookimport bench workflows
  - When debugging benchmark scoring behavior or artifacts
  - When comparing stage-blocks versus canonical-text evaluation modes
---

# Bench Section Reference

This file is the current, code-verified benchmark contract.
Retained active history lives in `docs/07-bench/07-bench_log.md`.
QualitySuite operator notes live in `docs/07-bench/qualitysuite-agent-sop.md` and `docs/07-bench/qualitysuite-product-suite.md`.

## 1. Scope

Benchmarking in this repo has three active surfaces:

- `cookimport bench ...` for deterministic speed, quality, retention, and upload-bundle workflows
- `cookimport labelstudio-benchmark` for single-run benchmark generation/eval plus the interactive benchmark modes
- `cf-debug ...` for deterministic follow-up packets built on top of `upload_bundle_v1`

Current scoring modes:

- `stage-blocks`: compare stage evidence labels against freeform gold block labels
- `canonical-text`: align prediction text to canonical gold text and score per canonical line

Current benchmark handoff model:

- `upload_bundle_v1` is the primary external-review packet
- follow-up requests should produce additive `followup_dataN/` packets, not replacement bundle formats

## 2. Active Command Surface

### 2.1 `cookimport bench`

Active commands:

- `bench speed-discover`: discover deterministic speed targets from pulled gold exports
- `bench speed-run`: run `stage_import`, `benchmark_canonical_pipelined`, and optionally `benchmark_all_method_multi_source`
- `bench speed-compare`: compare baseline/candidate speed runs with regression gates
- `bench quality-discover`: discover deterministic quality targets from pulled gold exports
- `bench quality-run`: run deterministic all-method quality experiments for one discovered suite
- `bench quality-leaderboard`: aggregate one quality-run experiment into a cross-source leaderboard and Pareto frontier
- `bench quality-compare`: compare baseline/candidate quality runs with strict/practical/source-success gates
- `bench eval-stage`: evaluate an existing stage run directly from `.bench/*/stage_block_predictions.json`
- `bench gc`: prune old benchmark artifacts using CSV durability checks
- `bench pin` / `bench unpin`: add or remove GC keep sentinels
- `bench oracle-upload`: upload an existing `upload_bundle_v1` to Oracle without rerunning the benchmark

Important current constraints:

- `bench quality-run` is deterministic-only. It rejects `--include-codex-farm`, Codex CLI overrides, and requested settings that enable Codex recipe/knowledge/tag surfaces.
- `bench speed-run --include-codex-farm` is still allowed, but it requires `--speedsuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION` and is blocked in agent-run shells.
- `bench quality-run` and `bench speed-run` both support crash-safe resume via `--resume-run-dir`.
- `bench quality-run` emits `agent_compare_control/` by default. `bench quality-compare` does the same for comparisons.
- `bench quality-discover` prefers curated CUTDOWN ids first:
  - `saltfatacidheatcutdown`
  - `thefoodlabcutdown`
  - `seaandsmokecutdown`
  - `dinnerfor2cutdown`
  - `roastchickenandotherstoriescutdown`
- `bench quality-lightweight-series` remains only as a disabled compatibility stub. It exits immediately and is not an active workflow.
- `bench gc` is benchmark-only retention, not a general `data/output` sweeper. It can prune matching benchmark-generated processed-output roots while preserving `performance_history.csv` and refusing destructive cleanup when durable history checks fail.

### 2.2 `cookimport labelstudio-benchmark`

`labelstudio-benchmark` is the active single-run benchmark primitive. It supports:

- action `run` or `compare`
- `--eval-mode stage-blocks|canonical-text`
- `--predictions-out` / `--predictions-in` for replayable evaluation-only reruns
- `--baseline` / `--candidate` compare inputs
- offline runs via `--no-upload`
- plan-only Codex preview via `--codex-execution-policy plan`

Current behavior notes:

- default eval mode is `stage-blocks`
- `stage-blocks` forces `line_role_pipeline=off` and `atomic_block_splitter=off`
- canonical-text runs can enable:
  - `atomic_block_splitter=atomic-v1`
  - `line_role_pipeline=deterministic-v1|codex-line-role-v1`
  - `llm_knowledge_pipeline=codex-farm-knowledge-v1`
- non-interactive live Codex-backed benchmark runs require:
  - `--allow-codex`
  - `--benchmark-codex-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION`
- agent-run environments are blocked from that live non-interactive Codex path and must use `--codex-execution-policy plan`
- `--codex-execution-policy plan` requires `--no-upload`, skips live Codex/eval, and still writes `codex_execution_plan.json`

Interactive benchmark modes are still active and remain offline canonical-text workflows:

- `single_offline`
- `single_offline_selected_matched`
- `single_offline_all_matched`

Current interactive contracts:

- `single_offline` writes one session root under `data/golden/benchmark-vs-golden/<timestamp>/single-offline-benchmark/<source_slug>/`
- when Codex-backed recipe extraction is selected, paired runs are written under sibling `vanilla/` and `codexfarm/` roots in that session
- paired success can emit:
  - `codex_vs_vanilla_comparison.json`
  - `single_offline_summary.md`
  - `upload_bundle_v1/`
- single-profile matched-book runs write under `.../single-profile-benchmark/`
- multi-book single-profile runs also emit one top-level group `upload_bundle_v1/`
- interactive single-offline auto-uploads its session bundle to Oracle
- multi-book single-profile auto-uploads only the top-level group bundle to Oracle

### 2.3 `cf-debug`

`cf-debug` is the deterministic follow-up CLI that operates on an existing `upload_bundle_v1`.

Active use cases:

- build a request template for external reviewers
- select/export concrete cases from the base bundle
- audit line-role joins and prompt links
- audit knowledge-stage evidence
- build additive `followup_dataN/` packets

Knowledge extraction is now a first-class follow-up seam:

- selectors can target knowledge source keys/output subdirs explicitly
- `audit-knowledge` emits run-level knowledge evidence
- follow-up packets can include `knowledge_audit.jsonl`
- uncertainty/follow-up exports now center on explicit escalation reasons; current reviewer packets do not carry scalar trust/confidence fields

## 3. Scoring And Artifact Contracts

### 3.1 Authoritative scored inputs

Primary scored prediction artifact:

- `stage_block_predictions.json` (`schema_version=stage_block_predictions.v1`)

Required supporting artifact:

- `extracted_archive.json`

Current rule:

- benchmark scoring reads one canonical pointer pair from prediction-run metadata:
  - `stage_block_predictions_path`
  - `extracted_archive_path`
- prediction generation is responsible for setting those canonical pointers to the correct artifacts for the run
- canonical-text line-role runs rewire that same pointer pair to the scored `line-role-pipeline/` projection artifacts; helpers should not guess stage-backed files or raw `full_text.json` from path layout
- new-format prediction/eval manifests and import return payloads do not publish separate line-role scorer keys anymore; helpers should fail on missing canonical pointers instead of probing legacy fallback filenames or implicit directories

### 3.2 Gold inputs

Stage-block mode expects:

- `exports/freeform_span_labels.jsonl`

Canonical-text mode expects:

- `exports/canonical_text.txt`
- `exports/canonical_span_labels.jsonl`
- `exports/canonical_manifest.json`

### 3.3 Stage-block scoring contract

Current rules:

- freeform gold may contain multiple labels for one block; any allowed label is a correct match
- missing gold rows for predicted blocks default to `OTHER` and are logged in `gold_conflicts.jsonl`
- evaluator fingerprints gold/prediction blockization metadata and fails with `gold_prediction_blockization_mismatch` when drift is severe enough to make block-level scoring misleading

Primary stage-block metrics:

- `strict_accuracy`
- `overall_block_accuracy`
- `macro_f1_excluding_other`
- `worst_label_recall`

Important diagnostics:

- `missed_gold_blocks.jsonl`
- `wrong_label_blocks.jsonl`
- `gold_conflicts.jsonl`

### 3.4 Canonical-text scoring contract

Current rules:

- prediction text is aligned against canonical gold text
- canonical scoring uses the enforced global SequenceMatcher alignment path for safety
- the sequence matcher is fixed to `dmp`; non-`dmp` modes are not an active benchmark surface
- canonical-text benchmark runs score the same canonical pointer pair used by all benchmark modes

Current line-role and knowledge behavior:

- `line-role-pipeline/` artifacts are written when line-role is enabled; prediction generation may set canonical scorer pointers to these projection artifacts for that run
- processed stage-backed artifacts still get written for the run; the regression fix was specifically to move the canonical scorer pointer pair to the projection artifacts instead of leaving scoring on the stage-backed pair
- when authoritative Stage 2 labels are reused, the scored line-role artifact pair still has to stay in canonical atomic-span coordinates:
  - `stage_block_predictions.json` should be serialized from canonical line-role projections, not copied from source blocks
  - `extracted_archive.json` should carry the matching atomic line coordinates and `line_role_projection` metadata
- those line-role artifacts now expose `decided_by`, `reason_tags`, and `escalation_reasons`; scalar trust/confidence fields are gone
- `08_nonrecipe_spans.json` is the authoritative Stage 7 ownership artifact for the scored outside-span `KNOWLEDGE` vs `OTHER` seam
- `09_knowledge_outputs.json` is the canonical run-level summary for optional knowledge extraction outputs
- prompt preview and live knowledge harvest both rebuild from the same compact `build_knowledge_jobs(...)` inputs
- prediction-run and eval diagnostics can emit:
  - `knowledge_manifest.json`
  - knowledge-merge changed-row diagnostics
  - knowledge-merge summary diagnostics

Canonical-text diagnostics commonly include:

- `aligned_prediction_blocks.jsonl`
- `missed_gold_lines.jsonl`
- `wrong_label_lines.jsonl`
- `missed_gold_blocks.jsonl`
- `wrong_label_blocks.jsonl`
- `joined_line_table.jsonl`
- legacy alias files such as `missed_gold_spans.jsonl` and `false_positive_preds.jsonl` are retired
- `line_role_flips_vs_baseline.jsonl`
- `slice_metrics.json`
- `knowledge_budget.json`
- `prompt_eval_alignment.md`

When `--line-role-gated` is enabled, canonical-text runs also write:

- `regression_gates.json`
- `regression_gates.md`

### 3.5 Replay and run manifests

Replay contract:

- `--predictions-out` writes `PredictionRecord` JSONL (`schema_kind=stage-block.v1`)
- `--predictions-in` supports evaluate-only replay from those prediction records only; older run-pointer records are rejected

Manifest contract:

- run-producing flows write `run_manifest.json`
- prediction/eval timing is surfaced in prediction manifests, `eval_report.json`, and benchmark run manifests

## 4. Upload Bundle And Follow-Up Contracts

`upload_bundle_v1` is the stable reviewer handoff.

Current written files:

- `upload_bundle_overview.md`
- `upload_bundle_index.json`
- `upload_bundle_payload.jsonl`

Current generation seams:

- `cookimport/bench/upload_bundle_v1_model.py`: normalized source/topology model
- `cookimport/bench/upload_bundle_v1_existing_output.py`: adapts existing benchmark roots into that model
- `cookimport/bench/upload_bundle_v1_render.py`: renders topology-tolerant bundle output

Current bundle rules:

- reviewer-facing topology should be derived from the normalized model, not guessed from path layout
- `analysis.recipe_pipeline_context` and `analysis.stage_separated_comparison` come from that model seam and expose semantic recipe stages (`recipe_topology_key`, ordered `recipe_stages`) instead of `pass2_stage` / `pass3_stage` compatibility fields
- current semantic recipe-stage values are:
  - `build_intermediate_det`
  - `recipe_llm_correct_and_link`
  - `build_final_recipe`
- `cookimport/bench/upload_bundle_v1_existing_output.py` should emit semantic recipe pipeline context only; do not add legacy recipe-topology compatibility metadata back into new bundles
- `cookimport/bench/followup_bundle.py` should resolve `knowledge_manifest_json` only for the live knowledge-manifest seam; old pass4 locator names belong only in archived/local compatibility code
- `scripts/benchmark_cutdown_for_external_ai.py` now treats semantic stage rows, `recipe_manifest.json` stage states, and `recipe_correction_audit` diagnostics as the primary existing-output contract; archived old-slot prompt rows are compatibility-only history input, not a new-output shape
- new cutdown and starter-pack outputs should write semantic `stage_key` values only. If archived prompt logs still carry `pass*` labels, normalize them in the read helper instead of synthesizing `pass*` fields back into current output
- knowledge extraction must surface explicitly through bundle analysis/index fields instead of being implied by generic prompt artifacts
- high-level multi-book bundles are intentionally size-capped first-look packets; heavier raw prompt dumps remain local for follow-up
- follow-up tooling may still accept historical local filenames when auditing archived bundles, but those are compatibility reads only and should not be reintroduced into new reviewer-facing bundle fields
- sparse bundles are valid first-class inputs:
  - request-template generation should choose a real bundle-local case when one exists
  - otherwise it should emit empty-selector asks that still let `cf-debug build-followup` succeed
  - `--include-knowledge-source-key` should resolve through bundle-local knowledge rows even when the bundle has no Codex-enabled paired run
- checked-in old-format bundle fixtures should be normalized in tests before running current `cf-debug` paths; production readers should not grow new compatibility branches just to satisfy stale fixtures

Oracle upload contract:

- the user-facing target can be a session root or an `upload_bundle_v1/` directory
- the actual upload code attaches the three concrete bundle files
- `--mode dry-run` uses Oracle dry-run when possible and falls back to a local preview when the payload file is too large

## 5. Speed And Quality Suite Notes

### 5.1 SpeedSuite

SpeedSuite is the deterministic runtime-regression loop:

1. `cookimport bench speed-discover`
2. `cookimport bench speed-run --suite ...`
3. `cookimport bench speed-compare --baseline ... --candidate ...`

Current active scenarios:

- `stage_import`
- `benchmark_canonical_pipelined`
- `benchmark_all_method_multi_source`

Current notes:

- task-level concurrency is bounded with `--max-parallel-tasks`
- worker availability fallback is allowed unless `--require-process-workers` is used
- baseline/candidate compare gates use both a percentage threshold and an absolute seconds floor

### 5.2 QualitySuite

QualitySuite is the deterministic quality-regression loop:

1. `cookimport bench quality-discover`
2. `cookimport bench quality-run --suite ... --experiments-file ...`
3. `cookimport bench quality-leaderboard --run-dir ... --experiment-id ...`
4. `cookimport bench quality-compare --baseline ... --candidate ...`

Current notes:

- `quality-run --search-strategy race` is the active default
- `quality-run --search-strategy exhaustive` still exists for full-grid runs
- experiment fanout is CPU-aware by default and can be overridden with `--max-parallel-experiments`
- WSL safety guard behavior is active by default and recorded in `experiments_resolved.json`
- output write pacing is on by default and can be disabled with `--io-pace-every-writes 0` or `--io-pace-sleep-ms 0`
- crash-safe checkpoints live under the run root and can be resumed with `--resume-run-dir`
- QualitySuite keeps two truths when normalizing experiments:
  - `requested_run_settings`
  - executable normalized `run_settings`

Active quality comparison gates:

- strict F1 drop threshold
- practical F1 drop threshold
- source success-rate drop threshold

## 6. Artifact Retention And Cleanup

`bench gc` is the active benchmark-retention tool.

Current rules:

- dry-run is the default; `--apply` is required to delete files
- benchmark roots are pruned only when CSV durability is already present
- `performance_history.csv` is not rewritten by GC
- optional label-studio benchmark pruning covers `data/golden/benchmark-vs-golden/*`
- matching processed outputs under `data/output/<run_id>/` can also be pruned when explicitly requested
- any root containing `.gc_keep*`, `.keep`, or `.pinned` is retained
- pytest temp eval fixtures are excluded so tests can inspect artifacts after command completion

## 7. Retired Surfaces

The following are no longer active benchmark workflows and should not be treated as current guidance:

- tournament-based QualitySuite promotion workflows
- `scripts/quality_top_tier_tournament.py`
- `bench run`, `bench sweep`, `bench validate`, and `bench knobs`
- canonical fast-alignment production scoring

`bench quality-lightweight-series` still exists only to fail fast with a retired message for old scripts and operator muscle memory.

## 8. Core Code Map

Primary benchmark modules:

- `cookimport/cli.py`: bench and `labelstudio-benchmark` command wiring, interactive benchmark flows, GC/pin/oracle-upload entrypoints
- `cookimport/bench/CONVENTIONS.md`: durable benchmark contracts inside the code folder
- `cookimport/bench/eval_stage_blocks.py`: stage-block scoring
- `cookimport/bench/eval_canonical_text.py`: canonical-text scoring and alignment telemetry
- `cookimport/bench/canonical_alignment_cache.py`: shared canonical alignment cache
- `cookimport/bench/prediction_records.py`: replay record schema/helpers
- `cookimport/bench/speed_suite.py`, `speed_runner.py`, `speed_compare.py`: SpeedSuite
- `cookimport/bench/quality_suite.py`, `quality_runner.py`, `quality_compare.py`, `quality_leaderboard.py`: QualitySuite
- `cookimport/bench/artifact_gc.py`: benchmark retention and pruning
- `cookimport/bench/oracle_upload.py`: Oracle upload wrapper for existing bundles
- `cookimport/bench/followup_bundle.py`: follow-up packet helpers used by `cf-debug`
- `scripts/benchmark_cutdown_for_external_ai.py`: existing-output external-review packet builder over semantic stage rows plus current recipe manifests/audits

## 9. See Also

- `docs/07-bench/07-bench_log.md`
- `docs/07-bench/qualitysuite-agent-sop.md`
- `docs/07-bench/qualitysuite-product-suite.md`
- `docs/07-bench/web-ai-followup-instructions.md`
- `cookimport/bench/README.md`
- `cookimport/bench/CONVENTIONS.md`
