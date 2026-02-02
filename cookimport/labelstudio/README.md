Label Studio benchmark mode helpers.

- `ingest.py` builds a full extracted text archive and uploads either chunk tasks (pipeline) or block tasks (canonical).
- `label_config_blocks.py` defines the block-classification labeling UI.
- `block_tasks.py` generates canonical block tasks with stable block IDs and context windows.
- `export.py` pulls annotations back and converts them into JSONL (pipeline tip eval + canonical block labels).
- `eval_canonical.py` compares pipeline structural chunks to canonical gold spans.
