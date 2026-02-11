---
summary: "How Label Studio scope routing works across import/export/eval."
read_when:
  - Extending Label Studio task scopes
  - Debugging resume behavior across pipeline/canonical/freeform projects
---

# Label Studio Scope Routing (Discovery)

- `cookimport/labelstudio/ingest.py` is the single routing point for task generation. The task ID key must stay scope-specific (`chunk_id`, `block_id`, `segment_id`) because resume logic reads prior IDs from manifests and `label_studio_tasks.jsonl`.
- `cookimport/labelstudio/export.py` reads the latest run manifest when possible; mismatched `task_scope` vs `--export-scope` should fail early to avoid parsing project data with the wrong schema.
- `cookimport/cli.py` keeps one command surface (`labelstudio-import`, `labelstudio-export`, `labelstudio-eval`) and switches behavior by explicit scope values. This lets pipeline, canonical, and freeform workflows coexist without adding parallel commands.
