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
- shard-based recipe runtimes must reconcile per-recipe ownership from shard payload recipe ids and raw `recipe_manifest.json`; shard call ids are not recipe ids for upload-bundle span/stage summaries

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

Interactive benchmark wrap-up behavior:

- Single-offline benchmark runs now auto-start Oracle in the background after writing `upload_bundle_v1`, then return immediately instead of waiting on Oracle.
- Multi-book single-profile benchmark runs do the same for the top-level group `upload_bundle_v1`; per-book bundles are still written but are not auto-uploaded.
- Detached Oracle runs write `oracle_upload.log`, `oracle_upload.json`, and `oracle_upload_status.json` under `upload_bundle_v1/.oracle_upload_runs/<timestamp>/`. The actual Oracle response, if the run succeeds, is in `oracle_upload.log`. When the log stays quiet, the wrapper now also falls back to Oracle's own session store under `~/.local/share/oracle/sessions/` to recover the session slug and conversation URL.
- That detached launch directory is also the persistent staging root for any temporary sharded upload files, so the Oracle subprocess can keep reading them after benchmark wrap-up returns.
- Detached benchmark uploads now also launch a local follow-up worker in the same source run directory. It finalizes the saved turn-1 `oracle_upload_status.json` from the completed Oracle log, writes `oracle_auto_followup.json` plus `oracle_auto_followup.log`, and if Oracle requested follow-up data it automatically builds `followup_data1/` and sends turn 2 into the same ChatGPT conversation.
- Interactive terminal wrap-up should stay short and point operators at `oracle_upload.log`, but it should also surface the current Oracle status, `oracle session <id>` reattach command, and conversation URL when available; detailed launch metadata already lives beside it in the same launch directory.
- `cookimport bench oracle-upload <session root or upload_bundle_v1>` remains the manual retry/replay path, and browser-mode manual runs now persist the same `upload_bundle_v1/.oracle_upload_runs/<timestamp>/` artifact set as the auto-background uploader.
- benchmark-side Oracle upload now calls the canonical local Oracle wrapper at `/home/mcnal/.local/bin/oracle`, which in turn routes browser runs through the Oracle-owned wrapper stack and the editable `oracle-dev/package` mirror before falling back to the global install.
- the default Oracle browser model target for benchmark upload now follows `ORACLE_GENUINE_MODEL` and currently falls back to `gpt-5.4`; `ORACLE_PRO_MODEL`, `ORACLE_REVIEW_MODEL`, and `ORACLE_DEEP_REVIEW_MODEL` remain compatibility aliases, and `--model ...` is still the manual override seam.
- benchmark-side Oracle upload also passes hidden Oracle browser recovery flags (`--browser-reuse-wait`, `--browser-profile-lock-timeout`, `--browser-auto-reattach-*`) and honors `COOKIMPORT_ORACLE_CHATGPT_URL` when set so benchmark uploads can target a dedicated ChatGPT project URL.
- benchmark-side Oracle browser uploads still stage the logical bundle files (`upload_bundle_overview.md`, `upload_bundle_index.json`, and any payload shards), but with `--browser-bundle-files` Oracle may deliver them to ChatGPT as one synthetic attachment such as `attachments-bundle.txt`; the benchmark prompt now says that explicitly so the UI-level attachment shape matches the instructions.
- the default post-benchmark Oracle review prompt is now read from [benchmark.oracle-upload.prompt.md](/home/mcnal/projects/recipeimport/llm_pipelines/prompts/benchmark.oracle-upload.prompt.md). Text-only edits should happen there, not in Python. Keep the placeholder tokens `{{HELPER_BANNER}}`, `{{BUNDLE_SCOPE}}`, and `{{BENCHMARK_ROOT}}` intact so runtime can inject the current bundle metadata; helper-only pytest uploads use `{{HELPER_BANNER}}` to stamp the chat as disposable test traffic.
- that default Oracle review prompt now also teaches the reviewer how to request narrow follow-up evidence in a parse-friendly text format: prefer exact artifacts or row-locator-backed slices and use the `Requested follow-up data` section to ask for the smallest `cf-debug`-style packet that would test the current hypotheses.
- benchmark helper tests now run under a helper-only Oracle policy: if they launch a real benchmark-review chat, the shared helper fixture forces the Oracle test lane (`ORACLE_TEST_MODEL`, intended to track Instant) and stamps the prompt with `TEST HELPER ONLY` so the chat is unmistakably disposable test traffic rather than a genuine review run.
- `cookimport bench oracle-followup <session root or upload_bundle_v1>` remains the manual turn-2 seam. The detached benchmark path now invokes the same logic automatically after a grounded turn-1 answer, but the command is still the repair/replay path and `--dry-run` still stops after the local workspace is written.
- benchmark-side Oracle trust does not come from exit code alone anymore: the wrapper audits the saved answer against the local bundle root and topline counts and can mark a completed run as `invalid_grounding`.

Important current constraints:

- `bench quality-run` is deterministic-only. It rejects `--include-codex-farm`, Codex CLI overrides, and requested settings that enable live Codex recipe or knowledge surfaces.
- `bench speed-run --include-codex-farm` is still allowed, but it requires `--speedsuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION` and is blocked in agent-run shells.
- `bench quality-run` and `bench speed-run` both support crash-safe resume via `--resume-run-dir`.
- `bench quality-run` emits `agent_compare_control/` by default. `bench quality-compare` does the same for comparisons.
- `bench quality-discover` prefers curated CUTDOWN ids first:
  - `saltfatacidheatcutdown`
  - `thefoodlabcutdown`
  - `seaandsmokecutdown`
  - `dinnerfor2cutdown`
  - `roastchickenandotherstoriescutdown`
- `bench quality-lightweight-series` remains only as a disabled stub. It exits immediately and is not an active workflow.
- `bench gc` is benchmark-only retention, not a general `data/output` sweeper. It can prune matching benchmark-generated processed-output roots while preserving `performance_history.csv` and refusing destructive cleanup when durable history checks fail.

### 2.2 `cookimport labelstudio-benchmark`

`labelstudio-benchmark` is the active single-run benchmark primitive. It supports:

- action `run` or `compare`
- `--eval-mode stage-blocks|canonical-text`
- `--predictions-out` / `--predictions-in` for replayable evaluation-only reruns
- `--baseline` / `--candidate` compare inputs
- offline runs via `--no-upload`
- zero-token Codex handoff rehearsal by pointing `--codex-farm-cmd` at `scripts/fake-codex-farm.py`

Current behavior notes:

- default eval mode is `stage-blocks`
- `stage-blocks` forces `line_role_pipeline=off` and `atomic_block_splitter=off`
- canonical-text runs can enable:
  - `atomic_block_splitter=atomic-v1`
  - `line_role_pipeline=off|codex-line-role-shard-v1`
  - `llm_knowledge_pipeline=codex-knowledge-shard-v1`
- non-interactive live Codex-backed benchmark runs require:
  - `--allow-codex`
  - `--benchmark-codex-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION`
- agent-run environments are blocked from that live non-interactive Codex path; use prompt preview or a fake-codex-farm rehearsal instead
- knowledge-phase progress now reports task packets rather than top-level shard counts, and worker rows can show packet-scale labels such as `book.ks0000.nr (47/48 task packets)`
- interrupted benchmark runs now write `partial_benchmark_summary.json` plus `benchmark_status.json` so the preserved worker/artifact tree stays diagnosable after an abort
- interrupted benchmark runs now also record `interruption_cause = "operator"` in both files, and when the prediction run contains `raw/llm/<workbook>/knowledge/stage_status.json` the partial summary carries forward the normalized knowledge-stage attribution instead of treating missing wrap-up artifacts as generic failure by default

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
- benchmark manifests now surface both `full_prompt_log_rows` and `full_prompt_log_runtime_shard_count`; use the shard count for real shard-job volume and treat row count as reviewer-log volume only
- benchmark status panels now treat generic `task X/Y | running N` progress strings as worker activity, so shard-backed line-role and similar phases do not collapse back to one stale status line
- knowledge-stage benchmark progress is now packet-based rather than shard-based: the visible `task X/Y` counter tracks knowledge task packets, while the worker rows stay worker-based and show shard ownership plus packet counts or an active follow-up label such as repair/watchdog retry
- single-profile matched-book runs write under `.../single-profile-benchmark/`
- multi-book single-profile runs also emit one top-level group `upload_bundle_v1/`
- interactive single-offline writes its session bundle, auto-starts Oracle in the background, and returns immediately without blocking benchmark wrap-up
- multi-book single-profile writes the top-level group bundle and leaves Oracle upload as a separate manual step

### 2.3 `cf-debug`

`cf-debug` is the deterministic follow-up CLI that operates on an existing `upload_bundle_v1`.

Active use cases:

- build a request template for external reviewers
- export one bundle-wide structure-vs-nonrecipe score split
- select/export concrete cases from the base bundle
- audit line-role joins and prompt links
- audit knowledge-stage evidence
- build additive `followup_dataN/` packets

Knowledge extraction is now a first-class follow-up seam:

- selectors can target knowledge source keys/output subdirs explicitly
- `audit-knowledge` emits run-level knowledge evidence
- follow-up packets can include `knowledge_audit.jsonl`
- uncertainty/follow-up exports now center on explicit escalation reasons; current reviewer packets do not carry scalar trust/confidence fields

Structure-only triage is now a first-class follow-up seam:

- `structure-report` writes one bundle-wide `structure_report.json`
- the report separates `structure_core` labels (`RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `HOWTO_SECTION`, `YIELD_LINE`, `TIME_LINE`) from `nonrecipe_core` (`KNOWLEDGE`, `OTHER`)
- it also includes boundary exactness so reviewers can tell whether a low score is mostly a segmentation problem or a label-semantics problem
- high canonical boundary/alignment scores do not imply near-perfect overall accuracy; current single-offline misses can still be dominated by hard `KNOWLEDGE` vs `OTHER` disagreements even when recipe boundaries are mostly correct

Benchmark transport note:
- benchmark-mode recipe subprocesses now use CodexFarm's current flag name `--recipeimport-benchmark-mode line_label_v1`; the retired `--benchmark-mode` flag is no longer part of the active contract

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
- new-format prediction/eval manifests and import return payloads do not publish separate line-role scorer keys anymore; helpers should fail on missing canonical pointers instead of probing older fallback filenames or implicit directories

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
- when the benchmark reuses authoritative Stage 2 recipe-local labels, the scored line-role artifact pair still has to stay in canonical atomic-span coordinates:
  - `stage_block_predictions.json` is serialized from canonical line-role projections, not copied from source blocks
  - `extracted_archive.json` carries the matching atomic line coordinates and `line_role_projection` metadata
  - outside-recipe `KNOWLEDGE` versus `OTHER` labels in that projection must come from the final non-recipe authority, not the pre-knowledge seed
- those line-role artifacts now expose `decided_by`, `reason_tags`, and `escalation_reasons`; scalar trust/confidence fields are gone
- `08_nonrecipe_spans.json` is the authoritative scored outside-span contract; it contains both the deterministic seed and the final post-knowledge authority
- `09_knowledge_outputs.json` is the canonical run-level summary for optional knowledge refinement plus snippet outputs
- prompt preview and live knowledge harvest both rebuild from the same compact `build_knowledge_jobs(...)` inputs
- knowledge worker manifests and per-shard status files may now end with explicit knowledge-runtime reason codes such as `workspace_outputs_stabilized`, `watchdog_malformed_final_output`, or `watchdog_retry_oversized_skipped`; these mean the worker stopped after stabilized owned outputs, a strict retry emitted malformed pseudo-final JSON, or a multi-chunk oversized watchdog retry was intentionally skipped
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
- older alias files such as `missed_gold_spans.jsonl` and `false_positive_preds.jsonl` are retired
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
- bundle recipe-pipeline context now also carries `runtime_runs[*].runtime_stages` so reviewer packets can show shard-worker counts without inventing a second upload format

Current bundle rules:

- reviewer-facing topology should be derived from the normalized model, not guessed from path layout
- `analysis.recipe_pipeline_context` and `analysis.stage_separated_comparison` come from that model seam and expose semantic recipe stages (`recipe_topology_key`, ordered `recipe_stages`) instead of older numbered stage fields
- current semantic recipe-stage values are:
  - `build_intermediate_det`
  - `recipe_llm_correct_and_link`
  - `build_final_recipe`
- `cookimport/bench/upload_bundle_v1_existing_output.py` should emit semantic recipe pipeline context only; do not add older recipe-topology metadata back into new bundles
- `cookimport/bench/followup_bundle.py` should resolve `knowledge_manifest_json` only for the live knowledge-manifest seam; older knowledge-stage locator names belong only in archived/local reader code
- `scripts/benchmark_cutdown_for_external_ai.py` now treats semantic stage rows, `recipe_manifest.json` stage states, and `recipe_correction_audit` diagnostics as the primary existing-output contract; archived prompt rows with numbered stage labels are history input only, not a new-output shape
- existing-output bundle discovery must prefer current run-local artifact roots before older inferred layouts:
  - prompt logs and prompt samples from `<run>/prompts/`
  - prompt budget summaries from `<run>/prompt_budget_summary.json` or `<run>/prediction-run/prompt_budget_summary.json`
  - knowledge manifests from either prediction-run raw LLM outputs or processed-output `raw/llm/*/knowledge_manifest.json`
  - when a required knowledge manifest lives outside the session root, the bundle should mirror it into a derived payload row so `navigation.row_locators.knowledge_by_run` still resolves bundle-locally
- upload-bundle runtime snapshots should prefer row-level prompt telemetry when it is present, but they must fall back to aggregate prompt-budget stage totals when archived/full-prompt rows are missing token coverage or omit whole stages such as `line_role`
- new cutdown and starter-pack outputs should write semantic `stage_key` values only. If archived prompt logs still carry `pass*` labels, normalize them in the read helper instead of synthesizing `pass*` fields back into current output
- knowledge extraction must surface explicitly through bundle analysis/index fields instead of being implied by generic prompt artifacts
- high-level multi-book bundles are intentionally size-capped first-look packets; heavier raw prompt dumps remain local for follow-up
- follow-up tooling may still accept historical local filenames when auditing archived bundles, but those are archived-reader inputs only and should not be reintroduced into new reviewer-facing bundle fields
- sparse bundles are valid first-class inputs:
  - request-template generation should choose a real bundle-local case when one exists
  - otherwise it should emit empty-selector asks that still let `cf-debug build-followup` succeed
  - `--include-knowledge-source-key` should resolve through bundle-local knowledge rows even when the bundle has no Codex-enabled paired run
- checked-in old-format bundle fixtures should be normalized in tests before running current `cf-debug` paths; production readers should not grow new reader branches just to satisfy stale fixtures

Oracle upload contract:

- the user-facing target can be a session root or an `upload_bundle_v1/` directory
- the actual upload code targets the three concrete bundle files; browser uploads may temporarily shard oversized files into ordered `partNNN` attachments to get past Oracle's per-file cap without changing the on-disk bundle format
- the browser upload path now enters through the canonical local Oracle wrapper at `/home/mcnal/.local/bin/oracle`; the browser wrapper layer still uses one machine-wide auto Chromium launcher, `/home/mcnal/.local/bin/chromium-oracle-auto`, plus `ORACLE_BROWSER_REMOTE_DEBUG_HOST=127.0.0.1`
- that launcher opens visible Chromium when a usable display exists and falls back to `chromium-nosandbox-xvfb` otherwise, so the same benchmark upload path works both from interactive shells and from the agent shell
- browser uploads use the canonical Oracle browser profile at `~/.local/share/oracle/browser-profile`; the legacy `~/.oracle/browser-profile` path is now only a compatibility symlink to that same directory
- browser uploads now pass `--browser-model-strategy ignore`, so Oracle stops failing on stale picker labels and leaves the current/manual ChatGPT model alone instead of trying to auto-switch it
- `--mode dry-run` uses Oracle dry-run when possible and falls back to a local preview when the payload file is too large
- transport sharding is strictly upload-time glue for oversized text files such as `upload_bundle_payload.jsonl`; checked-in and local `upload_bundle_v1` artifacts should stay unmodified on disk
- benchmark status rendering treats generic `task X/Y | running N` updates as first-class worker-row signals, and plain legacy `run=... queued=... running=...` stderr snapshots are compatibility noise when structured progress is already present

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

## 10. Recent Durable Notes

- In canonical-text benchmarking, `eval_report.json -> per_label.RECIPE_TITLE` is the title-label metric. `eval_report.json -> recipe_counts.predicted_recipe_count` is a separate import-level recipe total and can diverge sharply.
- When post-refactor CodexFarm canonical-text quality drops toward vanilla, inspect the `KNOWLEDGE` seam first. Stage 7 deterministic labels now own outside-recipe `KNOWLEDGE` vs `OTHER`, so optional knowledge harvest no longer relabels benchmark truth.
- Single-offline benchmark folder naming is about Codex participation, not every deterministic helper. A run with recipe Codex off and only deterministic line-role still belongs under `vanilla/`; only actual Codex-backed line-role belongs in the Codex/hybrid branch.
- High Codex recipe task counts in single-offline runs usually mean grouped recipe-span overproduction upstream, not retry storms inside CodexFarm.
- Tiny line-role token spend in a Codex single-offline run does not mean line-role was skipped; older helper paths only sent escalated rows to live Codex and then scored a projected artifact built from authoritative outputs.
- Canonical benchmark scoring should project final non-recipe authority, not just deterministic seed labels. The current contract is seed deterministic authority plus optional knowledge-stage refinement merged into final scored `KNOWLEDGE` / `OTHER`.
- Benchmark prompt export should include every CodexFarm interaction the reviewer cares about:
  - recipe correction
  - line-role prompt artifacts copied from `line-role-pipeline/prompts`
  - knowledge harvest
- Reviewer-facing trace summaries should be derived from the merged `prompts/full_prompt_log.jsonl`, not from a second raw-trace discovery path.
- Oracle shared-profile browser failures can look like a fresh-port `ECONNREFUSED` problem even when Chromium is already alive. If upload starts failing after bundle generation succeeds, inspect shared-profile reuse (`DevToolsActivePort`, stale `chrome.pid`, singleton locks, canonical browser profile) before redesigning the bundle or upload flow.
- Benchmark Oracle upload trust is now multi-layered:
  - empty-composer or launch failures should fail fast
  - in-flight runs should persist `oracle_upload_status.json`, session id, reattach command, and conversation URL as early as possible
  - completed answers that contradict the local bundle root or topline counts should be treated as `invalid_grounding`, not silent success
- When validating Codex benchmark regressions, do not over-trust a stale run root after runtime/prompt changes land. The March 18 Salt Fat Acid Heat work established that some fixes were code-complete locally while live benchmark proof was still pending explicit approval for a fresh rerun.
