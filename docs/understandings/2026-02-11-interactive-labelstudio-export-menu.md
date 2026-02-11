---
summary: "How the interactive CLI now routes Label Studio export runs."
read_when:
  - Extending C3imp/cookimport interactive Label Studio export prompts
  - Debugging missing Label Studio export options in interactive mode
---

# Interactive Label Studio Export Menu

- `_interactive_mode` now exposes `labelstudio_export` as a top-level action even when no importable source files are present.
- Export flow prompts for project name, export scope (`pipeline`, `canonical-blocks`, `freeform-spans`), and target output root (`data/golden` recommended, or `data/output`).
- It reuses `run_labelstudio_export(...)` and existing Label Studio credential resolution (`LABEL_STUDIO_URL`, `LABEL_STUDIO_API_KEY`, or prompt fallback).
