---
summary: "Catalog-driven auto-tagging reference for current draft, DB, and stage tagging workflows."
read_when:
  - When changing auto-tagging rules, scoring, or category policies
  - When working on tag-catalog or tag-recipes CLI commands
---

# Tagging Section Reference

Auto-tagging code lives under `cookimport/tagging/` and is wired into the main CLI via `tag-catalog`, `tag-recipes`, and the optional stage tags pass in `cookimport/cli.py`.
For tagging architecture/build/fix-attempt history and anti-loop context, use `docs/09-tagging/09-tagging_log.md`.

## Current Runtime Contract

- Deterministic tagging is the base path everywhere:
  - signal extraction (`signals.py` or `db_read.py`) -> rules/policies (`rules.py`, `policies.py`) -> scoring/selection (`engine.py`).
- Optional LLM tagging is additive (fills missing categories only), never replacement:
  - standalone draft path: `cookimport tag-recipes suggest ... --llm`
  - standalone DB path: `cookimport tag-recipes apply ... --llm`
  - stage path: `cookimport stage ... --llm-tags-pipeline codex-farm-tags-v1 --tag-catalog-json <path>`
- Stage observability already treats this optional work as the semantic `tags` stage. Historical `pass5` wording is now only background context for older plans/logs/tests and should not be reintroduced into new runtime/output names.
- Stage pass is gated:
  - if `llm_tags_pipeline=off`, stage does not run tagging pass and writes no `tags/` artifacts.
  - if enabled, stage requires `tag_catalog_json` to exist.
- Default remains no-LLM/off-by-default.

## Code Map

### `cookimport/tagging/` modules

- `catalog.py`: catalog dataclasses, DB loader, JSON import/export, fingerprinting helpers
- `signals.py`: `RecipeSignalPack` and draft-json signal extraction/normalization
- `db_read.py`: DB recipe+steps+ingredient fetch into `RecipeSignalPack`
- `rules.py`: regex rule matrix keyed by `tag.key_norm`
- `policies.py`: category single/multi policy + thresholds/max-tags
- `engine.py`: regex/numeric scoring, thresholds, and policy application
- `llm_second_pass.py`: missing-category shortlist requests + failure-mode behavior (`fail` or `fallback`)
- `codex_farm_tags_provider.py`: tags bundle schema validation, shortlist/category enforcement, raw I/O/manifest writing
- `orchestrator.py`: shared draft-file runner and stage pass runner
- `render.py`: text/json serializers + per-run tagging report writer
- `db_write.py`: idempotent `recipe_tag_assignments` insert + tag-id verification
- `eval.py`: precision/recall harness used by tests and offline quality checks
- `cli.py`: `tag-catalog` and `tag-recipes` command implementations
- `__init__.py`: package marker only (no runtime logic)

### Nearby integration code

- `cookimport/cli.py`:
  - mounts `tag-catalog` / `tag-recipes` command groups
  - exposes stage options `--llm-tags-pipeline`, `--codex-farm-pipeline-tags`, `--tag-catalog-json`, `--codex-farm-failure-mode`
  - validates `--tag-catalog-json` when stage tags are enabled
  - runs `run_stage_tagging_pass(...)` after staged `final drafts/` outputs exist
- `cookimport/config/run_settings.py`:
  - typed fields/defaults for `llm_tags_pipeline`, `tag_catalog_json`, and `codex_farm_failure_mode`
  - exposes the fixed tags pipeline id via `RunSettings.codex_farm_pipeline_tags`
  - normalizes values via `build_run_settings(...)`

Naming note:

- the remaining live seam is narrow and semantic:
  - config property: `codex_farm_pipeline_tags`
  - CLI option: `--codex-farm-pipeline-tags`
  - raw stage artifacts: `raw/llm/<workbook_slug>/tags/...`
- if you still see `pass5_tags`, treat it as historical fixture/log language or a cleanup target, not the current contract

## CLI Surfaces

- `cookimport tag-catalog export`:
  - exports current DB catalog to JSON + fingerprint
- `cookimport tag-recipes debug-signals`:
  - inspects extracted signals from draft JSON or DB recipe
- `cookimport tag-recipes suggest`:
  - draft file/folder tagging, optional `--llm`, report + optional per-recipe `*.tags.json`
- `cookimport tag-recipes apply`:
  - DB recipe tagging (dry-run default), optional `--llm`, insert-only apply path

## Tags Runtime And Artifacts

When LLM tagging is enabled (`llm_tags_pipeline=codex-farm-tags-v1`), stage writes:

- `tags/<workbook_slug>/<draft_stem>.tags.json`
- `tags/<workbook_slug>/tagging_report.json`
- `tags/tags_index.json`
- `raw/llm/<workbook_slug>/tags/in/*.json`
- `raw/llm/<workbook_slug>/tags/out/*.json`
- `raw/llm/<workbook_slug>/tags_manifest.json`

For ad-hoc `tag-recipes suggest --llm` / `apply --llm` paths, the tags pipeline can run in temporary dirs unless a raw stage directory is explicitly provided by caller.

Per-recipe `*.tags.json` artifacts preserve deterministic + LLM provenance:

- `source` (`deterministic` or `llm`)
- `llm_pipeline_id` (for LLM-origin suggestions)
- `new_tag_proposals` (review-only; not auto-applied)

Run reports preserve aggregate validation details:

- `llm.validation` counters in `tagging_report.json`
- `llm.reports` and `llm.validations` in `tags/tags_index.json`

## Tags Validation And Failure Boundaries

- Provider accepts only schema-valid bundle outputs (`bundle_version=1`).
- Selected tags are dropped when any check fails:
  - category not requested
  - unknown `tag_key_norm`
  - catalog category mismatch
  - tag not in shortlisted candidates for that category
- Unknown/new labels are captured only as `new_tag_proposals`; they are never auto-created.
- `codex_farm_failure_mode=fail` raises setup/runtime errors; `fallback` logs and keeps deterministic-only results.

## Known Gaps and Caveats

- Existing in-repo fixtures can validate tags-pipeline wiring and schemas, but quality of proposed tags still depends on catalog quality and prompt quality.
- Missing `tags/` outputs are usually wiring/gating issues:
  - `llm_tags_pipeline` disabled
  - missing `tag_catalog_json`
  - tags runner failure under `codex_farm_failure_mode=fallback`
- If the tags pipeline is set to `fail`, setup/runtime errors intentionally fail the stage run.

## Operational docs

- LLM tagging details:
  `docs/10-llm/tags_pass.md`
- Version/build/fix-attempt history:
  `docs/09-tagging/09-tagging_log.md`
