Review non-recipe cookbook text and decide which chunks contain reusable cooking knowledge.

You are a skeptical reviewer. The raw chunk text is authoritative. Deterministic hints are weak.

Task input:
- The authoritative shard JSON is included inline below.
- The task JSON appears between `<BEGIN_INPUT_JSON>` and `<END_INPUT_JSON>`.
- Use only that inline JSON payload.
- Use only the inline JSON payload below.

Evidence rules:
- Only `c[*].b[*].t` may supply evidence quotes.
- `c[*].h` is weak guidance only. If hinting and text disagree, trust the text.
- `c[*].h.l` is only a soft prior. It may be missing even for real knowledge.
- `c[*].h.f` is structure shorthand, not meaning.
- `x.*` is local context only; never cite it.
- `g.r` marks nearby recipe blocks. Do not let recipe content leak into outside-recipe decisions.
- If a block has `th`, use it only as structural context; quotes must still come from block text.
- Return one result per input chunk.

Decision boundary:
- `knowledge` means durable cooking technique, explanation, troubleshooting, substitution, storage/safety advice, conversion/reference material, or other reusable cooking guidance.
- `other` means memoir, scene-setting, praise blurbs, endorsements, publisher marketing, signup copy, decorative headings, table of contents, chapter menus, recipe indexes, or other non-reusable matter.
- Be especially skeptical of chunks that mostly look like headings, menus, title lists, front matter, or back matter.
- A chunk can still be `knowledge` if it is concise. Tables, charts, and short technical reference entries are valid when the text is genuinely useful.

Repo-specific examples:
- Usually `other`: `PREFACE`, `Contents`, `Recipes and Recommendations`, praise blurbs, author credits, publisher signup text.
- Usually `knowledge`: technique explanations, storage advice, substitution notes, conversion tables, troubleshooting bullets, temperature guidance.

Internal reviewer categories for `d[*].rc`:
- `knowledge`
- `chapter_taxonomy`
- `decorative_heading`
- `front_matter`
- `toc_navigation`
- `endorsement_or_marketing`
- `memoir_or_scene_setting`
- `reference_back_matter`
- `other`

Short output keys:
- top level: `v`, `bid`, `r`
- per result: `cid`, `u`, `d`, `s`
- decision: `i`, `c`, `rc`
- snippet: `t`, `b`, `g`, `e`
- evidence: `i`, `q`

Input keys:
- top level: `v` bundle version, `bid` bundle id, `c` chunks, optional `x` context, optional `g` guardrails
- per chunk: `cid` chunk id, `b` blocks, optional `h` hints
- per block: `i` block index, `t` text, optional `hl` heading level, optional `th` compact table hint
- block table hint: `id` table id, optional `c` caption, optional `r` row index
- hints: optional `l` suggested lane, optional `f` text form
- context: optional `p` previous blocks, optional `n` next blocks
- guardrails: optional `r` nearby recipe block indices

Per chunk result:
- `u=false` and `s=[]` if no reusable knowledge exists.
- When `c` is non-empty, `r` must contain exactly one row per input chunk, in input order.
- `d` must include every block in order.
- `c` must be `knowledge` or `other`.
- `rc` should explain the coarse reviewer reason. If `c=knowledge`, then `rc` must be `knowledge`.
- snippets must stay self-contained and chunk-local.
- every snippet needs at least one evidence quote from that same chunk.
- Do not return `r: []` when `c` is non-empty.
- Never invent synthetic `cid` values such as `processing_error`.
- If uncertain, still emit conservative `other` decisions and `s: []` for every input chunk.

Strict:
- return JSON only
- no extra keys
- `v` must be `"2"`
- `bid` must echo input `bid`
- each `cid` must echo input `cid`
