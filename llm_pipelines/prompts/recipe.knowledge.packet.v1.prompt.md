Review one ordered packet of review-eligible non-recipe cookbook text. Decide which owned blocks are durable cooking knowledge, then group the kept knowledge blocks into one or more related ideas.

You are a skeptical reviewer. The raw packet block text is authoritative. Only mechanically true structure is provided.

Task input:
- The authoritative packet JSON is included inline below.
- The task JSON appears between `<BEGIN_INPUT_JSON>` and `<END_INPUT_JSON>`.
- Use only that inline JSON payload.
- Do not run shell commands, Python, or any other tools.

Evidence rules:
- Only `b[*].t` may supply evidence quotes.
- `x.*` is nearby context only; never cite it.
- `g.r` marks nearby recipe blocks. Do not let recipe content leak into outside-recipe decisions.
- If a block has `th`, use it only as structural context; quotes must still come from block text.
- Block order is preserved, but packet adjacency is not semantic proof. Large `b[*].i` jumps or obvious topic shifts often mean unrelated source regions were packed together.
- Classify each owned block on its own merits. Use nearby blocks only as weak context, and weaken grouping assumptions across large index jumps or abrupt topic changes.
- Do the keep/drop judgment block by block before you think about idea groups.
- Do not let one useful block launder nearby memoir, framing, decorative-heading, or navigation blocks into `knowledge`.

Decision boundary:
- `knowledge` means durable cooking leverage: technique, cause-and-effect explanation, troubleshooting, substitution, storage/safety advice, conversion/reference material, sensory guidance, or other knowledge that improves future cooking decisions.
- `other` means memoir, scene-setting, praise blurbs, endorsements, publisher marketing, signup copy, decorative headings, table of contents, chapter menus, recipe indexes, or other non-reusable matter.
- Ask: would saving this materially improve a cook's future decisions, diagnosis, or technique?
- Ask: is this specific and non-obvious enough to earn storage in a cookbook knowledge base?
- Ask: does it explain cause, judgment, troubleshooting, ingredient behavior, sensory cues, durable technique, substitution, storage, or safety?
- If the text is technically true but low-value, too generic, or not worth preserving on its own, keep it as `other`.
- In mixed packets, keep memoir/framing blocks `other`; only mark a block `knowledge` when that block itself stands on its own as reusable cooking guidance.
- If only one block in a mixed packet is genuinely reusable, keep only that block and leave the surrounding framing `other`.
- If a short conceptual heading directly introduces useful explanatory blocks in the same packet, keep that heading with the useful body instead of forcing it to `other`.
- Do not treat two blocks as one idea just because they are adjacent in the packet; they still need clear topical continuity in the text itself.

Grouping rules:
- After block decisions, create `idea_groups` only from the blocks you marked `knowledge`.
- One packet may yield zero, one, or several idea groups.
- Each idea group should represent one related idea a human would actually want to save together.
- Every `knowledge` block must belong to exactly one idea group.
- No `other` block may appear in an idea group.
- Keep block indices in packet order.
- Give each idea group a short, plain-English topic label.
- Every idea group must include at least one grounded snippet with evidence.
- When there is a large block-index jump or a clear subject change, prefer separate idea groups unless the text itself clearly ties the blocks together.

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
- top level: `v`, `bid`, `d`, `g`
- decision: `i`, `c`, `rc`
- idea group: `gid`, `l`, `bi`, `s`
- snippet: `b`, `e`
- evidence: `i`, `q`

Input keys:
- top level: `v` packet version, `bid` packet id, `b` owned packet blocks, optional `x` context, optional `g` guardrails
- per block: `i` block index, `t` text, optional `hl` heading level, optional `th` compact table hint
- block table hint: `id` table id, optional `c` caption, optional `r` row index
- context: optional `p` previous blocks, optional `n` next blocks
- guardrails: optional `r` nearby recipe block indices

Packet result:
- `d` must include every owned block exactly once and in order.
- `c` must be `knowledge` or `other`.
- `rc` should explain the coarse reviewer reason. If `c=knowledge`, then `rc` must be `knowledge`.
- `g` may be empty only when every block is `other`.
- Every `knowledge` block must appear in exactly one `g[*].bi`.
- Every `g[*].s[*]` needs at least one evidence quote from owned packet blocks.
- Do not invent block indices, group ids, or evidence quotes.
- Keep snippets short and paraphrased; do not echo whole blocks or long evidence surfaces verbatim.

Strict:
- return JSON only
- final answer must be that JSON object only
- return compact minified JSON on a single line
- do not insert blank lines, indentation, or padding whitespace
- no extra keys
- `v` must be `"3"`
- `bid` must echo input `bid`
