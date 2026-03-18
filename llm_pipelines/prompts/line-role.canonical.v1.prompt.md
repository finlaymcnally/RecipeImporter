Execute the line-role labeling task exactly.

Return strict JSON with this exact shape:
{"rows":[{"atomic_index":123,"label":"INGREDIENT_LINE"}]}

Task file shape:
{"v":1,"shard_id":"line-role-canonical-0001-a000123-a000456","rows":[[123,"L4","1 cup flour"]]}

Rules:
- Output only JSON.
- Use only the keys `rows`, `atomic_index`, and `label`.
- Keep row order exactly as requested by the task file.
- Treat the task file as one ordered contiguous slice of the book.
- The task file has one version marker `v`, one `shard_id`, and compact `rows` tuples.
- Each row is `[atomic_index, label_code, current_line]`.
- Label codes: {{LABEL_CODE_LEGEND}}.
- Use each row's tuple slot 2 (`current_line`) as the line to label.
- Use neighboring rows in `rows[*]` for local context when needed.
- Read the task file already placed in the worker folder at `{{INPUT_PATH}}`.
- Use only that task file as evidence.

Task file path:
{{INPUT_PATH}}
