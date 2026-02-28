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

2. `2026-02-27_19.44.41` docs pruning for relevance
- Removed stale sectioning/migration context that was only about README/log split mechanics.
- Removed retired-path references that are no longer needed to operate or debug tagging.
- Kept rollout and anti-loop notes for active tagging behavior (deterministic engine + optional pass5 codex-farm lane).

3. `2026-02-27_19.50.10` tagging docs parity audit (code coverage gap close)

Problem captured:
- `09-tagging_README.md` summarized only part of the live runtime surface.
- Several active modules/integration files were missing from docs (`db_read.py`, `render.py`, `eval.py`, `tagging/cli.py`, and nearby `cookimport/cli.py`, `cookimport/config/run_settings.py`, `cookimport/entrypoint.py` pass5 wiring).

Surprises/discoveries preserved:
- Stage tagging is strictly pass5-gated (`llm_tags_pipeline != off`); deterministic tagging is always present in standalone commands, but stage emits no `tags/` artifacts when the tags pipeline is off.
- Provider-level validation has more explicit drop reasons than prior docs captured (category not requested, unknown tag key, category mismatch, shortlist mismatch).
- Standalone `--llm` flows can run pass5 in temp directories, while stage persists raw pass5 IO + manifest under run output.

What shipped:
- Expanded `09-tagging_README.md` into a code-coverage map for every module under `cookimport/tagging/`.
- Added explicit section for nearby integration surfaces outside tagging package (`cookimport/cli.py`, `run_settings.py`, `entrypoint.py`).
- Documented `tag-recipes` subcommands (`debug-signals`, `suggest`, `apply`) and pass5 validation/report counters.

Anti-loop notes:
- When docs feel incomplete, inventory `cookimport/tagging/*.py` first, then reconcile stage wiring in `cookimport/cli.py` + `run_settings.py`.
- Missing `tags/` output during stage is usually config gating (`llm_tags_pipeline`, `tag_catalog_json`) before it is algorithm drift.

4. `2026-02-27_19.45.55` tagging docs cleanup current contract

Problem captured:
- Tagging docs still contained stale split/migration bookkeeping that no longer affected runtime behavior.

Durable decisions preserved:
- Keep rollout + anti-loop notes for active pass5 lane.
- Keep runtime wiring clarity for `tag-catalog`/`tag-recipes` command groups and stage pass integration.
- Remove retired planning/task-link noise that does not affect operation/debugging.

5. `2026-02-27_19.50.10` provenance note

Source understanding merged:
- `docs/understandings/2026-02-27_19.50.10-tagging-doc-code-coverage-map.md`

Current status:
- Its code-to-doc audit checklist is retained in this log and reflected in `09-tagging_README.md`.
