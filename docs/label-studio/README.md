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
  --project-name "ATK Cookbook Benchmark" \
  --chunk-level both
```

### Export Workflow

```bash
# Export labeled data as golden set
cookimport labelstudio-export \
  --project-name "ATK Cookbook Benchmark" \
  --output-dir data/golden/
```

---

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
