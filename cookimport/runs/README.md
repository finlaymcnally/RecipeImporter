Run manifests live here.

`run_manifest.json` is the small cross-command index for a run folder.
`stage_observability.json` is the paired stage-topology record for the same run root.
Knowledge stage roots can also carry `stage_status.json` to distinguish operator interruption fallout from genuinely missing wrap-up artifacts.
Knowledge stage roots now also carry `knowledge_stage_summary.json` as the compact packet/worker/follow-up summary view for operators and reviewers.
Recipe stage roots can carry `recipe_stage_summary.json` and line-role stage roots can carry `line_role_stage_summary.json`; `stage_observability.json` indexes those compact summaries back to the run root the same way it already indexes the knowledge summary.
For `stage` runs, `run_manifest.json` now indexes `stage_observability.json`, `run_summary.json`, and `run_summary.md`.
Eval/benchmark commands use the shared helpers here to build/write these run-level records consistently.
