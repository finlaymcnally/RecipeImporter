https://chatgpt.com/c/69933885-7fdc-8330-ab2f-87fc8aab0782

# Holistic EPUB pipeline hardening: multi-backend extraction, auto-selection, and benchmark-driven iteration

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan must be maintained in accordance with `docs/PLANS.md` (ExecPlan requirements and workflow rules).


## Purpose / Big Picture

After this change, a user who is “stuck on EPUBs” can do three concrete things that make the pipeline measurably better *before* adding LLMs:

1) Run `cookimport stage data/input/book.epub` (or interactive Import) and get **more reliable EPUB extraction**, because the importer can use **multiple extraction backends** (Unstructured, legacy HTML tag-walker, and a new “HTML→Markdown→Blocks” backend) and can **auto-select** the best one per book using deterministic scoring.

2) Understand and debug why a given EPUB is failing, because the run writes **explicit, diff-friendly extraction diagnostics artifacts** (not just logs), and the conversion report records both the **requested** and **effective** extractor choices, plus any fallback events.

3) Improve the pipeline iteratively without guessing, because `cookimport bench run` can be configured to run suites under different EPUB extractors, letting you quantify regressions/improvements in a repeatable offline loop (gold vs predictions), keeping “LLM as cheatcode” costs low by first tightening deterministic quality.

How to see it working (human-verifiable):
- You can run stage on the same EPUB with `--epub-extractor legacy|unstructured|markdown|auto` and see:
  - each run completes without crashes,
  - the output report includes which extractor actually ran,
  - raw artifacts include extractor-specific diagnostics (e.g., Unstructured JSONL; Markdown conversion diagnostics),
  - and `auto` picks a backend deterministically and records why.
- You can run `cookimport bench run --suite <suite>` twice, once with extractor A and once with extractor B (via a knobs config), and see the report differ in the expected direction (even if only “no regression” at first).


## Progress

- [ ] (2026-02-16) Milestone 0: Establish reproducible baselines for “known bad” EPUB behavior (one real input + at least one synthetic fixture) and record the run roots + reports.
- [ ] (2026-02-16) Milestone 1: Refactor EPUB extraction into an explicit backend interface (legacy + unstructured) with shared post-processing and invariant-preserving diagnostics (no intended behavior change).
- [ ] (2026-02-16) Milestone 2: Implement the new `markdown` extraction backend (HTML→Markdown→Blocks) with optional Pandoc acceleration and deterministic, testable Markdown parsing.
- [ ] (2026-02-16) Milestone 3: Implement `auto` extractor selection (deterministic scoring + sampling) in the stage/CLI layer so split jobs remain consistent; persist “why” artifacts and report fields.
- [ ] (2026-02-16) Milestone 4: Wire extractor choice into `cookimport bench` (knob + per-item reporting) so extractor experiments are measurable and reproducible.
- [ ] (2026-02-16) Milestone 5: Add focused unit + integration tests, plus a short CLI smoke runbook, proving extraction backends and `auto` mode work end-to-end and do not break split-merge invariants.


## Surprises & Discoveries

(Keep this section updated as you implement. Include short evidence snippets like a failing command output or a before/after metric excerpt.)

- Observation: TBD
  Evidence: TBD


## Decision Log

(Record decisions as you implement, even “small” ones; they become critical later.)

- Decision: TBD
  Rationale: TBD
  Date/Author: TBD


## Outcomes & Retrospective

(Fill in at the end of major milestones and at completion.)

- Outcome: TBD
  What remains: TBD
  Lessons learned: TBD


## Context and Orientation

This repository is a Python 3.12 CLI project (`cookimport`) that ingests recipe sources (Excel, EPUB, PDF, text, app exports) and emits structured outputs. EPUB ingestion is currently block-stream-based:

- EPUB is a ZIP container with a **spine**, the ordered list of XHTML/HTML “spine documents” that define reading order.
- The EPUB importer produces a linear list of internal **Blocks** (paragraphs/headings/list items/tables) from those spine documents, preserving stable ordering. The importer can be split across workers by spine ranges (`start_spine`, `end_spine`), and merge relies on each Block carrying an absolute `spine_index` in `Block.features`.

Key terms used below:
- **Extractor / backend**: the code that converts a spine document’s HTML into a list of Blocks. This plan treats “legacy”, “unstructured”, and “markdown” as backends.
- **Diagnostics artifact**: a file written under `data/output/<run>/raw/...` that captures per-element/per-block metadata in a diff-friendly way (usually JSONL) so you can debug regressions without re-running with custom logs.
- **Auto-selection**: deterministic logic that chooses which backend to use for a book by sampling a few spine documents and scoring the resulting Blocks.

Files and modules you will touch (repo-relative paths):
- `cookimport/plugins/epub.py` (EPUB importer; spine iteration; range slicing; extraction backend selection hook)
- `cookimport/parsing/unstructured_adapter.py` (Unstructured element→Block mapping)
- `cookimport/parsing/block_roles.py` (deterministic roles; should apply to all backends)
- `cookimport/parsing/signals.py` (enrichment; should apply to all backends)
- `cookimport/staging/writer.py` (raw artifact writing conventions and merge behavior)
- `cookimport/cli.py` (stage command; split job orchestration; environment/config plumbing)
- `cookimport/bench/*` (offline benchmark suite; knobs/config)

Existing config surfaces (must stay consistent after changes):
- CLI: `cookimport stage ... --epub-extractor <value>`
- Env: `C3IMP_EPUB_EXTRACTOR=<value>` (used at runtime)
- Interactive settings: `cookimport` → Settings → `epub_extractor` (written to `cookimport.json`)
- Report: run report JSON includes `runConfig` (must record extractor selection clearly)

Critical invariants you must not break:
1) **Split-job determinism**: for `--workers > 1`, each worker processes `[start_spine, end_spine)` and the merged block stream must remain in correct global order. Blocks must preserve absolute `spine_index` and must not be reordered within a spine doc by “smart sorting”.
2) **Traceability**: output must remain traceable back to source via provenance + features. New backends must record enough metadata to debug.
3) **No silent fallback**: if a user explicitly chooses a backend and it fails, the failure should be loud and actionable. “Auto” mode may fall back, but must record that it did and why.


## Plan of Work

### Milestone 0 — Baseline + fixtures you can legally ship

Goal:
Create a repeatable baseline so improvements are measurable and regressions are catchable.

Work:
1) Pick one “known bad” EPUB input (your local cookbook) and commit *only its derived run artifacts paths* into the plan notes (do not commit copyrighted content).
2) Add at least one **synthetic** EPUB fixture usable in unit tests (no copyrighted content). The fixture should intentionally stress:
   - headings + lists,
   - multiple “recipes” separated by headings,
   - and a spine split edge case (recipe spans two spine docs).

Concrete implementation guidance (synthetic fixture):
- Prefer generating a minimal EPUB in tests using temporary files (`tmp_path`) so no binary fixture needs to live in the repo.
- If you already have helper code for building minimal EPUBs, reuse it. Otherwise:
  - Create a ZIP with the bare minimum EPUB structure (mimetype + META-INF/container.xml + OEBPS/content.opf + spine XHTML files).
  - Keep XHTML tiny and deterministic.

Commands to run (repo root):
    python -m pytest -q tests/test_epub_importer.py

Acceptance:
- You can reproduce “before” behavior via saved run roots (for your personal EPUB) and via a synthetic fixture in CI tests.
- The synthetic fixture is stable and does not depend on network or external binaries.


### Milestone 1 — Make extraction backends explicit (legacy + unstructured), unify post-processing, and standardize diagnostics

Goal:
Turn “EPUB extraction” into a first-class, testable subsystem so adding a third backend (Markdown) does not create ad-hoc divergence across code paths.

Work:
1) Create a new module to hold backend interfaces and shared helpers, for example:
- `cookimport/parsing/epub_extractors.py`

Define the core types in plain Python (keep it simple; avoid heavy abstraction):

    from dataclasses import dataclass
    from typing import Protocol

    @dataclass(frozen=True)
    class EpubExtractionResult:
        blocks: list[Block]
        diagnostics_rows: list[dict]   # JSON-serializable rows for JSONL
        meta: dict                     # small dict: backend name/version, counts, etc.

    class EpubExtractor(Protocol):
        name: str
        def extract_spine_html(
            self,
            html: str,
            *,
            spine_index: int,
            source_location_id: str,
        ) -> EpubExtractionResult: ...

2) Implement `LegacyEpubExtractor` by moving/wrapping the existing BeautifulSoup tag-walker code from `cookimport/plugins/epub.py` into this module.
- Preserve behavior: same tag coverage, same Block.type assignments, same normalization.
- Make sure it emits diagnostics_rows too (even if minimal), such as:
  - `spine_index`, `element_index`, `source_location_id`, `tag_name`, `text`, `stable_key`.
- The point is not “parity with Unstructured”; it is “debuggable and diffable”.

3) Implement `UnstructuredEpubExtractor` as a thin wrapper over `partition_html_to_blocks` in `cookimport/parsing/unstructured_adapter.py`.
- Ensure it returns both Blocks and diagnostics_rows.
- Ensure it includes backend version metadata in `meta` (Unstructured version string if available).

4) Standardize shared post-processing in one place:
- For every backend result, run:
  - `signals.enrich_block(block)` for each Block,
  - `assign_block_roles(blocks)` once per spine document (or once for the final list, but do it consistently),
  - any shared `cleaning.normalize_text()` policy (avoid double-normalization: decide where it lives and keep consistent across backends).

5) Wire `cookimport/plugins/epub.py` to call the backend interface instead of having backend-specific code paths scattered around.
- The importer should still be responsible for:
  - selecting spine docs (ebooklib + zip fallback),
  - respecting `[start_spine, end_spine)` slicing,
  - aggregating Blocks in spine order,
  - and preserving `spine_index` in Block.features.

Acceptance:
- Running `cookimport stage ... --epub-extractor legacy` and `--epub-extractor unstructured` both still work.
- Both modes write backend-specific diagnostics JSONL artifacts under raw outputs (names can differ per backend, but must be discoverable).
- Unit tests cover: backend extraction order invariants, and that post-processing ran (signals + roles exist on Blocks).


### Milestone 2 — Add a third backend: `markdown` (HTML→Markdown→Blocks)

Goal:
Provide an alternate extraction backend that can succeed on messy EPUB HTML when other approaches degrade, using a deterministic conversion to Markdown and then a deterministic Markdown-to-Blocks parser.

Important constraint:
The markdown backend must not require system-wide dependencies in CI. If you optionally support Pandoc for better conversion when installed, it must be a best-effort enhancement, not a hard dependency.

Work:
1) Add a lightweight Python dependency for HTML→Markdown conversion.
- Preferred: `markdownify` (pure Python).
- Alternative: `html2text` (also pure Python).
Pick one and pin it to a reasonably narrow range.

2) Optional Pandoc acceleration:
- If `pandoc` is available on PATH, use it to convert HTML→GFM markdown for improved structure retention.
- Detection should be:

    shutil.which("pandoc") is not None

- Call it via subprocess with stdin=HTML and capture stdout.
- If Pandoc fails (non-zero exit), fall back to Python converter and record the failure in diagnostics meta (do not crash unless explicitly configured to “pandoc-only”).

3) Implement Markdown→Blocks parsing with a minimal deterministic parser, not a full markdown AST.
This is intentional: we want predictable behavior and easy debugging.

Rules (first pass; keep it conservative):
- Headings:
  - Lines starting with `#` (1–6) become a heading Block with heading_level set accordingly.
- List items:
  - Lines that match `^\s*([-*]|\d+\.)\s+` become list_item Blocks.
- Paragraphs:
  - Non-empty lines grouped until a blank line become one paragraph Block.
  - Preserve internal newlines as single spaces (or keep as `\n` consistently).
- Code fences:
  - Treat fenced blocks as paragraph Blocks (or drop them) but be consistent and test it.

For each produced Block, set these features at minimum:
- `spine_index` (absolute)
- `source_location_id`
- `extractor_backend = "markdown"`
- `markdown_line_start`, `markdown_line_end` (for traceability)
- `markdown_stable_key = f"{source_location_id}:spine{spine_index}:md{block_index}"`

Diagnostics rows:
- One row per produced Block containing:
  - `spine_index`, `line_start`, `line_end`, `kind` (heading/list/paragraph), `text`, `stable_key`.
- If Pandoc was used, include `pandoc_used: true` in meta.

4) Add this backend to the CLI/config surfaces:
- `cookimport stage ... --epub-extractor markdown`
- Interactive Settings menu: allow selecting `markdown`.
- `cookimport.json` setting validator must accept the new value.

Acceptance:
- The markdown backend can stage the synthetic EPUB fixture and produce Blocks with headings/list items preserved.
- The markdown backend writes a diagnostics artifact (JSONL) that can be diffed between runs.
- No tests depend on Pandoc; Pandoc usage (if present) is covered by an opt-in test that skips when Pandoc is unavailable.


### Milestone 3 — Implement `auto` selection in the stage/CLI layer (deterministic scoring + recorded rationale)

Goal:
Let the pipeline pick the best extractor per EPUB *without* manual toggling, while preserving split-job consistency and making the decision auditable.

Key design choice (required for split jobs):
Auto-selection must happen once in the parent process (stage orchestration), then the **effective extractor** must be passed to workers. Workers must not each “decide” independently.

Work:
1) Implement a deterministic extraction quality scorer:
- Create `cookimport/parsing/extraction_quality.py` (or similar) with:

    @dataclass(frozen=True)
    class ExtractionScore:
        score: float          # 0..1
        reasons: list[str]    # short explanations
        stats: dict           # counts + aggregate numbers

    def score_blocks(blocks: list[Block]) -> ExtractionScore: ...

Scoring must be simple and explainable. A reasonable first pass:
- Reward presence of structure:
  - headings count > 0,
  - list items count > 0,
  - diversity of block_roles (if roles exist).
- Penalize “collapsed text”:
  - extremely long blocks (e.g., > 2000 chars) dominating,
  - total block count too low (e.g., < 20 for a spine doc that clearly has content),
  - high mojibake/replacement-char rate (`�`) or control chars.
- Normalize to 0..1.

2) Implement auto-selection sampling:
- When user requests `--epub-extractor auto` (or settings chooses auto), do:
  - inspect the EPUB to get spine count,
  - pick deterministic sample indices, e.g.:
    - first 2 spine docs in range,
    - one middle doc,
    - last 2 docs in range (if available),
  - for each candidate backend (`unstructured`, `markdown`, `legacy`):
    - run extraction for the sample docs only,
    - compute average score,
    - keep per-backend score details.

3) Choose the backend with the highest average score as `effective_extractor`.
- If a backend errors during sampling, treat it as “failed” and record the exception string in the auto-selection artifact; do not crash unless all backends fail.
- If all backends fail, fail loudly and write whatever debug artifacts you can.

4) Persist the auto-selection rationale:
- Write a raw artifact like:
  - `raw/epub/<source_hash>/epub_extractor_auto.json`
- Include:
  - requested extractor (“auto”),
  - candidate backend list,
  - sample indices,
  - per-backend scores + stats + reasons,
  - chosen effective extractor,
  - timestamp and versions (unstructured version if present; markdown converter version if available).

5) Apply effective extractor consistently:
- Before launching split workers, set the run’s effective extractor in the mechanism workers already read (most likely `C3IMP_EPUB_EXTRACTOR`), but also record both requested and effective in report `runConfig`.
- Ensure interactive mode’s “Import Flow” still works: it currently sets `C3IMP_EPUB_EXTRACTOR` from settings; for `auto`, it must resolve then set the effective value.

6) Fallback behavior during full conversion:
- If the effective backend fails on a particular spine doc during full extraction, you may fall back to the next-best backend for that spine doc only, but:
  - only on hard failure (exception or zero blocks),
  - record a “fallback event” in a raw artifact (JSONL is good),
  - and increment warnings in the conversion report.
If you decide fallback is too risky for boundary stability, do not implement it now; instead, hard-fail and rely on `auto` sampling to choose a working backend. Either path must be explicitly documented in Decision Log.

Acceptance:
- `cookimport stage ... --epub-extractor auto --workers 1` produces output and records:
  - requested=auto, effective=<one of the real backends>,
  - auto rationale artifact exists,
  - outputs are deterministic across two runs (effective extractor and sample indices do not change).
- `cookimport stage ... --epub-extractor auto --workers 2` uses the same effective extractor across both workers and merges correctly.


### Milestone 4 — Integrate extractor choice into `cookimport bench` (knobs + reporting)

Goal:
Make backend experiments measurable and reproducible without manual env var flipping.

Work:
1) Add a new bench knob `epub_extractor`:
- In `cookimport/bench/knobs.py`, register a Tunable that:
  - accepts strings,
  - restricts to allowed values: `legacy`, `unstructured`, `markdown`, `auto`,
  - defaults to `unstructured` (or whatever the system default is; be explicit).

2) Ensure pred-run uses the knob:
- In `cookimport/bench/pred_run.py` (or wherever `generate_pred_run_artifacts()` is called), set the stage run to use that extractor.
- Prefer passing it explicitly into the stage pipeline rather than relying on ambient env vars.
- If you must use env vars, use a small context manager:

    old = os.environ.get("C3IMP_EPUB_EXTRACTOR")
    os.environ["C3IMP_EPUB_EXTRACTOR"] = knob_value
    try: ...
    finally: restore old

3) Improve bench reporting:
- In per-item outputs, include:
  - requested extractor,
  - effective extractor (especially if auto),
  - and whether any fallbacks occurred.
This should show up in:
  - `per_item/<item_id>/pred_run/...` metadata,
  - and ideally summarized in the suite `report.md`.

Acceptance:
- `cookimport bench run --suite <dev_suite> --config <knobs.json>` can change the extractor and you can see the change reflected in the run artifacts.
- The bench run remains offline (no Label Studio required), and all tests still pass.


### Milestone 5 — Tests, CLI smoke runbook, and “Definition of Done” gate

Goal:
Make the work safe to maintain and hard to regress.

Work:
1) Tests:
Add/extend tests in `tests/` to cover:
- Markdown parsing rules (headings/lists/paragraphs) on simple markdown strings.
- Markdown backend extraction on the synthetic EPUB fixture (ensures wiring, ordering, and features exist).
- Auto-selection determinism:
  - create a contrived case where one backend yields obviously worse output (e.g., legacy collapses, markdown preserves headings), and ensure auto picks the expected one.
- Split-job invariant:
  - ensure block ordering remains stable and `spine_index` features survive merge.

2) CLI smoke runbook:
Update or create a short doc section (or add to an existing runbook) that tells a novice exactly what to run to verify the change:
- stage with each backend on a local EPUB,
- stage with auto,
- run a bench suite with a config selecting a backend,
- and where to look in outputs (report JSON + raw artifacts).

3) Fast regression gate:
Keep a short “run every PR” test list (do not require large local epubs).

Acceptance:
- `python -m pytest -q` passes in CI.
- Manual smoke runs produce the expected artifacts and the report fields are easy to find.
- A future contributor can add a fourth backend without re-learning where to hook diagnostics and scoring; the interface makes it obvious.


## Concrete Steps

(These are the commands and “what you should see” checkpoints. Update with real transcripts as you implement.)

Environment setup (repo root):
    python -m venv .venv
    source .venv/bin/activate
    python -m pip install -U pip
    python -m pip install -e ".[dev]"

Fast tests (repo root):
    pytest -q

Targeted tests while iterating:
    pytest -q tests/test_unstructured_adapter.py
    pytest -q tests/test_epub_importer.py
    pytest -q tests/test_epub_job_merge.py
    pytest -q tests/test_bench.py

Manual stage checks (repo root; with a local EPUB you have rights to use):
    cookimport stage data/input/<book>.epub --epub-extractor legacy --workers 1
    cookimport stage data/input/<book>.epub --epub-extractor unstructured --workers 1
    cookimport stage data/input/<book>.epub --epub-extractor markdown --workers 1
    cookimport stage data/input/<book>.epub --epub-extractor auto --workers 1

What to inspect in each run folder:
- `<workbook_slug>.excel_import_report.json`:
  - confirm runConfig includes requested/effective extractor fields.
- `raw/epub/<source_hash>/...`:
  - unstructured: `unstructured_elements.jsonl` (or equivalent)
  - markdown: a markdown diagnostics JSONL (new)
  - auto: `epub_extractor_auto.json` (new)

Bench checks (repo root; using an existing suite):
    cookimport bench validate --suite data/golden/bench/suites/dev.json
    cookimport bench run --suite data/golden/bench/suites/dev.json --config data/golden/bench/knobs/epub_unstructured.json

(Then repeat with a config selecting markdown or auto and compare report.md.)


## Validation and Acceptance

This work is accepted when all of the following are true:

1) Backend support:
- `cookimport stage ... --epub-extractor legacy|unstructured|markdown` works on the synthetic EPUB fixture and on at least one real local EPUB.

2) Diagnostics:
- Every backend writes a diff-friendly diagnostics artifact under `raw/epub/<source_hash>/...` that makes it possible to understand what was extracted and why boundaries changed.
- Auto-selection writes a single JSON artifact explaining:
  - which backends were tried,
  - what sample indices were used,
  - scoring stats,
  - and which backend was chosen.

3) Split-job safety:
- Running EPUB stage with `--workers > 1` still merges correctly, preserves ordering, and does not produce nondeterministic backend choice across workers.

4) Bench integration:
- `cookimport bench run` can be configured to use a chosen extractor and the suite report reflects that choice.

5) Test coverage:
- New unit tests exist for the markdown parser and auto-selection determinism.
- Existing tests remain passing; no regressions to unrelated importers.


## Idempotence and Recovery

Idempotence:
- Stage and bench runs always write to timestamped output folders. Re-running is safe; you get new run roots.
- Auto-selection artifacts are written under the run’s raw artifact folder and do not overwrite prior runs.

Recovery / debugging:
- If split-job merge fails, `.job_parts/<workbook_slug>/` is expected to remain. Treat it as a debug artifact and do not auto-delete it on failure.
- If a backend crashes:
  - explicit backend choice (`--epub-extractor markdown`) should fail loudly and explain what to try next,
  - `auto` should either choose a working backend or fail with a single, clear error after recording which candidates failed during sampling.


## Artifacts and Notes

During Milestone 0, record (in this plan) the following for your “known bad” local EPUB:
- run root path for legacy extraction
- run root path for unstructured extraction
- (after this plan) run root path for markdown extraction
- (after this plan) run root path for auto extraction
Also record which outputs regressed or improved (e.g., recipe boundary examples), but do not paste copyrighted text.

For the synthetic EPUB fixture, include in this plan:
- the expected number of Blocks per spine doc (approximate),
- which headings/lists should exist,
- and which extractor `auto` should choose in that scenario.


## Interfaces and Dependencies

New/updated dependencies:
- Add one Python HTML→Markdown dependency (prefer `markdownify` or `html2text`) and pin it.
- Optional: support Pandoc when present, but do not require it for tests/CI.

New interfaces (must exist at end of Milestone 1):
- `cookimport/parsing/epub_extractors.py`:
  - `EpubExtractionResult`
  - `EpubExtractor` Protocol
  - `LegacyEpubExtractor`
  - `UnstructuredEpubExtractor`

New interfaces (must exist at end of Milestone 2):
- `MarkdownEpubExtractor` implementing `EpubExtractor`
- A deterministic `markdown_to_blocks()` helper (module-local or separate file)

New interfaces (must exist at end of Milestone 3):
- `cookimport/parsing/extraction_quality.py`:
  - `ExtractionScore`
  - `score_blocks(blocks) -> ExtractionScore`
- A stage-layer function to resolve `auto` into an effective extractor before worker launch, for example:
  - `cookimport/cli.py: resolve_epub_extractor_auto(path, candidate_extractors, ...) -> (effective, artifact_dict)`

Bench integration (must exist at end of Milestone 4):
- `cookimport/bench/knobs.py` includes `epub_extractor` tunable and validation.
- Bench pred-run path reliably sets extractor for the run and records it in per-item metadata.

Plan revision note:
- (2026-02-16) Initial ExecPlan drafted to coordinate multi-backend EPUB extraction, deterministic auto-selection, and benchmark integration as a single cohesive implementation and validation story.
