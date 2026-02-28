---
summary: "ExecPlan for Priority 5: deterministic fallback instruction-step segmentation wired through stage and benchmark run settings."
read_when:
  - "When implementing instruction step fallback segmentation for long instruction blobs"
  - "When adding run settings/CLI/bench wiring for instruction segmentation policy/backend"
  - "When debugging mismatch between final draft steps, JSON-LD recipeInstructions, and sections artifacts"
---

# Build Priority 5: Deterministic Fallback Instruction-Step Segmentation

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository includes `docs/PLANS.md` at the repository root. This plan must be maintained in accordance with that file.

## Purpose / Big Picture

After this change, stage conversion will recover useful step boundaries when importer output contains one or two oversized instruction blobs. The segmentation will be deterministic and applied consistently across final draft output, intermediate JSON-LD, and section artifacts.

User-visible outcomes are:

1. `final drafts/.../r*.json` gets practical step lines instead of giant instruction paragraphs.
2. `intermediate drafts/.../r*.jsonld` continues emitting section-aware `HowToSection` when appropriate, but from the same effective segmented lines used by draft shaping.
3. `sections/.../r*.sections.json` and `sections.md` no longer drift from draft/JSON-LD instruction boundaries.
4. Behavior is reproducible and tunable through explicit run settings (`off|auto|always`) without any LLM parsing path.

This priority stays deterministic only. Recipe codex-farm parsing remains policy-locked `off`.

## Progress

- [x] (2026-02-27_22.24.59) Ran docs discovery via `npm run docs:list` and read required docs (`docs/PLANS.md`, `docs/AGENTS.md`, `docs/04-parsing/04-parsing_readme.md`, `docs/05-staging/05-staging_readme.md`, `docs/02-cli/02-cli_README.md`, `docs/07-bench/07-bench_README.md`).
- [x] (2026-02-27_22.24.59) Audited current code paths: `cookimport/staging/draft_v1.py`, `cookimport/staging/jsonld.py`, `cookimport/staging/writer.py`, `cookimport/config/run_settings.py`, `cookimport/config/run_settings_adapters.py`, `cookimport/cli.py`, `cookimport/labelstudio/ingest.py`, and `cookimport/bench/knobs.py`.
- [x] (2026-02-27_22.24.59) Rebuilt `docs/plans/priority-5.md` as a current ExecPlan aligned to existing repository contracts.
- [x] (2026-02-27_22.27.26) Externalized discovery notes to `docs/understandings/2026-02-27_22.27.26-priority5-current-step-segmentation-status.md`.
- [x] (2026-02-27_22.38.32) Re-audited live code/docs after Priority 4 wiring landed; confirmed Priority 5 runtime remains unimplemented and wiring points are still valid.
- [x] (2026-02-27_22.38.32) Baseline test slice still passes in `.venv`: `pytest -q tests/staging/test_draft_v1_variants.py tests/staging/test_section_outputs.py tests/parsing/test_recipe_sections.py` (`PASS: priority5 baseline test slice`).
- [x] (2026-02-27_22.38.32) Added refreshed audit note to `docs/understandings/2026-02-27_22.38.32-priority5-wiring-refresh-audit.md`.
- [x] (2026-02-27_23.19.34) Milestone 0 complete: baseline behavior was captured by existing staging tests and preserved in plan evidence.
- [x] (2026-02-27_23.19.34) Milestone 1 complete: added canonical run settings fields + CLI normalization/options + adapter propagation for instruction segmentation policy/backend.
- [x] (2026-02-27_23.19.34) Milestone 2 complete: implemented `cookimport/parsing/step_segmentation.py` with `off|auto|always`, `heuristic_v1`, optional `pysbd_v1`, header preservation, and sanity fallback.
- [x] (2026-02-27_23.19.34) Milestone 3 complete: staged draft/jsonld/sections now consume one shared effective instruction-shaping path via run-config options.
- [x] (2026-02-27_23.19.34) Milestone 4 complete: benchmark knobs + pred-run pass-through + benchmark run-config payloads now include instruction segmentation fields.
- [x] (2026-02-27_23.19.34) Milestone 5 complete: added/updated parser, staging, run-settings, adapter, and bench tests; updated parsing/staging/CLI/bench docs and module README notes.
- [x] (2026-02-27_23.19.34) Validation slice passed in `.venv`: `python -m pytest -q tests/parsing/test_step_segmentation.py tests/staging/test_draft_v1_variants.py tests/staging/test_section_outputs.py tests/llm/test_run_settings.py tests/cli/test_run_settings_adapters.py tests/bench/test_bench.py`.
- [x] (2026-02-27_23.21.17) Finalized this ExecPlan to implemented-state documentation: removed stale pre-implementation assertions, aligned orientation/workflow sections to shipped behavior, and recorded final revision rationale.

## Surprises & Discoveries

- Observation: Initial sentence splitting was too conservative for medium-length multi-sentence lines and failed Priority-5 test expectations.
  Evidence: first implementation failed `tests/parsing/test_step_segmentation.py` (`auto` trigger false-negative + no split after section header), then passed after lowering auto single-line threshold and enabling splitting when multiple sentence delimiters are present.

- Observation: Tiny-fragment merge logic can accidentally attach numbered step markers (`2.`, `3.`) to prior sentences if sentence splitting runs on numbered fragments.
  Evidence: failing test showed output `\"1. Mix flour and water. 2.\"`; fixed by treating numbered-step fragments as atomic in heuristic sentence splitting.

- Observation: Matching step boundaries across final draft, intermediate JSON-LD, and sections required one writer-level instruction-shaping flow rather than three local copies.
  Evidence: parity checks in `tests/staging/test_section_outputs.py` passed only after `write_draft_outputs(...)`, `write_intermediate_outputs(...)`, and `write_section_outputs(...)` all consumed shared effective instruction shaping.

- Observation: JSON-LD backward compatibility needed a conditional serializer path.
  Evidence: `cookimport/staging/jsonld.py` keeps legacy `HowToStep` object emission when segmentation does not trigger, while segmented runs emit segmented step strings and preserve section grouping behavior.

## Decision Log

- Decision: Implement Priority 5 as a staging safety net (not importer-specific extraction logic).
  Rationale: Keeps behavior centralized and consistent across all importer families that feed `RecipeCandidate.instructions`.
  Date/Author: 2026-02-27_22.24.59 / Codex GPT-5

- Decision: Default policy is `auto`, with explicit `off` and `always` modes.
  Rationale: `auto` provides practical benefit by default; `off` preserves a deterministic rollback path; `always` provides deterministic stress-testing.
  Date/Author: 2026-02-27_22.24.59 / Codex GPT-5

- Decision: Ship `heuristic_v1` as required backend and keep `pysbd_v1` optional.
  Rationale: Core behavior must remain dependency-light and deterministic; pySBD can be an additive sentence-splitting option without making base runtime heavier.
  Date/Author: 2026-02-27_22.24.59 / Codex GPT-5

- Decision: Keep heavy secondary backends (TextTiling/ruptures/textsplit/DeepTiling) out of core Priority-5 delivery.
  Rationale: They add maintenance/dependency burden and are not needed to deliver deterministic fallback splitting now.
  Date/Author: 2026-02-27_22.24.59 / Codex GPT-5

- Decision: Apply identical effective instruction shaping to draft-v1, intermediate JSON-LD, and section artifacts.
  Rationale: Prevents cross-artifact drift where one output shows split steps and another keeps giant blobs.
  Date/Author: 2026-02-27_22.24.59 / Codex GPT-5

- Decision: Keep Priority-5 settings in canonical `RunSettings`/adapter surfaces instead of ad-hoc-only CLI kwargs.
  Rationale: Maintains interactive, stage, pred-run, speed-suite, and quality-suite settings parity.
  Date/Author: 2026-02-27_22.38.32 / Codex GPT-5

- Decision: Preserve existing JSON-LD `HowToStep` object serialization only when fallback segmentation is not active; when segmentation is active, serialize segmented strings directly.
  Rationale: Prevents metadata drift in no-segmentation paths while allowing deterministic segmented step boundaries when Priority-5 policy triggers.
  Date/Author: 2026-02-27_23.19.34 / Codex GPT-5

## Outcomes & Retrospective

Completed.

- Stage outputs now support deterministic fallback instruction segmentation (`off|auto|always`) with backend selection (`heuristic_v1|pysbd_v1`).
- Final draft, intermediate JSON-LD, and section artifacts now use one effective instruction-shaping contract, reducing cross-artifact boundary drift.
- Run settings, stage CLI, benchmark CLI, run-setting adapters, pred-run builder, and bench knobs now all carry these settings end-to-end.
- Coverage now includes parser-level segmentation behavior, staging parity behavior, run-settings/UI choices, adapter propagation, and bench knob/pred-run wiring.

Remaining follow-up outside this plan:

- Optional real-world tuning for `should_fallback_segment(...)` thresholds if new regression fixtures show over/under-splitting.

## Context and Orientation

Priority 5 is implemented. Instruction shaping now runs through one deterministic segmentation helper plus one shared staging integration path.

- `cookimport/staging/draft_v1.py`
  - Accepts `instruction_step_options`.
  - Applies fallback segmentation before variant split and section extraction.
  - Preserves existing `parse_instruction(...)` behavior after effective step boundaries are formed.

- `cookimport/staging/jsonld.py`
  - Accepts `instruction_step_options`.
  - Applies fallback segmentation before section grouping.
  - Preserves legacy `HowToStep` serialization when segmentation is inactive.

- `cookimport/staging/writer.py`
  - Provides the shared effective instruction-shaping path used by draft, JSON-LD, and section outputs.
  - Threads `instruction_step_options` through `write_draft_outputs(...)`, `write_intermediate_outputs(...)`, and `write_section_outputs(...)`.

Priority-5 parsing and settings surfaces:

- Canonical settings model: `cookimport/config/run_settings.py`
- Interactive editor metadata: `run_settings_ui_specs()` in same file; rendered by `cookimport/cli_ui/toggle_editor.py`
- Stage/prediction adapters: `cookimport/config/run_settings_adapters.py`
- Segmentation engine: `cookimport/parsing/step_segmentation.py`
- Stage CLI entrypoint: `cookimport/cli.py::stage(...)`
- Benchmark/prediction generation entrypoints:
  - `cookimport/cli.py::labelstudio_benchmark(...)`
  - `cookimport/labelstudio/ingest.py::generate_pred_run_artifacts(...)`
  - `cookimport/bench/pred_run.py::build_pred_run_for_source(...)`
- Sweep knobs registry: `cookimport/bench/knobs.py`

Current adjacent test coverage:

- `tests/parsing/test_step_segmentation.py`
- `tests/staging/test_draft_v1_variants.py`
- `tests/staging/test_section_outputs.py`
- `tests/llm/test_run_settings.py`
- `tests/cli/test_run_settings_adapters.py`
- `tests/bench/test_bench.py`

Important current-state overlap with other priorities:

- Priority 4 ingredient parser settings are already live in `RunSettings` and CLI/pred-run adapters.
- Priority 5 now follows the same settings wiring pattern and avoids one-off paths.

## Plan of Work (Implemented)

### Milestone 0: Baseline behavior capture

Captured a before-state showing unsplit long-blob instruction behavior.

Work:

1. Add a minimal fixture or inline candidate test case where instructions are one long paragraph with multiple actions and one `For the sauce:` header line.
2. Confirm current behavior leaves the paragraph unsplit in draft output.
3. Record baseline evidence in `Progress` with exact test command and output path.

Acceptance:

- Baseline test demonstrates unsplit long instruction behavior.
- Baseline artifact path is recorded.

### Milestone 1: Run settings and CLI wiring

Added explicit policy/backend controls in the same style as existing deterministic run settings.

Work:

1. In `cookimport/config/run_settings.py`, add enums and fields:
   - `instruction_step_segmentation_policy`: `off|auto|always` (default `auto`)
   - `instruction_step_segmenter`: `heuristic_v1|pysbd_v1` (default `heuristic_v1`)
2. Add both fields to `_SUMMARY_ORDER` so they appear in summary/hash artifacts.
3. Extend `build_run_settings(...)` signature and payload mapping for these fields.
4. Extend stage CLI options in `cookimport/cli.py::stage(...)` and include normalized values in the `build_run_settings(...)` call.
5. Extend benchmark/prediction CLI options in `cookimport/cli.py::labelstudio_benchmark(...)` and pass-through to `generate_pred_run_artifacts(...)`.
6. Extend adapter pass-through in `cookimport/config/run_settings_adapters.py` for both stage and benchmark adapter helpers.

Acceptance:

- New fields appear in `RunSettings().to_run_config_dict()` and `RunSettings().summary()`.
- Interactive run settings editor automatically shows both fields (via `run_settings_ui_specs()`).
- Stage and benchmark run manifests include the selected values.

### Milestone 2: Deterministic segmentation module

Introduced one shared parsing helper that performs fallback segmentation deterministically.

Work:

1. Add `cookimport/parsing/step_segmentation.py` with public entrypoint:
   - `segment_instruction_steps(instructions: list[str], policy: str, backend: str) -> list[str]`
2. Add helper `should_fallback_segment(instructions: list[str]) -> bool` used by `policy=auto`.
3. Implement `heuristic_v1` pipeline:
   - Normalize whitespace/newlines.
   - Split explicit list markers first (newline bullets/numbering).
   - Preserve section-header-like lines as standalone boundaries.
   - Split oversized fragments into sentences.
   - Merge tiny non-header fragments into neighbors.
   - Apply sanity cap (for example 80 steps) and fall back to original input if exceeded.
4. Implement `pysbd_v1` as optional sentence splitter backend only when `pysbd` is installed.
5. Make unavailable backend selection fail fast with a clear install hint.

Acceptance:

- Deterministic outputs for fixed input text and settings.
- `policy=off` returns original boundaries unchanged.
- `policy=auto` only triggers on suspicious long-blob patterns.

### Milestone 3: Staging integration and artifact parity

Applied the same effective instruction text list in all stage conversion surfaces.

Work:

1. Update `cookimport/staging/draft_v1.py` to segment effective instruction lines before section extraction and `parse_instruction(...)` when policy triggers.
2. Update `cookimport/staging/jsonld.py` to apply the same segmentation policy before section extraction/grouping.
3. Update `cookimport/staging/writer.py::write_section_outputs(...)` to use the same effective instruction shaping path so section artifacts do not drift from draft/jsonld behavior.
4. Thread run settings into writer conversion calls:
   - `write_intermediate_outputs(...)`
   - `write_draft_outputs(...)`
   - `write_section_outputs(...)`
5. Update call sites in:
   - `cookimport/cli_worker.py`
   - `cookimport/cli.py` split-merge path
   - `cookimport/labelstudio/ingest.py`

Acceptance:

- Long instruction blob cases produce matching effective boundaries in final draft, intermediate JSON-LD, and section artifacts.
- Existing variant extraction and fallback-step behavior stay intact.

### Milestone 4: Benchmark knob and pred-run wiring

Exposed the new settings in benchmark tuning surfaces.

Work:

1. Add knobs in `cookimport/bench/knobs.py`:
   - `instruction_step_segmentation_policy` (str choices)
   - `instruction_step_segmenter` (str choices)
2. Extend `cookimport/bench/pred_run.py::build_pred_run_for_source(...)` to pass these values into `generate_pred_run_artifacts(...)`.
3. Ensure benchmark config validation accepts only declared choices.
4. Ensure `cookimport bench knobs` output lists the new knobs.

Acceptance:

- `cookimport bench knobs` shows both new knobs.
- Benchmark runs can set these values through knob config and they appear in run config artifacts.

### Milestone 5: Tests and docs updates

Added focused tests and aligned docs with delivered behavior.

Work:

1. Add parser tests in `tests/parsing/test_step_segmentation.py` for:
   - long paragraph split in `always`
   - `auto` trigger/no-trigger cases
   - numbering/bullet/newline splitting
   - section header boundary preservation
   - tiny-fragment merge behavior
2. Update/add staging tests:
   - draft conversion behavior for fallback segmentation
   - JSON-LD `HowToSection` behavior with segmented inputs
   - section artifact parity with effective segmented instructions
3. Update run-settings and bench tests:
   - `tests/llm/test_run_settings.py`
   - `tests/bench/test_bench.py`
4. Update docs as behavior lands:
   - `docs/04-parsing/04-parsing_readme.md`
   - `docs/05-staging/05-staging_readme.md`
   - `docs/02-cli/02-cli_README.md` (new options)

Acceptance:

- New tests pass in `.venv`.
- Docs match delivered runtime behavior and option names.

## Concrete Steps

Run from repo root:

    cd /home/mcnal/projects/recipeimport
    source .venv/bin/activate
    PIP_CACHE_DIR=/tmp/.pip-cache python -m pip install -e '.[dev]'

Baseline checks (before edits):

    python -m pytest -q tests/staging/test_draft_v1_variants.py tests/staging/test_section_outputs.py tests/parsing/test_recipe_sections.py

Baseline proof marker from this refresh:

    PASS: priority5 baseline test slice

Focused validation command used for implementation verification:

    python -m pytest -q tests/parsing/test_step_segmentation.py tests/staging/test_draft_v1_variants.py tests/staging/test_section_outputs.py tests/llm/test_run_settings.py tests/cli/test_run_settings_adapters.py tests/bench/test_bench.py

Stage evidence run (after implementation):

    cookimport stage tests/fixtures/sectioned_components_recipe.txt --out /tmp/priority5-evidence --workers 1 --pdf-split-workers 1 --epub-split-workers 1 --no-write-markdown

Optional long-blob stress case (after adding fixture):

    cookimport stage data/input/priority5_long_instructions.txt --out /tmp/priority5-evidence --workers 1 --pdf-split-workers 1 --epub-split-workers 1 --instruction-step-segmentation-policy always --instruction-step-segmenter heuristic_v1

## Validation and Acceptance

Acceptance criteria:

1. `policy=off` preserves old step boundaries exactly.
2. `policy=auto` splits suspicious long blobs but leaves already step-like recipes unchanged.
3. Section headers (`For the X:` style) remain section boundaries and are not merged into neighboring sentences.
4. Draft output, intermediate JSON-LD output, and section artifacts use consistent effective step boundaries.
5. Run manifests/reports include segmentation policy/backend in run config payloads.
6. `cookimport bench knobs` exposes both new knobs and benchmark config can set them.

## Idempotence and Recovery

Idempotence:

- The default backend (`heuristic_v1`) must be fully deterministic for the same input and run settings.
- `policy=off` is a strict no-op path for segmentation.

Recovery:

- If segmentation behavior regresses a source, rerun with `--instruction-step-segmentation-policy off`.
- If optional backend dependency is missing, use `heuristic_v1` immediately and keep the run deterministic.

## Artifacts and Notes

Implemented code changes:

- New file: `cookimport/parsing/step_segmentation.py`
- Updated:
  - `cookimport/config/run_settings.py`
  - `cookimport/config/run_settings_adapters.py`
  - `cookimport/cli.py`
  - `cookimport/staging/draft_v1.py`
  - `cookimport/staging/jsonld.py`
  - `cookimport/staging/writer.py`
  - `cookimport/cli_worker.py`
  - `cookimport/labelstudio/ingest.py`
  - `cookimport/bench/knobs.py`
  - `cookimport/bench/pred_run.py`

Implemented tests:

- New: `tests/parsing/test_step_segmentation.py`
- Updated:
  - `tests/staging/test_section_outputs.py`
  - `tests/llm/test_run_settings.py`
  - `tests/bench/test_bench.py`
  - plus any staging conversion tests impacted by instruction boundary changes.

## Interfaces and Dependencies

New/updated external interfaces:

- Stage CLI options:
  - `--instruction-step-segmentation-policy off|auto|always`
  - `--instruction-step-segmenter heuristic_v1|pysbd_v1`
- Benchmark/prediction generation options mirror the same names/choices.
- Run settings fields use the same canonical keys for stage, benchmark, and saved last-run settings.

Dependencies:

- Required: none beyond current deterministic runtime for `heuristic_v1`.
- Optional: `pysbd` only for `pysbd_v1` backend.
- No LLM-based parsing/cleaning is introduced.

## Revision Notes

- 2026-02-27_22.24.59 (Codex GPT-5): Rewrote this ExecPlan from a stale pre-implementation draft to a current, code-verified plan.
- 2026-02-27_22.38.32 (Codex GPT-5): Refreshed this ExecPlan after a second full code/docs audit, added baseline test evidence, documented the current benchmark knob surface, and linked a new Priority-5 wiring audit note under `docs/understandings/`.
- 2026-02-27_23.21.17 (Codex GPT-5): Converted this file to a true post-implementation record by removing contradictory pre-implementation observations, updating orientation to the shipped architecture, and syncing validation/workstream wording with the completed Priority-5 delivery.
