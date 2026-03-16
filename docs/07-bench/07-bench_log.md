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
- scoring keeps legacy global alignment semantics for safety
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
- replay boundary functions are explicit: predict, evaluate, legacy direct-call, and pipelined run paths
- `--predictions-out` writes stage-block prediction records
- `--predictions-in` accepts both current record files and older run-pointer records
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

## 7. 2026-03-02 interactive single-offline and single-profile benchmark contract

Problem captured:

- interactive benchmark flows needed one stable session-root model, paired-run semantics, and one reviewer handoff packet

Durable decisions:

- `single_offline` writes one session root under `single-offline-benchmark/<source_slug>/`
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
  - `llm_tags_pipeline=off`
  - `line_role_pipeline=off`
  - `atomic_block_splitter=off`
- build Codex variants from that normalized baseline, but do not re-normalize those Codex payloads back into baseline form

Anti-loop note:

- if `include_codex_farm=True` stops producing Codex variants, check for accidental re-normalization of Codex payloads

## 10. 2026-03-06 QualitySuite deterministic-only guard, pass4 wiring, and selective retry

Problem captured:

- QualitySuite metadata could drift from the real executable baseline
- Codex-enabled settings could sneak into supposedly deterministic quality runs
- pass4 benchmark evidence existed but was inconsistently surfaced
- partial pass failures needed salvage at the pass boundary, not whole-book reruns

Durable decisions:

- `bench quality-run` is deterministic-only end-to-end
- preserve both `requested_run_settings` and normalized executable `run_settings`
- pass4 benchmark helpers keep baseline variants off and enable pass4 only in Codex variants
- `knowledge/<workbook_slug>/block_classifications.jsonl` is the preferred scored pass4 artifact for outside-span `KNOWLEDGE`
- `cf-debug` now has pass4-specific selectors and `audit-pass4-knowledge`
- benchmark selective retry retries only missing bundle files for the current failed pass and records detailed truth in `raw/llm/<workbook_slug>/llm_manifest.json`

Anti-loop note:

- if pass4 “ran” but benchmark lift is flat, inspect the narrow scored upgrade seam before assuming pass4 failed

## 11. 2026-03-13 execution semantics and single-root output contract

Problem captured:

- benchmark metadata and path layout were easy to misread as evidence of separate execution modes or paired-root behavior

Durable decisions:

- one direct benchmark invocation should resolve one eval root
- prediction-generation scratch stays under that same eval root as `<eval_output_dir>/prediction-run`
- interactive nested benchmark flows pass explicit child `eval_output_dir` paths inside their session root

Anti-loop note:

- nearby sibling timestamps are not proof of a filesystem contract; verify whether there were separate invocations

## 12. 2026-03-15 stage-backed scoring and upload-bundle seam map

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

## 13. 2026-03-15 canonical scorer-pointer cutover and hard deletion

Problem captured:

- benchmark helper paths still carried stage-vs-line-role scorer branches and duplicate manifest keys
- compatibility readers could silently recover artifacts from old filenames or implicit directories, which made it hard to tell whether the canonical benchmark contract was actually populated

Durable decisions:

- every prediction/eval run now exposes one canonical scorer pointer pair:
  - `stage_block_predictions_path`
  - `extracted_archive_path`
- when line-role projection artifacts become the scored surface for a run, prediction generation rewires that same canonical pointer pair to the line-role artifacts instead of publishing a second scorer namespace
- duplicate scorer keys were removed from manifests/import payloads rather than kept as aliases
- benchmark bundle/eval resolution now requires the canonical pointers and should fail loudly when they are missing

Anti-loop note:

- if a helper wants to guess scorer files from path layout, that is reintroducing the deleted compatibility contract

## 14. 2026-03-16 semantic recipe-stage bundle contract

Problem captured:

- reviewer-facing bundle output was still teaching pass-slot internals (`pass2_stage`, `pass3_stage`) instead of the semantic recipe stages a reviewer actually needs
- starter-pack/casebook rendering and follow-up tooling were at risk of baking those implementation names back into the external surface

Durable decisions:

- `upload_bundle_v1` and related rendering now expose `recipe_topology_key` plus ordered semantic `recipe_stages`
- the active stage meanings are:
  - standard recipe pipeline: `schemaorg`, `final`
  - historical merged-repair topology: `merged_repair`
- starter-pack and casebook rendering should present chunking separately from recipe correction/finalization rather than flattening everything into pass-slot labels
- historical bundles may still be read through narrow compatibility adapters for old pass4 sample names and related local artifact names, but new reviewer-facing bundle fields must stay semantic

Anti-loop note:

- if external-review output starts showing pass-slot field names again, fix the normalized model or renderer instead of adding more compatibility prose around it

## 15. 2026-03-15 QualitySuite guard order and payload projection

Problem captured:

- baseline coercion could hide Codex-enabled requests before validation
- strict `RunSettings` loading could fail on mixed payloads that still contained persistence metadata

Durable decisions:

- run Codex-disallow validation against the requested payload before baseline coercion
- project QualitySuite payloads through `project_run_config_payload(..., contract=RUN_SETTING_CONTRACT_FULL)` before `RunSettings.from_dict(...)`

Anti-loop note:

- if QualitySuite behavior looks inconsistent, debug validation order and payload projection before relaxing strict settings loading

## 16. Retired History Notice

The following removed benchmark workflows were intentionally pruned from this log:

- tournament-based QualitySuite promotion flows
- `scripts/quality_top_tier_tournament.py`
- retired `bench run`, `bench sweep`, `bench validate`, and `bench knobs` surfaces
- line-role projection as the primary scored truth
- fast canonical alignment production scoring

If an older artifact references one of those surfaces, treat it as historical context only, not current contract guidance.
