Run manifests live here.

`run_manifest.json` is the small cross-command index for a run folder.
`stage_observability.json` is the paired stage-topology record for the same run root.
For `stage` runs, `run_manifest.json` now indexes `stage_observability.json`, `run_summary.json`, and `run_summary.md`.
Eval/benchmark commands use the shared helpers here to build/write these run-level records consistently.
