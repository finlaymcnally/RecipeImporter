## Section A: Current QualitySuite architecture (code-grounded)

### A1) Suite discovery (`bench quality-discover`)

**Facts (from code):**

* **Gold discovery = “freeform span” exports.** `cookimport/bench/quality_suite.py::_discover_freeform_gold_exports()` walks `gold_root/*/exports/freeform_span_labels.jsonl` and returns `{target_id -> path}`. 
* **Input matching happens via SpeedSuite helper.** `discover_quality_suite()` calls `cookimport.bench.speed_suite.match_gold_exports_to_inputs(...)`. 
* **If importable scan is empty, discovery falls back to raw filenames.** When `matches` is empty but `unmatched` exists, discovery lists all files under `input_root` via `_list_input_files()` and retries `match_gold_exports_to_inputs(...)` with `importable_files=<raw list>`. 

  * The behavior is covered by a test that monkeypatches `cookimport.bench.speed_suite._list_importable_files` to return `[]`, forcing the fallback path. 
* **Targets are annotated for “representative” selection using only gold export stats.**

  * `_canonical_text_size()` reads `canonical_text.txt` size (bytes) next to the gold spans file. 
  * `_gold_rows_and_labels()` counts JSONL rows and unique labels in `freeform_span_labels.jsonl`. 
  * `_assign_tercile_buckets()` assigns size + label terciles (`small/medium/large` and `sparse/medium/dense`). 
  * `_annotate_quality_targets()` combines those into each `QualityTarget` (`canonical_text_chars`, `gold_span_rows`, `label_count`, `size_bucket`, `label_bucket`). 
* **Curated-first is hard-coded.** Default curated IDs are:
  `("saltfatacidheatcutdown", "thefoodlabcutdown", "seaandsmokecutdown")`. 
  A determinism test asserts those 3 lead the selected list when present. 
* **Suite manifest + validation.**

  * `write_quality_suite()` writes `suite.model_dump_json(indent=2)`. 
  * `validate_quality_suite()` checks duplicates + file existence by resolving paths with `resolve_repo_path(...)`. 

**How formats enter discovery (facts + inference):**

* **Fact:** Each `QualityTarget` stores an absolute `source_file` path and optional `source_hint` (often the original filename, including extension). 
* **Inference (based on tests + call site):** `match_gold_exports_to_inputs(...)` likely depends on the `source_file` field embedded in the gold JSONL rows (e.g., `"alpha.epub"`) and an “importable file list” from SpeedSuite. Tests patch `_list_importable_files`, implying extension-based discoverability lives there. 

---

### A2) Quality execution (`bench quality-run`)

**Facts (from code + tests):**

* **Runner module:** `cookimport/bench/quality_runner.py::run_quality_suite()` orchestrates the run, writes `summary.json` and `report.md`, and persists checkpoints. 
* **Experiments file schema:** `_load_experiment_file()` supports schema v1/v2 and rejects unsupported versions. 
* **Schema v2 lever expansion exists (documented) and is resolved into `experiments_resolved.json`.** 
* **All-method execution is delegated through CLI helpers.** Unit tests monkeypatch `cookimport.cli._run_all_method_benchmark_multi_source`, and `run_quality_suite(...)` calls it. 
* **Race strategy is a staged pruning system.** Docs describe probe → mid → full suite on finalists. 
* **Race probing is format-aware at the “target selection per round” level.** `_select_probe_targets(...)` groups targets by `Path(target.source_file).suffix.lower()` via `_target_source_extension`. 

**How formats enter quality-run (facts):**

* **Target extension is explicitly used for probe selection** as above. 
* **Leaderboard logic knows about a `source_extension` “dimension key”.** It explicitly ignores `source_extension` when turning dimensions back into a run-settings payload. 
  This is strong evidence that the all-method variant system emits `dimensions["source_extension"]` for each config.

---

### A3) Tournament / lightweight flows

**Lightweight series (facts):**

* `cookimport/bench/quality_lightweight_series.py` runs multiple folds/rounds by repeatedly calling `discover_quality_suite()` and then `run_quality_suite()` per fold. 
* It writes a per-series summary + report: `lightweight_series_summary.json` and `lightweight_series_report.md`. 
* CLI docs describe the three rounds (main-effects screening → composition check → interaction smoke) and resume behavior. 

**Tournament (limited facts, mostly documentation):**

* Product-suite docs reference a “two-phase parser workflow” and tournament handoff flags, but the actual tournament script code (`scripts/quality_top_tier_tournament.py`) isn’t present in the excerpt I can cite directly. 
* So: **I can describe the *documented* flow, but not fully “code-ground” the script internals from this bundle.**

---

### A4) Compare + leaderboard

**Leaderboard (facts from code):**

* `cookimport/bench/quality_leaderboard.py::write_quality_leaderboard_artifacts()` writes:
  `leaderboard.json/.csv`, `pareto_frontier.json/.csv`, `winner_run_settings.json`, `winner_dimensions.json`. 
* Winner settings computation intentionally **ignores** `"deterministic_sweep"` and `"source_extension"` dimension keys. 

**Quality compare (facts from docs; code not in excerpt):**

* Compare gates: `strict_f1_drop_max`, `practical_f1_drop_max`, `source_success_rate_drop_max`, plus run-settings hash parity unless overridden by `--allow-settings-mismatch`. 

---

## Section B: Current PDF processing architecture (code-grounded)

### B1) Importer registration + selection

**Facts:**

* `cookimport/plugins/pdf.py::PdfImporter.detect()` returns `0.95` for `.pdf`. 
* `PdfImporter.inspect()` opens the PDF with `fitz.open`, samples first pages, and labels it `text-pdf`, `image-pdf`, or `mixed-pdf`; it sets a `MappingConfig.parsing_overrides` stub like `ocr_engine:doctr` when it believes OCR is needed. 

### B2) Convert path (high-level pipeline)

**Facts (from `PdfImporter.convert`):**

1. **Hash + open PDF + slice pages.** It computes `file_hash`, opens with `fitz.open`, clamps `start_page/end_page`, and returns early if slice empty. 
2. **OCR decision + block extraction.**

   * It calls `self._needs_ocr(doc)`. 
   * If OCR is needed and available, it calls `_extract_blocks_via_ocr(...)` with `device` + `batch_size`, and sets `ocr_used=True`. 
   * Otherwise it loops pages and uses `_extract_blocks_from_page(page, abs_page)`; if OCR was needed but unavailable, it adds a warning. 
3. **Extracted blocks artifact.** It writes a RawArtifact `locationId="full_text"` (JSON) that includes all blocks, block count, and `ocr_used`. 
4. **Deterministic pattern detection + feature injection.**

   * Runs `detect_deterministic_patterns(all_blocks)`; applies flags to blocks; sets `exclude_from_candidate_detection` for excluded indices. 
5. **Candidate segmentation + post-processing.**

   * `candidates_ranges = self._detect_candidates(all_blocks)` 
   * Applies multi-recipe splitter `_apply_multi_recipe_splitter(...)` (can emit `multi_recipe_split_trace` artifact). 
   * Applies `apply_candidate_start_trims(...)` and overlap resolution. 
6. **Field extraction + scoring loop.**

   * For each `(start,end,score)`, it builds a `RecipeCandidate` via `_extract_fields(candidate_blocks)`, adds provenance (page range, segmentation score, OCR confidences), and then scores with `score_recipe_likeness(...)` and gates with `recipe_gate_action(...)`. 
   * It writes `recipe_scoring_debug` artifact (JSONL) when present. 
7. **Standalone tips + non-recipe blocks.**

   * Calls `_extract_standalone_tips(...)`, then builds `non_recipe_blocks` from uncovered blocks (including rejected-candidate details). 
8. **Finalize report + return.** Returns `ConversionResult(...)` with recipes, tips, candidates, rawArtifacts, report, workbook info. 

### B3) Candidate splitting/scoring details

**Facts:**

* **Column boundary heuristic is hard-coded:** `_detect_column_boundaries` uses `threshold = page_width * 0.12`. 
* **Candidate detection is a scan for anchors** and produces `(start_idx, end_idx, score)` tuples; it respects `exclude_from_candidate_detection`. 
* **Scoring uses recipe-likeness thresholds + penalties** (short/long/noise + pattern penalties), then assigns tier (gold/silver/bronze/reject) and reasons. 

### B4) Section detection / splitter behavior

**Facts:**

* `PdfImporter` stores `_section_detector_backend` and sets it from `run_settings.section_detector_backend` (default `"legacy"`). 
* In `_extract_fields`, when backend is `"shared_v1"`, it delegates to `_extract_fields_shared_v1(...)`. 
* `_extract_fields_shared_v1` runs `detect_sections_from_blocks(...)`, tries to infer a title, and returns structured fields + per-section text. 
* Multi-recipe splitting backend comes from `run_settings.multi_recipe_splitter` (`legacy|off|rules_v1`), and config consumes `multi_recipe_min_*` and `multi_recipe_trace`. 

### B5) Run-setting knobs that affect PDF

**Facts (RunSettings model):**

* PDF worker slicing: `pdf_split_workers`, `pdf_pages_per_job`. 
* OCR: `ocr_device`, `ocr_batch_size`. 
* Shared levers that the PDF importer actually reads: `section_detector_backend`, `multi_recipe_splitter`, `multi_recipe_trace`, `multi_recipe_min_ingredient_lines`, `multi_recipe_min_instruction_lines`, `multi_recipe_for_the_guardrail`.  

### B6) PDF artifacts (what you get today)

**Facts:**

* Raw artifacts include:

  * `locationId="full_text"` JSON with blocks + `ocr_used`. 
  * `locationId="pattern_diagnostics"` JSON with trim + overlap actions (and warnings are surfaced). 
  * `locationId="multi_recipe_split_trace"` JSON when rules splitter produces trace. 
  * `locationId="recipe_scoring_debug"` JSONL for accepted/rejected candidates. 
* There are already targeted PDF tests for these behaviors (pattern diagnostics + multi-recipe postprocessing). 

---

## Section C: Gaps/risks for PDF in QualitySuite (concrete)

1. **Suite discovery is EPUB-biased by default due to curated IDs.** The curated list is fixed and selected first when present.  

   * Result: mixed-format gold sets will still skew toward those EPUB CUTDOWN targets unless you explicitly disable curated preference.

2. **Representative selection ignores format entirely.** It stratifies only by `canonical_text_chars` and `label_count` buckets. 

   * Risk: with `max_targets` caps, PDFs can easily be under-sampled (or dropped) even if you have PDF gold exports.

3. **QualitySuite manifests don’t carry “format” as first-class metadata.** `QualityTarget` has `source_file` + `source_hint`, but no `source_format` field today. 

   * Consequence: reporting and selection-by-format requires re-deriving from file paths in multiple places.

4. **Some PDF-critical heuristics are hard-coded, reducing what you can experiment with in QualitySuite.**

   * Example: column boundary threshold is `page_width * 0.12` with no `RunSettings` knob. 
   * This makes it hard to benchmark “column reconstruction sensitivity” deterministically via experiment levers.

5. **QualitySuite’s main all-method scoring is canonical-text oriented; stage-block segmentation metrics are not integrated.**

   * Docs explicitly say segmentation controls and richer metrics are only exposed on `bench eval-stage`, while all-method stays canonical-text. 
   * PDFs often fail in block ordering / layout more than label classification; without easy stage-block evaluation inside QualitySuite, you’ll miss regressions/improvements in “layout correctness”.

6. **Cross-format reporting is underpowered.** Leaderboard ignores `source_extension` when reconstructing winner settings, implying extensions exist as dimensions—but there isn’t (yet) a first-class “PDF vs EPUB” breakdown in artifacts. 

---

## Section D: Incremental plan (phased, pragmatic, deterministic)

### Phase 0 — Make format visible + selectable (low-risk, immediate)

* Add `QualityTarget.source_format` (derived from file suffix) and record `selection.format_counts` in suite JSON.
* Update representative selection to be **format-aware only when multiple formats are present** (avoid EPUB-only behavior changes).
* Add a unit test ensuring mixed PDF+EPUB suites don’t silently drop PDFs when capped.

### Phase 1 — PDF-first suite discovery UX (still small)

* Add optional `allowed_formats`/`--formats pdf` to `bench quality-discover`.

  * Implementation: in `discover_quality_suite()`, filter matched targets by inferred `source_format` before `_select_quality_target_ids`.
  * Default stays “no filter” to preserve current behavior.
* Mirror the same option into `bench quality-lightweight-series` (so PDF-first series runs are easy).

### Phase 2 — PDF lever pack (use what already exists, then add 1–2 knobs)

**Use existing knobs first (already deterministic and wired into PDF):**

* `section_detector_backend=legacy|shared_v1` (PDF uses it). 
* `multi_recipe_splitter=legacy|off|rules_v1` + `multi_recipe_min_*` + trace. 

**Then add 1–2 PDF-specific knobs (small, high impact):**

* `pdf_column_gap_ratio` (default `0.12`) to replace the hard-coded constant. 
* `pdf_ocr_policy = auto|force|off` (default auto), to benchmark “OCR always vs never” deterministically.

  * Keep deterministic by only controlling which deterministic path runs (no ML parsing; OCR here is already part of deterministic pipeline choice).

### Phase 3 — Benchmark/reporting surfaces (minimal, value-dense)

* In `bench quality-run` report:

  * add a small section: **suite format counts**, **per-format success rate**, **per-format mean practical F1** (derived from existing all-method multi-source reports and/or dimensions).
* In `bench quality-leaderboard`:

  * output an additional CSV grouped by `source_extension` (or the new `source_format`) so PDF regressions are visible even when overall score is stable.

### Phase 4 — Tests (keep them synthetic + fast)

* Add a suite-discovery test for mixed formats (see “first patch” below).
* Add one leaderboard test for per-format breakdown logic once implemented.
* For PDF knob tests, generate small PDFs in-test (e.g., via `reportlab`) rather than checking in binaries—keeps repo light and deterministic.

### Phase 5 — Rollout sequence (low regression risk)

1. Phase 0 patch (metadata + format-aware selection when mixed).
2. Add `--formats` filter flag (Phase 1).
3. Add “PDF lever file” (schema v2) using existing knobs (Phase 2a).
4. Add `pdf_column_gap_ratio` + `pdf_ocr_policy` (Phase 2b).
5. Add reporting breakdowns (Phase 3).

---

## Section E: Minimal first patch to implement now (1–3 files, real forward progress)

### Goal

Make QualitySuite **format-aware** in discovery *without changing EPUB-only behavior*, and surface PDF coverage explicitly.

### Patch (2 files)

#### 1) `cookimport/bench/quality_suite.py`

* Add field:

  * `source_format: str = "unknown"` to `QualityTarget`. (Back-compat: old suite JSON loads.)
* Add helper:

  * `_infer_source_format(path_str) -> str` based on suffix.
* Populate `source_format` in `_annotate_quality_targets(...)`.
* Add `selection["format_counts"]`.
* Make representative strata include format **only when multiple formats exist**.

Sketch (illustrative diff):

```diff
 class QualityTarget(BaseModel):
     target_id: str
     source_file: str
     gold_spans_path: str
     source_hint: str | None = None
+    source_format: str = "unknown"
     canonical_text_chars: int
     gold_span_rows: int
     label_count: int
     size_bucket: str
     label_bucket: str

+def _infer_source_format(source_file: str) -> str:
+    suffix = Path(str(source_file)).suffix.lower().lstrip(".")
+    if not suffix:
+        return "unknown"
+    if suffix in {"epub", "pdf", "docx"}:
+        return suffix
+    if suffix in {"txt", "md"}:
+        return "text"
+    return suffix

 def _annotate_quality_targets(...):
     ...
     for match in matches:
         ...
         source_file = resolve_repo_path(...)
         ...
         quality_targets.append(
             QualityTarget(
                 target_id=target_id,
                 source_file=str(source_file),
                 gold_spans_path=str(gold_path),
                 source_hint=match.get("source_hint"),
+                source_format=_infer_source_format(str(source_file)),
                 canonical_text_chars=...,
                 ...
             )
         )

+def _format_counts(targets: list[QualityTarget]) -> dict[str, int]:
+    counts: dict[str, int] = {}
+    for t in targets:
+        key = str(getattr(t, "source_format", "unknown") or "unknown")
+        counts[key] = counts.get(key, 0) + 1
+    return counts

 def discover_quality_suite(...):
     ...
     quality_targets = _annotate_quality_targets(...)
+    selection_metadata["format_counts"] = _format_counts(quality_targets)
     selected_target_ids, selection_metadata = _select_quality_target_ids(...)

 def _select_representative_target_ids(...):
-    strata_key = f"{target.size_bucket}:{target.label_bucket}"
+    formats = {t.source_format for t in quality_targets if getattr(t, "source_format", None)}
+    multi_format = len(formats) > 1
+    strata_key = (
+        f"{target.source_format}:{target.size_bucket}:{target.label_bucket}"
+        if multi_format
+        else f"{target.size_bucket}:{target.label_bucket}"
+    )
```

#### 2) `tests/bench/test_quality_suite_discovery.py`

Add a deterministic test ensuring mixed-format selection doesn’t drop PDFs under a cap:

```py
def test_discover_quality_suite_represents_formats_when_mixed(monkeypatch, tmp_path):
    input_root = tmp_path / "input"
    input_root.mkdir()
    (input_root / "a.pdf").write_text("pdf", encoding="utf-8")
    (input_root / "b.epub").write_text("epub", encoding="utf-8")

    gold_root = tmp_path / "gold"
    _write_target(gold_root, target_name="a_target", source_file="a.pdf",
                 labels=["OTHER"], canonical_chars=100)
    _write_target(gold_root, target_name="b_target", source_file="b.epub",
                 labels=["OTHER"], canonical_chars=100)

    monkeypatch.setattr(
        "cookimport.bench.speed_suite._list_importable_files",
        lambda _root: [input_root / "a.pdf", input_root / "b.epub"],
    )

    suite = discover_quality_suite(
        gold_root=gold_root,
        input_root=input_root,
        max_targets=2,
        seed=123,
        preferred_target_ids=None,  # avoid curated EPUB IDs
    )

    assert {t.source_format for t in suite.targets} >= {"pdf", "epub"}
    assert len(suite.selected_target_ids) == 2
    selected_formats = {
        next(t.source_format for t in suite.targets if t.target_id == tid)
        for tid in suite.selected_target_ids
    }
    assert selected_formats == {"pdf", "epub"}
```

**Why this is “real progress” for PDF readiness:**

* You immediately get **visibility** into whether a suite actually contains PDFs (`format_counts`).
* You stop “accidental PDF starvation” when `max_targets` is small (format-aware strata when mixed), without impacting EPUB-only selection.

---

## Section F: Suggested test/benchmark command matrix (EPUB + PDF)

### Unit tests (fast)

* QualitySuite selection + new mixed-format behavior:

  * `pytest -q tests/bench/test_quality_suite_discovery.py`
* PDF importer regression tests already exist (pattern + multi-recipe):

  * `pytest -q tests/plugins/test_pdf_importer.py` *(path inferred; the bundle shows PDF tests but not the exact filename header—search for `test_convert_pdf_...` if your tree differs)* 

### Bench commands (current surfaces, deterministic)

From the docs, these are the intended surfaces: 

**EPUB-centric baseline (current workflow)**

* Discover:

  * `cookimport bench quality-discover --gold-root <gold_root> --input-root <input_root> --max-targets 5`
* Run (race default):

  * `cookimport bench quality-run --suite <suite.json> --experiments <experiments.json> --search-strategy race`
* Leaderboard:

  * `cookimport bench quality-leaderboard --run-dir <quality_run_dir> --experiment-id baseline`
* Compare (gated):

  * `cookimport bench quality-compare --baseline <runA> --candidate <runB>`

**PDF-first workflow *today* (before new `--formats` exists)**

* Use `--no-prefer-curated` so EPUB CUTDOWN IDs don’t dominate when present. 

  * `cookimport bench quality-discover --no-prefer-curated --gold-root <gold_root> --input-root <pdf_input_root> --max-targets 10`
* Run with PDF-relevant levers already supported by all-method controls (shared with benchmark): 

  * `cookimport bench quality-run --suite <suite.json> --experiments <pdf_experiments.json> --search-strategy race`
  * Where `<pdf_experiments.json>` sweeps:

    * `section_detector_backend: legacy vs shared_v1`
    * `multi_recipe_splitter: legacy vs rules_v1`
    * `multi_recipe_trace: true` (for debugging)

**Targeted stage-block evaluation (PDF layout debugging)**

* When you need to validate segmentation/layout rather than canonical-text metrics:

  * `cookimport bench eval-stage --gold-spans <.../exports/freeform_span_labels.jsonl> --stage-run <...> --eval-mode stage-blocks` 

---

If you want, I can also draft a **PDF-focused schema-v2 lever file** (just JSON) that uses only existing deterministic knobs (`section_detector_backend`, `multi_recipe_*`) so you can start running PDF comparisons immediately—no new code required.
