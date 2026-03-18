You are deciding recipe-region membership for cookbook atomic lines.

TASK BOUNDARY
- Review one ordered slice of the book.
- `deterministic_label` is a weak hint only.
- Decide whether each line is part of an active recipe region.
- Do not invent a recipe region from an isolated title-like heading, chapter heading, blurb, testimonial, or front matter line.
- Never invent lines or labels.

Compact input legends:
- Label codes: {{LABEL_CODE_LEGEND}}
- Span codes: {{SPAN_CODE_LEGEND}}
- Treat the targets as one ordered contiguous slice of the book.
- `hint_codes` are compact deterministic heuristic tags, not final truth.

Region status meaning:
- `recipe`: clearly belongs to an active recipe region
- `outside_recipe`: clearly not part of a recipe region
- `boundary_uncertain`: ambiguous edge line near a possible recipe boundary

RETURN FORMAT (STRICT JSON ONLY)
Return exactly a JSON object shaped like:
{"rows":[{"atomic_index": <int>, "region_status": "recipe|outside_recipe|boundary_uncertain"}]}

Hard output rules:
1) Return each requested `atomic_index` exactly once.
2) Keep output order identical to input target order.
3) Each `region_status` must be `recipe`, `outside_recipe`, or `boundary_uncertain`.
4) No markdown, no commentary, no extra keys.

Target row format:
{{TARGET_ROW_FORMAT}}

Grounding windows:
{{LOCAL_CONTEXT_ROWS}}

Targets:
{{TARGETS_ROWS}}
