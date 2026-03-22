---
summary: "Retained benchmark architecture/build/fix chronology for active benchmark features."
read_when:
  - When benchmark behavior debugging is looping and you need prior decisions
  - When changing active benchmark contracts (stage-block, canonical-text, all-method, speed suite)
  - When validating why current benchmark constraints exist
---

# Bench Log: Architecture, Builds, and Fix Attempts

This log keeps only history that still maps to active benchmark features.
Removed benchmark workflows were intentionally pruned so this file stays useful during current debugging.

## 1. 2026-02-25 stage-block benchmark contract rollout

Problem captured:

- benchmark scoring could diverge from stage outputs and produce misleading label results

Durable decisions:

- primary prediction surface is `stage_block_predictions.json`
- benchmark runs require both:
  - `stage_block_predictions.json`
  - `extracted_archive.json`
- stage-block reporting centers on:
  - `overall_block_accuracy`
  - `macro_f1_excluding_other`
  - `worst_label_recall`

Anti-loop note:

- missing stage-block artifacts is an artifact-generation problem, not scorer drift

## 2. 2026-02-25 multi-label gold and mismatch-guard hardening

Problem captured:

- freeform gold can contain multiple labels for one block
- extractor/blockization drift could silently corrupt block-level scoring

Durable decisions:

- multi-label gold per block is valid; any allowed label is a correct prediction
- missing-gold predicted blocks default to `OTHER` and are logged in `gold_conflicts.jsonl`
- evaluator fingerprints blockization metadata and fails with `gold_prediction_blockization_mismatch` when drift is severe

Anti-loop note:

- if metrics look impossible, inspect mismatch diagnostics before changing scorer math

## 3. 2026-02-26 canonical-text default and alignment-safety boundary

Problem captured:

- all-method extractor permutations need a scoring space that does not require stage-block parity
- fast alignment experiments risked changing scoring semantics

Durable decisions:

- interactive benchmark modes use `canonical-text`
- canonical-text exists to score extractor permutations in canonical line space
- scoring keeps older global alignment semantics for safety
- benchmark matcher selection is effectively locked to `dmp`

Anti-loop note:

- if canonical score movement looks suspicious, treat non-`dmp` matcher assumptions as stale first

## 4. 2026-02-27 cache, replay, and artifact-write contracts

Problem captured:

- canonical eval tails were expensive
- replay/evaluate-only paths were under-specified
- markdown/task writes added avoidable runtime cost in non-scoring loops

Durable decisions:

- canonical eval uses a shared per-source alignment cache
- dead-owner lock reclamation checks PID liveness before age-only fallback
- replay boundary functions are explicit: predict, evaluate, older direct-call, and pipelined run paths
- `--predictions-out` writes stage-block prediction records
- `--predictions-in` now accepts current prediction-record files only; older run-pointer records were intentionally removed during the canonical scorer-pointer cutover
- write toggles for markdown and Label Studio tasks are explicit and recorded in manifests

Anti-loop note:

- when cache benefit is absent, compare alignment cache keys before changing cache policy

## 5. 2026-02-27 speed-suite and scheduler interpretation contracts

Problem captured:

- operators needed a baseline/candidate timing workflow
- all-method scheduler telemetry was easy to misread

Durable decisions:

- SpeedSuite flow is `speed-discover -> speed-run -> speed-compare`
- scheduler heavy-slot telemetry represents split-active occupancy only
- low late-run CPU can be normal during canonical eval tails
- scheduler/runtime payloads must record configured/effective eval-tail fields and admission ceilings

Anti-loop note:

- use scheduler events plus cache/lock health before declaring an all-method stall

## 6. 2026-02-28 QualitySuite discovery, schema, and throughput controls

Problem captured:

- quality discovery needed a deterministic curated default
- experiment specs needed a compact but strict schema
- worker availability and split throughput were shaping wall time more than matcher experiments

Durable decisions:

- `quality-discover` prefers curated CUTDOWN ids first, then representative fallback
- experiments schema v2 expands `levers[]` into baseline plus lever-isolated runs
- `run_settings_patch` keys are validated against `RunSettings`
- if process workers are unavailable, QualitySuite preserves useful concurrency through fallback worker paths instead of silently collapsing into a useless serial loop
- split-slot/resource-guard throughput controls are mirrored across scheduler paths
- prediction-side non-scoring writes stay disabled for all-method predict-only calls

Evidence worth keeping:

- split-throughput tuning improved `benchmark_all_method_multi_source` wall time materially without regressing quality on the compared runs from 2026-02-28

Anti-loop note:

- if throughput changes diverge by scheduler path, check mirrored slot/admission logic before adding new knobs

## 7. 2026-03-02 interactive single-book and single-profile benchmark contract

Problem captured:

- interactive benchmark flows needed one stable session-root model, paired-run semantics, and one reviewer handoff packet

Durable decisions:

- `single_book` writes one session root under `single-book-benchmark/<source_slug>/`
- Codex-enabled paired runs normalize into explicit `vanilla` and `codexfarm` roots
- paired success can emit one `codex_vs_vanilla_comparison.json`, one session summary markdown, and one `upload_bundle_v1/`
- single-profile matched-book flows write under `single-profile-benchmark/`
- multi-book single-profile runs emit one high-level top-level group `upload_bundle_v1/`
- dashboard refresh is deferred until the full interactive batch completes

Anti-loop note:

- when two nearby timestamps exist, prove there were two invocations before assuming paired roots are intrinsic behavior

## 8. 2026-03-04 to 2026-03-05 upload bundle, follow-up packet, and reuse-boundary ledger

Problem captured:

- expensive reruns were being triggered by path-resolution mistakes, over-broad reuse identity, or unclear reviewer handoff seams

Durable decisions:

- `upload_bundle_v1` is the base reviewer packet
- follow-up work should produce additive `followup_dataN/` packets keyed by a request manifest
- deterministic follow-up tooling should reuse the existing bundle seam
- upload-bundle internals are split into model/adapter/renderer seams:
  - `upload_bundle_v1_model.py`
  - `upload_bundle_v1_existing_output.py`
  - `upload_bundle_v1_render.py`
- reuse/cache identity must stay prediction-shaped; runtime-only knobs should not fragment reuse keys
- compare-gate recovery should prefer evaluate-only reruns from `--predictions-in` before re-importing or rerunning Codex

Anti-loop note:

- “missing debug artifact” is often artifact-key resolution drift, not missing files on disk

## 9. 2026-03-05 QualitySuite deterministic baseline contract

Problem captured:

- QualitySuite baselines could inherit AI-on defaults from incoming settings and still present as “baseline”

Durable decisions:

- normalize every all-method baseline payload through the explicit benchmark baseline contract before hashing or emitting variants
- baseline contract is:
  - `llm_recipe_pipeline=off`
  - `llm_knowledge_pipeline=off`
  - `line_role_pipeline=off`
  - `atomic_block_splitter=off`
- build Codex variants from that normalized baseline, but do not re-normalize those Codex payloads back into baseline form

Anti-loop note:

- if `include_codex_farm=True` stops producing Codex variants, check for accidental re-normalization of Codex payloads

## 10. 2026-03-06 QualitySuite deterministic-only guard, knowledge-stage wiring, and selective retry

Problem captured:

- QualitySuite metadata could drift from the real executable baseline
- Codex-enabled settings could sneak into supposedly deterministic quality runs
- knowledge-stage benchmark evidence existed but was inconsistently surfaced
- partial pass failures needed salvage at the pass boundary, not whole-book reruns

Durable decisions:

- `bench quality-run` is deterministic-only end-to-end
- preserve both `requested_run_settings` and normalized executable `run_settings`
- knowledge-stage benchmark helpers keep baseline variants off and enable knowledge-stage only in Codex variants
- `knowledge/<workbook_slug>/block_classifications.jsonl` is the preferred scored knowledge-stage artifact for outside-span `KNOWLEDGE`
- `cf-debug` now has knowledge-stage selectors and `audit-knowledge`
- benchmark selective retry retries only missing bundle files for the current failed pass and records detailed truth in `raw/llm/<workbook_slug>/llm_manifest.json`

Anti-loop note:

- if knowledge-stage “ran” but benchmark lift is flat, inspect the narrow scored upgrade seam before assuming knowledge-stage failed

## 11. 2026-03-16 quality-runner live Codex surface boundary

Problem captured:

- quality-run requested-settings validation still had stale assumptions about a separate tags Codex surface

Durable decisions:

- `CodexSurfaceDecision` should track the live surfaces only
- deterministic `bench quality-run` validation needs to reject Codex recipe and knowledge usage; the removed tags surface should not return as a compatibility alias

Anti-loop note:

- if a quality-suite fix proposal wants to add `tags_codex_enabled` back, it is restoring a deleted surface instead of aligning to the live model

## 12. 2026-03-13 execution semantics and single-root output contract

Problem captured:

- benchmark metadata and path layout were easy to misread as evidence of separate execution modes or paired-root behavior

Durable decisions:

- one direct benchmark invocation should resolve one eval root
- prediction-generation scratch stays under that same eval root as `<eval_output_dir>/prediction-run`
- interactive nested benchmark flows pass explicit child `eval_output_dir` paths inside their session root

Anti-loop note:

- nearby sibling timestamps are not proof of a filesystem contract; verify whether there were separate invocations

## 13. 2026-03-15 stage-backed scoring and upload-bundle seam map

Problem captured:

- benchmark generation had drifted away from the real import/stage path
- line-role projection still looked like a primary scored lane in some helper paths
- reviewer bundle semantics were coupled too tightly to current path topology

Durable decisions:

- benchmark/import unification centers on one shared stage session
- authoritative score inputs come from stage-backed artifacts, not line-role projection copies
- canonical line-role remains diagnostics only and runs after the shared stage session
- `upload_bundle_v1` should derive recipe/stage topology from a normalized model instead of path guessing
- prompt artifact export stays topology-neutral at the renderer boundary

Anti-loop note:

- if a refactor needs a second primary prediction lane or path-derived topology again, it is reintroducing the old fork

## 14. 2026-03-15 canonical scorer-pointer cutover and hard deletion

Problem captured:

- benchmark helper paths still carried stage-vs-line-role scorer branches and duplicate manifest keys
- transition readers could silently recover artifacts from old filenames or implicit directories, which made it hard to tell whether the canonical benchmark contract was actually populated

Durable decisions:

- every prediction/eval run now exposes one canonical scorer pointer pair:
  - `stage_block_predictions_path`
  - `extracted_archive_path`
- when line-role projection artifacts become the scored surface for a run, prediction generation rewires that same canonical pointer pair to the line-role artifacts instead of publishing a second scorer namespace
- duplicate scorer keys were removed from manifests/import payloads rather than kept as aliases
- benchmark bundle/eval resolution now requires the canonical pointers and should fail loudly when they are missing

Anti-loop note:

- if a helper wants to guess scorer files from path layout, that is reintroducing the deleted transition contract

## 15. 2026-03-16 semantic recipe-stage bundle contract

Problem captured:

- reviewer-facing bundle output was still teaching pass-slot internals (`pass2_stage`, `pass3_stage`) instead of the semantic recipe stages a reviewer actually needs
- starter-pack/casebook rendering and follow-up tooling were at risk of baking those implementation names back into the external surface

Durable decisions:

- `upload_bundle_v1` and related rendering now expose `recipe_topology_key` plus ordered semantic `recipe_stages`
- the active stage meanings are:
  - `build_intermediate_det`
  - `recipe_llm_correct_and_link`
  - `build_final_recipe`
- starter-pack and casebook rendering should present chunking separately from recipe correction/finalization rather than flattening everything into pass-slot labels
- the external-AI cutdown path should read semantic stage rows, `recipe_manifest.json` stage states, and `recipe_correction_audit` diagnostics directly instead of reconstructing pass-slot trees
- historical bundles may still be read through narrow transition adapters for old knowledge-stage sample names and related local artifact names, but new reviewer-facing bundle fields must stay semantic

Anti-loop note:

- if external-review output starts showing pass-slot field names again, fix the normalized model or renderer instead of adding more transition prose around it

## 16. 2026-03-16 bundle follow-through, scorer regressions, and retention boundaries

### 2026-03-16_10.20.11 upload-bundle semantic contract guard

Problem captured:

- bundle helpers were at risk of reintroducing older recipe-topology metadata even after the renderer/model seam had moved to semantic stages

Durable decisions:

- `upload_bundle_v1_existing_output.py` should emit semantic recipe pipeline context only
- `followup_bundle.py` should treat `knowledge_manifest_json` as the live knowledge-manifest locator
- archived old-format bundles belong in fixture rewrite/normalization code during test setup, not in new production transition branches

Anti-loop note:

- if a fix proposal adds new pass-slot bundle fields to make stale fixtures happy, update the fixture instead

### 2026-03-16_11.06.13, 2026-03-16_12.02.26, and 2026-03-16_15.26.00 external-AI cutdown semantic-stage cutover

Problem captured:

- `scripts/benchmark_cutdown_for_external_ai.py` had already switched some outer surfaces to semantic names, but prompt reconstruction, scoring summaries, and starter-pack fields still rebuilt `first-stage`/`second-stage`/`third-stage` internals

Durable decisions:

- prompt rows, sampled prompt logs, and runtime call inventories should be keyed by semantic `stage_key`
- recipe triage should read `recipe_manifest.json` stage states plus `recipe_correction_audit/*.json` instead of synthetic pass-slot trees
- recipe artifacts now live under `recipe_correction/{in,out}` and `build_final_recipe/out`; `chunking/schemaorg/final` should not be rebuilt as a live contract
- archived prompt logs may still carry `first-stage` / `second-stage` / `third-stage` / `fourth-stage`; keep that transition isolated to the read-side stage-key normalizer

Anti-loop note:

- if starter-pack output starts showing synthetic `pass*` fields again, the cutdown writer regressed even if old logs still load

### 2026-03-16_12.21.38 upload-bundle functional check

Problem captured:

- there was a risk that current follow-up readers worked only on rich paired bundles and silently broke on sparse single-profile bundles

Durable decisions:

- sparse `upload_bundle_v1` bundles are valid when the topology/index files load and bundle-local selectors can resolve
- request-template generation must be bundle-aware:
  - choose a real recipe/outside-span case when present
  - otherwise emit an empty-selector ask so `build-followup` still succeeds
- `--include-knowledge-source-key` must resolve through any run that has a bundle knowledge row, not only Codex-enabled paired runs

Evidence worth keeping:

- the checked bundle at `data/golden/benchmark-vs-golden/2026-03-16_12.14.35/single-book-benchmark/saltfatacidheatcutdown/upload_bundle_v1` loaded cleanly with `topline.run_count=1`, `pair_count=0`, and semantic single-correction recipe context

Anti-loop note:

- empty case files on a sparse bundle are usually legitimate sparsity, not artifact breakage

### 2026-03-16_12.30.30 and 2026-03-16_12.41.00 canonical scorer-pointer and atomic-artifact regressions

Problem captured:

- canonical benchmark quality cratered after label-first reuse even though the run had healthy `line-role-pipeline/` outputs
- the scorer pointers stayed on stage-backed artifacts, and the first reuse path also serialized source-block coordinates instead of atomic-line coordinates

Durable decisions:

- canonical benchmark helpers must trust the one canonical pointer pair and rewire it explicitly to `line-role-pipeline/stage_block_predictions.json` plus `line-role-pipeline/extracted_archive.json` when that pair is the scored surface
- authoritative Stage 2 reuse still has to serialize the scored artifact pair through the canonical projection builders, not by copying `label_first_result.archive_blocks` or source-block predictions directly
- the fix stays local to prediction-run artifact selection; scorer logic and artifact formats do not need a separate benchmark-side fork

Evidence worth keeping:

- bad regression run symptom:
  - projection archive contained `1471` nonempty rows, but `eval_report.json` matched only `85` nonempty prediction blocks because the scorer was still reading the wrong manifest pointers
- source-block serialization also collapsed the scored surface from `1768` atomic rows to `1471` source-block rows on `saltfatacidheatcutdown`
- after the pointer and provenance fixes, `cookimport labelstudio-benchmark ... --eval-mode canonical-text --no-upload --atomic-block-splitter atomic-v1 --line-role-pipeline deterministic-v1 --llm-recipe-pipeline off --llm-knowledge-pipeline off` produced `strict_accuracy=0.5238744884038199` and `macro_f1_excluding_other=0.44441642590611175` under `data/golden/benchmark-vs-golden/2026-03-16_12.46.31/`

Anti-loop note:

- if canonical metrics collapse after a label-first refactor, inspect manifest pointers and coordinate system before retuning labels or aligner math

### 2026-03-16_13.33.17 benchmark GC retention boundary

Problem captured:

- disk cleanup around benchmark runs was easy to confuse with destructive history cleanup

Durable decisions:

- `cookimport bench gc` is benchmark-only retention
- the aggressive safe cleanup path can prune old benchmark roots plus matching processed-output roots while preserving `performance_history.csv`
- GC should refuse deletion when durable CSV history cannot be confirmed

Anti-loop note:

- do not script ad hoc `rm -rf` cleanup of benchmark roots when `bench gc` already knows how to preserve history

### 2026-03-16_14.17.02 canonical eval older alias purge

Problem captured:

- canonical eval still synthesized span-style alias files that no live scorer or reviewer contract needed

Durable decisions:

- `_legacy_alias_rows` and files like `missed_gold_spans.jsonl` / `false_positive_preds.jsonl` are retired
- the live canonical diagnostics contract is the explicit line/block mismatch set plus alignment diagnostics

Anti-loop note:

- if tests start expecting older alias outputs again, update the tests rather than reviving the alias writer

### 2026-03-16_14.48.06 cf-debug fixture normalization

Problem captured:

- checked-in `upload_bundle_v1` fixtures still used old knowledge-stage keys even though active `cf-debug` paths had already moved to semantic names

Durable decisions:

- current `cf-debug` tests should normalize copied bundle fixtures in temp dirs before invoking the CLI
- the working helper path is:
  - rewrite old knowledge index keys to current semantic names
  - materialize minimal local knowledge artifacts
  - append matching payload rows and locators so `knowledge_audit` and `case_export` can resolve evidence

Anti-loop note:

- production `cf-debug` readers should not grow fixture-only transition branches

## 17. 2026-03-15 QualitySuite guard order and payload projection

Problem captured:

- baseline coercion could hide Codex-enabled requests before validation
- strict `RunSettings` loading could fail on mixed payloads that still contained persistence metadata

Durable decisions:

- run Codex-disallow validation against the requested payload before baseline coercion
- project QualitySuite payloads through `project_run_config_payload(..., contract=RUN_SETTING_CONTRACT_FULL)` before `RunSettings.from_dict(...)`

Anti-loop note:

- if QualitySuite behavior looks inconsistent, debug validation order and payload projection before relaxing strict settings loading

## 18. Retired History Notice

The following removed benchmark workflows were intentionally pruned from this log:

- tournament-based QualitySuite promotion flows
- `scripts/quality_top_tier_tournament.py`
- retired `bench run`, `bench sweep`, `bench validate`, and `bench knobs` surfaces
- line-role projection as the primary scored truth
- fast canonical alignment production scoring

## 19. 2026-03-16 Codex single-book follow-through

### 2026-03-16_18.20.49, 2026-03-16_19.01.54, and 2026-03-16_19.18.20 upload-bundle artifact discovery on current layouts

Problem captured:
- fresh single-book benchmark runs were healthy on disk but `upload_bundle_v1` under-reported prompt and knowledge evidence because the existing-output builder no longer matched the refactored artifact layout

Durable decisions:
- existing-output discovery must search current run-local roots first:
  - `<run>/prompts/full_prompt_log.jsonl`
  - `<run>/prompt_budget_summary.json`
  - processed-output `raw/llm/*/knowledge_manifest.json` when `pred_run_dir` is absent
- per-run knowledge locators must not use loose basename fallback; null is safer than binding another run's artifact row
- if a required knowledge manifest lives outside the session root, mirror it into `_upload_bundle_derived/runs/<run_id>/knowledge_manifest.json` so bundle-local locators still work
- a missing prompt or knowledge row in `upload_bundle_v1` is often a discovery bug, not proof that the run failed

Evidence worth keeping:
- the inspected `saltfatacidheatcutdown` session had real Codex prompt and knowledge work on disk, including `56` knowledge calls in `prompt_budget_summary.json`, while the pre-fix bundle still reported `0`

Anti-loop note:
- when bundle analysis disagrees with the filesystem, debug artifact discovery roots before changing benchmark runtime generation

### 2026-03-16_18.21.25 canonical-text regression seam is mostly `KNOWLEDGE`

Problem captured:
- post-refactor CodexFarm benchmark quality dropped sharply versus the older Codex run and it was easy to blame the whole recipe path

Durable decisions:
- the dominant benchmark delta is the disappearance of codex-driven outside-recipe `KNOWLEDGE` relabeling after Stage 7 became authoritative
- recipe-path failures still matter, but they are a separate regression from the main score drop

Evidence worth keeping:
- 2026-03-14 CodexFarm: `strict_accuracy=0.6152796725784447`, `KNOWLEDGE precision/recall=0.6741 / 0.6118`, `pred_total=540`
- 2026-03-16 CodexFarm: `strict_accuracy=0.5320600272851296`, `KNOWLEDGE precision/recall=0.8630 / 0.1059`, `pred_total=73`
- the same 2026-03-16 run also had `52` `recipe_correction_error` rows rejected as `placeholder_steps_only`, but that was not the main explanation for the benchmark score collapse

Anti-loop note:
- if CodexFarm no longer beats vanilla on canonical-text, inspect Stage 7 authority changes before rewriting scorer math or prompt packs

### 2026-03-16_18.56.30, 2026-03-16_19.16.07, and 2026-03-16_19.27.06 prompt export completeness

Problem captured:
- benchmark `codexfarm/prompts/` initially omitted line-role interactions and had no reviewer-facing trace summary surface

Durable decisions:
- benchmark prompt export must contain recipe, line-role, and knowledge interactions in one merged `full_prompt_log.jsonl`
- line-role prompt artifacts should be copied from saved `line-role-pipeline/prompts` artifacts rather than reconstructed through a separate fake path
- `thinking_trace_summary.jsonl` and `thinking_trace_summary.md` should be built from the merged prompt log so every exported row stays on one authoritative surface

Evidence worth keeping:
- the target backfill grew the exported prompt log from `231` rows to `233` rows: `175` recipe, `2` line-role, `56` knowledge

Anti-loop note:
- if a reviewer bundle has recipe and knowledge prompts but no line-role rows, treat it as export incompleteness, not proof that line-role did not run

### 2026-03-16_20.02.00 title metrics versus import recipe counts

Problem captured:
- canonical-text benchmark title-label quality and import-level recipe totals were being read as if they were the same signal

Durable decisions:
- use `per_label.RECIPE_TITLE` when judging title labeling
- use `recipe_counts.predicted_recipe_count` only as a downstream import sanity check

Anti-loop note:
- if title recall and imported recipe count disagree, that is expected until you prove the same surface is being measured

### 2026-03-16_19.56.57 and 2026-03-16_19.58.11 whole-book intent versus projected final authority

Problem captured:
- single-book benchmark behavior was easy to misread as "whole-book line-role Codex authority" when the scored artifact was actually a projection built from authoritative outputs and only a small escalated subset went through live Codex

Durable decisions:
- token spend and scored surface are different seams:
  - live line-role Codex may only see escalated batches
  - canonical scoring can still read a projected artifact built from final authority
- final benchmark `KNOWLEDGE` / `OTHER` scoring should come from final non-recipe authority:
  - deterministic Stage 7 seed authority first
  - optional knowledge-stage block-decision merge second
  - projected scored artifact last
- helper renames alone are not enough; if the benchmark helper still cannot access returned final non-recipe authority from the stage session, it is still at risk of projecting the wrong seam

Evidence worth keeping:
- on `2026-03-16_18.10.25`, saved prompt artifacts showed only `2` line-role batches covering `42` rows total, which is why live line-role token spend was only about `25.5k`

Anti-loop note:
- if prompt spend and scored artifact size disagree, inspect projection mode and final-authority plumbing before assuming Codex line-role execution silently failed

### 2026-03-16_19.35.12 final non-recipe authority must be the scored benchmark truth

Problem captured:
- Codex-enabled benchmark runs could spend large knowledge-stage token budgets while the scored artifact still reflected deterministic seed authority or `authoritative_reuse`

Durable decisions:
- canonical benchmark scoring must follow the final non-recipe authority after optional knowledge refinement, not the deterministic seed alone
- prediction-run helpers must keep the scorer on the canonical projection artifact pair with atomic coordinates; moving back to stage-backed source-block coordinates or stale scorer pointers recreates the regression
- benchmark reporting should make scored-effect truth obvious. If a run spends knowledge tokens but the scored artifact cannot reflect those changes, treat that as a seam bug rather than a model-quality result

Evidence worth keeping:
- the motivating March 16 run spent `424,619` knowledge-stage tokens while telemetry still said `mode=authoritative_reuse`
- after the final-authority projection fixes, canonical scoring again followed the processed import result instead of the seed shortcut

Anti-loop note:
- if a Codex benchmark looks "flat," first prove whether the scored artifact is final-authority projection or a deterministic shortcut before retuning prompts or evaluation code

### 2026-03-16_20.52.23 oversized Oracle payload browser sharding

Problem captured:
- `cookimport bench oracle-upload` could fail in browser mode when one bundle file exceeded Oracle CLI's per-file input cap, even though the bundle itself was otherwise valid

Durable decisions:
- keep `upload_bundle_v1` unchanged on disk; oversized files are split into ordered temporary transport parts only for browser upload
- dry-run stays zero-cost and should fall back to a local preview instead of pretending Oracle accepted an oversized inline payload
- the fix belongs in this repo's upload wrapper, not in benchmark bundle generation or reviewer packet shape

Evidence worth keeping:
- focused regression coverage now verifies that oversized browser uploads use ordered shard attachments and that dry-run still reports the local-preview fallback path

Anti-loop note:
- if browser upload breaks on a large bundle again, inspect the transport shim before redesigning `upload_bundle_v1`

### 2026-03-17_14.30.55 Oracle browser headless wrapper drift

Problem captured:
- the local `oracle-browser-headless` wrapper was no longer the old off-screen Linux `xvfb` path, so browser uploads could start stealing focus or failing with `Missing X server or $DISPLAY` again after payload sharding had already succeeded

Durable decisions:
- benchmark upload should bypass the visible-browser wrapper and call Oracle directly
- force `ORACLE_BROWSER_REMOTE_DEBUG_HOST=127.0.0.1` so Oracle does not chase the WSL nameserver host for DevTools
- pass the Linux off-screen Chromium launcher explicitly instead of trusting the drifted wrapper script

Evidence worth keeping:
- the wrapper had drifted to visible-browser/manual-login settings and `chromium-nosandbox`, which led to Chromium child logs showing `Missing X server or $DISPLAY` and later `ECONNREFUSED 127.0.0.1:9222`

Anti-loop note:
- if browser upload starts failing after payload sharding succeeds, inspect the Chromium launcher / wrapper path before debugging bundle generation or Oracle attachment splitting

### 2026-03-17 interactive Oracle upload cutover and stable browser contract

Problem captured:
- interactive benchmark wrap-up was blocking on synchronous Oracle upload
- detached Oracle uploads needed stable transport files after the benchmark process returned
- Oracle browser failures were easy to misdiagnose because several causes stacked together: stale picker assumptions, split profile roots, wrapper drift, and missing displays in the agent shell

Durable decisions:
- interactive benchmark flows should auto-start Oracle in the background and return immediately after bundle generation
- detached launches must stage everything under `upload_bundle_v1/.oracle_upload_runs/<timestamp>/`, including temporary sharded upload files plus `oracle_upload.log` / `oracle_upload.json`
- the terminal wrap-up should stay short and point straight at `oracle_upload.log`; the final Oracle answer lives there when the run succeeds
- the stable browser contract is:
  - machine-wide auto Chromium launcher
  - canonical browser profile under `~/.local/share/oracle/browser-profile`
  - compatibility symlink from the old `~/.oracle/browser-profile`
  - `--browser-model-strategy ignore` so the visible/manual ChatGPT model wins instead of brittle picker automation

Evidence worth keeping:
- an early theory that only `gpt-5.2-pro` was stale was too narrow; the observed ChatGPT picker had shifted to mode-based options, so even base model-id targeting was brittle
- login churn came from two different profile roots being used over time
- headful Oracle smoke tests from the agent shell failed before ChatGPT interaction because no X display existed, while the xvfb-backed path succeeded against the same canonical profile

Anti-loop note:
- if Oracle upload fails after bundle generation works, debug launcher/profile/model-ignore behavior before reworking `upload_bundle_v1`

### 2026-03-17 benchmark progress rendering and single-book interpretation

Problem captured:
- benchmark progress rows could under-report active worker state, and single-book canonical results were easy to over-read as pure recipe-structure failures

Durable decisions:
- generic `task X/Y | running N` benchmark messages should populate worker rows the same way codex-farm-prefixed messages do
- plain legacy stderr `run=... queued=... running=...` snapshots are compatibility progress noise when structured events are already present
- on current canonical single-book runs, strong boundary exactness does not imply the remaining misses are mostly structural; large error mass can still live in `KNOWLEDGE` vs `OTHER`

Evidence worth keeping:
- on the 2026-03-17 `saltfatacidheatcutdown` single-book run, codexfarm had perfect-or-near-perfect boundary counts but wrong-label rows were still dominated by `KNOWLEDGE -> OTHER` and `OTHER -> KNOWLEDGE`

Anti-loop note:
- if canonical benchmark accuracy looks "too low for a solved structure problem," inspect wrong-label distribution before chasing scorer or boundary changes

### 2026-03-17 benchmark transport and operator surfaces

Problem captured:
- benchmark upload and transport still had a few stale seams after the main shard-runtime cutover: drifted Oracle wrapper usage, stale default model/picker assumptions, and one retired CodexFarm benchmark flag.

Durable decisions:
- benchmark upload bypasses the drifted local wrapper and invokes the real Oracle CLI with the known Linux xvfb Chromium path plus `ORACLE_BROWSER_REMOTE_DEBUG_HOST=127.0.0.1`
- benchmark Oracle default model is `gpt-5.2`; manual `--model` override remains supported
- recipe benchmark subprocesses use CodexFarm's current `--recipeimport-benchmark-mode line_label_v1` flag and do not send benchmark-only flags for extract mode

Anti-loop note:
- if a benchmark subprocess or Oracle upload breaks again, verify the active local transport contract before editing bundle format or interactive wrap-up flow

### 2026-03-17 shared-profile Oracle reattach failure mode

Problem captured:
- Oracle browser uploads against the shared manual-login profile could fail with `connect ECONNREFUSED 127.0.0.1:<port>` even though Chromium was already running on that profile

Durable decisions:
- treat missing `DevToolsActivePort` plus a stale `chrome.pid` as a recoverable profile-reuse failure, not proof that no browser exists
- recover the live port from current Chromium process args when needed, rewrite `DevToolsActivePort`, and only clear singleton lock state when no live Chromium still owns the profile
- keep benchmark upload on the canonical shared profile path; do not start inventing per-run browser profiles just to dodge this failure mode

Evidence worth keeping:
- the failing state was:
  - live Chromium still running on the shared profile
  - `DevToolsActivePort` missing
  - `chrome.pid` pointing at a dead process
  - Chromium singleton files still redirecting launches into the already-running browser

Anti-loop note:
- if Oracle fails on a new localhost port while the shared profile browser is visibly alive, debug profile reattach first, not upload bundle sharding or benchmark wrap-up

### 2026-03-18 Oracle benchmark browser reliability needed both transport fixes and trust fixes

Problem captured:
- March 18 benchmark uploads exposed three different failure classes that looked similar from the outside:
  - composer state / launch failures
  - browser disconnects after a real session had started
  - completed answers that were grounded badly enough to contradict the local bundle

Durable decisions:
- benchmark uploads should always start from an empty composer or fail fast
- detached upload launches must persist `oracle_upload_status.json` beside `oracle_upload.json` and record Oracle version, session id, reattach command, and conversation URL as soon as that data exists
- browser disconnects should classify as `reattachable` when the saved metadata is enough to resume
- exit code `0` is not enough to trust an Oracle answer; benchmark upload must compare the answer against the local bundle root and key topline counts and classify contradictions as `invalid_grounding`

Evidence worth keeping:
- the repo-owned fix was only part of the story; there was also a local Oracle composer patch involved, which is why the durable lesson is "persist recovery metadata early and audit grounding" rather than "assume the browser transport is solved forever"

Anti-loop note:
- if Oracle upload "succeeds" but the answer reads like it reviewed a different bundle, debug grounding/trust checks before reopening browser transport or upload-bundle rendering

### 2026-03-18 Salt Fat Acid Heat regression revalidation proved the stale-run trap

Problem captured:
- the latest measured Salt Fat Acid Heat Codex benchmark in the repo was already stale relative to later prompt/runtime fixes, which made it too easy to keep chasing an old diagnosis

Durable decisions:
- revalidate locally first when benchmark evidence predates prompt/runtime changes
- keep the benchmark story honest when live reruns are blocked by explicit-approval policy: code/tests/docs can be complete while benchmark proof is still pending
- for this specific seam, the lasting policy outcome was:
  - recipe and line-role keep literal prompt-target overrides
  - knowledge returns to a soft prompt-target policy because hard bundle safety caps are correctness-critical

Evidence worth keeping:
- the stale `2026-03-18_22.19.18` run still mattered because it showed the failure family (`missing_owned_chunk_results`, one schema-invalid contradictory row), but it was not enough to prove the later workspace fixes

Anti-loop note:
- if a benchmark diagnosis depends on a run that predates the current workspace changes, treat that run as historical evidence, not final proof

If an older artifact references one of those surfaces, treat it as historical context only, not current contract guidance.

### 2026-03-19 Oracle follow-up bridge and reviewer-request grammar

Problem captured:
- external review was stopping at Oracle turn 1, and the reviewer-facing follow-up note had drifted away from the live `cf-debug` selector/parser surface

Durable decisions:
- Oracle turn 1 may now request narrow follow-up evidence in a parse-friendly `Requested follow-up data` section; recipeimport normalizes that into `cf.followup_request.v1`, writes additive `followup_dataN/`, and continues the same ChatGPT conversation through a linked turn-2 local Oracle session
- detached benchmark uploads must finalize saved turn-1 status from logs/session recovery before deciding whether auto-followup can run
- auto-followup and manual `cookimport bench oracle-followup` reuse the resolved turn-1 model when no explicit override is present
- reviewer docs and parser grammar must stay aligned:
  - canonical line-range syntax is `source:start:end`
  - legacy `source:start-end` remains accepted for backward compatibility

Anti-loop note:
- if follow-up automation looks broken, first prove whether turn 1 actually produced a parseable follow-up request and whether the saved launch status was finalized from Oracle evidence before changing bundle builders or Oracle transport code

### 2026-03-21 paired benchmark contract cleanup

Problem captured:
- paired benchmark comparison roots were drifting on representation because some helper paths still forced different `atomic_block_splitter` values, and interactive mode ids/labels were harder to read than the runtime actually needed

Durable decisions:
- paired `vanilla` / `codexfarm` variants share one `atomic_block_splitter` value sourced from the selected run settings or preserved benchmark baseline payload
- default/profile paths now leave `atomic_block_splitter=off` unless the operator explicitly selects `atomic-v1`
- interactive benchmark mode ids normalize to the current names:
  - `single_book`
  - `selected_matched_books`
  - `all_matched_books`
- older mode ids remain compatibility aliases; artifact roots such as `single_book` are unchanged

Anti-loop note:
- if a paired benchmark comparison moves because one side silently switched representation, inspect `atomic_block_splitter` in the planned run payload before blaming Codex surfaces or scorer drift

### 2026-03-21 single-book benchmark naming converged across runtime, internals, and artifacts

Problem captured:
- the interactive mode rename had landed only halfway: operators were seeing `single_book`, but helper names, split-cache keys, analytics paths, scope values, fixture roots, and some docs still carried the older contract

Durable decisions:
- the active benchmark contract is now aligned end to end:
  - interactive mode id: `single_book`
  - scope string: `single_book`
  - artifact root: `single-book-benchmark`
  - top-level summary filename: `single_book_summary.md`
- split-cache helpers, analytics field paths, helper/test module names, and related runtime strings should use `single_book` too
- older mode ids are compatibility inputs only; they are not the preferred names for new code, docs, or fixtures

Evidence worth keeping:
- the useful lesson from the rename was that product-surface cleanup is not enough; Oracle/upload scope detection, analytics, and checked-in fixtures were all still relying on the stale internal naming until the full convergence pass landed

Anti-loop note:
- if a new benchmark surface or helper works only after mentally translating between `single_book` and an older internal name, the contract is drifting again

### 2026-03-22 Oracle browser upload moved from temporary ignore-mode workarounds to explicit review-model selection

Problem captured:
- earlier Oracle browser reliability work had left the benchmark docs with stale guidance:
  - one section still said to ignore model selection and trust the current browser mode
  - default fallback guidance could still be read as version-pinned
  - one benchmark path was passing an unsupported negated keep-browser flag

Durable decisions:
- the current benchmark Oracle browser contract is:
  - `--browser-model-strategy select`
  - stable Pro-lane fallback via `gpt-5-pro`
  - no negated `--no-browser-keep-browser` flag on turn 1 or turn 2
- env overrides remain the real override seam:
  - `ORACLE_GENUINE_MODEL`
  - `ORACLE_PRO_MODEL`
  - `ORACLE_REVIEW_MODEL`
  - `ORACLE_DEEP_REVIEW_MODEL`
- the earlier `ignore` model-strategy guidance is historical only; it was a temporary workaround during browser-wrapper instability, not the active benchmark contract

Evidence worth keeping:
- the saved 2026-03-22 Oracle failure made the contract bug undeniable: the run could still show a stale version-pinned Pro id plus the unsupported negated keep-browser flag before ChatGPT ever saw the upload

Anti-loop note:
- if Oracle browser review lands on the wrong lane again, debug the active benchmark command contract first; do not assume the old `ignore` strategy is still the right answer

### 2026-03-22 upload_bundle diagnostics were narrowed so blame, call counts, and trace parity agree

Problem captured:
- `upload_bundle_v1` diagnostics were still contradicting themselves:
  - correction-stage empty mappings could be blamed on `build_final_recipe`
  - observed final-recipe call counts could be inflated from correction calls
  - baseline-trace parity could claim codex-only trace artifacts were missing even when bundle-local derived rows and run diagnostics said they existed

Durable decisions:
- `final_recipe_empty_mapping` must mean actual `build_final_recipe` empty-mapping output only
- `analysis.recipe_pipeline_context.observed_recipe_stage_call_counts.build_final_recipe` counts only observed final-recipe calls
- `16_baseline_trace_parity.json` should honor derived bundle-local trace artifacts when run diagnostics already mirrored them into the bundle
- keep this narrowly in the bundle existing-output/model/render seams; it is not a scoring change and not an Oracle transport change

Evidence worth keeping:
- the regression mattered because it looked like recipe-stage topology disagreement when the real bug was diagnostic attribution: bundle rows, run diagnostics, and parity output were disagreeing about the same run

Anti-loop note:
- if upload-bundle diagnostics disagree again, inspect the normalized bundle model and derived bundle-local rows before blaming scorer logic or the underlying benchmark run

## 20. 2026-03-22 Oracle follow-up recovery must trust recovered grounded answers and reuse the same session home

Problem captured:
- detached Oracle uploads could recover a timed-out turn 1 into `oracle_upload.log`, but the follow-up audit still saw the old timeout text first and left the run stuck in `recovering_turn_1`
- even after that audit bug, turn 2 could still miss the saved browser session when Oracle fell back to ambient home/profile settings instead of the source run's Oracle environment

Durable decisions:
- a later grounded `Answer:` block with parsed follow-up data beats earlier timeout markers in the same saved log
- turn-2 `continue-session` must inherit the source run's Oracle browser home/profile so it targets the same saved chat/session
- keep this fix narrow:
  - log-audit precedence
  - env/home inheritance
  It is not a packet-builder redesign and not a broader Oracle recovery rewrite

Evidence worth keeping:
- the March 22 stalled follow-up proved both seams in one chain: one saved run already contained a recovered grounded answer but still remained in `recovering_turn_1`, and the next post-fix attempt reached turn 2 but failed with `No session found ...` after Oracle stopped using the original session home

Anti-loop note:
- if Oracle follow-up stalls after a visible recovered answer, debug audit precedence and session-home reuse before changing request parsing or bundle selection

## 21. 2026-03-22 upload_bundle recipe-correction debug views had to count compact outputs and honest fallbacks

Problem captured:
- `upload_bundle_v1` recipe-correction debug views were still lying in two ways:
  - compact correction outputs looked empty because readers only trusted older wide shapes
  - `regression_casebook` could still claim `top_negative_delta_recipes` even when there were no negative-delta fallback candidates

Durable decisions:
- compact `recipe_llm_correct_and_link` outputs with `payload.r[].cr.i` / `payload.r[].cr.s` count as non-empty correction outputs
- `empty_output_signal` now means truly empty correction output, not just an empty ingredient-step mapping
- casebook fallback source/reason becomes signal-based when there is no negative-delta recipe to point at
- bundle generation should fail loudly if parsed correction outputs are visibly non-empty while stage observability still says every correction output is empty

Evidence worth keeping:
- the regression looked like stage-topology disagreement at first, but the real bug was derived debug-view attribution: compact shard payloads, observability summaries, and fallback labels were disagreeing about the same run

Anti-loop note:
- if recipe-correction debug views drift again, inspect compact existing-output parsing and fallback-source selection before changing benchmark scoring or recipe topology metadata
