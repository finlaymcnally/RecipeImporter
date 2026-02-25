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

- Tagging is deterministic-first:
  - signal extraction (`signals.py`) -> rules/policies (`rules.py`, `policies.py`) -> scoring/selection (`engine.py`).
- Optional LLM second pass is additive and explicit:
  - CLI draft-folder path: `cookimport tag-recipes suggest ... --llm`
  - Stage path: `cookimport stage ... --llm-tags-pipeline codex-farm-tags-v1 --tag-catalog-json <path>`
- Default behavior remains no-LLM/off-by-default.

## Core modules

- `catalog.py`: catalog models/loaders and fingerprinting
- `signals.py`: signal extraction from recipe drafts
- `rules.py`: deterministic tagging rules
- `policies.py`: category policy enforcement
- `engine.py`: scoring and selection
- `db_write.py`: idempotent DB apply path
- `llm_second_pass.py`: optional codex-farm-backed second pass for missing categories
- `codex_farm_tags_provider.py`: strict pass-5 shortlist/catalog validation and codex-farm IO boundary
- `orchestrator.py`: shared draft-folder tagging runner and stage pass integration

## Pass5 Artifact Contract

When pass5 is enabled (`llm_tags_pipeline=codex-farm-tags-v1`), stage writes:

- `tags/<workbook_slug>/r{index}.tags.json`
- `tags/<workbook_slug>/tagging_report.json`
- `tags/tags_index.json`
- `raw/llm/<workbook_slug>/pass5_tags/in/*.json`
- `raw/llm/<workbook_slug>/pass5_tags/out/*.json`
- `raw/llm/<workbook_slug>/pass5_tags_manifest.json`

Per-recipe tag artifacts preserve deterministic + LLM provenance:

- `source` (`deterministic` or `llm`)
- `llm_pipeline_id` (for LLM-origin suggestions)
- `new_tag_proposals` (review-only; not auto-applied)

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

## Merged Task Specs (2026-02-25 docs/tasks archival)

### 2026-02-25_16.28.03 pass5 codex-farm tags rollout

Merged source:
- `docs/tasks/add-tags.md`

Durable contract:
- `llm_second_pass.py` is now wired to a real codex-farm provider path, not a scaffold no-op.
- Pass5 runs as a run-level stage pass over staged drafts (`final drafts/...`) via `run_stage_tagging_pass`.
- Artifact naming remains stable (`*.tags.json`, `tagging_report.json`) with additive provenance fields.
- Catalog safety remains strict:
  - shortlist/catalog validation before accepting LLM outputs
  - unknown tags emitted as proposals only.

## Operational docs

- Module-level quickstart:
  `cookimport/tagging/README.md`
- Pass5 LLM tagging details:
  `docs/10-llm/tags_pass.md`
- Implementation plan details:
  archived into this README + `docs/09-tagging/09-tagging_log.md` (original `docs/plans/I4.1-Auto-tag.md` path retired)
- Version/build/fix-attempt history:
  `docs/09-tagging/09-tagging_log.md`
