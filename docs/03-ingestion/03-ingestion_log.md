---
summary: "Ingestion architecture/build/fix-attempt log to avoid repeated dead ends and circular debugging."
read_when:
  - When you are going in multi-turn circles on ingestion behavior or implementation
  - When the human says "we are going in circles on this"
  - When you need prior architecture versions, build attempts, or failed fixes before trying another change
---

# Ingestion Log

Read the current runtime docs first in `docs/03-ingestion/03-ingestion_readme.md`. Use this log to understand prior attempts and avoid retrying failed paths.

## Consolidation Note

`docs/03-ingestion` intentionally keeps only:
- `docs/03-ingestion/03-ingestion_readme.md` (current runtime reference)
- `docs/03-ingestion/03-ingestion_log.md` (historical/anti-loop notes)

Older one-off ingestion notes were consolidated into these files and removed from the docs tree. Use `git log` / `git show` if you need archaeology.

## Historical Attempts (Preserve To Avoid Rework Loops)

### 2026-02-12 10:17:19: Pipeline convergence note

Established and still true:
- Importers differ early (block-first vs record-first vs structured-first).
- They converge at `ConversionResult` and downstream writer pipeline.
- Chunking is fed from non-recipe/topic paths post-convert.

Do not re-litigate unless code changed:
- “Should we force all importers into same early extraction model?”
- Existing design intentionally allows importer-specific extraction while standardizing handoff contract.

### 2026-02-12: Unstructured EPUB adapter note

Established and still true:
- Unstructured is default EPUB extractor.
- Adapter emits traceability metadata and diagnostics JSONL artifact.
- Deterministic role assignment exists and is covered by unit tests.

Do not re-litigate unless objective evidence appears:
- "Need to change the default extractor globally without evidence."
- Current default was chosen to retain richer semantic signals and traceability.

### 2026-02-15: Prior ingestion README consolidation

Preserved decisions:
- Split-job merge architecture for PDF + EPUB.
- Main-process merge + ID rewrite strategy.
- Serial fallback for environments blocking multiprocessing.
- Raw artifact merge from temporary `.job_parts` workspace.

Known incomplete idea intentionally not implemented:
- Earlier EPUB split plan considered overlap + owned-range filtering.
- Implemented version uses straightforward spine ranges without overlap.
- If boundary errors become frequent, revisit overlap as a targeted fix, not a broad redesign.

### 2026-02-15_22.06.34: Split-merge and ID rewrite discovery map

Preserved operational details:
- Split workers write raw artifacts under `.job_parts/<workbook>/job_<index>/raw/...` and return merge payloads.
- Main-process merge sorts by source range, rewrites recipe IDs globally (`c0..cN`), then rebuilds tips/chunks once.
- Raw merge collisions are renamed with `job_<index>_...` prefixes so artifacts are not dropped.
- `.job_parts` is expected to be removed on successful merge; leftover `.job_parts` is usually merge-failure/interruption evidence and should be treated as debug signal.
- Stage builds and passes `base_mapping` for workers; worker `inspect()` is mainly a split-planning concern, not the normal non-split conversion initialization path.

### 2026-02-16_13.02.32: MarkItDown extractor split contract

Preserved contract:
- `epub_extractor` remains the single run-setting knob across stage and benchmark prediction generation.
- `markitdown` is whole-book EPUB conversion and cannot honor spine-range split jobs.
- Split-planner parity must be maintained in both planners together:
  - `cookimport/cli.py:_plan_jobs(...)`
  - `cookimport/labelstudio/ingest.py:_plan_parallel_convert_jobs(...)`
- Effective worker reporting must stay honest when split capability changes:
  - `cookimport/config/run_settings.py:compute_effective_workers(...)`.
- `labelstudio_benchmark(...)` must forward selected extractor explicitly so manifests/history rows record the true extractor used.

Anti-loop note:
- Do not "fix" markitdown split errors by forcing pseudo-ranges; extractor behavior is whole-book by design.

### 2026-02-16_14.00.37: Unstructured v2 input-shape caveat + option propagation

Discovery preserved:
- `partition_html(..., html_parser_version=\"v2\")` can fail on normal EPUB XHTML with:
  - `No <body class='Document'> or <div class='Page'> element found in the HTML.`
- This is usually parser-v2 input-shape mismatch, not EPUB corruption.

Durable contract:
- Keep parser default at `v1` for broad compatibility.
- When parser `v2` is requested, compatibility wrapping/annotation must happen in adapter layer (`cookimport/parsing/unstructured_adapter.py`) so all flows share behavior.
- EPUB unstructured option triplet must propagate in every run-producing path (not stage only):
  - `epub_unstructured_html_parser_version`
  - `epub_unstructured_skip_headers_footers`
  - `epub_unstructured_preprocess_mode`
- These options must appear in run config, drive `C3IMP_EPUB_UNSTRUCTURED_*` runtime env vars, and be reflected in diagnostics metadata.

Debugging evidence worth preserving:
- Per-spine `raw_spine_xhtml_*.xhtml` and `norm_spine_xhtml_*.xhtml` artifacts made parser-shape failures and preprocessing effects visible quickly without reopening EPUB internals repeatedly.

### 2026-02-19_14.19.06: EPUB postprocess + health wiring map

Preserved contract:
- `cookimport/plugins/epub.py:_extract_docpack(...)` is the shared join point where extractor-specific block extraction converges before downstream segmentation.
- Shared EPUB postprocess (`postprocess_epub_blocks`) applies to `beautifulsoup`/`unstructured`/`markdown`; `markitdown` intentionally bypasses this cleanup path.
- EPUB extraction health is computed from final blocks and persisted as `epub_extraction_health.json`; warning keys are promoted into `ConversionReport.warnings`.
- Spine metadata now uses typed `EpubSpineItem` records so zip-fallback and ebooklib flows apply the same nav/TOC skip logic.

Anti-loop note:
- Do not duplicate cleanup logic per extractor backend; keep common cleanup centralized in the shared join point.

### 2026-02-22_14.08.34 - elapsed spinner ticker + post-candidate importer progress

Problem captured:
- After `candidate X/Y` extraction completed, long importer phases could continue with unchanged status text, making CLI spinners appear stalled.

Behavior contract preserved:
- Callback-driven CLI status wrappers append elapsed seconds when phase text remains unchanged long enough.
- Shared wrapper usage was expanded across Label Studio import flows, benchmark import, and bench run/sweep flows.
- EPUB and PDF converters emit explicit post-candidate callbacks before finalization so visible progress continues past extraction counters.

Verification and evidence preserved:
- Recorded command set includes:
  - `pytest -q tests/test_labelstudio_benchmark_helpers.py -k "status_progress_message or run_with_progress_status"`
  - `pytest -q tests/test_epub_importer.py tests/test_pdf_importer.py -k post_candidate_progress`
  - `pytest -q tests/test_bench_progress.py`
- Recorded evidence includes examples such as:
  - unchanged phase text receiving elapsed suffix (for example `... (17s)`),
  - post-candidate callbacks (`Analyzing standalone knowledge blocks...`, `Finalizing ... extraction results...`).

Key constraints and anti-loop notes:
- Reuse existing `progress_callback` plumbing; do not introduce separate indicator systems.
- Default elapsed ticker threshold is 10 seconds with one-second updates for readability.
- Progress update additions are text-only; do not treat this as a data-contract/output-contract change.

Rollback path preserved:
- Revert shared `_run_with_progress_status` callback wrappers in `cookimport/cli.py` and importer post-candidate `_notify(...)` additions.

## 2026-02-22 understanding merge batch (chronological)

### 2026-02-22_14.09.33 spinner stale after candidate loop

Preserved findings:
- CLI spinner text is callback-driven; no new callback text means perceived stall.
- EPUB/PDF importers had long post-candidate phases where callback text previously did not change.

Durable rule:
- Keep liveness fixes split between runtime callback emission and wrapper elapsed suffix display; avoid introducing parallel status systems.

### 2026-02-22_14.25.24 importer review fixture gaps and inspect fallback

Preserved findings:
- Paprika/RecipeSage test reliability can be blocked by missing template fixtures before importer logic is actually exercised.
- `WorkbookInspection` extra-field validation can turn exception-path warning injection into secondary failures.
- RecipeSage missing-file exceptions raised before guarded `try` blocks skip report-level conversion error handling.

Anti-loop note:
- If importer tests fail "too early," verify fixture presence and exception-path schema compliance before reworking parser logic.

### 2026-02-22_14.43.40 split merge codex-farm full_text rebase

Preserved findings:
- codex-farm pass1 context requires one merged absolute block stream.
- Split runs already produce per-job `full_text.json`; merge must reassemble and rebase into one workbook-level `full_text.json`.
- Matching offset application across recipe/tip/topic location fields is required so provenance and pass1 windows align.

Anti-loop note:
- If split-run codex-farm context looks shifted, inspect merged `raw/.../full_text.json` and location-offset application before changing pass logic.

### 2026-02-22_23.46.43 standalone knowledge-analysis parallelism

Merged source:
- `docs/understandings/2026-02-22_23.46.43-standalone-knowledge-analysis-parallelism.md`

Problem captured:
- EPUB/PDF could appear stuck on "Analyzing standalone knowledge blocks..." because standalone containers were processed serially.

Preserved contract:
- Container-level standalone analysis can run in parallel after chunking because containers are independent.
- Even when completion is out-of-order, merged outputs must be sorted back by original container index to keep deterministic ordering.
- Emit `task X/Y` progress for this phase (including `0/Y` start) so spinner throughput/ETA stays visible.
- Bounded worker control remains `C3IMP_STANDALONE_ANALYSIS_WORKERS` (default `4`, minimum `1`).

### 2026-02-22_23.46.51 - parallelize standalone knowledge analysis (`docs/tasks/2026-02-22_23.46.51 - parallelize-standalone-knowledge-analysis.md`)

Problem captured:
- EPUB/PDF imports could stall visibly during standalone knowledge-block analysis because container loops were serial.

Decision preserved:
- Parallelize at standalone-container boundary with `ThreadPoolExecutor` in EPUB and PDF importer paths.
- Keep deterministic merge order by sorting container results by original container index after worker completion.
- Keep progress callback text in `task X/Y` format for spinner throughput and ETA compatibility.

Evidence preserved from task:
- Recorded verification run:
  - `source .venv/bin/activate && pytest tests/parsing/test_tip_extraction.py tests/ingestion/test_epub_importer.py tests/ingestion/test_pdf_importer.py -q -o addopts=''` -> `37 passed, 7 warnings in 10.97s`.

Anti-loop notes:
- Do not append from worker threads into shared output arrays directly.
- If order drift appears, inspect post-merge container-index sort before touching extraction heuristics.

## 2026-02-25 understanding merge batch (EPUB extractor variants + canonical naming)

### 2026-02-25_17.57.34 extractor variants and unstructured-only knob contract

Merged source:
- `docs/understandings/epub-extractor-variants-unstructured-knobs.md`

Problem captured:
- Extractor-mode comparisons kept mixing backend selection with unstructured-only knobs, leading to false tuning loops.

Decision/outcome preserved:
- Keep four mutually exclusive extractor modes in runtime: `unstructured`, `beautifulsoup`, `markdown`, `markitdown`.
- Keep `parser` / `skiphf` / `pre` as unstructured-only controls.
- Preserve split-job boundary contract: `markitdown` remains whole-book only; other explicit extractors can split by spine ranges.
- Keep separate run labels for `semantic_v1` and `br_split_v1` even while behavior is currently the same.

Anti-loop notes:
- Do not attribute non-unstructured behavior changes to unstructured-only knobs.
- If reports/slugs imply those knobs changed non-unstructured runs, debug settings normalization/reporting before changing importer logic.

### 2026-02-25_18.05.02 `beautifulsoup` canonical-name normalization boundary

Merged source:
- `docs/understandings/2026-02-25_18.05.02-epub-extractor-beautifulsoup-canonical-name.md`

Problem captured:
- Canonical-name drift across CLI/run-settings/importer paths can split one backend into multiple extractor names in manifests, dashboard groups, and fixtures.

Decision/outcome preserved:
- Canonical token is `beautifulsoup` only.
- Normalization occurs centrally in `cookimport/epub_extractor_names.py` before validation.
- Runtime/config/debug/ingest call sites must stay aligned (`run_settings`, CLI, epubdebug CLI, Label Studio ingest, EPUB plugin).

Anti-loop note:
- If one backend appears under multiple names in analytics/benchmark history, treat canonical-name drift as the primary fix target.

### 2026-02-27_19.50.48: ingestion docs completeness audit (readme + nearby code)

Scope of audit:
- Cross-checked `docs/03-ingestion/03-ingestion_readme.md` against active ingestion runtime paths in `cookimport/cli.py`, `cookimport/cli_worker.py`, `cookimport/staging/writer.py`, importer modules, and parsing helpers.

Decisions applied:
- Expanded README module map to include active run-settings normalization/policy modules, EPUB backend modules, tips/atoms/chunks/tables/sections helpers, and stage-block prediction writer module.
- Updated output-contract section to include active artifacts that were missing from docs:
  - `sections/<workbook>/...`
  - `tables/<workbook>/...`
  - `.bench/<workbook>/stage_block_predictions.json`
  - `processing_timeseries.jsonl`
- Updated worker/merge flow descriptions to include optional table extraction and stage-block prediction writes.
- Updated ingestion test-path pointers to current `tests/ingestion`, `tests/parsing`, and `tests/staging` locations.

Anti-loop note:
- For future ingestion doc audits, diff README claims against these code hubs first:
  - `cookimport/cli.py`
  - `cookimport/cli_worker.py`
  - `cookimport/staging/writer.py`
  - `cookimport/plugins/epub.py`
  - `cookimport/plugins/pdf.py`
  - `cookimport/parsing/{tips.py,chunks.py,tables.py}`

### 2026-02-27_19.53.12 markdown/markitdown policy-lock scope

Problem captured:
- Enforcing extractor policy in only one command path left other runtime paths able to reintroduce locked extractors.

Durable decisions:
- Enforce extractor lock at command normalization + run-settings coercion + UI/knob surfaces.
- Keep one explicit temporary unlock env (`COOKIMPORT_ENABLE_MARKDOWN_EXTRACTORS=1`) instead of per-surface exceptions.

### 2026-02-28_00.45.23 ingestion doc retirement audit

Problem captured:
- Ingestion docs still carried repeated archival text around retired extractor-auto behavior.

Durable decisions:
- Keep only active-runtime contracts in `03-ingestion_readme.md`.
- Keep extractor-auto as compatibility migration context only.
- Preserve active markitdown whole-book and split-merge ordering rules.

## 2026-02-28 migrated understanding ledger

Chronological migration from `docs/understandings`; source files were removed after this merge.

### 2026-02-27_21.19.47 priority 1 plan rebuild context

Source: `docs/understandings/2026-02-27_21.19.47-priority-1-plan-rebuild-context.md`
Summary: Priority-1 plan rebuild context: active plan duplicated OG archive and referenced a missing source doc.

Details preserved:


# Priority-1 Plan Rebuild Context

The previous `docs/plans/priority-1.md` was byte-for-byte identical to `docs/plans/OGplan/priority-1.md`, so there was no distinction between active and archived versions.

The draft also referenced `BIG PICTURE UPGRADES.md`, which is not present in this repository.

Rebuild approach used for the active plan:

- align the plan to actual code entrypoints (`cookimport/core/scoring.py`, importer plugin call sites, strict report/model contracts),
- keep codex-farm recipe parsing policy-locked off,
- split work into required core gating/reporting milestones and optional additive backend permutations.

### 2026-02-27_22.03.50 priority1 fixtures and default gate parity

Source: `docs/understandings/2026-02-27_22.03.50-priority1-fixtures-and-default-gate-parity.md`
Summary: Priority-1 discovery: stabilize importer tests with local fixtures and keep recipe gate defaults aligned across stage/pred-run.

Details preserved:


# Priority-1 Fixture and Gate-Parity Discovery

Paprika and RecipeSage ingestion tests were pointing at `docs/template/examples/*`, but that folder is not present in this workspace. Creating fixture payloads directly in `tmp_path` makes those tests self-contained and removes environment drift.

Recipe scoring defaults also need to stay aligned across all entrypoints. `score_recipe_likeness(...)` already defaults `recipe_score_min_ingredient_lines` to `1`; stage and benchmark/pred-run defaults should match (`RunSettings`, `stage`, `labelstudio-benchmark`, `generate_pred_run_artifacts`, `run_labelstudio_import`) so one-line-ingredient recipes are not unexpectedly penalized only in CLI-driven runs.

### 2026-02-27_22.14.51 priority2 current section detection and wiring map

Source: `docs/understandings/2026-02-27_22.14.51-priority2-current-section-detection-and-wiring-map.md`
Summary: Priority-2 discovery: section grouping is shared downstream, but importer extraction and run-setting wiring are still fragmented.

Details preserved:


# Priority-2 Current Section Detection and Wiring Map

Current shared behavior is mostly downstream:

- `cookimport/parsing/sections.py` already drives section grouping consumed by `staging/jsonld.py`, `staging/writer.py`, `staging/draft_v1.py`, and section-aware step linking.

Current upstream extraction is still importer-specific:

- `plugins/text.py` and `plugins/excel.py` each contain near-identical `_extract_sections_from_blob` logic.
- `plugins/epub.py` and `plugins/pdf.py` each use their own `_extract_fields` heuristics for ingredient/instruction partitioning.

Current wiring gap:

- `RunSettings` has no section-detector backend knob yet.
- Stage and prediction-generation wiring patterns are already established (`cli.py`, `cli_worker.py`, `labelstudio/ingest.py`, `run_settings_adapters.py`) and should be reused.

Benchmark scope note:

- `_build_all_method_variants(...)` currently permutes EPUB extractor settings only, so adding section-backend permutations should be explicit/opt-in to avoid accidental runtime growth.

### 2026-02-27_22.25.43 priority3 current state audit

Source: `docs/understandings/2026-02-27_22.25.43-priority3-current-state-audit.md`
Summary: Priority 3 audit: multi-recipe splitting is still importer-local heuristics; shared splitter wiring has not landed yet.

Details preserved:


# Priority 3 Current-State Audit (2026-02-27)

- Active `docs/plans/priority-3.md` and archived `docs/plans/OGplan/priority-3.md` were identical and stale, including invalid citation placeholders.
- There is currently no shared `multi_recipe_splitter` run setting or CLI/adapters wiring in `run_settings.py`, `cli.py`, `run_settings_adapters.py`, or `labelstudio/ingest.py`.
- Multi-recipe behavior today is importer-local:
  - Text: `_split_recipes(...)` heuristics in `cookimport/plugins/text.py`.
  - EPUB: `_detect_candidates(...)` + `_find_recipe_end(...)` and `_is_subsection_header(...)` guard in `cookimport/plugins/epub.py`.
  - PDF: `_detect_candidates(...)` + `_find_recipe_end(...)` heuristics in `cookimport/plugins/pdf.py`.
- Existing tests cover text multi-recipe fixtures and EPUB `For the X` subsection behavior, but there are no shared splitter tests yet.
- Priority 3 segmentation-eval ambitions overlap Priority 8 planning, so shared splitter delivery should land first and evaluation surfaces should be coordinated.

### 2026-02-27_22.27.41 priority7 current runtime gap map

Source: `docs/understandings/2026-02-27_22.27.41-priority7-current-runtime-gap-map.md`
Summary: Priority-7 audit: webschema lane is not implemented; importer selection is score-based with no stage pipeline flag.

Details preserved:


# Priority 7 Current Runtime Gap Map

- Current importers are `text`, `excel`, `epub`, `pdf`, `paprika`, and `recipesage`; nothing claims `.html`, `.htm`, or `.jsonld`.
- Stage runtime does not support `--pipeline` importer forcing; importer choice is automatic via `registry.best_importer_for_path(...)`.
- `RunSettings` and CLI knobs currently cover EPUB/scoring/table/LLM surfaces only; there are no webschema fields.
- All-method variant expansion is EPUB-specific today; non-EPUB inputs get a single variant.
- Paprika already has a limited local HTML+JSON-LD path, which is a useful reference for Priority 7 plugin design.

### 2026-02-27_22.37.24 priority3 shared splitter wiring map

Source: `docs/understandings/2026-02-27_22.37.24-priority3-shared-splitter-wiring-map.md`
Summary: Priority 3 refresh discovery: shared section detection is live, but multi-recipe splitting is still importer-local and unwired in run settings.

Details preserved:


# Priority 3 Shared-Splitter Wiring Map (2026-02-27)

- `section_detector_backend` is already wired end-to-end (`run_settings`, stage CLI, run-settings adapters, Label Studio ingest).
- Text/Excel call `extract_structured_sections_from_lines(...)`; EPUB/PDF have `shared_v1` extraction branches.
- Multi-recipe splitting is still importer-local:
  - Text uses `_split_recipes(...)`.
  - EPUB/PDF rely on `_detect_candidates(...)` and `_find_recipe_end(...)`.
- `_build_all_method_variants(...)` already adds `section_detector_backend` as a dimension when non-legacy; Priority 3 should follow this pattern for reproducible backend comparisons without auto-expanding default variant count.

### 2026-02-27_22.52.17 priority7 webschema detection and variant guardrails

Source: `docs/understandings/2026-02-27_22.52.17-priority7-webschema-detection-and-variant-guardrails.md`
Summary: Priority-7 implementation detail: keep RecipeSage precedence for .json while expanding webschema all-method variants only for webschema-capable inputs.

Details preserved:


# Priority 7 WebSchema Guardrails

- `webschema` detection is high-confidence for `.html/.htm/.jsonld`, but `.json` is guarded:
  - if JSON payload looks like RecipeSage export (`recipes` list with Recipe rows), webschema returns `0.0` so RecipeSage remains selected.
  - otherwise, webschema claims `.json` only when schema Recipe objects are actually present.
- All-method variant expansion remains bounded:
  - EPUB keeps existing extractor matrix behavior.
  - non-EPUB keeps one variant except webschema-capable sources.
  - webschema-capable sources expand only `web_schema_policy` (`prefer_schema`, `schema_only`, `heuristic_only`) while reusing base values for other webschema settings.


### 2026-02-27_23.20.08 priority3 rules v1 coverage signal thresholds

Source: `docs/understandings/2026-02-27_23.20.08-priority3-rules-v1-coverage-signal-thresholds.md`
Summary: Priority-3 splitter discovery: rules_v1 coverage thresholds must count section-header signals, not only content-like lines, to avoid rejecting valid short recipe splits.

Details preserved:


## Discovery

`rules_v1` boundary acceptance originally computed left/right coverage using only ingredient/instruction content-line flags. In short recipe spans, instruction bodies like `Do the thing.` may not classify as instruction-like content, causing false `left_section_coverage_below_threshold` rejects even when clear `Directions:` headers exist.

## Durable Contract

Coverage thresholds for shared multi-recipe splitting should use ingredient/instruction signal lines (content plus section-header signals) so `min_* = 1` remains practical for markdown/text fixtures with short imperative instruction lines.

## Evidence

- Failing test before fix: `tests/ingestion/test_text_importer.py::test_convert_multi_recipe_rules_v1_backend`
- Rejection trace reason before fix: `left_section_coverage_below_threshold` at boundary `# Recipe Two`
- Passing tests after fix:
  - `tests/parsing/test_multi_recipe_splitter.py`
  - `tests/ingestion/test_text_importer.py::test_convert_multi_recipe_rules_v1_backend`

## Anti-loop Note

If rules_v1 misses obvious boundaries, inspect `multi_recipe_split_trace` first and verify whether coverage failed because header signals were excluded.

## 2026-02-27 tasks consolidation ledger (migrated from `docs/tasks`)

The following task files were merged into this section and then removed from `docs/tasks`:
- `priority-1.md` (mtime `2026-02-27 22:05:02`)
- `priority-2.md` (mtime `2026-02-27 22:42:18`)
- `priority-7.md` (mtime `2026-02-27 22:57:03`)
- `priority-3.md` (mtime `2026-02-27 23:22:43`)

### 2026-02-27_22.05.02: Priority 1 deterministic recipe-likeness gating

Problems captured:
- Active and archived Priority 1 plan files were identical and stale.
- Test fixtures depended on missing `docs/template/examples/*` paths.
- Importer fallback `warnings=[...]` values broke strict `WorkbookInspection(extra="forbid")`.
- Default mismatch existed between scorer min-ingredient-lines and CLI/run-settings defaults.

Durable decisions:
- Keep one deterministic core scoring lane in `cookimport/core/scoring.py` with additive reporting (`RecipeCandidate.recipeLikeness`, `ConversionReport.recipeLikeness`).
- Preserve project policy: recipe codex-farm parsing stays off.
- Align default `recipe_score_min_ingredient_lines=1` across scorer, run settings, stage, and benchmark/pred-run paths.
- Replace path-coupled importer tests with local temp fixtures.

Outcome preserved:
- Priority 1 core lane is implemented across importer families with deterministic gate actions and debug/report artifacts.
- Optional permutation lane was explicitly left open and not implemented in this pass.

Anti-loop notes:
- If recipe gating appears inconsistent between stage and benchmark paths, verify defaults in run settings and CLI adapters before retuning thresholds.
- Treat missing fixture paths as test-smell; keep ingestion tests self-contained.

### 2026-02-27_22.42.18: Priority 2 shared section detection rollout

Problems captured:
- Section grouping downstream was shared, but upstream importer extraction stayed fragmented.
- No section-detector run-setting/backend surface existed initially.
- Shared EPUB/PDF extraction could collapse `For the X` headers via wrapped-line merge.
- Label Studio ingest test doubles broke after `run_settings` kwargs were threaded through importer convert calls.

Durable decisions:
- Implement additive backend `section_detector_backend=legacy|shared_v1` with `legacy` default.
- Keep deterministic, LLM-free behavior and preserve existing `sections.py` output contracts.
- Preserve component headers as standalone lines in shared EPUB/PDF paths.
- Keep all-method variant growth explicit (dimension surfaces in reports when non-default, no automatic matrix explosion).

Outcome preserved:
- Text/Excel/EPUB/PDF now support shared section backend wiring and report reproducible backend choice.
- Stage/benchmark prediction-generation flows persist section backend in run-config/report surfaces.

Anti-loop notes:
- When section behavior differs between runs, compare per-source import reports (`runConfig.section_detector_backend`) rather than only top-level run manifests.
- If `For the X` regressions reappear, inspect wrapped-line merge behavior before touching section classifier heuristics.

### 2026-02-27_22.57.03: Priority 7 schema-first web ingestion

Problems captured:
- No dedicated local webschema importer existed for `.html/.htm/.jsonld/.json`.
- Old plan assumptions relied on nonexistent `--pipeline` forcing and stale docs.
- `.json` extension overlap with RecipeSage required guarded detection.

Durable decisions:
- Implement a dedicated deterministic `webschema` importer (not ad-hoc extensions to existing importers).
- Keep behavior local-file and LLM-free.
- Use run settings as canonical webschema knob surface.
- Guard `.json` detection so RecipeSage exports retain precedence.
- Keep all-method expansion bounded to `web_schema_policy` variants for webschema-capable sources.

Outcome preserved:
- `webschema` importer is implemented with schema-first lane plus deterministic fallback text extraction lane.
- Report/raw artifacts include webschema extraction evidence (`schema_extracted`, optional `schema_accepted`, optional `fallback_text`).

Anti-loop notes:
- There is still no stage `--pipeline` importer selector; selection remains score-based in registry.
- If webschema comparisons explode runtime, check for accidental non-policy variant expansion first.

### 2026-02-27_23.22.43: Priority 3 shared multi-recipe splitter rollout

Problems captured:
- Importer-local splitter heuristics diverged across text/EPUB/PDF and were difficult to benchmark consistently.
- Early `rules_v1` threshold logic rejected short valid recipe units because coverage used content-like lines only.

Durable decisions:
- Add backend selector `multi_recipe_splitter=legacy|off|rules_v1` with `legacy` default and `off` for strict isolation.
- Reuse shared section detector output for splitter guardrails (`For the X` semantics) rather than creating a second independent heuristic stack.
- Keep all-method splitter dimension explicit/opt-in.
- Use signal-line coverage (content + header signals) for threshold gating in `rules_v1`.

Outcome preserved:
- Shared splitter module is in place and wired across stage/benchmark prediction-generation surfaces.
- Trace output (`multi_recipe_split_trace`) is first-line evidence for accepted/rejected boundaries.

Anti-loop notes:
- If obvious boundaries are rejected, read trace reasons before tuning thresholds globally.
- Keep segmentation-eval ambitions coordinated with benchmark Priority 8 work; do not duplicate evaluator surfaces in ingestion paths.

## 2026-02-28 docs/tasks consolidation batch (deterministic pattern detection + optional hint handoff)

### 2026-02-28_12.19.18 EPUB/PDF deterministic pattern detector and codex-hint boundary

Source task file:
- `docs/tasks/2026-02-28_12.19.18-deterministic-pattern-detector-and-codex-hints.md`

Problem captured:
- Cookbook TOC-like clusters, duplicate title+ramble blocks, and overlap duplicates were still leaking into candidate extraction/scoring paths in ways that caused avoidable false candidates.

Durable decisions/outcomes:
- Added shared deterministic pattern module used by both EPUB and PDF candidate flows.
- Added explicit deterministic actions and diagnostics (`pattern_diagnostics.json` + warning keys) before and after candidate detection.
- Preserved all suppressed text in `non_recipe_blocks` to avoid silent evidence loss.
- Added optional pass1 `pattern_hints` wiring as advisory metadata only, env-gated and default-off.

Evidence preserved:
- `pytest -o addopts='' tests/ingestion/test_epub_importer.py tests/ingestion/test_pdf_importer.py tests/ingestion/test_epub_extraction_quickwins.py tests/core/test_recipe_likeness_scoring.py -q` (`45 passed` recorded)
- `pytest -o addopts='' tests/staging/test_split_merge_status.py tests/llm/test_codex_farm_contracts.py tests/llm/test_codex_farm_orchestrator.py -q` (`20 passed` recorded)
- Gap-closure assertions added later for PDF trim/diagnostics and direct pattern-penalty scoring checks.

Anti-loop note:
- Do not turn pattern suppression into silent deletion; if suppression is active, diagnostics + non-recipe preservation must remain intact.
