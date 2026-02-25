---
summary: "Tagging architecture/build/fix-attempt log to avoid repeated dead ends and circular debugging."
read_when:
  - When you are going in multi-turn circles on tagging behavior or implementation
  - When the human says "we are going in circles on this"
  - When you need prior tagging architecture versions, build attempts, or failed fixes before trying another change
---

# Tagging Log

Read this if you are going in multi-turn circles on the program, or if the human says "we are going in circles on this."
This file tracks tagging architecture versions, builds, fix attempts, and prior dead ends so we do not repeat them.

## Split Baseline (2026-02-19)

- `docs/09-tagging/09-tagging_README.md` is the source-of-truth for current tagging behavior and runtime contracts.
- `docs/09-tagging/09-tagging_log.md` is the running history of attempts and anti-loop notes.
- No prior tagging-specific attempt ledger existed in this folder before this split.

## Preserved Baseline Snapshot From Pre-split README

Preserving the pre-split baseline here so context is not lost:

- Auto-tagging code location and CLI wiring:
  - `cookimport/tagging/` via `tag-catalog` and `tag-recipes`.
- Core modules:
  - `catalog.py`: catalog models/loaders and fingerprinting
  - `signals.py`: signal extraction from recipe drafts
  - `rules.py`: deterministic tagging rules
  - `policies.py`: category policy enforcement
  - `engine.py`: scoring and selection
  - `db_write.py`: idempotent DB apply path
  - `llm_second_pass.py`: optional second-pass LLM scaffolding
- Operational docs:
  - `cookimport/tagging/README.md`
  - historical `docs/plans/I4.1-Auto-tag.md` guidance is now merged into this log/README (original plan path retired)

## Attempt Ledger

1. `2026-02-19` README/log split
- Established the two-file pattern in this section:
  - README for current behavior.
  - log for architecture/build/fix-attempt history.

2. `2026-02-25_16.28.03` pass5 codex-farm tagging rollout (merged from `docs/tasks/add-tags.md`)

Problem captured:
- `--llm` path in tagging CLI existed but second-pass implementation was scaffold/no-op.
- Needed one auditable optional pass that could run in both standalone tagging and stage flows without changing deterministic defaults.

Surprises/discoveries preserved:
- `llm_second_pass.py` previously returned mock empties (`_check_provider_configured=False` path).
- Stage integration is cleaner as a run-level pass after `final drafts/...` are written; split and non-split runs already converge there.
- Historical `docs/plans/I4.1-Auto-tag.md` policy notes (catalog keys, precision-first, insert-only safety) stayed valid and were kept in merged docs.

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
  - `codex_farm_pipeline_pass5_tags`
  - `tag_catalog_json`
- Run-level manifest/artifact indexing for pass5 outputs.

Validation evidence preserved:
- Task recorded targeted slices as green (`45 passed, 2 warnings`) across:
  - tagging provider/orchestrator tests,
  - LLM pack asset tests,
  - run settings + CLI passthrough tests,
  - staging/pred-run manifest parity tests.

Anti-loop notes:
- Missing pass5 artifacts are usually gate/config/failure-mode issues, not deterministic rules-engine regressions.
- Do not route unknown LLM tag strings directly to DB apply paths; keep `new_tag_proposals` review-only.
- Do not fold pass5 behavior into recipe-pass pipelines while `llm_recipe_pipeline` remains policy-locked off.
