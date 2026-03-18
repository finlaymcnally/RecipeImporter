Execute the recipe-region gate task exactly.

Return strict JSON with this exact shape:
{"rows":[{"atomic_index":123,"region_status":"boundary_uncertain"}]}

Rules:
- Output only JSON.
- Use only the keys `rows`, `atomic_index`, and `region_status`.
- Keep row order exactly as requested by the task file.
- Read the task file already placed in the worker folder at `{{INPUT_PATH}}`.
- Use only that task file as evidence.

Task file path:
{{INPUT_PATH}}
