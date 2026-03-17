Execute the line-role labeling task below exactly.

Return strict JSON with this exact shape:
{"rows":[{"atomic_index":123,"label":"INGREDIENT_LINE"}]}

Rules:
- Output only JSON.
- Use only the keys `rows`, `atomic_index`, and `label`.
- Keep row order exactly as requested by the task.

Task:
{{INPUT_TEXT}}
