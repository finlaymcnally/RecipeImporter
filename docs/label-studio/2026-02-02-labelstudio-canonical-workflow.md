---
summary: "Notes on Label Studio canonical block workflow and resume behavior."
read_when:
  - When debugging labelstudio canonical-blocks imports/exports or resume behavior
---

- `cookimport/labelstudio/ingest.py` writes `label_studio_tasks.jsonl` plus `manifest.json`; resume reuses `task_scope` + `task_ids` and skips already-uploaded IDs.
- Canonical block tasks are keyed by `block_id = urn:cookimport:block:{source_hash}:{block_index}` with context stored in task `data`.
- Canonical exports create `canonical_block_labels.jsonl` and `canonical_gold_spans.jsonl` under `exports/` for evaluation.
