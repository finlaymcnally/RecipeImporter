---
summary: "How to run the optional codex-farm pass5 tag suggestion workflow and where its artifacts live."
read_when:
  - "When enabling or debugging pass5 tag suggestion outputs"
  - "When editing the recipe.tags.v1 codex-farm pipeline prompt/schema assets"
---

# Pass 5: Tag Suggestions (codex-farm)

Pass 5 is an optional codex-farm pipeline that assigns recipe tags from a provided tag catalog shortlist.

It is off by default and only runs when explicitly enabled.

## How to run

From repo root:

    source .venv/bin/activate
    cookimport stage <path> --llm-tags-pipeline codex-farm-tags-v1 --tag-catalog-json data/tagging/tag_catalog.json

Optional knobs:

- `--codex-farm-pipeline-pass5-tags recipe.tags.v1`
- `--codex-farm-root <pack_root>` and `--codex-farm-workspace-root <dir>`
- `--codex-farm-failure-mode fail|fallback`

## Output locations

Per staged workbook (`<workbook_slug>`):

- Raw codex-farm IO:
  - `data/output/<ts>/raw/llm/<workbook_slug>/pass5_tags/in/*.json`
  - `data/output/<ts>/raw/llm/<workbook_slug>/pass5_tags/out/*.json`
  - `data/output/<ts>/raw/llm/<workbook_slug>/pass5_tags_manifest.json`
- User-facing tag artifacts:
  - `data/output/<ts>/tags/<workbook_slug>/r{index}.tags.json`
  - `data/output/<ts>/tags/<workbook_slug>/tagging_report.json`

Run-level index:

- `data/output/<ts>/tags/tags_index.json`

## Pipeline assets

Local default pass-5 files:

- `llm_pipelines/pipelines/recipe.tags.v1.json`
- `llm_pipelines/prompts/recipe.tags.v1.prompt.md`
- `llm_pipelines/schemas/recipe.tags.v1.output.schema.json`
