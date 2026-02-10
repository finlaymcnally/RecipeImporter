---
summary: "How guided freeform benchmark mode resolves gold exports and source files."
read_when:
  - Extending labelstudio benchmark UX or source/gold discovery logic
---

# Guided Benchmark Flow (Discovery)

- `cookimport labelstudio-benchmark` wraps three steps: select freeform gold export, generate pipeline prediction tasks for a source file, and run freeform evaluation in one command.
- Gold export discovery scans `data/output/**/exports/freeform_span_labels.jsonl`, sorted by newest first.
- Source-file inference first checks the gold run `manifest.json` (`source_file`), then falls back to the first gold row `source_file` field mapped into `data/input/<name>`.
- If inference fails, the command prompts for source selection from importable files (or custom path).
