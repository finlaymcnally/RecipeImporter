Below is a code-grounded map based on the uploaded repo bundle. I’m treating **code and tests as strongest evidence**, and **docs as current contract** where the corresponding code file was not present in the bundle. I label **Fact** vs **Inference** explicitly. 

## Section A: Current QualitySuite architecture

### A1) Discovery: `bench quality-discover` → suite manifest

**Fact.** The active product contract says `bench quality-discover` builds a deterministic quality suite from pulled gold exports, with **curated CUTDOWN IDs first** (`saltfatacidheatcutdown`, `thefoodlabcutdown`, `seaandsmokecutdown`) and representative fallback. `--no-prefer-curated` disables that preference.

**Fact.** The code entrypoint is `cookimport/bench/quality_suite.py:discover_quality_suite(...)`. It:

1. finds freeform gold exports,
2. matches them to inputs via `match_gold_exports_to_inputs(...)`,
3. annotates matched targets,
4. selects `selected_target_ids`,
5. writes a `QualitySuite` manifest with `targets`, `selected_target_ids`, `selection`, and `unmatched`.

**Fact.** `QualityTarget` currently stores:

* `target_id`
* `source_file`
* `gold_spans_path`
* `source_hint`
* `canonical_text_chars`
* `gold_span_rows`
* `label_count`
* `size_bucket`
* `label_bucket`

**Fact.** Discovery annotation is driven by **canonical text size** and **gold label density**, not by format/layout metadata. The suite manifest validates file existence for **every** target row in `targets[]`, not just the selected rows.

**Fact.** Tests lock in:

* deterministic representative selection,
* curated CUTDOWN preference,
* curated fill behavior when `max_targets` exceeds curated count,
* fallback to raw input filenames when importable scan is empty.

**Inference.** Today’s suite discovery is structurally **EPUB-centric by default**, because the built-in curated IDs and their test fixtures are all EPUB-based, and the target descriptor model has no explicit format/layout fields.

---

### A2) Execution: `bench quality-run` → experiments → all-method benchmark

**Fact.** The active contract says `bench quality-run`:

* runs all-method quality experiments for one discovered suite,
* defaults to `--search-strategy race`,
* supports `exhaustive`,
* persists checkpoints/partials,
* supports `--resume-run-dir`,
* can run experiments in parallel,
* writes `suite_resolved.json`, `experiments_resolved.json`, `summary.json`, `report.md`, and per-experiment roots under `experiments/<experiment_id>/...`.

**Fact.** The main implementation is `cookimport/bench/quality_runner.py:run_quality_suite(...)`. It:

* resolves selected targets from the suite,
* loads experiment files (schema v1/v2),
* expands schema-v2 levers,
* merges each experiment’s `run_settings_patch`,
* writes resolved suite/experiment manifests,
* dispatches experiments serially or in parallel,
* checkpoints continuously,
* writes final summary/report. This is visible in the uploaded code snippet and reinforced by docs/tests around resume/checkpointing and schema-v2 behavior.

**Fact.** Schema v2 supports:

* baseline inclusion,
* one experiment per enabled lever,
* optional `all_on`,
* optional `all_method_runtime_patch`,
* top-level `all_method_runtime`. Unknown runtime keys fail validation.

**Fact.** Quality-run’s actual source entry into benchmarking happens in `quality_runner._build_target_variants_for_targets(...)`, which converts suite targets into `cli.AllMethodTarget(...)` rows and delegates variant expansion to `cli._build_all_method_target_variants(...)`. That is the main place where source formats enter the experiment grid.

**Fact.** All-method benchmark forwarding uses the shared adapter `cookimport/config/run_settings_adapters.py:build_benchmark_call_kwargs_from_run_settings(...)`, which forwards shared deterministic knobs such as:

* `section_detector_backend`
* `multi_recipe_splitter`
* `multi_recipe_min_*`
* `multi_recipe_for_the_guardrail`
* `instruction_step_segmentation_policy`
* `instruction_step_segmenter`
* OCR settings
* recipe scoring knobs
* split knobs including `pdf_split_workers` / `pdf_pages_per_job`.

**Fact.** Race mode in `quality_runner._run_single_experiment(...)` is staged pruning:

* full variant count is computed first,
* if `variants_effective <= race_finalists`, it auto-collapses to exhaustive,
* otherwise it runs probe → optional mid → final on survivors ranked by mean practical F1, mean strict F1, coverage, median duration.

**Fact.** Tests lock in:

* subprocess fallback behavior,
* WSL guard behavior,
* deterministic-sweep forwarding,
* race no-prune collapse,
* resume compatibility checks,
* schema-v2 runtime patch validation.

---

### A3) Lightweight series / tournament / compare / leaderboard

**Fact.** The current product surface is explicitly three-track:

1. `bench quality-lightweight-series`
2. `scripts/quality_top_tier_tournament.py`
3. `bench quality-run` + `bench quality-compare`.

**Fact.** `cookimport/bench/quality_lightweight_series.py` is code-present and reuses `discover_quality_suite(...)` and `run_quality_suite(...)` per fold. Each fold writes:

* `suite.json`
* `experiments_effective.json`
* `fold_summary_extract.json`
* nested `quality_runs/<timestamp>/...` outputs.

**Fact.** Per-seed suite discovery inside lightweight series uses `_discover_suite_for_seed(...)`, which passes `preferred_target_ids=None` when thresholds set `prefer_curated=false`.

**Fact.** `bench quality-leaderboard` is a separate aggregation step. The code in `cookimport/bench/quality_leaderboard.py:build_quality_leaderboard(...)` reads one experiment’s multi-source report and builds a global cross-source config ranking. By default it ignores `source_extension` in its grouping key (`ignore_dimension_keys={"source_extension"}`).

**Fact (docs only).** `bench quality-compare` is the regression gate surface, and tournament is the promotion-confidence surface. The bundle contains their docs/contract, but I did **not** see the actual `quality_compare.py` or tournament script code in the uploaded snippets, so those internals are **doc-verified, not code-inspected**.

---

## Section B: Current PDF processing architecture

### B1) Import path and split/range support

**Fact.** The PDF importer is `cookimport/plugins/pdf.py:PdfImporter`. `detect()` returns high confidence for `.pdf`. `inspect()` opens the PDF with PyMuPDF (`fitz`), counts pages, samples early pages, and classifies layout as:

* `text-pdf`
* `image-pdf`
* `mixed-pdf`

It also warns about OCR usage when needed and available/unavailable.

**Fact.** `convert(...)` supports `start_page` and `end_page` (end exclusive). If the requested slice is empty, it returns an empty `ConversionResult` with a warning.

**Fact.** The ingestion docs describe PDF as a block-first importer with:

* PyMuPDF text extraction,
* OCR fallback via docTR,
* candidate provenance including `start_page` / `end_page`,
* `full_text`, per-candidate dumps, and `pattern_diagnostics` artifacts,
* column ordering driven by x-gap thresholding.

---

### B2) Extraction path

**Fact.** In `PdfImporter.convert(...)`, the extraction phase is:

1. compute file hash,
2. open PDF,
3. decide whether OCR is needed,
4. either:

   * run `_extract_blocks_via_ocr(...)`, or
   * loop pages and call `_extract_blocks_from_page(...)`,
5. emit a `RawArtifact` `locationId="full_text"` containing all blocks plus `ocr_used`.

**Fact.** If OCR is required but unavailable, the importer records a warning that text extraction may be incomplete.

**Fact.** After extraction, the PDF importer runs deterministic pattern detection and marks excluded blocks with `exclude_from_candidate_detection` before candidate segmentation.

---

### B3) Block ordering, candidate splitting/scoring, and field extraction

**Fact.** PDF block ordering is heuristic. `_derive_column_boundaries(...)` computes candidate boundaries from x-coordinate gaps with threshold `page_width * 0.12`. `_order_blocks_by_columns(...)` assigns `column_id`, forces full-width/centered blocks to column 0, and sorts by `(page_num, column_id, y0, x0)`.

**Fact.** Candidate segmentation in `_detect_candidates(...)` is simple:

* iterate ordered blocks,
* skip excluded blocks,
* if `_is_recipe_anchor(...)` fires, backtrack for title,
* find recipe end,
* assign a fixed segmentation score `6.0`.

**Fact.** After `_detect_candidates(...)`, the importer applies:

* `_apply_multi_recipe_splitter(...)`
* `apply_candidate_start_trims(...)`
* overlap duplicate resolution / rejection downstream
  before final accepted candidates are fixed.

**Fact.** Shared multi-recipe splitting is wired for PDF:

* `_resolve_multi_recipe_splitter_backend(...)`
* `_build_multi_recipe_split_config(...)`
* `_apply_multi_recipe_splitter(...)`

`rules_v1` can split a parent candidate into multiple spans, attach `provenance["multi_recipe"]`, and emit `multi_recipe_split_trace`.

**Fact.** Candidate provenance for PDF records:

* `start_block`
* `end_block`
* `start_page`
* `end_page`
* `chunk_index`
* `segmentation_score`
* `pattern_detector_version`
  and may include pattern flags/actions and `multi_recipe` metadata. OCR confidence is also aggregated per candidate when present.

**Fact.** Field extraction is deterministic. `PdfImporter._extract_fields(...)` uses:

* shared section detector path when `section_detector_backend == "shared_v1"`,
* otherwise legacy heuristics to separate title / description / ingredients / instructions / yield from block features and text patterns.

**Fact.** Tests confirm:

* basic PDF conversion works,
* `rules_v1` multi-recipe postprocessing can split one PDF candidate into two and emit trace artifacts,
* `shared_v1` preserves “For the filling” component headers in PDF ingredient/instruction sections.

---

### B4) Candidate scoring, non-recipe preservation, and artifacts

**Fact.** Like EPUB, PDF conversion applies deterministic recipe-likeness scoring and gate actions (`keep_full`, `keep_partial`, `reject`) using the shared scoring utilities; rejected candidate text is preserved in `non_recipe_blocks`, not dropped silently.

**Fact.** The importer writes/produces:

* `full_text` raw artifact
* optional `multi_recipe_split_trace`
* `pattern_diagnostics`
* recipe scoring debug rows
* final `non_recipe_blocks`
* report totals / warnings / topic coverage metrics.

**Fact.** The ingestion docs explicitly say the same deterministic pattern detector/action flow used by EPUB is applied to PDF, and that `pattern_diagnostics.json` is a required debug artifact surface.

---

### B5) Run-setting knobs that matter to PDF today

**Fact.** Shared run settings relevant to PDF include:

* `pdf_split_workers`
* `pdf_pages_per_job`
* `ocr_device`
* `ocr_batch_size`
* `section_detector_backend`
* `multi_recipe_splitter`
* `multi_recipe_trace`
* `multi_recipe_min_ingredient_lines`
* `multi_recipe_min_instruction_lines`
* `multi_recipe_for_the_guardrail`
* `instruction_step_segmentation_policy`
* `instruction_step_segmenter`
* recipe scoring thresholds / backend.

**Fact.** Those knobs are forwarded both into stage-time ingestion and benchmark-time prediction through the shared adapters, which is important for parity between interactive benchmarking and QualitySuite flows.

---

## Section C: Gaps/risks for PDF in QualitySuite

### C1) Discovery currently under-represents PDF

**Fact.** The default curated targets are the three CUTDOWN IDs named above, and the discovery tests exercise EPUB-only source files for curated and representative cases.

**Fact.** `QualityTarget` has no explicit `source_extension`, `page_count`, `layout`, or OCR-related descriptor field; representative selection is driven by `size_bucket` and `label_bucket` only.

**Inference.** This means PDF presence in a discovered suite is currently **incidental**, unless you manually disable curated preference and happen to select PDFs through the current representative sampler.

---

### C2) Format only enters strongly after suite selection

**Fact.** Source files enter experiment generation through `_build_target_variants_for_targets(...)` once the suite is already selected.

**Fact.** Race probe/mid target selection has a small amount of suffix awareness, but that happens after suite selection, not during suite construction.

**Inference.** If the suite is already EPUB-only, quality-run/race cannot “recover” missing PDF coverage.

---

### C3) Experiment surface is much richer for EPUB than for PDF

**Fact.** The current docs and code show explicit experimentable format families for EPUB (`epub_extractor`, unstructured parser/preprocess variants) and webschema policy variants, while PDF behavior is benchmarked mostly through **shared** knobs plus split/OCR settings, not through a dedicated PDF variant family.

**Inference.** QualitySuite can evaluate PDF today, but it does not yet have an equally expressive, format-specific lever surface for PDF/non-EPUB tuning.

---

### C4) Reporting hides format distinctions in the main leaderboard

**Fact.** `build_quality_leaderboard(...)` ignores `source_extension` by default when aggregating configurations globally.

**Inference.** That is useful for one global winner, but it makes it harder to answer “what wins on PDF specifically?” from the first-line leaderboard artifacts.

---

### C5) PDF’s biggest failure modes are structural, but QualitySuite’s main surface is still F1-centric

**Fact.** Priority-8 segmentation controls are on `bench eval-stage`, not on all-method/quality-run flows.

**Fact.** PDF ordering and candidate detection are heuristic:

* column boundaries are x-gap based,
* candidate detection is anchor-based with fixed score `6.0`.

**Inference.** For PDF, many quality differences are likely to show up first as **boundary/order/split** issues rather than parser-family choice. Current QualitySuite can still score outcomes, but it under-surfaces those PDF-specific structural diagnostics in the main product loop.

---

### C6) Mixed-format suites are operationally brittle to stale rows

**Fact.** `validate_quality_suite()` checks every `targets[]` row for existing source/gold files, not just selected rows.

**Inference.** As you start hand-editing or generating mixed-format suites for PDF-first work, stale rows become a more common footgun.

---

## Section D: Incremental plan (phased, pragmatic)

### Phase 1: Make discovery format-aware without changing scoring

**Goal:** get PDFs into the suite reliably while preserving current EPUB defaults.

1. **Add format metadata to suite targets**

   * Extend `cookimport/bench/quality_suite.py:QualityTarget` with `source_extension`.
   * Populate it in `_annotate_quality_targets(...)` from `Path(source_file).suffix.lower()`.

2. **Add format counts to suite metadata**

   * Add `format_counts` and `selected_format_counts` into `suite.selection`.

3. **Make representative selection “format-aware first, strata-aware second”**

   * Keep curated default behavior unchanged.
   * In representative mode, guarantee one target per available source extension before the current size/label-strata fill.
   * For curated mode with `max_targets` overflow space, use the same format-aware fill for the remaining capacity.

**Why this is low risk:** it only changes discovery, not scorers, evaluators, or importer logic.

---

### Phase 2: Split experiment packs into “shared deterministic” vs “EPUB-specific”

**Goal:** make PDF-first evaluation useful without inventing a new parser architecture.

1. **Create a PDF-first/shared-knob experiments file**

   * Focus on knobs that already affect PDF deterministically:

     * `section_detector_backend`
     * `multi_recipe_splitter`
     * `instruction_step_segmentation_policy`
     * `instruction_step_segmenter`
     * recipe scoring thresholds if needed
     * maybe OCR/batching only if benchmarked reproducibly

2. **Keep EPUB parser levers in a separate experiments file**

   * `epub_extractor`
   * `epub_unstructured_html_parser_version`
   * `epub_unstructured_preprocess_mode`
   * `epub_unstructured_skip_headers_footers`

3. **Do not default to deterministic sweeps for PDF bring-up**

   * The docs explicitly say sweeps have not shown a proven must-enable default uplift, and race can be pure overhead when finalists exceed variant count.

**Result:** you preserve EPUB strength while giving PDF work a cleaner experimental surface.

---

### Phase 3: Add per-format reporting slices

**Goal:** make QualitySuite answers actionable for PDF.

1. **Quality-run summary/report**

   * include counts by `source_extension`
   * include selected target IDs by format
   * optionally include per-format mean practical/strict F1

2. **Leaderboard**

   * keep current global leaderboard unchanged,
   * add an extra by-format slice:

     * `leaderboard_by_source_extension.json/csv`
     * or an opt-in CLI flag that disables ignoring `source_extension`

This is compatible with today’s architecture because it is reporting-only.

---

### Phase 4: Add richer PDF descriptors only if Phase 1 proves useful

**Goal:** improve suite representativeness further, still deterministically.

Potential additions:

* `page_count`
* `layout` from `PdfImporter.inspect()` (`text-pdf`, `mixed-pdf`, `image-pdf`)
* maybe `ocr_expected` / `needs_ocr`

**Caution:** this requires inspect-time work during suite discovery, so I would not make it the first patch.

---

### Phase 5: Use `eval-stage` selectively for PDF structural debugging

**Goal:** avoid overloading QualitySuite with a redesign.

When a PDF candidate/winner looks odd:

* run the normal QualitySuite flow for ranking,
* then use `bench eval-stage` on representative PDF failures to inspect segmentation/boundary diagnostics.

That keeps the current scorer architecture intact while giving you a deterministic structural debug lane.

---

## Section E: Minimal first patch to implement now

### Recommendation

Implement a **2-file patch**:

1. **`cookimport/bench/quality_suite.py`**
2. **`tests/bench/test_quality_suite_discovery.py`**

### What to change

#### File 1: `cookimport/bench/quality_suite.py`

**Add**

* `source_extension: str` to `QualityTarget`

**Populate**

* in `_annotate_quality_targets(...)`

**Add selection metadata**

* `format_counts`
* `selected_format_counts`

**Change representative selection**

* In `_select_representative_target_ids(...)`, first select one target per source extension (deterministically; hardest target per extension is a sensible rule), then continue with the existing strata round-robin.

**Do not change**

* curated default behavior when `max_targets` is omitted and curated IDs are present.

### Why this is the best first patch

**Fact-based justification:**

* the suite model currently lacks format metadata,
* curated defaults are EPUB CUTDOWN-centric,
* the runner only sees whatever discovery selected.

**Inference:** discovery is the narrowest, safest choke point for making PDF QualitySuite-ready.

---

#### File 2: `tests/bench/test_quality_suite_discovery.py`

Add:

1. a mixed-format representative selection test (`.epub`, `.pdf`, `.docx`) that proves deterministic inclusion of at least one PDF when `preferred_target_ids=None`.
2. a curated-fill test showing that when curated targets occupy only part of `max_targets`, the fill step can deterministically include a non-EPUB format.

This matches the style of the existing discovery tests, which already lock determinism, curated preference, and representative fill behavior.

---

## Section F: Suggested test/benchmark command matrix (EPUB + PDF)

### F1) Unit/integration tests

Run these first:

```bash
pytest tests/bench/test_quality_suite_discovery.py
pytest tests/bench/test_quality_suite_runner.py
pytest tests/ingestion/test_pdf_importer.py
```

These cover:

* suite determinism / curated behavior,
* runner schema/race/resume behavior,
* PDF importer basics and splitter/shared-section behavior.

---

### F2) Current EPUB-strength regression check

```bash
cookimport bench quality-discover \
  --gold-root data/golden/pulled-from-labelstudio \
  --input-root data/input
```

```bash
cookimport bench quality-run \
  --suite <suite.json> \
  --experiments-file <epub_parsing_experiments.json> \
  --search-strategy race
```

```bash
cookimport bench quality-leaderboard \
  --run-dir <run_dir> \
  --experiment-id baseline
```

```bash
cookimport bench quality-compare \
  --baseline <baseline_run> \
  --candidate <candidate_run> \
  --baseline-experiment-id baseline \
  --candidate-experiment-id candidate \
  --fail-on-regression
```

This keeps the current EPUB workflow intact, which the docs still present as the core promotion/regression path.

---

### F3) Immediate mixed-format / PDF probe (before any code change)

```bash
cookimport bench quality-discover \
  --gold-root data/golden/pulled-from-labelstudio \
  --input-root data/input \
  --no-prefer-curated \
  --max-targets 6
```

```bash
cookimport bench quality-run \
  --suite <mixed_suite.json> \
  --experiments-file <shared_pdf_first_experiments.json> \
  --search-strategy exhaustive \
  --max-parallel-experiments 2
```

**Why exhaustive first:** until suite selection is format-aware and PDF lever files are cleaner, exhaustive is easier to reason about than race for early PDF bring-up.

---

### F4) Mixed-format lightweight series probe

Use a thresholds file with `prefer_curated=false` so per-seed discovery does not keep collapsing back to curated EPUBs:

```bash
cookimport bench quality-lightweight-series \
  --gold-root data/golden/pulled-from-labelstudio \
  --input-root data/input \
  --profile-file <lightweight_profile.json> \
  --experiments-file <shared_pdf_first_experiments.json> \
  --thresholds-file <thresholds_with_prefer_curated_false.json>
```

This works because lightweight-series delegates per-seed suite discovery through `_discover_suite_for_seed(...)`, which can disable curated preference.

---

### F5) After the first patch lands

Re-run the mixed-format flow, then switch to race:

```bash
cookimport bench quality-discover \
  --gold-root data/golden/pulled-from-labelstudio \
  --input-root data/input \
  --no-prefer-curated \
  --max-targets 6
```

```bash
cookimport bench quality-run \
  --suite <mixed_suite.json> \
  --experiments-file <shared_pdf_first_experiments.json> \
  --search-strategy race \
  --race-probe-targets 3 \
  --race-mid-targets 6 \
  --race-finalists 16
```

Then inspect:

* `suite_resolved.json`
* `experiments_resolved.json`
* `summary.json`
* leaderboard outputs

for actual PDF presence and per-format signal.

---

If you want, I can turn Section E into an exact patch diff against `cookimport/bench/quality_suite.py` and `tests/bench/test_quality_suite_discovery.py`.
