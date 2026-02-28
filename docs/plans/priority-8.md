---
summary: "ExecPlan for Priority 8: boundary-first segmentation evaluation on top of current stage-block benchmark contracts."
read_when:
  - "When implementing segmentation boundary metrics and taxonomy in bench evaluation"
  - "When extending bench eval command surfaces for boundary diagnostics"
---

# Build Priority 8: Boundary-First Segmentation Evaluation on Current Bench Surfaces


This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository includes `docs/PLANS.md` at the repository root. This plan must be maintained in accordance with that file.


## Purpose / Big Picture


Priority 8 adds measurement power, not new parsing behavior. After this change, stage-block benchmark outputs will still report existing classification metrics, but they will also report segmentation-boundary quality and a deterministic error taxonomy. The goal is to make merged/split-recipe regressions measurable without replacing current scoring contracts.

User-visible behavior after implementation:

1. `cookimport bench eval-stage ...` writes `eval_report.json` and `eval_report.md` with a new additive `segmentation` section containing boundary precision/recall/F1 and taxonomy buckets.
2. `cookimport bench run` per-item outputs in `per_item/*/eval_freeform/` include the same additive segmentation section.
3. Existing fields (`overall_block_accuracy`, `macro_f1_excluding_other`, mismatch JSONLs, compatibility aliases) remain unchanged in meaning.
4. Optional `segeval` metrics (`pk`, `windowdiff`, `boundary_similarity`) are available only when explicitly requested and installed; native boundary F1 remains default.


## Progress


- [x] (2026-02-27_22.25.29) Ran docs discovery (`npm run docs:list`) and read `docs/AGENTS.md`, `docs/PLANS.md`, and `docs/07-bench/07-bench_README.md`.
- [x] (2026-02-27_22.25.29) Audited current Priority 8 surfaces in code: `cookimport/bench/eval_stage_blocks.py`, `cookimport/bench/runner.py`, `cookimport/cli.py`, and `tests/bench/test_eval_stage_blocks.py`.
- [x] (2026-02-27_22.25.29) Rebuilt `docs/plans/priority-8.md` as a current-state ExecPlan aligned with active benchmark contracts and command surfaces.
- [x] (2026-02-27_22.46.20) Implemented segmentation primitives and focused tests in `cookimport/bench/segmentation_metrics.py` and `tests/bench/test_segmentation_metrics.py`.
- [x] (2026-02-27_22.46.20) Extended `evaluate_stage_blocks(...)` with additive `segmentation` boundaries/taxonomy, optional `segeval` metrics, and new boundary mismatch artifacts.
- [x] (2026-02-27_22.46.20) Extended `cookimport bench eval-stage` with `--label-projection`, `--boundary-tolerance-blocks`, and `--segmentation-metrics` pass-through options.
- [x] (2026-02-27_22.46.20) Added optional dependency wiring (`pyproject.toml` extra `segmentation_eval`) and lazy missing-dependency guidance via `cookimport/bench/segeval_adapter.py`.
- [x] (2026-02-27_22.46.20) Updated benchmark docs/conventions (`docs/07-bench/07-bench_README.md`, `docs/07-bench/runbook.md`, `docs/02-cli/02-cli_README.md`, `cookimport/bench/CONVENTIONS.md`).
- [x] (2026-02-27_22.46.20) Ran focused validation and captured evidence (`pytest tests/bench/test_segmentation_metrics.py tests/bench/test_eval_stage_blocks.py` -> `24 passed`; `cookimport bench eval-stage --help` shows new options/defaults).


## Surprises & Discoveries


- Observation: `docs/plans/priority-8.md` was an exact duplicate of `docs/plans/OGplan/priority-8.md`, so the active plan had not diverged from the archived draft.
  Evidence: `cmp -s docs/plans/priority-8.md docs/plans/OGplan/priority-8.md` returned identical.

- Observation: Current `evaluate_stage_blocks(...)` is classification-only and does not emit a `segmentation` section or taxonomy buckets.
  Evidence: `cookimport/bench/eval_stage_blocks.py` returns block-level metrics (`overall_block_accuracy`, `macro_f1_excluding_other`, `per_label`, mismatch artifacts) with no segmentation keys.

- Observation: The practical offline entrypoint for stage-block eval already exists as `cookimport bench eval-stage`.
  Evidence: `cookimport/cli.py` defines `@bench_app.command("eval-stage")` and calls `evaluate_stage_blocks(...)`.

- Observation: `labelstudio-benchmark` now supports both `stage-blocks` and `canonical-text` modes, and canonical-text is heavily used by modern benchmark loops (all-method/speed/quality).
  Evidence: `cookimport/cli.py` exposes `--eval-mode stage-blocks|canonical-text`; docs confirm canonical-text usage in active benchmark paths.

- Observation: `stage_block_predictions.v1` payload shape in this repo uses a `block_labels` mapping and optional `block_count`, not the older list-of-predictions format used in stale draft examples.
  Evidence: `load_stage_block_labels(...)` in `cookimport/bench/eval_stage_blocks.py` requires `block_labels` dict and validates completeness against `block_count`.

- Observation: `pyproject.toml` has no optional dependency group for segmentation metrics (`segeval`) yet.
  Evidence: `[project.optional-dependencies]` currently includes `db`, `benchaccel`, `dev`, and `epubdebug` only.

- Observation: Existing benchmark tests did not lock any `segmentation` payload shape, so additive JSON/markdown changes required explicit new assertions to prevent silent contract drift.
  Evidence: `tests/bench/test_eval_stage_blocks.py` previously validated only classification metrics/artifacts; no references to `segmentation` keys existed.

- Observation: The optional-metrics failure path needed to be normalized to `ValueError` at evaluator boundary so CLI callers receive standard `_fail(str(exc))` behavior.
  Evidence: `evaluate_stage_blocks(...)` now catches `OptionalSegmentationDependencyError` from `segeval_adapter` and re-raises `ValueError` with install guidance.


## Decision Log


- Decision: Implement Priority 8 by extending existing bench evaluation surfaces (`evaluate_stage_blocks`, `bench eval-stage`, and bench-run call sites) instead of introducing a separate top-level command namespace.
  Rationale: The repo already has stable stage-block evaluation entrypoints and artifact contracts; extending them avoids command duplication and keeps operational workflows coherent.
  Date/Author: 2026-02-27_22.25.29 / Codex GPT-5

- Decision: Keep segmentation outputs additive under `report["segmentation"]` and preserve all legacy keys/artifacts.
  Rationale: Existing analytics/report tooling consumes current fields; additive-only evolution minimizes regression risk.
  Date/Author: 2026-02-27_22.25.29 / Codex GPT-5

- Decision: Boundary metrics will always be computed from a structural projection (`RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, everything else collapsed to `OTHER`) even when classification metrics remain full-vocabulary.
  Rationale: Priority 8 is about structural segmentation boundaries; this projection keeps scores aligned to that intent.
  Date/Author: 2026-02-27_22.25.29 / Codex GPT-5

- Decision: `segeval` remains optional and explicit (`--segmentation-metrics ...`) rather than default.
  Rationale: Native boundary PRF must remain deterministic and dependency-light; optional backend preserves benchmarkability without forcing new installs.
  Date/Author: 2026-02-27_22.25.29 / Codex GPT-5

- Decision: Keep boundary mismatch JSONLs always written (empty when no rows) instead of conditionally creating files.
  Rationale: This matches existing evaluator artifact behavior (`missed_gold_blocks.jsonl` / `wrong_label_blocks.jsonl`) and keeps downstream tooling idempotent.
  Date/Author: 2026-02-27_22.46.20 / Codex GPT-5

- Decision: Define taxonomy bucket assignment as deterministic single-bucket routing per block mismatch, then add boundary miss counts into `boundary_errors`.
  Rationale: This keeps taxonomy interpretable and stable while still exposing segmentation-specific failures without introducing overlapping per-block bucket accounting.
  Date/Author: 2026-02-27_22.46.20 / Codex GPT-5


## Outcomes & Retrospective


Outcome at completion:

- Priority 8 is implemented on current bench surfaces with additive-only contracts:
  - `evaluate_stage_blocks(...)` now emits `report["segmentation"]` with boundary metrics, taxonomy, and optional `segeval`.
  - `eval_report.md` now includes “Segmentation Boundary Metrics” and “Error Taxonomy”.
  - per-item eval outputs now include `missed_gold_boundaries.jsonl` and `false_positive_boundaries.jsonl`.
- CLI support is live in `cookimport bench eval-stage`:
  - `--label-projection`
  - `--boundary-tolerance-blocks`
  - `--segmentation-metrics`
- Optional dependency path is wired:
  - `pyproject.toml` extra `segmentation_eval`
  - clear install guidance when optional metrics are requested without `segeval`.

Validation evidence:

- `source .venv/bin/activate && pytest tests/bench/test_segmentation_metrics.py tests/bench/test_eval_stage_blocks.py`
  - Result: `24 passed, 2 warnings in 1.36s`
- `source .venv/bin/activate && cookimport bench eval-stage --help`
  - Result: help output includes the three new segmentation flags with expected defaults.


## Context and Orientation


Current benchmark scoring surfaces relevant to Priority 8:

- `cookimport/bench/eval_stage_blocks.py`: stage-block classification evaluator used by `bench run`, `bench eval-stage`, and stage-block mode in `labelstudio-benchmark`.
- `cookimport/bench/eval_canonical_text.py`: canonical-text evaluator for extractor-independent scoring.
- `cookimport/bench/runner.py`: suite orchestrator; currently invokes `evaluate_stage_blocks(...)`.
- `cookimport/cli.py`: command wiring for `bench eval-stage`, `bench run`, and `labelstudio-benchmark`.
- `tests/bench/test_eval_stage_blocks.py`: existing tests for stage-block evaluator behaviors (multi-label gold, missing-gold defaulting, diagnostics, artifact contracts).

Important current behavior:

- `evaluate_stage_blocks(...)` computes legacy block-label classification metrics and additive segmentation diagnostics in one pass.
- Gold can be non-exhaustive; missing gold indices are defaulted to `OTHER` and noted in `gold_conflicts.jsonl`.
- Severe gold/prediction blockization mismatch can fail evaluation early.
- Segmentation boundaries use structural projection (`RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, else `OTHER`) with configurable boundary tolerance.
- Stage-block predictions are loaded from `stage_block_predictions.v1` with `block_labels` map and optional `block_count`.

Terms used in this plan:

- Block: ordered text unit identified by integer `block_index`.
- Structural label projection: reduced label set used for segmentation boundaries (`RECIPE_TITLE`, `INGREDIENT_LINE`, `INSTRUCTION_LINE`, `OTHER`).
- Boundary: start or end block index of a contiguous run for a target structural label.
- Recipe split boundary: start index of each `RECIPE_TITLE` run after the first.
- Taxonomy bucket: deterministic mismatch category (`extraction_failure`, `boundary_errors`, `ingredient_errors`, `instruction_errors`, `yield_time_errors`).


## Plan of Work


### Milestone 1: Add segmentation metric primitives and focused tests


Add a new dependency-free module that computes boundary sets and PRF from ordered label sequences. Keep matching deterministic and support tolerance windows.

Deliverables:

- New module: `cookimport/bench/segmentation_metrics.py`
- New tests: `tests/bench/test_segmentation_metrics.py`
- Core primitives:
  - contiguous run extraction for a target label,
  - boundary set extraction (`start`, `end`),
  - recipe-split boundary extraction from title runs,
  - deterministic boundary matching with tolerance,
  - PRF object serializer with `tp/fp/fn` counts and `not_applicable` support.

Acceptance:

- Unit tests cover exact-match and tolerance cases.
- Multi-recipe toy fixture validates recipe-split boundaries.


### Milestone 2: Integrate segmentation + taxonomy into stage-block evaluator


Extend `evaluate_stage_blocks(...)` to compute segmentation diagnostics after existing block classification metrics and before writing report artifacts.

Deliverables:

- Additive top-level report key: `segmentation`
- `segmentation` payload fields:
  - `label_projection`
  - `boundary_tolerance_blocks`
  - `boundaries` (ingredient/instruction start/end + recipe_split + overall_micro)
  - `error_taxonomy` (bucket counts and optional example counters)
  - `segeval` (optional, only when requested and available)
- Optional additive artifact files:
  - `missed_gold_boundaries.jsonl`
  - `false_positive_boundaries.jsonl`
- Markdown report section updates in `format_stage_block_eval_report_md(...)`:
  - “Segmentation Boundary Metrics”
  - “Error Taxonomy”

Acceptance:

- Existing fields and artifacts remain present and unchanged in meaning.
- New segmentation fields appear in both JSON and markdown outputs.


### Milestone 3: Expose segmentation options through current CLI eval surfaces


Start with `cookimport bench eval-stage` and keep options additive. This command already maps directly to stage-block evaluator inputs and is the least disruptive offline entrypoint.

Deliverables:

- Extend `bench eval-stage` options with:
  - `--label-projection` (`core_structural_v1` initially)
  - `--boundary-tolerance-blocks <int>` (default `0`)
  - `--segmentation-metrics <csv>` (default `boundary_f1`)
- Thread these options into `evaluate_stage_blocks(...)` function arguments.
- Ensure bench-run code paths either:
  - use defaults (segmentation on with default options), or
  - explicitly pass the same defaults for contract clarity.

Optional follow-up in same milestone:

- Add a convenience subcommand alias under `bench` if direct file-path entry is needed without changing existing `eval-stage` UX.

Acceptance:

- `cookimport bench eval-stage --help` documents new segmentation options.
- Running `bench eval-stage` with defaults produces segmentation output.


### Milestone 4: Add optional `segeval` backend


Implement optional external segmentation metrics while keeping native boundary PRF as default.

Deliverables:

- `pyproject.toml` optional extra:
  - `segmentation_eval = ["segeval>=<tested_version>"]`
- New adapter module: `cookimport/bench/segeval_adapter.py`
- Missing-dependency behavior:
  - if user requests `pk/windowdiff/boundary_similarity` without `segeval`, fail with clear install guidance.
- Report contract:
  - `report["segmentation"]["segeval"]["pk"]`
  - `report["segmentation"]["segeval"]["windowdiff"]`
  - `report["segmentation"]["segeval"]["boundary_similarity"]`

Acceptance:

- Native `boundary_f1` works with no extra install.
- Optional metrics appear only when requested and available.


### Milestone 5: Update docs and conventions


Document the segmentation contract where benchmark outputs are described so future debugging does not require reading evaluator internals.

Deliverables:

- Update:
  - `docs/07-bench/07-bench_README.md`
  - `docs/07-bench/runbook.md`
  - `cookimport/bench/CONVENTIONS.md`
- Add exact boundary definitions:
  - boundaries are block-index based and derived from contiguous runs,
  - recipe split boundary is each `RECIPE_TITLE` run start after the first.

Acceptance:

- Docs list and runbook describe where segmentation keys live and how to interpret them.


## Concrete Steps


All commands run from repository root (`/home/mcnal/projects/recipeimport`).

1. Activate local venv and ensure dev deps are present.

        source .venv/bin/activate
        python -m pip install -e ".[dev]"

2. Implement Milestone 1 module/tests and run focused tests.

        pytest -q tests/bench/test_segmentation_metrics.py

3. Integrate Milestone 2 evaluator changes and run existing evaluator tests.

        pytest -q tests/bench/test_eval_stage_blocks.py

4. Exercise CLI surface for Milestone 3.

        cookimport bench eval-stage --help

5. Run a representative eval-stage execution (existing fixture or local stage run), then inspect:

        <out_dir>/eval_report.json
        <out_dir>/eval_report.md

6. Run at least one bench item through suite flow (small suite) and inspect per-item eval output.

        cookimport bench run --suite <suite_path>

7. If implementing Milestone 4 in the same pass, install optional extra and verify optional metrics.

        python -m pip install -e ".[segmentation_eval]"
        cookimport bench eval-stage ... --segmentation-metrics boundary_f1,pk,windowdiff,boundary_similarity


## Validation and Acceptance


Implementation is accepted when all of the following hold:

1. Focused tests pass in `.venv`:
   - `tests/bench/test_segmentation_metrics.py`
   - `tests/bench/test_eval_stage_blocks.py`
   - any CLI tests touched for new options.

2. `cookimport bench eval-stage --help` shows segmentation options and defaults.

3. Stage-block eval outputs include additive segmentation content:
   - `eval_report.json` has `segmentation` object with boundary/taxonomy fields.
   - `eval_report.md` includes segmentation and taxonomy sections.

4. Existing stage-block metrics and artifacts are unchanged in meaning and remain present.

5. `cookimport bench run` per-item eval outputs include the same additive segmentation keys.

6. Optional `segeval` metrics appear only when requested and available.

Status snapshot (2026-02-27_22.46.20):

- Criteria 1-4 were directly validated by focused tests plus CLI help inspection.
- Criterion 5 is satisfied by additive evaluator defaults and unchanged `bench run` evaluator call path (`cookimport/bench/runner.py`), but a full suite execution was not run in this implementation pass.
- Criterion 6 is validated by the explicit missing-dependency failure test path in `tests/bench/test_eval_stage_blocks.py`.


## Idempotence and Recovery


- Evaluators are read-only on inputs and write only to `out_dir`.
- Re-running with same inputs is safe when writing to a fresh timestamped directory.
- On schema/shape mismatches (gold/pred index mismatch, invalid labels, missing dependency for requested optional metrics), commands must fail fast with explicit messages and no silent partial success.
- Rollback is straightforward because changes are additive to report shape and CLI flags.


## Artifacts and Notes


Expected additive artifacts:

- Existing:
  - `eval_report.json`
  - `eval_report.md`
  - `missed_gold_blocks.jsonl`
  - `wrong_label_blocks.jsonl`
  - compatibility aliases

- New additive (implemented):
  - `segmentation` key in `eval_report.json`
  - segmentation sections in `eval_report.md`
  - optional boundary mismatch JSONLs (`missed_gold_boundaries.jsonl`, `false_positive_boundaries.jsonl`)

Taxonomy bucket names remain:

- `extraction_failure`
- `boundary_errors`
- `ingredient_errors`
- `instruction_errors`
- `yield_time_errors`

Taxonomy assignment is heuristic from block-label confusions and boundary misses; it is not a full parser-level ingredient/yield/time correctness evaluator.


## Interfaces and Dependencies


Target interfaces for implementation:

1. New module `cookimport/bench/segmentation_metrics.py` with deterministic helpers:
   - `runs(labels: list[str], target_label: str) -> list[Span]`
   - `boundaries_from_runs(runs: list[Span], which: Literal["start", "end"]) -> set[int]`
   - `recipe_split_boundaries(labels: list[str]) -> set[int]`
   - `boundary_prf(gold: set[int], pred: set[int], tolerance: int, *, not_applicable_when_gold_empty: bool) -> PRF`
   - `compute_segmentation_boundaries(labels_gold: list[str], labels_pred: list[str], tolerance_blocks: int) -> SegmentationBoundaryReport`

2. Optional module `cookimport/bench/segeval_adapter.py`:
   - dedicated adapter that isolates `segeval` import and conversions.
   - never imported at module import-time by default paths; import lazily when optional metrics requested.

3. `evaluate_stage_blocks(...)` in `cookimport/bench/eval_stage_blocks.py`:
   - add args for segmentation projection/tolerance/metric selection.
   - preserve existing call compatibility with defaults.
   - write additive `segmentation` report fields.

4. CLI wiring in `cookimport/cli.py`:
   - extend `bench eval-stage` options and pass-through args.
   - optionally thread defaults from bench-suite run paths.


Revision note (2026-02-27_22.25.29): Rebuilt this plan from the stale OG copy so it reflects current code contracts (existing `bench eval-stage` command, current `stage_block_predictions.v1` payload shape, canonical-text coexistence, and missing `segeval` extra) before implementation begins.
Revision note (2026-02-27_22.46.20): Updated this plan to implementation-complete state after landing segmentation primitives, evaluator/CLI wiring, optional `segeval` integration, docs updates, and focused validation evidence so the document now explains shipped behavior and key choices.
