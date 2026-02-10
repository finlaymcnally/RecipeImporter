---
summary: "Label Studio integration for benchmarking and golden set creation."
read_when:
  - Setting up Label Studio for evaluation
  - Creating or exporting golden sets
  - Understanding chunking strategies
---

# Label Studio Integration

**Location:** `cookimport/labelstudio/`

Label Studio is used to create ground-truth datasets for validating extraction accuracy.

## Quick Start

### Prerequisites

```bash
# Start Label Studio (Docker)
docker run -it -p 8080:8080 heartexlabs/label-studio:latest

# Set environment variables
export LABEL_STUDIO_URL=http://localhost:8080
export LABEL_STUDIO_API_KEY=your_api_key_here
```

### Import Workflow

```bash
# Import a cookbook for labeling
cookimport labelstudio-import path/to/cookbook.epub \
  --chunk-level both
```

If `--project-name` is omitted, the CLI now defaults to the input filename stem (for example `the_food_lab`) and appends `-1`, `-2`, etc. when that title already exists in Label Studio.

Canonical block workflow (separate project):

```bash
cookimport labelstudio-import path/to/cookbook.epub \
  --project-name "ATK Cookbook Canonical (blocks)" \
  --task-scope canonical-blocks \
  --context-window 1
```

Freeform span workflow (separate project):

```bash
cookimport labelstudio-import path/to/cookbook.epub \
  --project-name "ATK Cookbook Freeform (spans)" \
  --task-scope freeform-spans \
  --segment-blocks 40 \
  --segment-overlap 5
```

### Export Workflow

```bash
# Export labeled data as golden set
cookimport labelstudio-export \
  --project-name "ATK Cookbook Benchmark" \
  --output-dir data/golden/
```

Canonical block export:

```bash
cookimport labelstudio-export \
  --project-name "ATK Cookbook Canonical (blocks)" \
  --export-scope canonical-blocks \
  --output-dir data/golden/
```

Freeform span export:

```bash
cookimport labelstudio-export \
  --project-name "ATK Cookbook Freeform (spans)" \
  --export-scope freeform-spans \
  --output-dir data/golden/
```

---

## Three Golden Sets: Pipeline vs Canonical vs Freeform

- **Pipeline golden set**: labels the chunker’s proposed structural/atomic chunks. Great for fast regression on current pipeline output.
- **Canonical golden set**: labels every extracted block so missed recipes/tips are still captured. Gold spans are derived from block labels and stay stable across chunking changes.
- **Freeform span golden set**: label arbitrary text spans in segment text using offsets. Exports preserve start/end offsets plus block mapping for downstream evaluation.

Keep these as **separate Label Studio projects** so each can use its own labeling config and stable contract.

Gotchas:

- Keep canonical vs pipeline projects separate (label configs are different).
- Keep freeform projects separate from canonical/pipeline projects.
- Preserve newlines in block text; the UI relies on them for context.
- Freeform offsets depend on exact text; the freeform config uses `white-space: pre-wrap` and segment text should not be manually edited.
- Rerun imports safely with resume mode; existing task IDs are skipped.

Freeform span label set (`label_config_freeform.py`):

- `RECIPE_TITLE`
- `INGREDIENT_LINE`
- `INSTRUCTION_LINE`
- `TIP` (broad reusable guidance)
- `NOTES` (recipe-specific notes; intended to map into recipe JSON notes)
- `VARIANT` (recipe/step variation)
- `NARRATIVE`
- `OTHER`

## Chunking Strategies

### Structural Chunks

Recipe-level units for validating segmentation accuracy.

**Use case:** "Did we correctly identify recipe boundaries?"

Each chunk contains:
- Full recipe text (ingredients + instructions)
- Extracted recipe title
- Source location (block indices)

**Labels:** Correct boundary, Over-segmented, Under-segmented, Not a recipe

### Atomic Chunks

Line-level units for validating parsing accuracy.

**Use case:** "Did we correctly parse this ingredient line?"

Each chunk contains:
- Single ingredient or instruction line
- Parsed fields (quantity, unit, item, etc.)
- Confidence score

**Labels:** Correct, Incorrect quantity, Incorrect unit, Incorrect item, etc.

### Chunk Levels

| Level | Description |
|-------|-------------|
| `structural` | Recipe-level chunks only |
| `atomic` | Line-level chunks only |
| `both` | Both structural and atomic chunks |

---

## Labeling Interface

The Label Studio project uses a custom labeling config (`label_config.py`):

### For Structural Chunks
- Boundary correctness (correct/over/under-segmented)
- Recipe vs non-recipe classification
- Title extraction accuracy

### For Atomic Chunks
- Field-by-field correctness
- Quantity kind accuracy
- Section header detection

---

## Canonical Block Labeling

Canonical labeling uses a separate Label Studio config (`label_config_blocks.py`) and block-level tasks with context. Each block gets exactly one label:

- `RECIPE_TITLE`
- `INGREDIENT_LINE`
- `INSTRUCTION_LINE`
- `TIP`
- `NARRATIVE`
- `OTHER`

Block IDs are stable: `urn:cookimport:block:{source_hash}:{block_index}`.

---

## Golden Set Export

Exported data format (JSONL):

```json
{
  "chunk_id": "urn:cookimport:epub:abc123:c5",
  "chunk_type": "structural",
  "source_file": "cookbook.epub",
  "labels": {
    "boundary": "correct",
    "is_recipe": true,
    "title_correct": true
  },
  "annotator": "user@example.com",
  "annotated_at": "2026-01-31T10:30:00Z"
}
```

---

Canonical export outputs:

- `canonical_block_labels.jsonl`: one line per labeled block (block_id, label, annotator).
- `canonical_gold_spans.jsonl`: derived recipe spans (start/end block indices).

---

## Pipeline Routing

The chunking module (`cookimport/labelstudio/chunking.py`) handles:

### Extraction Archive

Raw extracted content stored for reference:
- Block text and indices
- Source location
- Extraction method

### Chunk Generation

```python
# Structural chunks
chunks = chunk_structural(result, archive, source_file, book_id, pipeline, file_hash)

# Atomic chunks
chunks = chunk_atomic(result, archive, source_file, book_id, pipeline, file_hash)
```

### Coverage Tracking

Monitors extraction completeness:
- `extracted_chars`: Total characters from source
- `chunked_chars`: Characters included in chunks
- `warnings`: Coverage gaps or issues

---

## Artifacts

Each import run creates:

```
data/output/{timestamp}/labelstudio/{book_slug}/
├── manifest.json           # Run metadata, chunk IDs, coverage
├── extracted_archive.json  # Raw extracted blocks
├── extracted_text.txt      # Plain text for reference
├── label_studio_tasks.jsonl # Tasks uploaded to Label Studio
├── project.json            # Label Studio project info
└── coverage.json           # Extraction coverage stats
```

Export artifacts (under `exports/`):

- `labelstudio_export.json` (raw export)
- `golden_set_tip_eval.jsonl` (pipeline)
- `canonical_block_labels.jsonl` + `canonical_gold_spans.jsonl` (canonical)
- `freeform_span_labels.jsonl` + `freeform_segment_manifest.jsonl` (freeform spans)

---

## Resume Mode

Import supports resuming to add new chunks without duplicating:

```bash
# First import
cookimport labelstudio-import cookbook.epub --project-name "My Project"

# Later: resume with additional chunks
cookimport labelstudio-import cookbook.epub --project-name "My Project"
# Automatically detects existing chunks and only uploads new ones
```

Use `--overwrite` to start fresh (deletes existing project).

---

## Evaluation (Canonical)

Compare pipeline structural chunks to canonical gold spans:

```bash
cookimport labelstudio-eval canonical-blocks \
  --pred-run data/output/<timestamp>/labelstudio/<book_slug>/ \
  --gold-spans data/golden/<book_slug>/canonical_gold_spans.jsonl \
  --output-dir data/golden/<book_slug>/eval/
```

Optional: add `--overlap-threshold 0.5` to tune the match threshold.

Outputs:

- `eval_report.json`
- `eval_report.md`
- `missed_gold_spans.jsonl`
- `false_positive_preds.jsonl`

## Evaluation (Freeform Spans)

Compare pipeline chunk predictions to freeform span labels (mapped to block ranges):

```bash
cookimport labelstudio-eval freeform-spans \
  --pred-run data/output/<timestamp>/labelstudio/<book_slug>/ \
  --gold-spans data/golden/<book_slug>/freeform_span_labels.jsonl \
  --output-dir data/golden/<book_slug>/eval-freeform/
```

Outputs:

- `eval_report.json`
- `eval_report.md`
- `missed_gold_spans.jsonl`
- `false_positive_preds.jsonl`

### Guided benchmark flow (single command)

Run an end-to-end guided benchmark (choose gold export, choose source file, generate predictions, score):

```bash
cookimport labelstudio-benchmark
```

The command discovers `freeform_span_labels.jsonl`, prompts for selection, runs a pipeline prediction import for the chosen source file, and writes eval artifacts under `eval-vs-pipeline/<timestamp>/`.

---

## Client API

Direct API access for advanced use:

```python
from cookimport.labelstudio.client import LabelStudioClient

client = LabelStudioClient(url, api_key)

# Find or create project
project = client.find_project_by_title("My Project")
if not project:
    project = client.create_project("My Project", label_config_xml)

# Import tasks
client.import_tasks(project["id"], tasks)

# Export annotations
annotations = client.export_annotations(project["id"])
```
