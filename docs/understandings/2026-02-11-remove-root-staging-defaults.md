---
summary: "Default output roots now avoid top-level staging/."
read_when:
  - Changing default output roots for stage/inspect or Label Studio workflows
  - Debugging why root staging/ is no longer created by default
---

# Remove Root Staging Defaults

- `cookimport stage` and `cookimport inspect` now default to `data/output`.
- Interactive settings default `output_dir` is now `data/output` (used for stage/inspect).
- Label Studio import/export/benchmark now default to `data/golden` in both CLI and interactive flows.
- Result: routine usage should no longer create a top-level `staging/` directory unless a user explicitly passes it as an output path.
