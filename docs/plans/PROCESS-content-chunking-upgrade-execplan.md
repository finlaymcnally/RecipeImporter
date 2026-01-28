---
summary: "ExecPlan for upgrading standalone topic chunking to container + atom splitting."
read_when:
  - When modifying standalone tip chunking, topic candidates, or atom splitting
---

# Content Chunking Pipeline Upgrade ExecPlan

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document is maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

After this change, standalone (non-recipe) cookbook text is captured in a two-layer structure: containers that answer “where are the tips?” and atoms that answer “is this specific text a tip?”. The user-visible result is that `topic_candidates.json` and `topic_candidates.md` contain short, precise snippets instead of blended multi-paragraph chunks, while tip classification continues to work and preserves context via adjacent-atom pointers. You can see this working by running an EPUB or PDF import and observing that a paragraph like “Tip: Use cold butter. Also, preheat the oven.” becomes two separate candidates with shared container provenance and explicit `prev`/`next` context.

## Progress

- [x] (2026-01-28 16:53Z) Fixed `cookimport/parsing/atoms.py` regex syntax, added numbered-list support, container metadata, and atom tests.
- [x] (2026-01-28 16:53Z) Refactored `chunk_standalone_blocks` to return container metadata and updated EPUB/PDF standalone extraction to split into atoms with context.
- [x] (2026-01-28 16:53Z) Added `tip_index_start` and `header_hint` plumbing so per-atom extraction preserves header classification and stable tip ids.
- [x] (2026-01-28 16:53Z) Updated writer output to surface atom kind + context in `topic_candidates.md` and refreshed docs/conventions.

## Surprises & Discoveries

- Observation: `cookimport/parsing/atoms.py` had a newline embedded in `_LIST_ITEM_RE`, causing a syntax error on import.
  Evidence: the original file split the pattern literal across two lines.
- Observation: Moving to per-atom extraction can collide `tip_index` values because `extract_tip_candidates` restarts at 0 for each call.
  Evidence: per-atom calls share the same `location.chunk_index` (container index), so stable ids would repeat without a start offset.

## Decision Log

- Decision: Store atom metadata (kind, index, block index, prev/next context) under `provenance.atom` instead of adding new fields to `TopicCandidate`.
  Rationale: Keeps schema stable while still recording rich evaluation context.
  Date/Author: 2026-01-28, Codex
- Decision: Treat container headers as their own `header` atoms for coverage, but skip header atoms when extracting tips.
  Rationale: Preserves all text in `topic_candidates` while avoiding header-only noise in tip extraction.
  Date/Author: 2026-01-28, Codex
- Decision: Pass container headers into tip extraction via the new `header_hint` parameter instead of prepending header text to atom text.
  Rationale: Preserves header-based classification without re-merging atoms or duplicating header text.
  Date/Author: 2026-01-28, Codex
- Decision: Keep `source_section="standalone_topic"` for standalone atoms.
  Rationale: Reuses existing standalone gating logic without widening the heuristic surface area.
  Date/Author: 2026-01-28, Codex

## Outcomes & Retrospective

Standalone topic chunking is now container + atom based. Atom-level topic candidates include context for reviewers, and tip extraction remains gated as standalone with header-aware classification. Remaining work is limited to tuning split rules if atom granularity proves too fine or too coarse in real cookbooks.

## Context and Orientation

Standalone tip extraction currently works as follows:

- `cookimport/parsing/tips.py::chunk_standalone_blocks` groups leftover blocks into containers based on header cues and anchor overlap.
- `cookimport/parsing/atoms.py` splits each container block into atoms (paragraphs/list items), while `contextualize_atoms` links adjacent atoms.
- `cookimport/plugins/epub.py` and `cookimport/plugins/pdf.py` iterate atoms, store each atom as a `TopicCandidate` (with `provenance.atom` context), and extract tips per atom using `extract_tip_candidates`.
- `cookimport/staging/writer.py` writes `topic_candidates.json`/`.md` for evaluation; the markdown view now includes atom kind and prev/next context where present.

"Container" means a logical location (topic header + related blocks). "Atom" means the smallest classify-able unit (paragraph or list item). "Header atom" means the container header line captured as its own atom for coverage.

## Plan of Work

Implementation consists of repairing the atom splitter, returning container metadata from `chunk_standalone_blocks`, then splitting each container into atoms inside EPUB/PDF standalone extraction. Each atom gets its own provenance record, including container range, header, and adjacent-atom context. Tip extraction is invoked per atom using a `header_hint` to keep header-based classification without merging text. Writer output is updated to display atom kind and context in the evaluation markdown.

## Concrete Steps

From the repo root (`/home/mcnal/projects/recipeimport`), set up a local virtual environment and run tests:

    python -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    pip install -e ".[dev]"
    pytest tests/test_atoms.py tests/test_tip_extraction.py tests/test_tip_writer.py

To see the behavior on real data:

    cookimport import-epub tests/fixtures/sample.epub --output data/output/atom_chunking_smoke

Then open `data/output/atom_chunking_smoke/tips/<workbook>/topic_candidates.md` and confirm that entries are short atoms with `prev`/`next` context.

## Validation and Acceptance

Acceptance criteria:

- `topic_candidates.json` contains atom-level snippets with `provenance.atom` context and container header provenance.
- `topic_candidates.md` shows each atom as a separate entry, with kind and optional prev/next context.
- Tips extracted from standalone text still respect standalone gating and recipe-specific headers.
- No tip id collisions occur within a single container (stable IDs include unique `tip_index`).

## Idempotence and Recovery

All changes are deterministic and safe to rerun. If atom splitting proves too aggressive, tune the regexes in `cookimport/parsing/atoms.py` or adjust container boundaries in `chunk_standalone_blocks`. Restoring the previous behavior is as simple as reverting EPUB/PDF standalone extraction to pass container text directly to `extract_tip_candidates`.

## Artifacts and Notes

Evidence of atom context in provenance (example shape):

    "provenance": {
      "location": {"start_block": 12, "end_block": 19, "chunk_index": 12, "block_index": 14, "atom_index": 2},
      "topic_header": "WHICH SALT SHOULD I USE?",
      "atom": {"index": 2, "kind": "paragraph", "block_index": 14, "context_prev": "...", "context_next": "..."}
    }

## Interfaces and Dependencies

- `cookimport/parsing/atoms.py`:
  - `Atom` dataclass now carries container metadata (`container_start`, `container_end`, `container_header`).
  - `split_text_to_atoms(text, block_index, sequence_offset=0, container_start=None, container_end=None, container_header=None)`.
  - `contextualize_atoms(atoms)` populates `context_prev`/`context_next`.
- `cookimport/parsing/tips.py`:
  - `chunk_standalone_blocks(...) -> list[TopicContainer]` with `indices`, `blocks`, and `header`.
  - `extract_tip_candidates(..., tip_index_start=0, header_hint=None)` to avoid tip id collisions and preserve header classification.
- `cookimport/plugins/epub.py` and `cookimport/plugins/pdf.py`:
  - Build atom-level `TopicCandidate` records with container provenance and per-atom context.
  - Skip header atoms for tip extraction; pass `header_hint` for header-aware classification.
- `cookimport/staging/writer.py`:
  - `topic_candidates.md` now includes atom kind plus optional prev/next context for review.

Change note (2026-01-28): Updated this ExecPlan to reflect completed implementation (container → atom processing, per-atom provenance, header handling, writer updates) and added front matter per docs conventions.
