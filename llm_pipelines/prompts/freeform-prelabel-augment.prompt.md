You are labeling cookbook text BLOCKS for an additive annotation pass.
Return STRICT JSON only.
Output format exactly:
[{"block_index": <int>, "label": "<LABEL>"}]
Mode: augment existing annotations.
Only return blocks that should receive a NEW additional label.
Do not return labels that already exist on a block.
Allowed labels: {{ALLOWED_LABELS}}.
Only add labels from: {{ADD_LABELS}}.
Segment id: {{SEGMENT_ID}}
Existing labels per block:
{{EXISTING_LABELS_PER_BLOCK}}
Blocks:
{{BLOCKS_JSON_LINES}}
