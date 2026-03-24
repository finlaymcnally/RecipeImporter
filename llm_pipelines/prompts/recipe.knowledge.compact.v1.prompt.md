Review non-recipe cookbook text. Review one owned non-recipe cookbook chunk and decide whether it contains durable cooking knowledge worth preserving.

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
- The owned chunk under `c[0]` is authoritative. Any `x.*` context is informational only.
- Return exactly one result row for that owned chunk.

Decision boundary:
- `knowledge` means durable cooking leverage: technique, cause-and-effect explanation, troubleshooting, substitution, storage/safety advice, conversion/reference material, sensory guidance, or other knowledge that improves future cooking decisions.
- `other` means memoir, scene-setting, praise blurbs, endorsements, publisher marketing, signup copy, decorative headings, table of contents, chapter menus, recipe indexes, or other non-reusable matter.
- Ask: would saving this materially improve a cook's future decisions, diagnosis, or technique?
- Ask: is this specific and non-obvious enough to earn storage in a cookbook knowledge base?
- Ask: does it explain cause, judgment, troubleshooting, ingredient behavior, sensory cues, durable technique, substitution, storage, or safety?
- If the text is technically true but low-value, too generic, or not worth preserving on its own, keep it as `other`.
- If the owned chunk mixes memoir, author/teacher praise, book framing, or scene-setting with a few useful cooking sentences, do not promote the whole chunk.
- In mixed chunks, keep the memoir/framing blocks `other`; only mark a block `knowledge` when that block itself stands on its own as reusable cooking guidance.
- If a short conceptual heading directly introduces useful explanatory blocks in the same owned chunk, keep that heading with the useful body instead of forcing it to `other` as decoration.
- Statements like "this book will make you a better cook", personal origin stories, why the author wrote the book, or praise for a teacher/book are still `other` even when nearby blocks mention cooking principles.
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
- Usually `other`: forewords/intros that praise the book, explain why the author wrote it, recount culinary biography, or promise the reader they will become a great cook.
- Usually `knowledge`: technique explanations, storage advice, substitution notes, conversion tables, troubleshooting bullets, temperature guidance, concise reference charts, and short definitional callouts with real cooking value.
- Usually `knowledge`: a short concept heading such as `How Salt Affects . . .` when the very next owned blocks contain grounded explanation that the heading directly introduces.
- Usually `other` even if true: broad food-history filler, generic ingredient praise, vague educational framing, or low-information statements such as obvious definitions with no real cooking leverage.
- Mixed example: if one block explains why salting early helps meat retain moisture but the surrounding blocks are memoir, praise, or "this book teaches principles" framing, keep only the narrow mechanism block as `knowledge` and keep the framing blocks `other`.

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
- `u=true` only when the owned chunk contains durable cooking knowledge worth keeping.
- `u=true` requires at least one `d[*].c="knowledge"` decision and at least one snippet in `s`.
- `u=false` means no durable cooking leverage worth preserving exists in that chunk.
- `u=false` requires every `d[*].c` to be `other` and requires `s=[]`.
- The input always contains exactly one owned chunk. When `c` is non-empty, `r` must therefore contain exactly one row for that chunk.
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
- return exactly one row for the owned chunk
