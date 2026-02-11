---
summary: "System architecture, pipeline design, and project conventions."
read_when:
  - Starting work on the project
  - Making architectural decisions
  - Understanding output folder structure or naming conventions
---

# Architecture & Conventions

## Pipeline Overview

The cookimport system uses a **two-phase pipeline**:

```
Source Files → [Ingestion] → RecipeCandidate (JSON-LD) → [Transformation] → RecipeDraftV1
                    ↓                                           ↓
              Raw Artifacts                              Step-linked recipes
              Tip Candidates                             Parsed ingredients
              Topic Candidates                           Time/temp metadata
```

### Phase 1: Ingestion
Each source format has a dedicated plugin that:
1. Detects if it can handle the file (confidence score)
2. Inspects internal structure (layouts, headers, sections)
3. Extracts content to `RecipeCandidate` objects (schema.org JSON-LD compatible)
4. Preserves raw artifacts for auditing

### Phase 2: Transformation
Converts intermediate format to final output:
1. Parses ingredient strings into structured components
2. Extracts time/temperature from instruction text
3. Links ingredients to the steps where they're used
4. Classifies and extracts standalone tips

---

## Output Folder Structure

Each run creates a timestamped folder:

```
data/output/{YYYY-MM-DD_HH:MM:SS}/
├── intermediate drafts/{workbook_slug}/   # RecipeSage JSON-LD per recipe
├── final drafts/{workbook_slug}/          # RecipeDraftV1 per recipe
├── tips/{workbook_slug}/                  # Tips and topic candidates
├── chunks/{workbook_slug}/                # Knowledge chunks (optional)
├── raw/{importer}/{source_hash}/          # Raw extracted artifacts
└── {workbook_slug}.excel_import_report.json  # Conversion report
```

---

## Naming Conventions

### File Naming
- Workbook slug: lowercase, alphanumeric + underscores (from source filename)
- Recipe files: `r{index}.json` (0-indexed)
- Tip files: `t{index}.json` (0-indexed)
- Topic files: `topic_{index}.json`

### ID Generation
Stable IDs use URN format: `urn:cookimport:{importer}:{file_hash}:{location_id}`

Example: `urn:cookimport:epub:abc123:c5` (chunk 5 from EPUB with hash abc123)

---

## PDF & EPUB Job Splitting

When `cookimport stage` runs with `--workers > 1`, large PDFs can be split into
page-range jobs (`--pdf-pages-per-job` controls the target pages per job). Each
job parses a slice in parallel, then the main process merges results into a
single workbook output with sequential recipe IDs. During a split run, raw
artifacts are written to a temporary `.job_parts/` folder under the run output
and merged into `raw/` after the merge completes.

Large EPUBs can also be split into spine-range jobs with
`--epub-spine-items-per-job`. Each job parses a subset of spine items, and the
merge step rewrites recipe IDs to a single global sequence.

### Field Normalization
- `raw_text`, `raw_ingredient_text`, `raw_unit_text`, `preparation`, `note` → **lowercase**
- Whitespace: normalized (single spaces, max 2 newlines)
- Unicode: NFKC normalized, mojibake repaired

---

## Provenance System

Every output includes provenance for full traceability:

```json
{
  "provenance": {
    "source_file": "cookbook.epub",
    "source_hash": "sha256:abc123...",
    "extraction_method": "heuristic_epub",
    "confidence_score": 0.85,
    "location": {
      "start_block": 42,
      "end_block": 67,
      "chunk_index": 5
    },
    "extracted_at": "2026-01-31T10:30:00Z"
  }
}
```

---

## Plugin Architecture

Importers register with the plugin registry (`cookimport/plugins/registry.py`):

```python
class MyImporter:
    name = "my_format"

    def detect(self, path: Path) -> float:
        """Return confidence 0.0-1.0 that we can handle this file."""

    def inspect(self, path: Path) -> WorkbookInspection:
        """Quick structure analysis without full extraction."""

    def convert(self, path: Path, mapping: MappingConfig | None,
                progress_callback=None) -> ConversionResult:
        """Full extraction to RecipeCandidate objects."""

registry.register(MyImporter())
```

The registry's `best_importer_for_path()` selects the highest-confidence plugin.

---

## Future: LLM & ML Integration

The system follows a **deterministic-first** philosophy:
- Heuristics handle ~90%+ of cases
- LLM escalation only for low-confidence outputs
- ML classification reserved for cases where heuristics systematically fail

Infrastructure exists in `cookimport/llm/` (currently mocked):
- Schema-constrained output (Pydantic models)
- Caching by (model, prompt_version, input_hash)
- Token budget awareness (~30-40M tokens for 300 cookbooks)

ML options documented for future use:
- Zero-shot NLI (BART-large-mnli) for tip classification
- Weak supervision (Snorkel) for labeling function combination
- Supervised DistilBERT for ingredient/instruction segmentation
