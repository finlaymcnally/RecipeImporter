# Label Studio Integration & Benchmarking

**Location:** `cookimport/labelstudio/`

Label Studio is used to create ground-truth (golden) datasets for validating extraction and parsing accuracy. It supports three distinct evaluation workflows (Pipeline, Canonical, and Freeform) to balance fast regression testing with stable, long-term truth.

---

## Three Golden Set Types

| Type | Purpose | How it works | Stable Across Chunker Changes? |
| :--- | :--- | :--- | :--- |
| **Pipeline** | Fast regression on current chunking logic. | Labels the chunks the pipeline *proposes* (structural recipe candidates and atomic lines). | **No** (if chunker moves boundaries, old labels may not map). |
| **Canonical** | Measure recall (missed recipes) and stable truth. | Labels every extracted block (paragraph-ish unit) as Recipe/Tip/Narrative/etc. | **Yes** (keyed by stable block IDs). |
| **Freeform** | High-precision span highlighting. | Annotator highlights arbitrary text spans (any substring) and labels them (Recipe Title, Ingredient, etc.). | **Yes** (keyed by character offsets/block ranges). |

---

## Core Workflows

### 1. Import (Task Generation)
Imports cookbook content into a Label Studio project.

```bash
# Standard Pipeline Import
cookimport labelstudio-import path/to/cookbook.epub --chunk-level both --allow-labelstudio-write

# Canonical Block Import (Recall focused)
cookimport labelstudio-import path/to/cookbook.epub --task-scope canonical-blocks --context-window 1 --allow-labelstudio-write

# Freeform Span Import (Highlighting focused)
cookimport labelstudio-import path/to/cookbook.epub --task-scope freeform-spans --segment-blocks 40 --segment-overlap 5 --allow-labelstudio-write
```

**Key Import Flags:**
- `--allow-labelstudio-write`: Safety gate for network pushes.
- `--overwrite`: Deletes existing project and starts fresh.
- `--resume`: Skips already-uploaded tasks (based on `manifest.json` and `label_studio_tasks.jsonl`).
- `--workers` / `--pdf-split-workers` / etc.: Parallel processing for large PDF/EPUBs.

### 2. Export (Golden Set Creation)
Pulls annotations from Label Studio and converts them into JSONL golden sets.

```bash
cookimport labelstudio-export --project-name "My Project" --export-scope [pipeline|canonical-blocks|freeform-spans] --output-dir data/golden/
```

**Outputs:**
- `pipeline`: `labelstudio_export.json` + `golden_set_tip_eval.jsonl`.
- `canonical-blocks`: `canonical_block_labels.jsonl` + `canonical_gold_spans.jsonl` (derived recipe ranges).
- `freeform-spans`: `freeform_span_labels.jsonl` + `freeform_segment_manifest.jsonl`.

### 3. Benchmark & Evaluation
Runs a pipeline prediction and compares it to a golden set.

```bash
# Guided Benchmark (interactive discovery of gold and source)
cookimport labelstudio-benchmark --allow-labelstudio-write

# Manual Evaluation
cookimport labelstudio-eval freeform-spans 
  --pred-run data/output/<timestamp>/labelstudio/<slug>/ 
  --gold-spans data/golden/<slug>/exports/freeform_span_labels.jsonl
```

---

## "The Insane Spaghetti": Lessons Learned & History

The current system is the result of multiple revisions to handle parallel processing, coordinate stability, and UI feedback.

### 1. Split-Job Block Reindexing
**Problem:** When processing large PDFs or EPUBs in parallel (split jobs), each job starts its block indices at `0`.
**Solution:** `ingest.py` performs global reindexing during the merge phase (`_merge_parallel_results`). It accumulates the block counts from prior jobs to ensure every block in the final archive has a globally unique and sequential index. 
**Bad Thing:** Evaluation will show **0% matches** if predictions from a split run aren't rebased to match the global coordinates used in the golden export.

### 2. Freeform Offset Stability
**Problem:** Freeform labels rely on character offsets. If the Label Studio UI collapses whitespace or newlines, exported offsets won't line up with the stored text.
**Solution:** The freeform label config (`label_config_freeform.py`) enforces `white-space: pre-wrap`. 
**Crucial:** Do not manually edit segment text in the UI; any change to the text content invalidates offsets for all annotations in that task.

### 3. Unexpected Push Root Cause
**Problem:** Users were surprised to see tasks appearing in Label Studio during "benchmarking".
**Reason:** `labelstudio-benchmark` generates fresh predictions by running a full import-prediction cycle, which *must* upload tasks to Label Studio to verify they can be annotated.
**Safety:** All pushes are now gated by `--allow-labelstudio-write`.

### 4. Progress Reporting "Stalls"
**Problem:** Large books appeared to freeze after "Merged split job results."
**Reason:** Post-merge operations (archive building, processed output writes, chunk generation) take significant time.
**Solution:** `run_labelstudio_import` now emits distinct progress phases and batch upload counts.

### 5. Legacy Label Normalization
**Problem:** Over time, label names changed (e.g., `KNOWLEDGE` -> `TIP`, `NOTE` -> `NOTES`, `NARRATIVE` -> `OTHER`).
**Solution:** `eval_freeform.py` and `_normalize_freeform_label` handle this automatically so old golden sets remain usable.

---

## Known Bad Things & Pitfalls

- **0% Recall on Specialized Labels:** The system currently struggles with `TIP`, `NOTES`, and `VARIANT` labels. They are often misclassified as `OTHER` or missed entirely.
- **Heuristic Block Counting:** `_extract_result_block_count` in `ingest.py` is heuristic-heavy and tries multiple ways to find the count. It is a potential source of coordinate drift.
- **Punitive Metrics:** Strict span matching can be punitive. Always check the `app_aligned` (relaxed) and `classification_only` (boundary-insensitive) reports for a more nuanced view of performance.
- **Coordinate System Dependency:** Everything depends on the stable linear sequence of blocks. If the extraction logic (e.g., OCR or PDF parsing) changes how blocks are ordered, all existing golden sets for that file are invalidated.

---

## Implementation Details

- `ingest.py`: Core routing for imports and parallel split-job merging.
- `block_tasks.py`: Logic for generating canonical block tasks with context windows.
- `freeform_tasks.py`: Logic for segmenting text into overlapping windows for span highlighting.
- `eval_freeform.py`: Complex evaluator that maps gold offsets to block ranges for comparison. Includes `app_aligned` summary for "real world" metrics.
- `client.py`: Wrapper for Label Studio API.

---

## Artifacts

Artifacts are primarily routed to `data/golden/` for benchmarks and `data/output/` for staging.

```
data/golden/eval-vs-pipeline/{timestamp}/
├── prediction-run/         # The pipeline artifacts generated for the benchmark
│   ├── manifest.json
│   └── label_studio_tasks.jsonl
├── eval_report.json        # Machine-readable results
├── eval_report.md          # Human-readable summary
├── missed_gold_spans.jsonl # Debugging: what did we miss?
└── false_positive_preds.jsonl # Debugging: what did we invent?
```
