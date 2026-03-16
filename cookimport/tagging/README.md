# Auto-Tagging Subsystem

Catalog-driven recipe tagging engine. See `docs/plans/I4.1-Auto-tag.md` for full design.

## Quick start

```bash
# Suggest tags for draft files
cookimport tag-recipes suggest --draft-dir "data/output/<run>/final drafts/<workbook>/" \
  --catalog-json data/tagging/tag_catalog.json --explain

# Export catalog from DB
cookimport tag-catalog export --db-url "$COOKIMPORT_DATABASE_URL" --out data/tagging/tag_catalog.json

# Inspect signal pack
cookimport tag-recipes debug-signals --draft path/to/r0.json
```

## How to add rules

Edit `rules.py` — add an entry to `TAG_RULES` keyed by the tag's `key_norm`:

```python
"my-new-tag": {
    "min_score": 0.6,
    "patterns": [
        {"field": "ingredients", "regex": r"\bmy pattern\b", "weight": 0.7, "evidence": "matched X in ingredients"},
    ],
}
```

Always add a test case in `tests/test_tagging.py` and a gold label in `tests/tagging_gold/gold_labels.json`.

## Module layout

- `catalog.py` — Tag/Category models, DB/JSON loaders, fingerprinting
- `signals.py` — RecipeSignalPack extraction from drafts
- `db_read.py` — RecipeSignalPack extraction from DB
- `rules.py` — TAG_RULES dictionary (regex patterns per tag)
- `policies.py` — CATEGORY_POLICIES (single/multi, thresholds)
- `engine.py` — Scoring engine, category policy enforcement
- `render.py` — Output formatting (text, JSON, run reports)
- `db_write.py` — Idempotent INSERT for recipe_tag_assignments
- `llm_second_pass.py` — LLM second-pass orchestration (codex-farm-backed, still optional)
- `codex_farm_tags_provider.py` — Pass-5 codex-farm runner + strict shortlist/catalog validation
- `orchestrator.py` — Shared deterministic+LLM draft-folder runner and stage pass integration
- `eval.py` — Precision/recall evaluation harness
- `cli.py` — Typer commands wired into main app

## Stage integration (optional)

Stage can now run an optional tags pass after drafts are written:

```bash
cookimport stage <path> \
  --llm-tags-pipeline codex-farm-tags-v1 \
  --tag-catalog-json data/tagging/tag_catalog.json
```

Outputs are written under `data/output/<ts>/tags/<workbook_slug>/` with raw codex-farm IO under `raw/llm/<workbook_slug>/tags/`.
