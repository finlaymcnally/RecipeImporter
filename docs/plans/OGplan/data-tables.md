# Import cookbook tables as first-class knowledge artifacts

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan must be maintained in accordance with `docs/PLANS.md` (repository root).

## Purpose / Big Picture

Many “textbook-style” cookbooks contain high-value cooking knowledge in tables (conversion charts, doneness temps, sauce ratios, substitution matrices, pantry storage times, etc.). Today those tables are usually flattened into awkward text blocks during PDF/EPUB extraction, which makes them hard to search, hard to embed into a knowledge system, and easy for Stage 7 non-recipe knowledge review to miss or misinterpret.

After this change, a user can run:

    cookimport stage <cookbook.pdf|cookbook.epub> --table-extraction on --llm-knowledge-pipeline codex-farm-knowledge-v1

…and they will get, in addition to existing outputs:

- A deterministic, structured table export for the book (JSONL + human-readable markdown) under the run output.
- Table-aware chunking behavior that keeps table rows together (so “knowledge chunks” don’t split a table mid-way).
- Optional: Stage 7 non-recipe knowledge review gets “table structure hints” so it can extract reusable snippets grounded in table rows while still quoting verbatim evidence from the original text.

The “see it working” proof is: you can open `data/output/<timestamp>/tables/<workbook_slug>/tables.md` and visually see the tables preserved, and you can open `tables.jsonl` and ingest row-level text into your own “knowledge” index (vector DB, full-text search, etc.). If you enable pass4, you should also see snippets derived from table facts in `knowledge/<workbook_slug>/snippets.jsonl`.

## Progress

- [x] (2026-02-25 00:00Z) Drafted initial ExecPlan describing table extraction + table outputs + Stage 7 integration.
- [ ] Implement deterministic table extraction over non-recipe block streams (grouping row-like consecutive blocks into tables).
- [ ] Add table artifacts writer (`tables.jsonl`, `tables.md`) and wire into stage output.
- [ ] Make chunking “table-aware” so tables are not split across chunks and are classified as `knowledge` lane by default.
- [ ] Extend Stage 7 knowledge bundle inputs with optional table-structure hints and update the prompt to use them safely.
- [ ] Add tests (unit + small integration) and update docs (`docs/04-parsing`, `docs/05-staging`, `docs/10-llm/nonrecipe_knowledge_review.md`) to describe table behavior and outputs.
- [ ] Validate end-to-end on at least one PDF and one EPUB containing a table; capture evidence snippets in `Artifacts and Notes`.

## Surprises & Discoveries

- Observation: (placeholder)
  Evidence: (placeholder)

## Decision Log

- Decision: Treat “table importing for knowledge” as a deterministic extraction + export problem first, and only then as an optional LLM summarization problem.
  Rationale: Users can ingest deterministic structured tables into their own knowledge tooling even when LLMs are disabled; Stage 7 should be additive, not the only path.
  Date/Author: 2026-02-25 / GPT-5.2 Pro

- Decision: Preserve verbatim extracted text for evidence quotes; provide table structure as *hints* rather than rewriting block text.
  Rationale: Stage 7 requires verbatim quotes from `chunk.blocks[*].text` as evidence; rewriting would break “verbatim excerpt” semantics.
  Date/Author: 2026-02-25 / GPT-5.2 Pro

## Outcomes & Retrospective

- (Not implemented yet.) At completion, summarize: table extraction quality, false positive rate, what kinds of tables still fail (merged cells, multi-line cells), and how the outputs improved Stage 7 snippet recall.

## Context and Orientation

This repository is a deterministic cookbook import pipeline (`cookimport`) that stages artifacts under `data/output/<timestamp>/`.

Key concepts (plain language):

- A “block” is one extracted piece of text (often a paragraph, a heading, a list item, or a line) produced by an importer. Block-first importers (PDF/EPUB) produce a stream of blocks, which is written as a raw artifact (`raw/.../full_text.json`) and also used for downstream parsing.
- “Non-recipe blocks” are blocks the importer/segmenter believes are *not* part of a recipe. These blocks feed “knowledge chunking”.
- A “chunk” is a grouped sequence of non-recipe blocks that is meant to be a coherent unit of general cooking knowledge. Chunking is implemented in `cookimport/parsing/chunks.py` (`process_blocks_to_chunks`) and assigns each chunk a “lane” (currently `knowledge` or `noise`).
- “Stage 7 non-recipe knowledge review” is an optional codex-farm pipeline (`llm_knowledge_pipeline=codex-farm-knowledge-v1`) that reads chunk bundles and emits reusable knowledge snippets into `knowledge/<workbook_slug>/snippets.jsonl` and `knowledge.md`. Prompt: `llm_pipelines/prompts/recipe.knowledge.v1.prompt.md`.

Relevant files for this plan:

- Import and staging orchestration:
  - `cookimport/cli.py`
  - `cookimport/cli_worker.py` (`stage_one_file`)
- Importers (block-first sources):
  - `cookimport/plugins/pdf.py`
  - `cookimport/plugins/epub.py`
- Parsing and chunking:
  - `cookimport/parsing/chunks.py`
  - `cookimport/parsing/signals.py`
  - `cookimport/parsing/block_roles.py`
- Staging writers and output layout:
  - `cookimport/staging/writer.py`
  - Docs reference: `docs/05-staging/05-staging_readme.md`
- Stage 7 non-recipe knowledge review:
  - Docs: `docs/10-llm/nonrecipe_knowledge_review.md`
  - Prompt: `llm_pipelines/prompts/recipe.knowledge.v1.prompt.md`
  - Orchestration likely in `cookimport/llm/` (see `docs/10-llm/10-llm_README.md`)

Current problem in concrete terms:

- Tables in PDFs/EPUBs usually appear as:
  - One big block with many lines and spacing, or
  - Many consecutive blocks, each representing one “row-like” line after EPUB postprocessing splits multi-line blocks.
- Chunking and pass4 treat these as generic narrative/noise. Structure is lost, and extracting reusable facts becomes unreliable.

## Plan of Work

### Milestone 1: Define a minimal “ExtractedTable” model and table detection over block streams

Create a new parsing module that can detect and reconstruct tables from an ordered list of non-recipe blocks, without depending on importer-specific geometry (so it works for both PDF and EPUB extraction outputs).

The core behavior:

- Scan the non-recipe block sequence in order.
- Identify “row-like” blocks: lines that contain multiple columns separated by either:
  - Markdown pipes (`|`), or
  - Repeated whitespace gaps (e.g., 2+ spaces), or
  - Tab characters.
- Group consecutive row-like blocks into a “table run” if:
  - The column count is consistent across the run (allowing minor variance for 1–2 rows if we can normalize), and
  - The run length meets a minimum (default: 3 rows; 2 rows allowed if one is a header divider like `---|---`).
- Produce an `ExtractedTable` object that captures:
  - `table_id` (stable within the run; derived from file hash + starting block index)
  - `start_block_index`, `end_block_index` (absolute indices in the full stream if available; otherwise relative indices plus provenance)
  - `caption` (best-effort: nearest preceding heading-like block within N blocks)
  - `headers` (optional; inferred from markdown divider row or simple heuristics)
  - `rows` (list of row cell arrays)
  - Renderings:
    - `markdown` (normalized markdown table)
    - `row_texts` (deterministic row-level “facts” strings for embedding/search, like `Header1: v1 | Header2: v2`)
  - Confidence and parsing notes (so downstream can choose to ignore low-confidence tables)

This milestone should include unit tests that feed a synthetic list of blocks (just dicts or minimal Block objects) and verify table extraction, header inference, and row_text rendering.

### Milestone 2: Thread table extraction through stage flow and persist table artifacts

Add a new run setting / CLI flag:

- `--table-extraction off|on` (default: `off` to avoid changing behavior for existing users/runs)

When enabled:

- After importer conversion and before chunk writing, run table extraction over the non-recipe block list.
- Attach table metadata back onto blocks (non-destructively) so chunking can respect table boundaries.
- Write deterministic table artifacts under the run output, per workbook slug.

Proposed output layout (new):

- `data/output/<timestamp>/tables/<workbook_slug>/tables.jsonl`
  - One JSON object per table (`ExtractedTable` serialized).
- `data/output/<timestamp>/tables/<workbook_slug>/tables.md`
  - Human-friendly summary with captions and markdown-rendered tables.

These artifacts are meant to be the “knowledge import substrate”: you can ingest the JSONL row_texts directly into whatever knowledge search/index you have.

### Milestone 3: Make chunking table-aware (keep tables intact, keep them in knowledge lane)

Update chunking so table content is not accidentally split and not misclassified as noise.

Concretely:

- In `cookimport/parsing/chunks.py`, in the steps that decide chunk boundaries and perform max-char splitting:
  - Treat a detected table run as an “atomic segment”: if a chunk is being split, do not split inside `table_id` runs; instead move the split boundary to before the table or after the table.
- In lane assignment:
  - If a chunk contains any block marked with `table_id`, bias strongly toward `ChunkLane.knowledge` (unless there are explicit “stop headings” / index/credits filters that already drop the chunk).
- In highlight extraction:
  - Leave behavior unchanged initially; tables often have no “tip-like” highlight spans, and that is acceptable. (A future improvement could add a small table-specific highlight rule, but keep this milestone minimal and safe.)

Add focused tests in `tests/test_chunks.py` or a new test file to prove:
- A table run is not split across two chunks.
- A chunk containing a table run is assigned `knowledge` lane.

### Milestone 4: Optional Stage 7 integration: provide table-structure hints to the LLM prompt safely

The Stage 7 knowledge-review prompt (`llm_pipelines/prompts/recipe.knowledge.v1.prompt.md`) currently instructs the model to extract only from `chunk.blocks` and to quote verbatim excerpts from `chunk.blocks[*].text`.

We want to help the model interpret tables without violating the evidence contract.

Approach:

- Extend the pass4 bundle JSON writer (wherever the “pass4 knowledge input files” are staged under `raw/llm/<workbook_slug>/pass4_knowledge/in/`) to include, for each block in `chunk.blocks`, an optional `table_hint` field when that block is part of a detected table:
  - For example:
    - `table_hint.table_id`
    - `table_hint.caption`
    - `table_hint.markdown` (normalized table)
    - `table_hint.row_index_in_table` (if the block corresponds to a row)
- Do NOT modify `block.text`; keep it verbatim extracted text so evidence quotes remain truthful.

Update `llm_pipelines/prompts/recipe.knowledge.v1.prompt.md` by adding a narrow rule, such as:

- “If a block contains `table_hint`, you may use it to understand table structure, but your evidence quotes must still be verbatim excerpts from `chunk.blocks[*].text`.”

This keeps the grounding model the same but improves table comprehension.

Add/extend tests around pipeline pack assets if needed (there are tests named in docs: `tests/test_llm_pipeline_pack.py`, `tests/test_llm_pipeline_pack_assets.py`). Add a unit test for the Stage 7 input bundle builder asserting `table_hint` appears when table extraction is on.

### Milestone 5: Documentation and UX polishing

Update docs to make the feature discoverable and to keep “source of truth” aligned:

- `docs/04-parsing/04-parsing_readme.md`
  - Add a short subsection under Knowledge Chunking describing table detection, table_id markers, and chunking behavior.
- `docs/05-staging/05-staging_readme.md`
  - Add the new `tables/<workbook_slug>/tables.jsonl` + `tables.md` outputs to the output layout list (and note they are gated by `--table-extraction on`).
- `docs/10-llm/nonrecipe_knowledge_review.md`
  - Mention that enabling `--table-extraction on` is recommended for table-heavy sources, because it improves Stage 7 extraction and provides deterministic table artifacts.

## Concrete Steps

All commands below assume repository root as the working directory.

1) Read the relevant source to orient before coding:

    - docs/PLANS.md
    - docs/04-parsing/04-parsing_readme.md (Knowledge Chunking section)
    - docs/05-staging/05-staging_readme.md (output layout and writer functions)
    - docs/10-llm/nonrecipe_knowledge_review.md
    - llm_pipelines/prompts/recipe.knowledge.v1.prompt.md
    - cookimport/parsing/chunks.py
    - cookimport/staging/writer.py
    - cookimport/cli_worker.py (stage_one_file)

2) Add a new parsing module for tables:

    - Create: cookimport/parsing/tables.py
    - Implement:
      - ExtractedTable (pydantic model or dataclass; follow existing project patterns)
      - detect_tables_from_blocks(blocks: list[Block]) -> tuple[list[ExtractedTable], list[BlockTableMarker]]
      - render_table_markdown(table) -> str
      - render_table_row_texts(table) -> list[str]

    Keep it deterministic, pure (easy to test), and dependency-light.

3) Add tests for table parsing:

    - Create: tests/test_tables.py
    - Add fixtures:
      - markdown table case
      - whitespace column table case
      - false positive guard: narrative paragraph with extra spaces should not become a table
      - multi-block table run grouping case

    Run:

      source .venv/bin/activate
      pytest -q

4) Add a run setting and CLI flag:

    - Find RunSettings definition (likely in cookimport/core or cli config).
    - Add: table_extraction: Literal["off","on"] (default "off")
    - Wire CLI:
      - In cookimport/cli.py stage command options: add --table-extraction [off|on]
      - Ensure it is persisted into report.runConfig and any manifests, consistent with other run-config knobs.

    Validate the flag is visible:

      cookimport stage --help | sed -n '1,200p'

    (The exact pager/grep is optional; the goal is to confirm the flag exists.)

5) Wire table extraction into stage flow (non-split and merged-split):

    In cookimport/cli_worker.py stage_one_file (and in the split-merge path in cookimport/cli.py if chunking/writing happens there):

    - When table_extraction == "on":
      - Run detect_tables_from_blocks on the non-recipe blocks that are used for chunking.
      - Store the resulting extracted tables on the ConversionResult (if there is a good place) or in a parallel variable that is passed to writer.
      - Annotate blocks with minimal markers (table_id, role) if Block supports extension; if Block is strict, add an optional field to the Block model.

    Do not change behavior when table_extraction == "off".

6) Add writer support for table artifacts:

    In cookimport/staging/writer.py:

    - Add a new function:
      - write_table_outputs(run_out_dir: Path, workbook_slug: str, tables: list[ExtractedTable]) -> None

    It should create:

      data/output/<timestamp>/tables/<workbook_slug>/tables.jsonl
      data/output/<timestamp>/tables/<workbook_slug>/tables.md

    Make the markdown summary compact and readable:
    - Heading per table: caption or “Table <n>”
    - Then the markdown-rendered table
    - Then a short provenance line: source file, block range

    Wire it in the same places writer emits tips/chunks so artifacts appear beside existing ones.

7) Update chunking behavior:

    In cookimport/parsing/chunks.py:

    - Ensure max-size splitting does not split a table run.
    - Ensure lane assignment treats table-containing chunks as knowledge.

    Add/update tests (likely in tests/test_chunks.py) to cover “table doesn’t get split”.

8) Optional: pass4 integration

    - Locate the code that builds pass4 input JSON files under raw/llm/.../pass4_knowledge/in/.
    - Add table_hint fields for blocks in chunk.blocks when table_extraction == "on".
    - Update llm_pipelines/prompts/recipe.knowledge.v1.prompt.md with the safe table_hint rule described above.

    Run pack tests:

      pytest -q tests/test_llm_pipeline_pack.py tests/test_llm_pipeline_pack_assets.py

9) End-to-end validation run

    Pick one PDF and/or EPUB fixture that contains a table (a real cookbook in data/input, or add a small test fixture if the repo already uses fixtures). Run:

      source .venv/bin/activate
      cookimport stage data/input/<your_table_book>.pdf --table-extraction on

    Confirm outputs exist:

      ls -R data/output/<timestamp>/tables/<workbook_slug>/

    If also validating pass4:

      cookimport stage data/input/<your_table_book>.pdf --table-extraction on --llm-knowledge-pipeline codex-farm-knowledge-v1

    Confirm:
    - tables artifacts exist
    - pass4 input JSON includes table_hint (open one file under raw/llm/.../pass4_knowledge/in/)
    - knowledge snippets include some table-derived facts (not guaranteed, but should improve)

## Validation and Acceptance

Acceptance is user-visible behavior, not just code shape.

The change is accepted when:

1) With table extraction off (default), staging output for an existing known input is unchanged (or changes only in explicitly intended, documented ways).

How to prove:
- Run `cookimport stage <known_fixture>` before and after.
- Compare output directory structure and key markdown summaries (tips.md, chunks.md). They should match or diffs should be explained and justified.

2) With `--table-extraction on`, a table-heavy book produces table artifacts:

- `data/output/<timestamp>/tables/<workbook_slug>/tables.jsonl` exists and contains at least one entry.
- `tables.md` exists and shows a readable table in markdown.

3) Chunking does not split tables:

- In `chunks/<workbook_slug>/chunks.md` (or the chunk JSON), a table is contained within a single chunk rather than being split across chunk boundaries.
- Unit test proves this deterministically.

4) If pass4 is enabled:

- The generated pass4 input JSON contains `table_hint` on relevant blocks.
- The prompt pack tests pass.
- The pipeline still enforces evidence quotes from `block.text` (verbatim), not from table_hint.

## Idempotence and Recovery

- Table extraction is read-only over the source files; it should be safe to run multiple times.
- Output is written into a new timestamped run directory, so re-running does not overwrite prior results.
- If a table is misdetected (false positive), the system should degrade gracefully:
  - Table outputs may include low-confidence tables flagged in JSONL.
  - Chunking should still succeed.
- If table_extraction introduces a runtime error, the user can recover immediately by re-running with `--table-extraction off`.

## Artifacts and Notes

As implementation proceeds, keep short evidence snippets here.

Include:

- A sample `tables.jsonl` entry (redacted if needed) showing headers/rows/markdown/row_texts.
- A short excerpt of `tables.md` demonstrating the rendered table.
- A test transcript showing new tests passing:

    pytest -q
    <expected: all tests pass, including test_tables.py and chunking tests>

## Interfaces and Dependencies

New interfaces to add (names are prescriptive; adjust only if the repo already has an established pattern for similar models):

- In cookimport/parsing/tables.py:

    class ExtractedTable:
      - table_id: str
      - caption: str | None
      - start_block_index: int
      - end_block_index: int
      - headers: list[str] | None
      - rows: list[list[str]]
      - markdown: str
      - row_texts: list[str]
      - confidence: float
      - notes: list[str]

    def detect_tables_from_blocks(blocks: list[Block]) -> list[ExtractedTable]

    def annotate_blocks_with_tables(blocks: list[Block], tables: list[ExtractedTable]) -> None

- Block/table markers:

  Prefer adding optional fields to the existing Block model rather than introducing a parallel block type (to minimize downstream conditionals). Suggested optional fields:

  - table_id: str | None
  - table_row_index: int | None
  - table_is_caption: bool | None
  - table_hint: dict | None   (only in pass4 input JSON, not necessarily on Block everywhere)

- CLI / run config:

  - RunSettings.table_extraction: "off" | "on" (default "off")

Dependency policy:

- Avoid heavy PDF table extraction dependencies (camelot/tabula) in this milestone; work from already-extracted text blocks and block ordering so the feature remains deterministic and lightweight.
- If HTML parsing is later needed for higher fidelity EPUB tables, treat it as a future milestone behind the same flag, and add a small dependency only after verifying it’s already present or acceptable in pyproject constraints.

---

Plan change note (required for living plans):

- 2026-02-25: Initial ExecPlan created to add deterministic table extraction + exports + chunking/pass4 support for table-heavy cookbooks.
