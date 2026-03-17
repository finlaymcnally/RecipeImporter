Extract reusable cooking knowledge from non-recipe cookbook text.

Read the input JSON file at `{{INPUT_PATH}}`.

Rules:
- Use only the JSON file at `{{INPUT_PATH}}`.
- Only `chunks[*].blocks` may supply evidence.
- `context.*` is local hint only; never cite it.
- `guardrails.context_recipe_block_indices` marks nearby recipe context. Do not let recipe content leak into outside-recipe decisions.
- `chunks[*].heuristics` are hints only.
- If `table_hint` exists, use it only for structure; quotes must still come from block text.
- Return one result per input chunk.

Meaning:
- `knowledge` = reusable technique, definition, substitution, do/don't guidance, or durable cooking reference.
- `other` = narrative, memoir, scene-setting, blurb, front/back matter, decorative heading, or non-reusable prose.

Short output keys:
- top level: `v`, `bid`, `r`
- per result: `cid`, `u`, `d`, `s`
- decision: `i`, `c`
- snippet: `t`, `b`, `g`, `e`
- evidence: `i`, `q`

Per chunk:
- `u=false` and `s=[]` if no reusable knowledge exists.
- `d` must include every block in order.
- `c` must be `knowledge` or `other`.
- snippets must stay self-contained and chunk-local.
- every snippet needs at least one evidence quote from that same chunk.

Strict:
- return JSON only
- no extra keys
- `v` must be `"2"`
- `bid` must echo input `bundle_id`
- each `cid` must echo input `chunk_id`
