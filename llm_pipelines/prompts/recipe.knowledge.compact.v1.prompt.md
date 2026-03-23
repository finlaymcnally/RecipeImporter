Review non-recipe cookbook text and decide which chunks contain durable cooking knowledge worth preserving.

You are a skeptical reviewer. The raw chunk text is authoritative. Only mechanically true structure is provided.

Task input:
- The authoritative shard JSON is included inline below.
- The task JSON appears between `<BEGIN_INPUT_JSON>` and `<END_INPUT_JSON>`.
- Use only that inline JSON payload.
- Use only the inline JSON payload below.
- Do not run shell commands, Python, or any other tools.

Evidence rules:
- Only `c[*].b[*].t` may supply evidence quotes.
- `x.*` is local context only; never cite it.
- `g.r` marks nearby recipe blocks. Do not let recipe content leak into outside-recipe decisions.
- If a block has `th`, use it only as structural context; quotes must still come from block text.
- Return one result per input chunk.

Decision boundary:
- `knowledge` means durable cooking leverage: technique, cause-and-effect explanation, troubleshooting, substitution, storage/safety advice, conversion/reference material, sensory guidance, or other knowledge that improves future cooking decisions.
- `other` means memoir, scene-setting, praise blurbs, endorsements, publisher marketing, signup copy, decorative headings, table of contents, chapter menus, recipe indexes, or other non-reusable matter.
- Ask: would saving this materially improve a cook's future decisions, diagnosis, or technique?
- Ask: is this specific and non-obvious enough to earn storage in a cookbook knowledge base?
- Ask: does it explain cause, judgment, troubleshooting, ingredient behavior, sensory cues, durable technique, substitution, storage, or safety?
- If the text is technically true but low-value, too generic, or not worth preserving on its own, keep it as `other`.
- Be especially skeptical of chunks that mostly look like headings, menus, title lists, front matter, or back matter.
- A chunk can still be `knowledge` if it is concise. Tables, charts, and short technical reference entries are valid when the text is genuinely useful.
- Borderline positive examples that still count as `knowledge` when grounded in the chunk text:
  - a short smoke-point table
  - a concise substitution chart
  - a one-block storage or food-safety rule
  - a glossary-style ingredient or technique definition
  - a troubleshooting bullet such as how to prevent curdling, sticking, or overcooking

Repo-specific examples:
- Usually `other`: `PREFACE`, `Contents`, `Recipes and Recommendations`, praise blurbs, author credits, publisher signup text.
- Usually `knowledge`: technique explanations, storage advice, substitution notes, conversion tables, troubleshooting bullets, temperature guidance, concise reference charts, and short definitional callouts with real cooking value.
- Usually `other` even if true: broad food-history filler, generic ingredient praise, vague educational framing, or low-information statements such as obvious definitions with no real cooking leverage.

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
- snippet: `b`, `e`
- evidence: `i`, `q`

Input keys:
- top level: `v` bundle version, `bid` bundle id, `c` chunks, optional `x` context, optional `g` guardrails
- per chunk: `cid` chunk id, `b` blocks
- per block: `i` block index, `t` text, optional `hl` heading level, optional `th` compact table hint
- block table hint: `id` table id, optional `c` caption, optional `r` row index
- context: optional `p` previous blocks, optional `n` next blocks
- guardrails: optional `r` nearby recipe block indices

Per chunk result:
- `u=true` only when the chunk contains durable cooking knowledge worth keeping.
- `u=true` requires at least one `d[*].c="knowledge"` decision and at least one snippet in `s`.
- `u=false` means no durable cooking leverage worth preserving exists in that chunk.
- `u=false` requires every `d[*].c` to be `other` and requires `s=[]`.
- When `c` is non-empty, `r` must contain exactly one row per input chunk, in input order.
- `d` must include every block in order.
- `c` must be `knowledge` or `other`.
- `rc` should explain the coarse reviewer reason. If `c=knowledge`, then `rc` must be `knowledge`.
- snippets must stay self-contained and chunk-local.
- every snippet needs at least one evidence quote from that same chunk.
- Do not return `r: []` when `c` is non-empty.
- Never invent synthetic `cid` values such as `processing_error`.
- Do not collapse a clearly useful technique/reference shard into blanket `u=false`.
- If the shard contains durable cooking leverage, surface it positively with `u=true`, `knowledge` decisions, and grounded snippets.

Strict:
- return JSON only
- final answer must be that JSON object only
- return compact minified JSON on a single line
- do not insert blank lines, indentation, or padding whitespace
- no extra keys
- `v` must be `"2"`
- `bid` must echo input `bid`
- each `cid` must echo input `cid`
- count input chunks and return exactly that many rows
