summary: "How to run the optional codex-farm tags-stage suggestion workflow and where its artifacts live."
read_when:
  - "When enabling or debugging tags-stage suggestion outputs"
  - "When editing the recipe.tags.v1 codex-farm pipeline prompt/schema assets"
---

# Tags Stage: Tag Suggestions (codex-farm)

The tags stage is an optional codex-farm pipeline that assigns recipe tags from a provided tag catalog shortlist.

It is off by default and only runs when explicitly enabled.

For stage runs, the accepted tag set is not just written to sidecar artifacts anymore. After the tags pass completes, the same accepted list is projected into:

- `final drafts/<workbook_slug>/r{index}.json` as `recipe.tags`
- `intermediate drafts/<workbook_slug>/r{index}.jsonld` as `keywords`

## How to run

From repo root:

    source .venv/bin/activate
    cookimport stage <path> --llm-tags-pipeline codex-farm-tags-v1 --tag-catalog-json data/tagging/tag_catalog.json

Optional knobs:

- `--codex-farm-pipeline-tags recipe.tags.v1`
- `--codex-farm-root <pack_root>` and `--codex-farm-workspace-root <dir>`
- `--codex-farm-failure-mode fail|fallback`

## Output locations

Per staged workbook (`<workbook_slug>`):

- Raw codex-farm IO:
  - `data/output/<ts>/raw/llm/<workbook_slug>/tags/in/*.json`
  - `data/output/<ts>/raw/llm/<workbook_slug>/tags/out/*.json`
  - `data/output/<ts>/raw/llm/<workbook_slug>/tags_manifest.json`
- User-facing tag artifacts:
  - `data/output/<ts>/tags/<workbook_slug>/r{index}.tags.json`
  - `data/output/<ts>/tags/<workbook_slug>/tagging_report.json`
- Embedded recipe outputs updated in-place:
  - `data/output/<ts>/final drafts/<workbook_slug>/r{index}.json`
  - `data/output/<ts>/intermediate drafts/<workbook_slug>/r{index}.jsonld`

Run-level index:

- `data/output/<ts>/tags/tags_index.json`

## Pipeline assets

Local default tags-stage files:

- `llm_pipelines/pipelines/recipe.tags.v1.json`
- `llm_pipelines/prompts/recipe.tags.v1.prompt.md`
- `llm_pipelines/schemas/recipe.tags.v1.output.schema.json`
