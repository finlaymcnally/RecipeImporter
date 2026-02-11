---
summary: "How C3imp interactive Label Studio import routes task scope and related prompts."
read_when:
  - Extending C3imp interactive Label Studio import prompts
  - Debugging missing freeform/canonical options in interactive imports
---

# Interactive Label Studio Scope Routing

- The C3imp/cookimport interactive `Label Studio benchmark import` path now asks for `task_scope` first.
- Scope drives follow-up prompts:
  - `pipeline`: asks for `chunk_level` (`both`, `structural`, `atomic`).
  - `canonical-blocks`: asks for `context_window`.
  - `freeform-spans`: asks for `segment_blocks` and `segment_overlap`.
- The interactive flow passes these values directly into `run_labelstudio_import(...)` instead of hardcoding `task_scope="pipeline"`.
