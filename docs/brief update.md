---
summary: "Overview of the current system status and the two-phase pipeline (Ingestion and Transformation)."
read_when:
  - When understanding the overall system architecture
  - When working on Phase 1 or Phase 2 of the pipeline
---

# Brief Update: Current System Status

## Executive Summary
The `cookimport` CLI now implements the two-phase pipeline as originally designed. Both intermediate RecipeSage JSON-LD files and final DraftV1 files are persisted to disk, enabling independent re-processing and future source additions.

## Current Implementation

### Output Structure
```
data/output/{timestamp}/
├── intermediate drafts/     # RecipeSage JSON-LD (.jsonld)
│   └── {workbook_slug}/
│       └── r{index}.jsonld
├── final drafts/            # RecipeDraftV1 (.json)
│   └── {workbook_slug}/
│       └── r{index}.json
├── tips/                    # Tip/knowledge snippets (.json)
│   └── {workbook_slug}/
│       ├── t{index}.json
│       └── tips.md           # Markdown summary with t{index} ids + anchor tags
│       ├── topic_candidates.json  # Topic chunks for evaluation/LLM prefiltering
│       └── topic_candidates.md    # Human-readable topic chunk list
└── reports/
    └── {workbook_slug}.excel_import_report.json
```

Each run creates a new timestamped folder (e.g., `2026-01-22-182409`).

### Two-Phase Pipeline

**Phase 1: Ingestion (Excel → Intermediate)**
- **Input:** Source file (Excel)
- **Action:** Extract raw content, detect layout, normalize fields
- **Output:** RecipeSage JSON-LD files in `intermediate drafts/{workbook_slug}/r{index}.jsonld`

**Phase 2: Transformation (Intermediate → Final)**
- **Input:** RecipeCandidate objects (same data as JSON-LD)
- **Action:** NLP ingredient parsing, step-ingredient linking, schema conversion
- **Output:** RecipeDraftV1 JSON files in `final drafts/{workbook_slug}/r{index}.json`

### Data Flow

```
Excel File (.xlsx)
    ↓
[ExcelImporter.convert()]
    ↓
RecipeCandidate (in-memory)
    ├─→ [write_intermediate_outputs()] → intermediate drafts/{workbook_slug}/r{index}.jsonld
    └─→ [write_draft_outputs()]        → final drafts/{workbook_slug}/r{index}.json
    └─→ [write_tip_outputs()]          → tips/{workbook_slug}/t{index}.json
```

### File Formats

**Intermediate (RecipeSage JSON-LD):**
- Schema.org Recipe type with `@context` and `@type`
- Raw ingredient strings (unparsed)
- Raw instruction text
- Full provenance metadata

**Final (RecipeDraftV1):**
- `schema_v: 1` for versioning
- Parsed ingredients with quantity, unit, preparation, confidence
- Ingredients assigned to instruction steps
- Recipe metadata (title, yield, notes)

## Code Reference
In `cookimport/cli.py`, the stage command:
```python
result = importer.convert(file_path, mapping_config)

# Phase 1: Write intermediate JSON-LD
write_intermediate_outputs(result, intermediate_dir)

# Phase 2: Write final DraftV1
write_draft_outputs(result, final_dir)
```

## Key Files
- `cookimport/staging/writer.py` - Output functions for both formats
- `cookimport/staging/jsonld.py` - RecipeCandidate → JSON-LD conversion
- `cookimport/staging/draft_v1.py` - RecipeCandidate → DraftV1 conversion
