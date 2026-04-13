---
summary: "Current benchmark-suite reference for cookimport bench and related benchmark flows."
read_when:
  - When running or modifying cookimport bench workflows
  - When debugging benchmark scoring behavior or artifacts
  - When comparing stage-blocks versus canonical-text evaluation modes
---

# Bench Section Reference

This file is the current, code-verified benchmark contract.
QualitySuite operator notes live in `docs/07-bench/qualitysuite-agent-sop.md`.

## 1. Scope

Benchmarking in this repo has three active surfaces:

- `cookimport bench ...` for deterministic speed, quality, retention, and upload-bundle workflows
- `cookimport labelstudio-benchmark` for single-run benchmark generation/eval plus the interactive benchmark modes
- `cf-debug ...` for deterministic follow-up packets built on top of `upload_bundle_v1`

Current owner note for large benchmark helpers:

- `cookimport/cli_support/bench_all_method.py` remains the orchestration root, but target discovery now lives in `bench_all_method_targets.py`, variant/codex matrix building in `bench_all_method_variants.py`, source-estimation/job planning plus scheduler/runtime planning and process-pool probing in `bench_all_method_scheduler.py`, split-cache/prediction-reuse/eval-signature helpers in `bench_cache.py`, QualitySuite compare-control bridge writing in `bench_all_method_qualitysuite.py`, and dashboard/report rendering in `bench_all_method_reporting.py`.
  The extracted owner modules now import their real dependencies explicitly and only resolve patch-sensitive root hooks at call time; they no longer clone the full `bench` helper namespace into themselves.
- `scripts/benchmark_cutdown_for_external_ai.py` remains the public wrapper, but deterministic run discovery, prompt/prediction/processed-output artifact-path resolution, per-run cutdown assembly and existing-run record hydration, root README/flattened-summary generation, prompt-row excerpt/scoring helpers for pair diagnostics, pair-diagnostics/comparison-summary aggregation, starter-pack recipe selection/casebook/readme helpers plus the heavier starter-pack assembly writer, `full_prompt_log.jsonl` reconstruction, recipe-span projection/line-prediction views, prompt-response warning/correction interpretation, wrong-label/preprocess compressed packet generation, projection-trace/alignment-health helpers, JSON/JSONL/clipping helpers, prompt-log sampling, project-context digest rendering, and canonical-line sampling helpers now start in `cookimport/bench/external_ai_cutdown/`.
- the shared per-book cache now lives below the benchmark helpers in `cookimport/staging/deterministic_prep.py` and `cookimport/staging/book_cache.py`. Interactive single-book shard suggestions, single-book benchmark variants, single-profile matched-book runs, and later stage reruns can all point at the same repo-level cache root (`.cache/cookimport/book-cache/` by default) instead of rebuilding whole-book conversion, deterministic prep, and prompt-preview state independently.

Current scoring modes:

- `stage-blocks`: compare stage evidence labels against freeform gold block labels
- `canonical-text`: align prediction text to canonical gold text and score per canonical line
- canonical-text scoring now projects gold spans to lines without title-specific rewrites. If exported gold contains suspicious patterns such as inline `RECIPE_TITLE`/`RECIPE_VARIANT` subspans inside `OTHER` prose or `RECIPE_TITLE` lines without nearby recipe structure, the evaluator surfaces those as `gold_projection_warnings.jsonl` so the gold can be fixed directly instead of silently normalized during scoring.

Current benchmark handoff model:

- `upload_bundle_v1` is the primary external-review packet
- follow-up requests should produce additive `followup_dataN/` packets, not replacement bundle formats
- shard-based recipe runtimes must reconcile per-recipe ownership from shard payload recipe ids and raw `recipe_manifest.json`; shard call ids are not recipe ids for upload-bundle span/stage summaries
- `cookimport/cli_support/bench.py` is now only the benchmark facade; start in `bench_single_book.py`, `bench_single_profile.py`, `bench_all_method.py`, `bench_oracle.py`, `bench_artifacts.py`, or `bench_cache.py` depending on the workflow you are changing

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
- `bench gc`: prune old benchmark artifacts, keep only the newest five Label Studio benchmark runs by default, and wipe timestamped `data/output` run roots while preserving non-run folders
- `bench pin` / `bench unpin`: add or remove GC keep sentinels
- `bench oracle-upload`: upload an existing `upload_bundle_v1` to Oracle without rerunning the benchmark; defaults to both review lanes and accepts `--profile quality|token|all`
- `bench oracle-followup`: build a follow-up packet from an Oracle review and continue the same chat

Interactive benchmark wrap-up behavior:

- Single-book benchmark runs now auto-start Oracle in the background after writing `upload_bundle_v1`, then return immediately instead of waiting on Oracle.
- Multi-book single-profile benchmark runs do the same for the top-level group `upload_bundle_v1`; per-book bundles are still written but are not auto-uploaded.
- Detached Oracle runs now fan out into two review lanes by default: `quality` and `token`. The durable handoff packet is `upload_bundle_v1/quality/{overview.md,index.json,payload.json}` and the same three files under `upload_bundle_v1/token/`.
- Those lane-local Oracle packets are now the only supported turn-1 handoff contract. They are always compact, summary-first packets: `index.json` is a bounded review index rather than a clone of the full root analysis tree, and `payload.json` is a curated evidence packet with digested heavy artifacts instead of raw literal dumps.
- Oracle runtime logs/status moved out of the handoff folder into a sibling `.oracle_upload_runs/<timestamp>-<profile>/` directory under the benchmark root. The actual Oracle response, if the run succeeds, is still in that lane's `oracle_upload.log`. When the log stays quiet, the wrapper also falls back to Oracle's own session store under `~/.local/share/oracle/sessions/` to recover the session slug and conversation URL.
- Detached benchmark uploads now also launch a local follow-up worker in the same per-lane source run directory. It finalizes the saved turn-1 `oracle_upload_status.json` from the completed Oracle log, writes `oracle_auto_followup.json` plus `oracle_auto_followup.log`, and if Oracle requested follow-up data it automatically builds `followup_data1/` and sends turn 2 into the same ChatGPT conversation.
- turn-1 timeout recovery now appends any reattached Oracle answer back into the original `oracle_upload.log` before the follow-up worker re-audits it, and automatic turn 2 may proceed from either a grounded turn-1 answer or an `invalid_grounding` answer when Oracle explicitly requested follow-up data to resolve the mismatch.
- turn-1 recovery is now deliberately broader than explicit `assistant-timeout`: if the saved lane is still `running` after the grace window, the follow-up worker will also attempt one bounded `oracle session <id>` recovery when the saved controller PID is gone or when ChatGPT already shows a visible answer but Oracle never finalized the lane state.
- if a benchmark Oracle lane stays `running` long past launch time, the follow-up worker now does one bounded `oracle session <id>` recovery attempt even when the saved controller PID is still alive; this covers the case where ChatGPT already shows the answer but Oracle never promoted the run into explicit `assistant-timeout`.
- same-chat Oracle turn 2 now reuses the concrete turn-1 browser model when that launch metadata is available, so automatic follow-ups stay on the same ChatGPT model instead of drifting to the shared browser profile's current picker state; operator `--model` overrides still win and are translated into browser-visible picker labels before calling `oracle continue-session`.
- Interactive terminal wrap-up should stay short and point operators at `oracle_upload.log`, but it should also surface the current Oracle status, `oracle session <id>` reattach command, and conversation URL when available; detailed launch metadata already lives beside it in the same launch directory.
- `cookimport bench oracle-upload <session root or upload_bundle_v1>` remains the manual retry/replay path, now with `--profile quality|token|all` (`all` default), and browser-mode manual runs persist the same sibling `.oracle_upload_runs/<timestamp>-<profile>/` artifact set as the auto-background uploader.
- benchmark-side Oracle upload now calls the fork-owned launcher at `/home/mcnal/projects/shared/oracle-fork/scripts/wsl/oracle-runtime.sh`, so benchmark browser runs execute the built `oracle-fork` runtime directly instead of the old `~/.local/bin/oracle` wrapper stack.
- the Oracle benchmark wrapper now speaks in semantic lanes first: default operator review is `pro`, helper/test review is `instant`, and `thinking` is an explicit opt-in lane instead of the default policy. `--model ...` accepts those selectors or a literal Oracle model id as a low-level escape hatch. The final Oracle command still receives one concrete model string, resolved only from `ORACLE_PRO_MODEL`, `ORACLE_INSTANT_MODEL`, and `ORACLE_THINKING_MODEL`.
- benchmark-side Oracle upload also passes hidden Oracle browser recovery flags (`--browser-reuse-wait`, `--browser-profile-lock-timeout`, `--browser-auto-reattach-*`) and now passes `--chatgpt-url https://chatgpt.com/` by default so successful benchmark review chats stay visible in normal ChatGPT history; `COOKIMPORT_ORACLE_CHATGPT_URL` still overrides that when you want a dedicated ChatGPT project URL or another explicit target.
- benchmark-side Oracle browser uploads stage the lane-local logical files (`overview.md`, `index.json`, and a temporary trimmed `payload.json` or payload shards), but with `--browser-bundle-files` Oracle may still deliver them to ChatGPT as one synthetic attachment such as `attachments-bundle.txt`; the benchmark prompt says that explicitly so the UI-level attachment shape matches the instructions.
- turn-1 Oracle packet sizing is now enforced by packet shape, not by alternate bundle versions: the quality and token lanes should stay around the low-hundreds-of-kilobytes range, and heavier benchmark evidence should move to deterministic follow-up packets instead of re-bloating turn 1.
- benchmark-side Oracle browser upload now passes `--browser-model-strategy select`, so the wrapper explicitly switches ChatGPT to the requested benchmark review model instead of inheriting the current browser mode.
- benchmark-side Oracle turn 1 uploads and same-chat turn 2 follow-ups no longer pass a negated keep-browser flag; the installed Oracle CLI only accepts the positive `--browser-keep-browser` form, and default behavior already closes the controller after completion.
- when a lane `payload.json` is oversized and its `index.json` has navigation row locators, benchmark-side Oracle browser upload prefers a compact first-pass starter-pack subset built from the lane's selected logical paths instead of fan-out sharding the full payload; the prompt tells Oracle that attached payload-row `path` values are real and full sharding remains the fallback when the trimmed lane packet is still too large.
- the post-benchmark Oracle review prompts are now read from [benchmark.oracle-upload.prompt.md](/home/mcnal/projects/recipeimport/llm_pipelines/prompts/benchmark.oracle-upload.prompt.md) for `quality` and [benchmark.oracle-upload.token.prompt.md](/home/mcnal/projects/recipeimport/llm_pipelines/prompts/benchmark.oracle-upload.token.prompt.md) for `token`. Text-only edits should happen there, not in Python. Keep the placeholder tokens `{{HELPER_BANNER}}`, `{{BUNDLE_SCOPE}}`, and `{{BENCHMARK_ROOT}}` intact so runtime can inject the current bundle metadata; helper-only pytest uploads use `{{HELPER_BANNER}}` to stamp the chat as disposable test traffic.
- both Oracle review prompts teach the reviewer how to request narrow follow-up evidence in a parse-friendly text format: prefer exact artifacts or row-locator-backed slices and use the `Requested follow-up data` section to ask for the smallest `cf-debug`-style packet that would test the current hypotheses.
- benchmark helper tests now run under a helper-only Oracle policy: if they launch a real benchmark-review chat, the shared helper fixture forces the `instant` lane and stamps the prompt with `TEST HELPER ONLY` so the chat is unmistakably disposable test traffic rather than a genuine review run.
- `cookimport bench oracle-followup <session root or upload_bundle_v1>` remains the manual turn-2 seam. The detached benchmark path now invokes the same logic automatically after a grounded turn-1 answer, but the command is still the repair/replay path and `--dry-run` still stops after the local workspace is written.
- benchmark-side Oracle trust does not come from exit code alone anymore: the wrapper audits the saved answer against the local bundle root and topline counts and can mark a completed run as `invalid_grounding`.

Important current constraints:

- `bench quality-run` is deterministic-only. It rejects `--include-codex-farm`, Codex CLI overrides, and requested settings that enable live Codex recipe or knowledge surfaces.
- `bench speed-run --include-codex-farm` is still allowed, but it requires `--speedsuite-codex-farm-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION` and is blocked in agent-run shells.
- `bench quality-run` and `bench speed-run` both support crash-safe resume via `--resume-run-dir`.
- `cookimport/bench/qualitysuite/runtime.py` and `cookimport/bench/qualitysuite/worker_cli.py` own the active QualitySuite run/worker surface.
- `bench quality-run` emits `agent_compare_control/` by default. `bench quality-compare` does the same for comparisons.
- `bench quality-discover` prefers curated CUTDOWN ids first:
  - `saltfatacidheatcutdown`
  - `thefoodlabcutdown`
  - `seaandsmokecutdown`
  - `dinnerfor2cutdown`
  - `roastchickenandotherstoriescutdown`
- `bench gc` now has a split retention policy: quality/speed roots still require durable CSV confirmation, Label Studio benchmark roots under `data/golden/benchmark-vs-golden/*` keep only the newest five by default, and timestamped `data/output/<run_id>/` roots are wiped by default while preserving non-run folders such as `data/output/history/dashboard`.

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
  - `line_role_pipeline=off|codex-line-role-route-v2`
  - `llm_knowledge_pipeline=codex-knowledge-candidate-v2`
- benchmark/operator defaults now keep `atomic_block_splitter=off` unless it is explicitly requested
- shared deterministic-prep reuse may still feed both vanilla and codex benchmark variants, but only variants whose `line_role_pipeline` matches the bundle may reuse its authoritative line-role outputs; codex line-role variants must not inherit a vanilla prep bundle
- non-interactive live Codex-backed benchmark runs require:
  - `--allow-codex`
  - `--benchmark-codex-confirmation I_HAVE_EXPLICIT_USER_CONFIRMATION`
- agent-run environments are blocked from that live non-interactive Codex path; use prompt preview or a fake-codex-farm rehearsal instead
- knowledge-phase progress now reports task packets rather than top-level shard counts, and worker rows can show packet-scale labels such as `book.ks0000.nr (47/48 task packets)`
- interrupted benchmark runs now write `partial_benchmark_summary.json` plus `benchmark_status.json` so the preserved worker/artifact tree stays diagnosable after an abort
- interrupted benchmark runs now also record `interruption_cause = "operator"` in both files, and when the prediction run contains `raw/llm/<workbook>/nonrecipe_finalize/stage_status.json` the partial summary carries forward the normalized knowledge-stage attribution instead of treating missing wrap-up artifacts as generic failure by default
- benchmark prediction runs now build `stage_observability.json` against the real `processed_output_run_dir` when that output tree lives outside the benchmark bundle root, so stage summaries and upload-bundle readers still see recipe/line-role/knowledge artifacts in `codex-exec` single-book runs
- benchmark-side actual-cost review should now use the finished recipe / knowledge / line-role rows in `prompt_budget_summary.json` when asking whether spend came from main `taskfile` workers or from repo-owned follow-up/finalization; those rows now carry the same work-unit / worker / follow-up vocabulary used by the stage-local summary artifacts
- those same stage rows now also expose `semantic_payload_tokens_total`, `protocol_overhead_tokens_total`, and `protocol_overhead_share`, so benchmark cost review can compare the thinner inline-JSON default against surviving taskfile stages without dropping back to raw `visible_*` plus `wrapper_overhead_tokens` arithmetic
- Codex-backed prediction/stage planning now also refuses unsafe requested shard counts before live worker launch. The shared survivability preflight uses deterministic prompt/output token estimates plus conservative per-stage caps, so benchmark/prediction operators should use prompt preview first when tuning shard counts and treat the refusal message as the minimum-safe recommendation rather than a runtime flake.
- Single-book interactive benchmark now resolves the concrete gold/source pair before the Codex shard-planning page opens, so the operator sees the actual selected target while editing block-labelling / recipe / knowledge shard counts on one screen.
- The single-book shard-planning screen now also shows deterministic prep KPIs pulled from the shared prep bundle, but the text stays short enough for the interactive list: a brief prepared-book summary at the top and per-row notes for the limiting factor plus average prompt size, average session size, and average work units per shard. This is preview-only operator context; the minimum-safe shard recommendation remains the enforcing guardrail.
- prediction-run manifests now surface `book_cache` telemetry for the shared conversion and deterministic-prep layers, including the shared cache root, content-addressed conversion key, hit/miss state, and timing. `bench gc` can now optionally prune that shared cache root by age or retained bytes.
- interactive single-book and single-profile benchmark reruns now also sit on one stable prediction-reuse cache under `<interactive processed output root>/.prediction_reuse_cache/` by default (or `COOKIMPORT_ALL_METHOD_PREDICTION_REUSE_CACHE_ROOT` when set). When the same source path and benchmark prediction identity repeat, those interactive paths can copy prior prediction artifacts into the new timestamped run root instead of rerunning the full prediction stage.

Interactive benchmark modes are still active and remain offline canonical-text workflows:

- `single_book`
- `selected_matched_books`
- `all_matched_books`

Current interactive contracts:

- `single_book` writes one session root under `data/golden/benchmark-vs-golden/<timestamp>/single-book-benchmark/<source_slug>/`
- when Codex-backed recipe extraction is selected, paired runs are written under sibling `vanilla/` and `codex-exec/` roots in that session
- paired benchmark variants now share the same selected `atomic_block_splitter`; benchmark helpers no longer hardcode `off` for `vanilla` and `atomic-v1` for `codex-exec`
- warm reruns of the same interactive single-book target can now reuse finished prediction artifacts across sessions before comparison/report publication runs
- benchmark prediction/import runs now resolve the same hidden runtime defaults as stage for EPUB segmentation, knowledge grouping caps, and workspace completion grace; support-only benchmark constants such as split-cache wait/poll, single-profile scheduler policy, and Oracle upload shard/poll budgets now live behind shared resolver helpers instead of scattered literals
- benchmark knowledge runs now use the same single live product behavior as stage: first-pass classification is binary `keep_for_review` versus `other`, and the second pass emits contiguous split-and-tag groups with shared grounding/tagging for each accepted span. Benchmark readers should expect group-oriented knowledge counts rather than row-level proposal-candidate counts.
- benchmark runtime contracts now preserve all three Codex Exec transport selections from `RunSettings` into `labelstudio-benchmark`: recipe, line-role, and knowledge. Interactive single-book and matched-book runs should keep those per-surface transport choices through prediction generation and manifests.
- benchmark helper/adaptor calls now also pass the hidden `knowledge_inline_repair_transcript_mode` knob through `labelstudio-benchmark`, so helper-built kwargs stay signature-compatible when knowledge inline repair switches between `resume` and `fresh`
- paired success can emit:
  - `codex_vs_vanilla_comparison.json`
  - `single_book_summary.md`
  - `single_book_summary.md` now renders per-label tables per variant; paired aggregate per-label stats stay in comparison metadata instead of being shown as if they were variant-local
  - `upload_bundle_v1/`
- single-book `upload_bundle_v1` is now a curated first-pass packet by default, capped to about 30 MB via the existing high-level bundle mode instead of embedding the full lossless payload dump; deeper evidence is expected to move through `cf-debug` follow-up packets when needed
- vanilla-only single-book `upload_bundle_v1` runs still leave pair-only sections empty, but they now preserve single-run recipe-span counts from `line-role-pipeline/telemetry_summary.json` / benchmark `manifest.json` and avoid misleading “no spans discovered” triage notes
- paired single-book starter-pack / upload-bundle call inventory exports now retain `line_role` prompt rows and include row-level runtime/token/cost columns when `request_telemetry` provides them; stage-level fallback totals in `prompt_budget_summary.json` still backfill the summary when per-call rows are sparse
- upload-bundle runtime/token summaries now also fall back stage-by-stage to `prompt_budget_summary.json` when the call inventory has the expected rows but a stage's per-call telemetry is blank; this keeps topline spend honest without inventing per-call values that were never recorded
- `prompt_budget_summary.json` now also records recipe transport/policy labels from direct-exec telemetry. For recipe cost review, check `by_stage.recipe_refine.codex_transport`, `codex_policy_mode`, and `codex_shell_tool_enabled` before comparing semantic payload versus protocol overhead.
- upload-bundle recipe-correction accounting must parse both single-recipe outputs and compact shard outputs (`payload.r[].cr` / `payload.r[].m`); `empty_output_signal` now means the parsed correction payload was actually empty, not just that the mapping object was empty
- upload-bundle warning summaries now keep empty-mapping counts separate from actual empty-output counts, and recipe-correction status rollups prefer output-aware labels such as `nonempty_output_without_manifest_status` when manifest/runtime status is missing but parsed outputs exist
- upload-bundle recipe-stage observability now reads recipe manifest diagnostics from `processed_output_run_dir` / `stage_run_dir` (and explicit `recipe_manifest_json`) when no `pred_run_dir` exists, so final mapping / structural statuses are not silently downgraded to generic projection gaps
- upload-bundle active recipe span breakout now projects prompt-derived recipe spans through `line-role-pipeline/projected_spans.jsonl` when that artifact is available; prompt `start_block_index` / `end_block_index` values are source-block coordinates, not canonical scored line coordinates
- upload-bundle recipe-stage blame uses that same projected span mapping so recipe-local changed lines do not silently fall back into the default `line_role` bucket just because prompt evidence was recorded in source block indices
- benchmark manifests now surface both `full_prompt_log_rows` and `full_prompt_log_runtime_shard_count`; use the shard count for real shard-job volume and treat row count as reviewer-log / actual model-turn volume
- benchmark run manifests publish those prompt-log metrics inside the standard top-level `artifacts` map; there is no separate persisted `benchmark_artifacts` object in `run_manifest.json`
- for inline-json knowledge structured-session runs, treat `prompts/full_prompt_log.jsonl` as the canonical turn-by-turn prompt record; `prompts/prompt_nonrecipe_finalize.txt` now mirrors those per-turn prompt / packet / response bodies too, but older benchmark bundles may still show only the stage IO export there
- benchmark status panels now treat generic `task X/Y | running N` progress strings as worker activity, so shard-backed line-role and similar phases do not collapse back to one stale status line
- recipe, knowledge, and line-role benchmark progress now all share the same story shape: visible work-unit counter, separate worker-session summary, separate repo follow-up/finalization summary, and worker rows that represent real worker sessions rather than repo cleanup
- single-profile matched-book runs write under `.../single-profile-benchmark/`
- multi-book single-profile runs also emit one top-level group `upload_bundle_v1/`
- warm reruns of the same interactive single-profile target can now reuse finished prediction artifacts across sessions on a per-book/per-variant basis before comparison/report publication runs
- interactive single-book writes its session bundle, auto-starts Oracle in the background, and returns immediately without blocking benchmark wrap-up
- multi-book single-profile writes the top-level group bundle and leaves Oracle upload as a separate manual step
- repo pytest runs now fail closed on heavyweight publication side effects (`upload_bundle_v1`, starter-pack export, dashboard refresh, background Oracle launch) unless a test explicitly opts in.
- the explicit pytest opt-in contract is `@pytest.mark.heavy_side_effects` plus the `allow_heavy_test_side_effects` fixture; subprocess-heavy tests can still rely on the inherited `COOKIMPORT_ALLOW_HEAVY_TEST_SIDE_EFFECTS=1` environment variable that fixture sets.
- single-book and single-profile benchmark helpers now compute their benchmark result first and publish heavy follow-up work second through explicit publisher seams; routine benchmark-helper tests should inject a lightweight publisher instead of patching every heavy helper individually.

### 2.3 `cf-debug`

`cf-debug` is the deterministic follow-up CLI that operates on an existing `upload_bundle_v1`.

Active use cases:

- build a request template for external reviewers
- export one bundle-wide structure-vs-nonrecipe score split
- select/export concrete cases from the base bundle
- audit line-role joins and prompt links
- audit knowledge-stage evidence
- build additive `followup_dataN/` packets
- when requested regression ids are missing and no negative-delta recipes remain, the base bundle casebook now falls back to high-signal recipes (outside-span density / changed-line / error pressure) instead of mislabeling zero-delta rows as top negative deltas
- `analysis.explicit_escalation_changed_lines_packet` now joins changed canonical lines through `line-role-pipeline/joined_line_table.jsonl` when that artifact is present, then resolves the real route row by `line_role_prediction_atomic_index`. Conservative fallback paths are only for older runs that do not have the joined-line artifact.
- explicit-escalation and follow-up bundle analysis now distinguish route broadness, post-route label change, and `NONRECIPE_EXCLUDE` leakage into final knowledge. Bundle blame can now attribute those leaked rows to `nonrecipe_authority` instead of collapsing them into generic line-role churn.
- canonical benchmark follow-up joins are now conservative too: `upload_bundle_v1` explicit-escalation rows and `cf-debug` line-role/prompt audits should use `line-role-pipeline/joined_line_table.jsonl` as the authority for canonical-line to route-row linkage. Raw `line_index == atomic_index` fallback is not a safe contract once canonical projection and route rows diverge.
- benchmark eval now prefers `line-role-pipeline/semantic_line_role_predictions.jsonl` when it exists, then materializes that reviewer-facing view as the local benchmark `line_role_predictions.jsonl`; prediction-run roots may still keep the older route-layer `line_role_predictions.jsonl` alongside the semantic file for compatibility.

Knowledge extraction is now a first-class follow-up seam:

- selectors can target knowledge source keys/output subdirs explicitly
- `audit-knowledge` emits run-level knowledge evidence
- follow-up packets can include `knowledge_audit.jsonl`
- uncertainty/follow-up exports now center on explicit escalation reasons; current reviewer packets do not carry scalar trust/confidence fields
- `cf-debug select-cases --include-line-range` accepts only canonical `source:start:end` selectors

Structure-only triage is now a first-class follow-up seam:

- `structure-report` writes one bundle-wide `structure_report.json`
- the report separates `structure_core` labels (`RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `HOWTO_SECTION`, `YIELD_LINE`, `TIME_LINE`) from `nonrecipe_core` (`KNOWLEDGE`, `OTHER`)
- it also includes boundary exactness so reviewers can tell whether a low score is mostly a segmentation problem or a label-semantics problem
- high canonical boundary/alignment scores do not imply near-perfect overall accuracy; current single-book misses can still be dominated by hard `KNOWLEDGE` vs `OTHER` disagreements even when recipe boundaries are mostly correct

Benchmark transport note:
- benchmark-mode recipe subprocesses now use CodexFarm's current flag name `--recipeimport-benchmark-mode line_label_v1`; the retired `--benchmark-mode` flag is no longer part of the active contract

## 3. Scoring And Artifact Contracts

### 3.1 Authoritative scored inputs

Primary scored prediction artifact:

- `stage_block_predictions.json` (`schema_version=stage_block_predictions.v1`)
  - the current staging owner map for that artifact is: `recipe_block_evidence.py` for recipe-local evidence, `knowledge_block_evidence.py` for final non-recipe evidence, `block_label_resolution.py` for priority rules, and `stage_block_predictions.py` as the assembly root

Required supporting artifact:

- `extracted_archive.json`

Current rule:

- benchmark scoring reads one canonical pointer pair from prediction-run metadata:
  - `stage_block_predictions_path`
  - `extracted_archive_path`
- prediction generation is responsible for setting those canonical pointers to the correct artifacts for the run
- canonical-text line-role runs rewire that same pointer pair to the scored `line-role-pipeline/` projection artifacts; helpers should not guess stage-backed files or raw `full_text.json` from path layout
- new-format prediction/eval manifests and import return payloads do not publish separate line-role scorer keys anymore; helpers should fail on missing canonical pointers instead of probing older fallback filenames or implicit directories
- semantic stage/canonical scoring uses only authoritative predictions. If `stage_block_predictions.json` carries unresolved candidate block indices, those rows are excluded from accuracy/F1 and reported separately as coverage/incompleteness.

### 3.2 Gold inputs

Stage-block mode expects:

- `exports/freeform_span_labels.jsonl`

Canonical-text mode expects:

- `exports/canonical_text.txt`
- `exports/canonical_span_labels.jsonl`
- `exports/canonical_manifest.json`

Canonical gold authority note:

- `exports/freeform_span_labels.jsonl` is still the entry artifact selected by benchmark discovery because it identifies the gold export bundle, but canonical-text scoring does not score that raw freeform file directly
- `exports/block_gold_labels.jsonl` is the derived block-authoritative gold built from the freeform export
- `exports/canonical_span_labels.jsonl` is then derived from `block_gold_labels.jsonl` and uses full canonical block spans for the labeled blocks
- broad freeform `KNOWLEDGE` or `OTHER` drags are therefore treated as per-block labeling intent, not as benchmark-authoritative span geometry

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
- canonical-text `eval_report.json` now carries both overlap-style `boundary` counts and structural `segmentation` metrics (`label_projection=core_structural_v1`, `boundaries.overall_micro`, error taxonomy), so single-book codex-vs-vanilla comparisons can attribute quality deltas across both label semantics and boundary structure
- canonical-text eval now also emits boundary-mismatch artifacts for structural debugging (`missed_gold_boundaries.jsonl` and `false_positive_boundaries.jsonl`) so segmentation regressions can be inspected without rerunning stage-block mode
- line-role regression tuning should keep one no-subsection source and one real-subsection source in the deterministic proof story. The current repo-local contrast pair is `saltfatacidheatcutdown` (`HOWTO_SECTION=0` in gold) versus `seaandsmokecutdown` (`HOWTO_SECTION=111` in gold).

Current line-role and knowledge behavior:

- `line-role-pipeline/` artifacts are written when line-role is enabled; prediction generation may set canonical scorer pointers to these projection artifacts for that run
- processed stage-backed artifacts still get written for the run; the regression fix was specifically to move the canonical scorer pointer pair to the projection artifacts instead of leaving scoring on the stage-backed pair
- when the benchmark reuses authoritative Stage 2 recipe-local labels, the scored line-role artifact pair still has to stay in canonical atomic-span coordinates:
  - `stage_block_predictions.json` is serialized from canonical line-role projections, not copied from source blocks
  - `extracted_archive.json` carries the matching atomic line coordinates and `line_role_projection` metadata
  - outside-recipe `KNOWLEDGE` versus `OTHER` labels in that projection must come from the final non-recipe authority, not the pre-knowledge seed
- those line-role artifacts now expose `decided_by`, `reason_tags`, and `escalation_reasons`; scalar trust/confidence fields are gone
- `09_nonrecipe_authority.json` is the authoritative scored outside-span contract; benchmark scoring and projection must read this file only when they need final outside-recipe truth
- `08_nonrecipe_route.json` and `09_nonrecipe_finalize_status.json` are debugging/progress artifacts; they can explain routing or incompleteness but must not be treated as scored truth
- `line-role-pipeline/line_role_predictions.jsonl` may still preserve provisional outside-recipe line-role labels for debugging, but `line-role-pipeline/stage_block_predictions.json` must fail closed and use explicit final authority only for scored outside-recipe `KNOWLEDGE`
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
- `joined_line_table.jsonl` now reuses the evaluator's canonical gold line-label projection rules, so reviewer diagnostics should agree with `eval_report.json` on filtered inline `RECIPE_TITLE` mentions, dropped contents-page titles, and preserved `RECIPE_VARIANT` runs
- older alias files such as `missed_gold_spans.jsonl` and `false_positive_preds.jsonl` are retired
- `line_role_flips_vs_baseline.jsonl`
- `slice_metrics.json`
- `routing_summary.json`
  - this routing artifact is now the plain-language upstream-diversion summary for line-role. It reports the coarse route split and whether outside-recipe rows were kept for knowledge review or filtered before the knowledge stage.
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
  - `recipe_build_intermediate`
  - `recipe_refine`
  - `recipe_build_final`
- `cookimport/bench/upload_bundle_v1_existing_output.py` should emit semantic recipe pipeline context only; do not add older recipe-topology metadata back into new bundles
- `cookimport/bench/followup_bundle.py` should resolve `knowledge_manifest_json` only from canonical current pointers. If a current run is missing those pointers, fail closed or surface the artifact as missing instead of scanning older raw layouts.
- `scripts/benchmark_cutdown_for_external_ai.py` treats semantic stage rows, `recipe_manifest.json` stage states, and `recipe_correction_audit` diagnostics as the primary existing-output contract. Current outputs should not reintroduce numbered-stage or guessed-path fallback logic.
- existing-output bundle discovery should use current run-local artifact roots and manifest pointers:
  - prompt logs and prompt samples from `<run>/prompts/`
  - prompt budget summaries from the manifest-declared `prompt_budget_summary_json` / `actual_costs_json` pointers rooted under the run's canonical artifact root
  - knowledge manifests from canonical prediction-run manifest pointers or processed-output stage observability
  - when a required knowledge manifest lives outside the session root, the bundle should mirror it into a derived payload row so `navigation.row_locators.knowledge_by_run` still resolves bundle-locally
- upload-bundle runtime snapshots should prefer row-level prompt telemetry when it is present, but they must fall back to aggregate prompt-budget stage totals when older/full-prompt rows are missing token coverage or omit whole stages such as `line_role`
- upload-bundle diagnostics must keep stage blame and trace parity semantically honest:
  - `final_recipe_empty_mapping` only counts actual `recipe_build_final` empty-mapping output
  - `analysis.recipe_pipeline_context.observed_recipe_stage_call_counts.recipe_build_final` counts only observed final-recipe calls, not correction-stage calls
  - `16_baseline_trace_parity.json` should treat derived bundle-local trace rows as present when run diagnostics already mirrored those artifacts into the bundle
- compact recipe-correction outputs are still real outputs. When existing-output readers inspect `recipe_refine`, compact `payload.r[].cr.i` / `payload.r[].cr.s` rows count as non-empty correction output even when the compact mapping itself is empty. `empty_output_signal` should mean "no correction output at all," not merely "empty mapping."
- `regression_casebook` fallback selection must stay honest when there are no negative-delta recipes. In that case the fallback source/reason should be signal-based instead of pretending `top_negative_delta_recipes` existed, and bundle generation should fail loudly if parsed correction outputs are visibly non-empty while stage observability still claims every correction output is empty.
- new cutdown and starter-pack outputs should write semantic `stage_key` values only. If older prompt logs still carry `pass*` labels, normalize them in the read helper instead of synthesizing `pass*` fields back into current output
- knowledge extraction must surface explicitly through bundle analysis/index fields instead of being implied by generic prompt artifacts
- high-level multi-book bundles are intentionally size-capped first-look packets; heavier raw prompt dumps remain local for follow-up
- sparse bundles are valid first-class inputs:
  - request-template generation should choose a real bundle-local case when one exists
    It now prefers a negative-delta recipe case, otherwise an outside-span window, otherwise the strongest remaining recipe-signal case.
  - otherwise it should emit empty-selector asks that still let `cf-debug build-followup` succeed
  - `--include-knowledge-source-key` should resolve through bundle-local knowledge rows even when the bundle has no Codex-enabled paired run
- checked-in old-format bundle fixtures should be normalized in tests before running current `cf-debug` paths; production readers should not grow new reader branches just to satisfy stale fixtures

Oracle upload contract:

- the user-facing target can be a session root or an `upload_bundle_v1/` directory
- the actual upload code targets the three concrete bundle files; browser uploads may temporarily shard oversized files into ordered `partNNN` attachments to get past Oracle's per-file cap without changing the on-disk bundle format
- the browser upload path now enters through the fork-owned launcher at `/home/mcnal/projects/shared/oracle-fork/scripts/wsl/oracle-runtime.sh`; that launcher executes the built fork with repo-local defaults and `ORACLE_BROWSER_REMOTE_DEBUG_HOST=127.0.0.1`
- the launcher defaults browser automation to `/home/mcnal/.local/bin/chromium-nosandbox-xvfb`, so the same benchmark upload path works from the agent shell without depending on the retired local wrapper chain
- browser uploads now use the fork-owned Oracle browser profile at `/home/mcnal/projects/shared/oracle-fork/var/oracle/browser-profile`
- browser uploads now pass `--browser-model-strategy select`, so benchmark review explicitly switches to the requested review model instead of inheriting a stale/manual ChatGPT mode
- the local editable Oracle package also has to keep its own concrete model mapping aligned with the benchmark wrapper. If benchmark metadata says `model=pro` but the actual Oracle browser launch still lands on an unexpected picker choice, inspect the saved `launch_model`, Oracle's local wrapper defaults, and the benchmark command together.
- `--mode dry-run` uses Oracle dry-run when possible and falls back to a local preview when the payload file is too large
- transport sharding is strictly upload-time glue for oversized text files such as `upload_bundle_payload.jsonl`; checked-in and local `upload_bundle_v1` artifacts should stay unmodified on disk
- benchmark status rendering treats generic `task X/Y | running N` updates as first-class worker-row signals, and plain `run=... queued=... running=...` stderr snapshots are noise when structured progress is already present
- detached Oracle follow-up has one more active contract: if `oracle_upload.log` contains an earlier timeout marker and a later grounded `Answer:` block, the recovered answer wins. Turn 2 must also inherit the source run's Oracle home/profile so `continue-session` targets the same saved chat instead of falling back to ambient shell state.

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
- quality/speed benchmark roots are pruned only when CSV durability is already present
- `performance_history.csv` is not rewritten by GC
- label-studio benchmark pruning is on by default and keeps only the newest five timestamped roots under `data/golden/benchmark-vs-golden/*` unless you override `--keep-labelstudio-runs`
- timestamped run roots directly under `data/output/<run_id>/` are wiped by default; non-run folders such as `data/output/history/dashboard` are preserved
- matched processed-output pruning still exists behind `--keep-output-runs --prune-benchmark-processed-outputs`
- any root containing `.gc_keep*`, `.keep`, or `.pinned` is retained
- pytest temp eval fixtures are excluded so tests can inspect artifacts after command completion

## 7. Core Code Map

Primary benchmark modules:

- `cookimport/cli.py`: top-level Typer app that mounts the benchmark and Label Studio command groups
- `cookimport/cli_commands/bench.py`: `cookimport bench` command registration (`speed-*`, `quality-*`, `gc`, `pin`, `oracle-*`, `eval-stage`)
- `cookimport/cli_commands/labelstudio.py`: `labelstudio-benchmark` command registration
- `cookimport/cli_support/bench.py`, `bench_single_book.py`, `bench_single_profile.py`, `bench_all_method.py`, `bench_oracle.py`, `bench_artifacts.py`, `bench_cache.py`: split benchmark implementation owners behind the CLI facade
- `cookimport/bench/CONVENTIONS.md`: durable benchmark contracts inside the code folder
- `cookimport/bench/eval_stage_blocks.py`: stage-block scoring
- `cookimport/bench/eval_canonical_text.py`: canonical-text scoring and alignment telemetry
- `cookimport/bench/canonical_alignment_cache.py`: shared canonical alignment cache
- `cookimport/bench/prediction_records.py`: replay record schema/helpers
- `cookimport/bench/speed_suite.py`, `speed_runner.py`, `speed_compare.py`: SpeedSuite
- `cookimport/bench/quality_suite.py`, `cookimport/bench/qualitysuite/`, `quality_compare.py`, `quality_leaderboard.py`: QualitySuite
- `cookimport/bench/artifact_gc.py`: benchmark retention and pruning
- `cookimport/bench/oracle_upload.py`: Oracle upload wrapper for existing bundles
- `cookimport/bench/followup_bundle.py`: follow-up packet helpers used by `cf-debug`
- `scripts/benchmark_cutdown_for_external_ai.py`: existing-output external-review packet builder over semantic stage rows plus current recipe manifests/audits

## 8. See Also

- `docs/07-bench/qualitysuite-agent-sop.md`
- `docs/07-bench/web-ai-followup-instructions.md`
- `cookimport/bench/README.md`
- `cookimport/bench/CONVENTIONS.md`

## 9. Recent Durable Notes

- In canonical-text benchmarking, `eval_report.json -> per_label.RECIPE_TITLE` is the title-label metric. `eval_report.json -> recipe_counts.predicted_recipe_count` is a separate import-level recipe total and can diverge sharply.
- When post-refactor CodexFarm canonical-text quality drops toward vanilla, inspect the `KNOWLEDGE` seam first. The non-recipe route stage now only routes outside-recipe review, while the finalize stage owns candidate `KNOWLEDGE` vs `OTHER` for benchmark truth.
- Single-book benchmark folder naming is about Codex participation, not every deterministic helper. A run with recipe Codex off and only deterministic line-role still belongs under `vanilla/`; only actual Codex-backed line-role belongs in the Codex/hybrid branch.
- High Codex recipe task counts in single-book runs usually mean grouped recipe-span overproduction upstream, not retry storms inside CodexFarm.
- Tiny line-role token spend in a Codex single-book run does not mean line-role was skipped; older helper paths only sent escalated rows to live Codex and then scored a projected artifact built from authoritative outputs.
- Canonical benchmark scoring should project explicit final non-recipe authority, not raw deterministic seed labels. The current contract is non-recipe routing plus optional finalize-stage review merged into final scored `KNOWLEDGE` / `OTHER`.
- Benchmark prompt export should include every CodexFarm interaction the reviewer cares about:
  - recipe correction
  - line-role prompt artifacts copied from `line-role-pipeline/prompts`
  - knowledge harvest
- Reviewer-facing activity traces now live under `prompts/activity_traces/<call_id>.json`, with summary files at `prompts/activity_trace_summary.jsonl` and `prompts/activity_trace_summary.md`. The per-call JSON is derived from saved worker `events.jsonl` / sidecars, and the summary files read those exported JSON traces rather than stale embedded row payloads. The surface is visible agent activity, including file-change entries when the worker event stream exposed them, not hidden chain-of-thought.
- Oracle shared-profile browser failures can look like a fresh-port `ECONNREFUSED` problem even when Chromium is already alive. If upload starts failing after bundle generation succeeds, inspect shared-profile reuse (`DevToolsActivePort`, stale `chrome.pid`, singleton locks, canonical browser profile) before redesigning the bundle or upload flow.
- Benchmark Oracle upload trust is now multi-layered:
  - empty-composer or launch failures should fail fast
  - in-flight runs should persist `oracle_upload_status.json`, session id, reattach command, and conversation URL as early as possible
  - completed answers that contradict the local bundle root or topline counts should be treated as `invalid_grounding`, not silent success
- Recovered Oracle turn-1 answers are authoritative even when the saved log still contains older timeout text. If a follow-up worker gets stuck in `recovering_turn_1`, inspect log-audit precedence and source Oracle home/profile inheritance before changing follow-up packet logic.
- Upload-bundle recipe-correction diagnostics are now deliberately split:
  - "empty correction output" is different from "correction output exists but the compact mapping is empty"
  - casebook fallback can be signal-based when no negative-delta recipe exists
  If those surfaces disagree again, inspect the normalized bundle model before blaming scorer math or the underlying benchmark run.
- When validating Codex benchmark regressions, do not over-trust a stale run root after runtime/prompt changes land. The March 18 Salt Fat Acid Heat work established that some fixes were code-complete locally while live benchmark proof was still pending explicit approval for a fresh rerun.
