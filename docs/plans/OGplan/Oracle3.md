According to a document from 2026-03-01, here’s the code-grounded current-state map and pragmatic PDF-first plan. I based this on the attached repo bundle plus the current bench/ingestion docs and code; the only pieces that are docs-grounded rather than code-inspected in the provided bundle are `scripts/quality_top_tier_tournament.py` and `cookimport/bench/quality_compare.py`. 

## Section A: Current QualitySuite architecture (with concrete file/function references)

1. **Discovery**

   * **Fact:** The suite builder is `cookimport/bench/quality_suite.py:discover_quality_suite`. It scans `**/exports/freeform_span_labels.jsonl` via `_discover_freeform_gold_exports`, matches gold exports to input files with `match_gold_exports_to_inputs(...)`, retries with `_list_input_files(...)` if importer-style matching comes back empty, annotates targets in `_annotate_quality_targets`, and chooses `selected_target_ids` in `_select_quality_target_ids`. `QualityTarget` currently stores `source_file`, `gold_spans_path`, `canonical_text_chars`, `gold_span_rows`, `label_count`, `size_bucket`, and `label_bucket`, but **not** an explicit format field. The current algorithm tag is `quality_representative_v1`.
   * **Fact:** Discovery is curated-first by default. The preferred ids are `saltfatacidheatcutdown`, `thefoodlabcutdown`, and `seaandsmokecutdown`; tests confirm those ids are selected first, and the docs say `bench quality-discover` uses those curated CUTDOWN ids first unless `--no-prefer-curated` is used. In code, curated mode only does representative fill when `max_targets` is set and there is remaining capacity; with `max_targets=None`, `remaining_capacity` becomes `0`, so curated mode stops at the curated ids it found. `strata_counts` are built only from `size_bucket:label_bucket`.
   * **Inference:** This is the core reason the current default suite-discovery behavior is EPUB-centric: the built-in anchors are EPUB cutdowns, and the default uncapped curated path does not add non-curated targets.

2. **Quality run**

   * **Fact:** The runner is `cookimport/bench/quality_runner.py:run_quality_suite`. It loads experiments from schema v1/v2 (`_load_experiment_file`), resolves a base settings payload (`_resolve_base_run_settings_payload`), expands schema-v2 levers (`_expand_experiments`), resolves each experiment to concrete `RunSettings` and all-method runtime (`_resolve_experiments`), writes `suite_resolved.json` and `experiments_resolved.json`, and persists checkpoints/partials plus per-experiment `quality_experiment_result.json` for resume. Docs and code both treat crash-safe resume as a first-class contract.
   * **Fact:** Search strategy is either `exhaustive` or `race`. In docs, `race` is probe -> mid -> finalists; in code, `_run_single_experiment(...)` executes that staged pruning and auto-collapses to exhaustive when pruning is impossible. Tests cover that no-prune fallback. Schema-v2 also supports `levers[]`, optional `baseline`, optional `all_on`, and optional `all_method_runtime_patch`.
   * **Fact:** The runner validates **all** suite targets, not just selected ones. That is explicit in docs and in `validate_quality_suite(...)`.

3. **Where source formats enter the flow**

   * **Fact:** Discovery itself does **not** explicitly bucket by format. The suite model stores `source_file`, and later `cookimport/bench/quality_runner.py:_target_source_extension` derives the suffix from that path. `_select_probe_targets(...)` then groups by extension for the race probe subset. That is the first explicit format-aware step inside QualitySuite code.
   * **Fact:** Per-target execution is handed off in `quality_runner._build_target_variants_for_targets(...)`, which converts each suite target into an `AllMethodTarget` using `source_file` and `gold_spans_path`, then delegates to `cookimport.cli._build_all_method_target_variants(...)`. In practical terms, source format enters the actual benchmark grid there.
   * **Inference:** Format awareness exists today, but **late**: after suite selection, not during initial suite construction.

4. **Lightweight / tournament surfaces**

   * **Fact:** `cookimport/bench/quality_lightweight_series.py:run_quality_lightweight_series` is orchestration over repeated suite discovery + `run_quality_suite(...)`, not a separate scoring engine. `_run_round_fold(...)` writes `suite.json`, writes `experiments_effective.json`, and then calls `run_quality_suite(...)`; `_discover_suite_for_seed(...)` simply re-calls `discover_quality_suite(...)`, with `preferred_target_ids=None` only when thresholds say `prefer_curated=false`.
   * **Fact:** Product docs define three official tracks: `bench quality-lightweight-series`, `scripts/quality_top_tier_tournament.py` Phase A/B/B+, and final `bench quality-run` + `bench quality-compare`.
   * **Inference:** PDF expansion should reuse this stack by improving target discovery, experiment presets, and reporting, not by adding a second benchmark/scoring path.

5. **Leaderboard / compare**

   * **Fact:** `cookimport/bench/quality_leaderboard.py:build_quality_leaderboard` aggregates one experiment’s all-method results across source groups and, by default, sets `ignore_dimension_keys={"source_extension"}`. So the global config identity intentionally ignores source extension unless the caller overrides that.
   * **Fact:** The compare surface is explicitly documented: `comparison.json` / `comparison.md`, baseline/candidate experiment ids, run-settings parity, strict/practical/source-success deltas, thresholds, and FAIL reasons. The docs also say `quality-compare` gates on strict F1 drop, practical F1 drop, source success-rate drop, and run-settings hash parity. The actual `cookimport/bench/quality_compare.py` file was not in the provided bundle, so this part is docs-grounded rather than code-inspected.

6. **Current operator surface**

   * **Fact:** The current product docs’ “quality-first parsing” recommendation is entirely EPUB-oriented (`epub_extractor=unstructured`, `epub_unstructured_html_parser_version=v1`, `semantic_v1`, `skip_headers_footers=true`) on a 3-target run.
   * **Inference:** The user’s assumption that the baseline quality workflow is strongly EPUB-centric matches the current code/docs.

---

## Section B: Current PDF processing architecture (with concrete file/function references)

1. **Import path**

   * **Fact:** PDF stage entry is `cookimport/cli.py:stage` -> `_plan_jobs(...)` -> `stage_pdf_job(...)` / `PdfImporter.convert(...)` -> `_merge_split_jobs(...)` for split runs. Docs say PDF split happens only when the suffix is `.pdf`, `pdf_split_workers > 1`, `pdf_pages_per_job > 0`, and `inspect(...)` returned a page count; ranges come from `plan_pdf_page_ranges(...)`. On merge, the main process sorts by page range, concatenates results, reassigns ids with `reassign_recipe_ids(...)`, and rebuilds merged `raw/.../full_text.json`.

2. **Inspection / OCR decision**

   * **Fact:** `cookimport/plugins/pdf.py:PdfImporter.inspect` samples early pages and classifies the workbook as `text-pdf`, `image-pdf`, or `mixed-pdf`. When OCR is needed and available, it sets `parsing_overrides.name` to `ocr_engine:doctr`; otherwise it emits warnings about OCR not being available. `PdfImporter.convert(...)` honors `start_page` and `end_page` (end exclusive), re-checks `_needs_ocr(...)`, and then either runs `_extract_blocks_via_ocr(...)` or standard page text extraction via `_extract_blocks_from_page(...)`.

3. **Block extraction and ordering**

   * **Fact:** Docs describe PDF extraction as PyMuPDF text extraction with layout features and column reconstruction, with OCR fallback via docTR when needed. Column boundaries are inferred by x-gap threshold `page_width * 0.12`; full-width blocks are forced into column 0; and ordering is `(page_num, column_id, y0, x0)`.
   * **Inference:** This is deterministic enough for benchmarking, but still a structural quality risk because wrong reading order changes candidate spans.

4. **Candidate detection / splitting / scoring**

   * **Fact:** Inside `PdfImporter.convert(...)`, the sequence is:

     1. emit `full_text` raw artifact,
     2. run `detect_deterministic_patterns(...)`,
     3. mark `exclude_from_candidate_detection`,
     4. run `_detect_candidates(...)`,
     5. optionally rewrite spans with `_apply_multi_recipe_splitter(...)`,
     6. apply `apply_candidate_start_trims(...)`,
     7. extract fields with `_extract_fields(...)`,
     8. score each candidate with deterministic recipe-likeness (`score_recipe_likeness`, `recipe_gate_action`),
     9. preserve rejected spans as `non_recipe_blocks`,
     10. emit `pattern_diagnostics` and optional `multi_recipe_split_trace`.
   * **Fact:** `_detect_candidates(...)` is deterministic and heuristic. It walks the block stream, skips blocks flagged `exclude_from_candidate_detection`, looks for `_is_recipe_anchor(...)`, backtracks for a title, ends with `_find_recipe_end(...)`, and currently assigns a fixed segmentation score of `6.0`. `_find_recipe_end(...)` stops on excluded blocks, column changes that do not look like continuation, level-1 section headers, or the next title-like ingredient run.
   * **Fact:** Multi-recipe splitting is post-candidate. `_resolve_multi_recipe_splitter_backend(...)` accepts `legacy|off|rules_v1`; `_build_multi_recipe_split_config(...)` uses `multi_recipe_min_ingredient_lines`, `multi_recipe_min_instruction_lines`, `multi_recipe_for_the_guardrail`, and `multi_recipe_trace`; `_apply_multi_recipe_splitter(...)` rewrites spans and annotates child provenance with `split_parent`, `split_index`, `split_count`, and `split_reason`. Tests cover this for PDF and assert `multi_recipe_split_trace` is emitted.

5. **Section behavior**

   * **Fact:** `PdfImporter._extract_fields(...)` switches to `_extract_fields_shared_v1(...)` when `section_detector_backend=="shared_v1"`. The shared path uses `detect_sections_from_blocks(...)` and preserves named component headers (`header_span.key != "main"`) as ingredient/instruction/notes content instead of dropping them. The legacy path is a simpler header/run heuristic.

6. **Artifacts and provenance**

   * **Fact:** PDF candidate provenance includes at least `start_block`, `end_block`, `start_page`, `end_page`, `chunk_index`, `segmentation_score`, `pattern_detector_version`, pattern flags/actions, and `provenance.multi_recipe` when the shared splitter split a parent span. OCR adds OCR engine/confidence metadata. Raw artifacts include `full_text`, per-candidate block dumps, `pattern_diagnostics.json`, and optional `multi_recipe_split_trace`; the stage layer also writes `.bench/<workbook_slug>/stage_block_predictions.json`.

7. **Run-setting knobs that already affect PDF deterministically**

   * **Fact:** `cookimport/config/run_settings.py` includes PDF/OCR knobs (`pdf_split_workers`, `pdf_pages_per_job`, `ocr_device`, `ocr_batch_size`) plus parser/eval knobs that matter for PDF (`section_detector_backend`, `multi_recipe_splitter`, `multi_recipe_trace`, `multi_recipe_min_ingredient_lines`, `instruction_step_segmentation_policy`, `benchmark_sequence_matcher`, `recipe_score_*`, etc.). `cookimport/config/run_settings_adapters.py:build_benchmark_call_kwargs_from_run_settings` forwards those knobs into benchmark prediction calls, including section detector, instruction segmentation, multi-recipe settings, OCR settings, and PDF split settings.

---

## Section C: Gaps/risks for PDF in QualitySuite

1. **Default suite selection can exclude PDF entirely**

   * **Fact:** Curated discovery anchors are three EPUB cutdowns, and curated mode with `max_targets=None` does not do representative fill. Docs explicitly point users to `--no-prefer-curated` to include all matched sources by default when `--max-targets` is omitted.
   * **Inference:** Even if PDF gold exists and matches inputs, the default suite may still be 100% EPUB.

2. **Representative downsampling is not format-aware**

   * **Fact:** `QualityTarget` has no `source_extension`, `strata_counts` are built only from `size_bucket:label_bucket`, and representative fill is seeded over those strata only.
   * **Inference:** In any capped mixed-format suite, PDF can still be sampled away silently.

3. **Format awareness appears too late**

   * **Fact:** `_select_probe_targets(...)` is the first built-in format-aware selection logic, and it only affects race probe rounds after suite selection.
   * **Inference:** If discovery picked no PDFs, probe-stage extension balancing is irrelevant.

4. **Reporting is weak on per-format visibility**

   * **Fact:** Quality-run summary artifacts are documented as per-experiment strict/practical/source-coverage plus run-settings parity data; they do not mention per-format coverage. Leaderboard grouping ignores `source_extension` by default.
   * **Inference:** A config can look globally strong while still being effectively untested or weak on PDF.

5. **Current operator guidance is EPUB-only**

   * **Fact:** The current “quality-first parsing” recommendation in the product doc is entirely about EPUB parsing knobs on a 3-target run.
   * **Inference:** The repo has productized EPUB quality tuning, but not yet productized PDF quality tuning.

6. **There is no PDF-first lever/preset pack yet**

   * **Fact:** Schema-v2 levers are generic, and the documented deterministic sweeps are section/splitter/instruction/P6/webschema related; no PDF-specific experiment pack is named in the current product docs.
   * **Inference:** PDF experiments are technically possible now, but operationally awkward.

7. **Test coverage is still EPUB-heavy**

   * **Fact:** Discovery tests use only `.epub` fixtures, and the runner’s multi-target helper suite is EPUB-only.
   * **Inference:** A regression that starves PDF from QualitySuite could slip through without tripping existing tests.

8. **Importer-side PDF uncertainty still exists**

   * **Fact:** PDF ordering is heuristic and OCR depends on environment/tool availability.
   * **Inference:** Early PDF QualitySuite work should focus on suite coverage and observability first, then on interpreting config deltas.

---

## Section D: Incremental plan (phased, pragmatic)

### Phase 1: Make suite discovery and outputs format-aware, with no scorer changes

* **Do now**

  * Add an optional `source_extension` field to `QualityTarget`.
  * Add `format_counts` and `selected_format_counts` to suite metadata.
  * Make representative selection stratify by `(source_extension, size_bucket, label_bucket)` instead of only `(size_bucket, label_bucket)`.
* **Why**

  * This is deterministic.
  * It preserves existing scorer/importer behavior.
  * It immediately makes mixed-format suites less likely to silently drop PDF.
* **Compatibility**

  * Keep curated, uncapped default behavior unchanged in this phase to minimize EPUB regression risk.
  * Make `source_extension` optional so old suite manifests still load.

### Phase 2: Add an explicit mixed-format discovery mode for product surfaces

* **Do next**

  * Add a discovery option that keeps curated EPUB anchors **and** guarantees minimum non-EPUB coverage when matched targets exist.
  * Best low-risk shape: an explicit discovery/thresholds knob, not a silent default flip.
* **Why**

  * `quality-lightweight-series` and tournament folds already re-call `discover_quality_suite(...)`, so once discovery supports “curated anchor + format fill,” those products inherit it automatically.
* **Determinism**

  * Keep the fill rule seeded and stable.
  * Do not add any AI/LLM parsing or cleanup.

### Phase 3: Create a PDF-focused experiment pack using existing deterministic knobs

* **Use already-wired levers**

  * `section_detector_backend`
  * `multi_recipe_splitter`
  * `instruction_step_segmentation_policy`
  * `ingredient_missing_unit_policy`
  * optionally `recipe_score_*` thresholds if there is a clear PDF gating issue
* **Do not use as quality levers**

  * `pdf_pages_per_job`
  * `pdf_split_workers`
  * other throughput-only knobs
* **Rationale**

  * Those are speed/runtime knobs; they belong in SpeedSuite or operational smoke runs, not in quality winner selection.

### Phase 4: Add per-format reporting slices

* **Update**

  * `suite_resolved.json`
  * `summary.json`
  * `report.md`
  * optionally `leaderboard.json`
* **Surface**

  * selected targets by extension
  * source-success by extension
  * mean strict/practical F1 by extension
  * winner coverage by extension
* **Keep current architecture**

  * Do not replace the global leaderboard.
  * Add format slices beside it.

### Phase 5: Roll out with low regression risk

1. Land Phase 1 metadata + tests.
2. Run a small mixed-format `quality-discover --no-prefer-curated --max-targets ...` smoke.
3. Run one exhaustive mixed-format `quality-run` before enabling race.
4. Add PDF-focused experiment presets.
5. Only after a few mixed-format runs, decide whether the product default should shift from EPUB-curated to curated-anchor-plus-format-fill.

---

## Section E: Minimal first patch to implement now

### Recommended immediate patch: **2 files**

1. `cookimport/bench/quality_suite.py`
2. `tests/bench/test_quality_suite_discovery.py`

### What to change in `cookimport/bench/quality_suite.py`

* Add `source_extension: str | None = None` to `QualityTarget` so older suite JSON still loads.
* Populate it in `_annotate_quality_targets(...)` from `Path(source_file).suffix.lower()`.
* Add `format_counts` and `selected_format_counts` into `suite.selection`.
* Change `_select_representative_target_ids(...)` so representative mode is extension-aware:

  * first-pass diversity over extension-aware strata,
  * then current seeded round-robin behavior.
* Bump `_QUALITY_SELECTION_ALGORITHM_VERSION` to something like `quality_representative_v2` **only if** selection semantics change.

### What to add in `tests/bench/test_quality_suite_discovery.py`

* A mixed EPUB+PDF fixture where:

  * both formats match gold,
  * `max_targets` forces representative selection,
  * the selected ids are deterministic,
  * at least one PDF survives selection,
  * `format_counts` / `selected_format_counts` are emitted.
* A round-trip test proving `source_extension` is optional/backward-compatible for old manifests.

### Why this is the right first patch

* It creates **real** PDF-readiness progress immediately.
* It does **not** change importer/scorer behavior.
* It preserves current EPUB strength.
* It improves every downstream product that depends on suite discovery.
* It is small enough to review safely.

### Next file after that

* `cookimport/bench/quality_runner.py` to echo `selected_format_counts` into `summary.json` and `report.md`.

---

## Section F: Suggested test/benchmark command matrix (EPUB + PDF)

### 1) Current EPUB-baseline smoke

Use the existing curated-default flow to preserve today’s baseline.

```bash
cookimport bench quality-discover \
  --gold-root data/golden/pulled-from-labelstudio \
  --input-root data/input
```

```bash
cookimport bench quality-run \
  --suite <quality_suite.json> \
  --experiments-file <epub_baseline_experiments.json> \
  --search-strategy race
```

This is the current default operator path, and it is still valuable as the EPUB regression anchor.

### 2) Mixed-format discovery smoke

Force a non-curated pool so PDFs can enter the suite today.

```bash
cookimport bench quality-discover \
  --gold-root data/golden/pulled-from-labelstudio \
  --input-root data/input \
  --no-prefer-curated \
  --max-targets 8
```

This is the safest current command for “show me EPUB + PDF together” before any discovery-default change. Docs explicitly call out `--no-prefer-curated` for including all matched sources by default when `--max-targets` is omitted.

### 3) Mixed-format correctness run (exhaustive first)

Run one exhaustive pass before race, so the first PDF signal is easy to interpret.

```bash
cookimport bench quality-run \
  --suite <mixed_quality_suite.json> \
  --experiments-file <pdf_focus_experiments.json> \
  --search-strategy exhaustive \
  --max-parallel-experiments 2
```

Use this for the first PDF-oriented runs because it removes race-pruning as a confounder. Docs support both `exhaustive` and `race`.

### 4) Mixed-format race run

After the exhaustive smoke looks sane, use race to keep runtime practical.

```bash
cookimport bench quality-run \
  --suite <mixed_quality_suite.json> \
  --experiments-file <pdf_focus_experiments.json> \
  --search-strategy race \
  --race-probe-targets 3 \
  --race-mid-targets 6 \
  --race-keep-ratio 0.5 \
  --race-finalists 16
```

The race probe is already extension-aware in code, so this becomes much more useful once discovery is format-aware too. `[Inference]`

### 5) Leaderboard on the mixed-format run

```bash
cookimport bench quality-leaderboard \
  --run-dir <quality_run_dir> \
  --experiment-id baseline
```

Today this gives you the global config ranking. After the reporting patch, it should also show per-format coverage/breakdown. The current code ignores `source_extension` in the default config-grouping key, so read results as global-first unless you add per-format slices.

### 6) Baseline/candidate regression gate

```bash
cookimport bench quality-compare \
  --baseline <baseline_run_dir> \
  --candidate <candidate_run_dir> \
  --baseline-experiment-id baseline \
  --candidate-experiment-id candidate \
  --fail-on-regression
```

Docs say this gates on strict F1, practical F1, source success-rate, and run-settings parity. Use it after every PDF-focused candidate change so EPUB stays protected.

### 7) Lightweight-series mixed-format directional pass

Once discovery can reliably produce mixed-format suites, use the existing lightweight-series surface rather than inventing a new PDF benchmark product.

```bash
cookimport bench quality-lightweight-series \
  --gold-root data/golden/pulled-from-labelstudio \
  --input-root data/input \
  --profile-file <mixed_format_lightweight_profile.json> \
  --experiments-file <pdf_focus_experiments.json> \
  --thresholds-file <mixed_format_thresholds.json>
```

That command path already discovers per-seed suites and delegates each fold to `run_quality_suite(...)`.

---

The shortest takeaway is:

* **PDF import/parsing already has meaningful deterministic machinery.**
* **QualitySuite’s main PDF weakness is suite selection + reporting, not missing scorer plumbing.**
* **The best first patch is in `quality_suite.py`, not in the importer.**
