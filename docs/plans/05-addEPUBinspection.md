---
summary: "ExecPlan and implementation record for EPUB inspection/debug CLI tooling and pipeline-faithful diagnostics."
read_when:
  - "When adding or changing `cookimport epub` debug commands"
  - "When debugging EPUB ingestion failures before changing parser heuristics"
---

# Add EPUB Inspection and Debugging Tools

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` are maintained as implementation progressed.

This document is maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

EPUB failures were expensive to diagnose because the CLI did not expose what the container/spine looked like, what block stream extraction produced, or why segmentation did not emit recipe candidates. This work adds a dedicated `cookimport epub ...` debugging surface with deterministic artifacts so EPUB debugging becomes a fast inspect-run-compare loop instead of manual archaeology.

User-visible outcomes after implementation:

- `cookimport epub inspect <book.epub>` prints a spine-oriented structural summary and can write `inspect_report.json`.
- `cookimport epub dump ...` and `cookimport epub unpack ...` extract exact spine/raw files for byte-level inspection.
- `cookimport epub blocks ...` emits a pipeline-faithful block stream preview (`blocks.jsonl`, `blocks_preview.md`, `blocks_stats.json`).
- `cookimport epub candidates ...` emits candidate ranges, scores, and boundary context (`candidates.json`, `candidates_preview.md`).
- `cookimport epub validate ...` integrates optional EPUBCheck jar execution with graceful missing-tool behavior.

## Progress

- [x] (2026-02-16_14.25.01) Mapped EPUB importer insertion points and reuse contracts in `cookimport/plugins/epub.py` (`_read_epub_spine`, `_extract_docpack`, `_detect_candidates`).
- [x] (2026-02-16_14.25.01) Added new `cookimport/epubdebug` module with archive parsing, report models, and EPUBCheck helpers.
- [x] (2026-02-16_14.25.01) Implemented `cookimport epub inspect`, `dump`, `unpack`, `blocks`, `candidates`, and `validate` subcommands.
- [x] (2026-02-16_14.25.01) Wired `epub` Typer sub-CLI into root app (`cookimport/cli.py`).
- [x] (2026-02-16_14.25.01) Added tooling docs under `tools/epubcheck/` and module notes under `cookimport/epubdebug/README.md`.
- [x] (2026-02-16_14.25.01) Added synthetic EPUB fixture helper (`tests/fixtures/make_epub.py`) and CLI coverage (`tests/test_epub_debug_cli.py`).
- [x] (2026-02-16_14.25.01) Validation complete on affected suites: `tests/test_epub_debug_cli.py`, `tests/test_epub_debug_extract_cli.py`, and `tests/test_epub_importer.py` all pass.
- [x] (2026-02-16_14.25.01) Updated docs/conventions/understandings and finalized this ExecPlan as implementation record.
- [x] (2026-02-16_20.12.39) Corrected dependency note: `epub-utils` is available as pre-release-only (`0.1.0a1`), added optional `epubdebug` extra in `pyproject.toml`, and updated docs/install guidance.

## Surprises & Discoveries

- Observation: Directly calling `EpubImporter._extract_docpack(...)` fails unless `_overrides` is initialized, because normal `convert(...)` sets that state before extraction.
  Evidence: Initial CLI test failed with `AttributeError: 'EpubImporter' object has no attribute '_overrides'`; fixed by setting `_overrides = None` in debug extraction path.

- Observation: `epub-utils` appears missing when checking stable-only versions, but is available as pre-release (`0.1.0a1`).
  Evidence: `python -m pip index versions epub-utils` returned no match, while `python -m pip index versions --pre epub-utils` listed `0.1.0a1`; install and import smoke test succeeded.

- Observation: Optional EPUBCheck integration must not hard-fail non-strict runs when no jar is present.
  Evidence: `tests/test_epub_debug_cli.py::test_epub_validate_missing_epubcheck_respects_strict` verifies non-strict exit code 0 and strict exit code 1 when jar is absent.

## Decision Log

- Decision: Implement EPUB debug commands as a dedicated sub-CLI (`cookimport epub ...`) under a new module (`cookimport/epubdebug`) instead of extending the already-large root `cli.py` command bodies.
  Rationale: Keeps responsibilities isolated and lets debug command logic evolve without increasing coupling to stage/Label Studio flows.
  Date/Author: 2026-02-16 / Codex

- Decision: Keep block/candidate debug output pipeline-faithful by reusing production importer internals (`_extract_docpack`, `_detect_candidates`, `_extract_title`) instead of reimplementing extraction/segmentation rules.
  Rationale: The point of debug tooling is behavioral parity with production staging.
  Date/Author: 2026-02-16 / Codex

- Decision: Treat EPUBCheck as optional and gate strictness via `--strict`.
  Rationale: Java/jar dependency should not be mandatory for regular local debugging flows.
  Date/Author: 2026-02-16 / Codex

- Decision: Keep `epub-utils` integration opportunistic (runtime import if available) and default to deterministic zip/OPF parsing.
  Rationale: `epub-utils` is pre-release-only for now, so it should remain an optional extra (`epubdebug`) while ZIP/OPF parsing stays the always-available fallback path.
  Date/Author: 2026-02-16 / Codex

## Outcomes & Retrospective

Primary goal achieved. The project now has a first-class EPUB inspection/debug surface that answers the critical questions that previously required manual extraction and ad hoc scripts.

Delivered:

- Structural inspection with machine-readable reports.
- Raw spine dumping and controlled unpacking.
- Block-level and candidate-level diagnostics tied to production extraction and segmentation behavior.
- Optional EPUBCheck invocation with graceful degradation.
- Synthetic EPUB-based regression tests that avoid copyrighted assets.

Known tradeoff:

- `epub-utils` is currently a pre-release-only optional dependency; to avoid forcing alpha installs in base runtime, fallback archive parsing remains the default baseline path.

## Context and Orientation

Implemented modules and touchpoints:

- `cookimport/epubdebug/archive.py`: EPUB container/OPF/manifest/spine parser with safe unpack member selection.
- `cookimport/epubdebug/models.py`: Pydantic report models for inspect and candidate debug outputs.
- `cookimport/epubdebug/epubcheck.py`: EPUBCheck jar discovery/execution helpers.
- `cookimport/epubdebug/cli.py`: Typer `epub_app` and command implementations.
- `cookimport/cli.py`: root CLI wiring (`app.add_typer(epub_app, name="epub")`).
- `tools/epubcheck/README.md` + `tools/epubcheck/.gitignore`: local jar placement contract.

Test surfaces:

- `tests/fixtures/make_epub.py`: deterministic synthetic EPUB generator.
- `tests/test_epub_debug_cli.py`: end-to-end CLI behavior checks for new subcommands.

Key terms used here:

- Pipeline-faithful blocks: the exact extraction route staging uses (not a separate parser).
- Candidate debug: segmentation ranges from the importer’s production heuristic detector, with context and anchors.

## Plan of Work (Implemented)

### Milestone 1: Archive and report foundations

Added reusable EPUB archive parsing in `cookimport/epubdebug/archive.py` and typed output models in `cookimport/epubdebug/models.py`. This established a stable data contract for all debug commands.

### Milestone 2: `cookimport epub` command implementations

Implemented:

- `inspect`: structural summary and `inspect_report.json` output.
- `dump`: targeted spine extraction (`xhtml`/`plain`) and `dump_meta.json`.
- `unpack`: full or spine-focused extraction with safe output path handling.
- `blocks`: production extraction reuse + JSONL/preview/stats artifacts.
- `candidates`: production segmentation reuse + candidate report/preview artifacts.
- `validate`: optional EPUBCheck execution and result artifact writing.

### Milestone 3: Root CLI integration and local operator docs

Mounted the new sub-CLI in `cookimport/cli.py` and documented jar handling under `tools/epubcheck/`.

### Milestone 4: Regression tests with synthetic EPUB fixture

Added deterministic CLI tests that generate an EPUB on demand, then validate inspect/dump/unpack/blocks/candidates/validate behavior without external dependencies.

## Concrete Steps

Run from repository root:

    source .venv/bin/activate
    pytest -q tests/test_epub_debug_cli.py tests/test_epub_debug_extract_cli.py tests/test_epub_importer.py

Manual smoke examples:

    cookimport epub inspect tests/fixtures/sample.epub --out /tmp/epub-inspect
    cookimport epub dump tests/fixtures/sample.epub --spine-index 0 --format plain --out /tmp/epub-dump
    cookimport epub blocks tests/fixtures/sample.epub --extractor legacy --out /tmp/epub-blocks
    cookimport epub candidates tests/fixtures/sample.epub --extractor legacy --out /tmp/epub-candidates
    cookimport epub validate tests/fixtures/sample.epub --out /tmp/epub-validate

## Validation and Acceptance

Acceptance criteria met:

- `cookimport epub inspect` writes `inspect_report.json` with metadata and spine inventory.
- `cookimport epub dump` writes spine output + `dump_meta.json`.
- `cookimport epub unpack --only-spine` writes container/package/spine documents.
- `cookimport epub blocks` writes JSONL/preview/stats and reports block/role counts.
- `cookimport epub candidates` writes candidate report + preview with range/score/context fields.
- `cookimport epub validate` warns cleanly when jar is missing (or fails in strict mode).

Proof command used:

    source .venv/bin/activate
    pytest -q tests/test_epub_debug_cli.py tests/test_epub_debug_extract_cli.py tests/test_epub_importer.py

Observed result:

- `19 passed` (warnings only).

## Idempotence and Recovery

- All `cookimport epub ...` commands are read-only with respect to input EPUB files.
- Output-writing commands require explicit `--out` and refuse non-empty output directories unless `--force` is passed.
- `validate` without EPUBCheck jar is non-fatal unless `--strict` is enabled.
- Rollback is file-scoped: remove `cookimport/epubdebug`, CLI wiring, and related tests/docs if the feature needs to be reverted.

## Artifacts and Notes

Primary artifact files emitted by new commands:

- `inspect_report.json`
- `dump_meta.json`
- `unpack_meta.json`
- `blocks.jsonl`
- `blocks_preview.md`
- `blocks_stats.json`
- `candidates.json`
- `candidates_preview.md`
- `epubcheck.txt` / `epubcheck.json` (when validator runs)

## Interfaces and Dependencies

New CLI surface:

- `cookimport epub inspect PATH [--out OUTDIR] [--json] [--force]`
- `cookimport epub dump PATH --spine-index N [--format xhtml|plain] --out OUTDIR [--open] [--force]`
- `cookimport epub unpack PATH --out OUTDIR [--only-spine] [--force]`
- `cookimport epub blocks PATH --out OUTDIR [--extractor ...] [--start-spine N] [--end-spine M] [--html-parser-version v1|v2] [--skip-headers-footers] [--preprocess-mode ...] [--force]`
- `cookimport epub candidates PATH --out OUTDIR [--extractor ...] [--start-spine N] [--end-spine M] [--html-parser-version v1|v2] [--skip-headers-footers] [--preprocess-mode ...] [--force]`
- `cookimport epub validate PATH [--jar PATH] [--out OUTDIR] [--strict] [--force]`

Dependencies:

- Required: existing repo dependencies only (`ebooklib`, `beautifulsoup4`, `lxml`, etc.).
- Optional runtime hook: `epub_utils` import if locally installed.
- Optional external tool: Java + EPUBCheck jar for `validate` command.

Revision note (2026-02-16_14.25.01): Replaced draft plan with completed implementation record, added required front matter/read hints, captured real constraints (`_overrides` contract and initial stable-only lookup confusion for `epub-utils`), and recorded validated command/test outcomes.

Revision note (2026-02-16_20.12.39): Corrected the dependency assumption for `epub-utils` (pre-release-only, not unavailable), documented `--pre`/pinned install guidance, and recorded optional-extra wiring in `pyproject.toml`.
