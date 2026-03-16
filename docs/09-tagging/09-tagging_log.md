---
summary: "Tagging architecture/build/fix-attempt log to avoid repeated dead ends and circular debugging."
read_when:
  - When you are going in multi-turn circles on tagging behavior or implementation
  - When the human says "we are going in circles on this"
  - When you need prior tagging architecture versions, build attempts, or failed fixes before trying another change
---

# Tagging Log

Read this if you are going in multi-turn circles on the program, or if the human says "we are going in circles on this."
This file tracks the tagging history that still explains current runtime behavior. Old docs-about-docs cleanup notes were pruned.

## Attempt Ledger

1. `2026-02-25_16.28.03` pass5 codex-farm tagging rollout (merged from retired task docs)

Problem captured:
- `--llm` path in tagging CLI existed but second-pass implementation was scaffold/no-op.
- Needed one auditable optional pass that could run in both standalone tagging and stage flows without changing deterministic defaults.

Surprises/discoveries preserved:
- `llm_second_pass.py` previously returned mock empties (`_check_provider_configured=False` path).
- Stage integration is cleaner as a run-level pass after `final drafts/...` are written; split and non-split runs already converge there.

Major decisions preserved:
- Implement pass5 as separate codex-farm pipeline (`recipe.tags.v1`), not as an extension of `recipe.final.v1`.
- Keep artifact names stable (`*.tags.json`, `tagging_report.json`) and add provenance fields (`source`, `llm_pipeline_id`, `new_tag_proposals`).
- Never auto-create unknown tags from LLM output; emit proposals for review only.
- Keep pass5 stage integration gated by `llm_tags_pipeline`; write pass5 raw IO under `raw/llm/<workbook_slug>/pass5_tags/`.

What shipped:
- New provider boundary: `cookimport/tagging/codex_farm_tags_provider.py`.
- `llm_second_pass.py` wiring to real provider/failure-mode handling.
- Shared orchestration entrypoint: `cookimport/tagging/orchestrator.py`.
- Stage integration with run settings:
  - `llm_tags_pipeline`
  - `tag_catalog_json`
  - fixed `codex_farm_pipeline_pass5_tags` (`recipe.tags.v1`)
- Run-level manifest/artifact indexing for pass5 outputs.

Anti-loop notes:
- Missing pass5 artifacts are usually gate/config/failure-mode issues, not deterministic rules-engine regressions.
- Do not route unknown LLM tag strings directly to DB apply paths; keep `new_tag_proposals` review-only.
- Do not fold pass5 behavior into recipe-pass pipelines while `llm_recipe_pipeline` remains policy-locked off.

2. `2026-03-16_14.57.28` pass5-to-tags runtime seam cleanup

Problem captured:
- broad stage observability had already standardized on semantic stage names, but tagging still carried `pass5` terminology in a few live config/CLI/artifact seams

What stuck:
- treat this as a narrow rename, not a broader pipeline-architecture migration
- stage observability already had the right semantic stage name; the stale seam was mostly config/CLI/raw-path naming plus a few tests/fixtures
- current live names are:
  - `RunSettings.codex_farm_pipeline_tags`
  - `--codex-farm-pipeline-tags`
  - `raw/llm/<workbook_slug>/tags/`
- `recipe.tags.v1` remains the pipeline id; only the surrounding runtime seam was renamed

Anti-loop notes:
- if a future cleanup touches tagging, do not widen it into the whole old pass-slot architecture unless the actual code path still depends on that language
- if tests/fixtures still say `pass5_tags`, prefer updating the fixture rather than teaching new runtime code to emit both names

3. `2026-03-16_15.35.00` embed stage tags into recipe outputs

Problem captured:
- the optional stage tags pass wrote useful sidecar artifacts, but final cookbook3 drafts still hid prior tags in `recipe.notes` and did not project the accepted stage-tag results back into the recipe outputs themselves

What stuck:
- the stage tags pass is the source of truth for embedded output tags once it runs
- final cookbook3 drafts should expose accepted tags in `recipe.tags`, not as a `Tags:` notes line
- intermediate JSON-LD should mirror the same ordered list in `keywords`
- sidecar tagging artifacts (`*.tags.json`, `tagging_report.json`, `tags_index.json`) remain part of the contract; embedding tags into drafts does not replace those artifacts

Anti-loop notes:
- if embedded recipe tags drift from sidecar tagging outputs, fix the projection step instead of inventing a second source of truth
- keep this change on the recipeimport output side; it does not imply a cookbook-site schema migration
