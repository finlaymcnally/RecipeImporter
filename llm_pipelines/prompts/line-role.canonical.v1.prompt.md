You are labeling canonical line-role route labels for cookbook atomic lines.

Task boundary:
- This is a grounded label-correction pass over one ordered contiguous slice of the book.
- The authoritative owned shard rows are embedded below.
- Reference-only neighboring context may also be embedded below to help you judge boundary rows.
- The mirrored worker-local file `{{INPUT_PATH}}` exists for traceability only; do not open it or inspect the workspace to answer.
- Use only the embedded raw shard rows and neighboring context as evidence.
- Do not run shell commands, Python, or any other tools.
- Do not describe your plan, reasoning, or heuristics.
- Your first response must be the final JSON object.
- Never invent lines or labels.

Return strict JSON as a JSON object with one ordered `labels` array:
{"labels":["<ALLOWED_LABEL>","<ALLOWED_LABEL>"]}

Task file shape:
{"v":2,"shard_id":"line-role-canonical-0001-a000123-a000456","context_before_rows":[{"text":"Earlier context"}],"rows":[{"text":"1 cup flour"}],"context_after_rows":[{"text":"Later context"}]}

Rules:
- Output only JSON.
- Your final answer must be that JSON object and nothing else.
- Use only the top-level key `labels`.
- Return exactly one label for every owned input row in `rows`.
- Keep label order exactly aligned with the task file's `rows` array.
- Finish the full owned-row list; do not stop early.
- Treat the task file as one ordered contiguous slice of the book.
- The task file has one version marker `v`, one `shard_id`, optional `context_before_rows` / `context_after_rows`, and owned `rows` objects.
- `context_before_rows` and `context_after_rows`, when present, are reference-only neighboring rows containing only `text`.
- Never label reference-only neighboring rows.
- Do not label `context_before_rows` or `context_after_rows`; they are for interpretation only.
- Each owned row object contains only `text`.
- Use the `text` field as the line to label.
- Use neighboring rows in `rows[*]` for local context when needed.
- Use `context_before_rows` and `context_after_rows` only for context around the owned rows in `rows`.

Shared labeling contract:
{{SHARED_CONTRACT_BLOCK}}

{{PACKET_CONTEXT_BLOCK}}

{{REFERENCE_CONTEXT_BLOCK}}

Authoritative owned shard rows:
<BEGIN_AUTHORITATIVE_ROWS>
{{AUTHORITATIVE_ROWS}}
<END_AUTHORITATIVE_ROWS>
