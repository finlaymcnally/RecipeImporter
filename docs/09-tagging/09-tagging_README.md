---
summary: "Catalog-driven auto-tagging reference for draft-file and DB-backed tagging workflows."
read_when:
  - When changing auto-tagging rules, scoring, or category policies
  - When working on tag-catalog or tag-recipes CLI commands
---

# Tagging Section Reference

Auto-tagging code lives under `cookimport/tagging/` and is wired into the main CLI via `tag-catalog` and `tag-recipes` command groups.
For tagging architecture/build/fix-attempt history and anti-loop context, use `docs/09-tagging/09-tagging_log.md`.

## Current Runtime Contract

- Deterministic tagging is the base path everywhere:
  - signal extraction (`signals.py` or `db_read.py`) -> rules/policies (`rules.py`, `policies.py`) -> scoring/selection (`engine.py`).
- Optional pass5 LLM tagging is additive (fills missing categories only), never replacement:
  - standalone draft path: `cookimport tag-recipes suggest ... --llm`
  - standalone DB path: `cookimport tag-recipes apply ... --llm`
  - stage path: `cookimport stage ... --llm-tags-pipeline codex-farm-tags-v1 --tag-catalog-json <path>`
- Stage pass is gated:
  - if `llm_tags_pipeline=off`, stage does not run tagging pass and writes no `tags/` artifacts.
  - if enabled, stage requires `tag_catalog_json` to exist.
- Default remains no-LLM/off-by-default.

## Code Coverage Map

### `cookimport/tagging/` modules

- `catalog.py`: catalog dataclasses, DB loader, JSON import/export, fingerprinting helpers
- `signals.py`: `RecipeSignalPack` and draft-json signal extraction/normalization
- `db_read.py`: DB recipe+steps+ingredient fetch into `RecipeSignalPack`
- `rules.py`: regex rule matrix keyed by `tag.key_norm`
- `policies.py`: category single/multi policy + thresholds/max-tags
- `engine.py`: regex/numeric scoring, thresholds, and policy application
- `llm_second_pass.py`: missing-category shortlist requests + failure-mode behavior (`fail` or `fallback`)
- `codex_farm_tags_provider.py`: pass5 bundle schema validation, shortlist/category enforcement, raw I/O/manifest writing
- `orchestrator.py`: shared draft-file runner and stage pass runner
- `render.py`: text/json serializers + per-run tagging report writer
- `db_write.py`: idempotent `recipe_tag_assignments` insert + tag-id verification
- `eval.py`: precision/recall harness used by tests and offline quality checks
- `cli.py`: `tag-catalog` and `tag-recipes` command implementations
- `__init__.py`: package marker only (no runtime logic)

### Nearby integration code (outside `cookimport/tagging/`)

- `cookimport/cli.py`:
  - mounts `tag-catalog` / `tag-recipes` command groups
  - exposes stage options `--llm-tags-pipeline`, `--codex-farm-pipeline-pass5-tags`, `--tag-catalog-json`, `--codex-farm-failure-mode`
  - runs `run_stage_tagging_pass(...)` at end of stage when tags pipeline is enabled
- `cookimport/config/run_settings.py`:
  - typed fields/defaults for `llm_tags_pipeline`, `codex_farm_pipeline_pass5_tags`, `tag_catalog_json`, `codex_farm_failure_mode`
  - normalizes values via `build_run_settings(...)`
- `cookimport/entrypoint.py`:
  - forwards saved settings into stage call defaults, including pass5 tagging keys

## CLI Surfaces

- `cookimport tag-catalog export`:
  - exports current DB catalog to JSON + fingerprint
- `cookimport tag-recipes debug-signals`:
  - inspects extracted signals from draft JSON or DB recipe
- `cookimport tag-recipes suggest`:
  - draft file/folder tagging, optional `--llm`, report + optional per-recipe `*.tags.json`
- `cookimport tag-recipes apply`:
  - DB recipe tagging (dry-run default), optional `--llm`, insert-only apply path

## Pass5 Runtime And Artifacts

When pass5 is enabled (`llm_tags_pipeline=codex-farm-tags-v1`), stage writes:

- `tags/<workbook_slug>/<draft_stem>.tags.json`
- `tags/<workbook_slug>/tagging_report.json`
- `tags/tags_index.json`
- `raw/llm/<workbook_slug>/pass5_tags/in/*.json`
- `raw/llm/<workbook_slug>/pass5_tags/out/*.json`
- `raw/llm/<workbook_slug>/pass5_tags_manifest.json`

For ad-hoc `tag-recipes suggest --llm` / `apply --llm` paths, pass5 can run in temporary dirs unless a raw pass directory is explicitly provided by caller.

Per-recipe tag artifacts preserve deterministic + LLM provenance:

- `source` (`deterministic` or `llm`)
- `llm_pipeline_id` (for LLM-origin suggestions)
- `new_tag_proposals` (review-only; not auto-applied)
- `llm_validation` counters in reports (accepted/dropped selections and drop reasons)

`tags/tags_index.json` includes workbook report paths, totals, and aggregated `llm.reports` + `llm.validations`.

## Pass5 Validation Boundaries

- Provider accepts only schema-valid bundle outputs (`bundle_version=1`).
- Selected tags are dropped when any check fails:
  - category not requested
  - unknown `tag_key_norm`
  - catalog category mismatch
  - tag not in shortlisted candidates for that category
- Unknown/new labels are captured only as `new_tag_proposals`; they are never auto-created.

## Safety/Policy Boundaries

- Keep catalog-key stability:
  - rules and suggestions are keyed by `tag.key_norm`, not mutable DB IDs.
- DB apply behavior is insert-only and intentionally conservative.
- Unknown tags from LLM output are never auto-created/applied:
  - they are recorded in `new_tag_proposals` for human review.
- Pass5 should remain independent from recipe parsing correction:
  - this lane adds tags to staged outputs and does not modify recipe draft text.

## Known Gaps and Caveats

- Existing in-repo fixtures can validate pass5 wiring and schemas, but quality of proposed tags still depends on catalog quality and prompt quality.
- Missing `tags/` outputs are usually wiring/gating issues:
  - `llm_tags_pipeline` disabled
  - missing `tag_catalog_json`
  - pass5 runner failure under `codex_farm_failure_mode=fallback`
- If pass5 is set to `fail`, setup/runtime errors intentionally fail the stage run.

## Operational docs

- Module-level quickstart:
  `cookimport/tagging/README.md`
- Pass5 LLM tagging details:
  `docs/10-llm/tags_pass.md`
- Version/build/fix-attempt history:
  `docs/09-tagging/09-tagging_log.md`

## 2026-02-27 Merged Understandings: Tagging Docs Cleanup + Coverage

Merged source notes:
- `docs/understandings/2026-02-27_19.45.55-tagging-doc-cleanup-current-contract.md`
- `docs/understandings/2026-02-27_19.50.10-tagging-doc-code-coverage-map.md`

Current-contract additions:
- Keep runtime docs centered on active deterministic tagging plus optional pass5 codex-farm tagging lane.
- Keep pass5 artifact and provenance contract explicit (`*.tags.json`, `tagging_report.json`, `tags_index`, raw pass5 directories, validation counters).
- Keep module-level code map complete for all active `cookimport/tagging/*.py` modules plus nearby stage/settings wiring (`cookimport/cli.py`, `cookimport/config/run_settings.py`, `cookimport/entrypoint.py`).

Anti-loop rule:
- When `tags/` outputs are missing, audit gating/config (`llm_tags_pipeline`, `tag_catalog_json`, failure mode) before changing deterministic rule logic.
