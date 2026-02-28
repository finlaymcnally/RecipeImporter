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


After this change, when an importer produces one or two oversized instruction blobs, stage conversion will deterministically split them into usable step lines before final draft and intermediate JSON-LD output are written.

User-visible outcomes:

1. `final drafts/.../r*.json` contains practical step boundaries instead of one giant instruction paragraph.
2. `intermediate drafts/.../r*.jsonld` keeps section-aware `HowToSection` behavior while also benefiting from fallback segmentation.
3. `sections/.../r*.sections.json` and `sections.md` reflect the same effective instruction boundaries used for draft/jsonld shaping.
4. The behavior is reproducible and tunable through run settings (`off|auto|always`) without enabling any LLM-based parsing.

This priority is deterministic only. Recipe codex-farm parsing remains policy-locked off.


## Progress


- [x] (2026-02-27_22.24.59) Ran docs discovery via `npm run docs:list` and read required docs (`docs/PLANS.md`, `docs/AGENTS.md`, `docs/04-parsing/04-parsing_readme.md`, `docs/05-staging/05-staging_readme.md`, `docs/02-cli/02-cli_README.md`, `docs/07-bench/07-bench_README.md`).
- [x] (2026-02-27_22.24.59) Audited current code paths: `cookimport/staging/draft_v1.py`, `cookimport/staging/jsonld.py`, `cookimport/staging/writer.py`, `cookimport/config/run_settings.py`, `cookimport/config/run_settings_adapters.py`, `cookimport/cli.py`, `cookimport/labelstudio/ingest.py`, and `cookimport/bench/knobs.py`.
- [x] (2026-02-27_22.24.59) Rebuilt `docs/plans/priority-5.md` as a current ExecPlan aligned to existing repository contracts.
- [x] (2026-02-27_22.27.26) Externalized discovery notes to `docs/understandings/2026-02-27_22.27.26-priority5-current-step-segmentation-status.md`.
- [ ] Milestone 0: capture baseline behavior and evidence on current no-fallback path.
- [ ] Milestone 1: add run-settings/CLI plumbing for instruction step segmentation policy/backend.
- [ ] Milestone 2: implement deterministic segmentation module (`heuristic_v1`, optional `pysbd_v1` sentence split backend).
- [ ] Milestone 3: integrate effective instruction shaping into draft-v1, JSON-LD, and section artifact paths.
- [ ] Milestone 4: wire benchmark/pred-run knobs and pass-through contracts.
- [ ] Milestone 5: add focused tests and update docs that describe staging/parsing behavior.


## Surprises & Discoveries


- Observation: Priority 5 is not implemented in runtime code yet.
  Evidence: `rg -n "instruction_step_segmentation|step_segmentation|instruction_step_segmenter" cookimport tests` returns no implementation hits.

- Observation: Staging currently uses raw importer instruction boundaries.
  Evidence: `recipe_candidate_to_draft_v1(...)` in `cookimport/staging/draft_v1.py` only applies variant stripping and section-header extraction before `parse_instruction`, with no fallback splitter.

- Observation: Intermediate JSON-LD also uses raw boundaries plus section-header removal only.
  Evidence: `_build_recipe_instructions(...)` in `cookimport/staging/jsonld.py` calls `extract_instruction_sections(...)` directly on raw instruction texts.

- Observation: Section artifact generation currently has separate instruction-line handling and will drift if fallback segmentation is added only to draft/jsonld.
  Evidence: `write_section_outputs(...)` in `cookimport/staging/writer.py` reads `candidate.instructions` directly and section-extracts those lines.

- Observation: Run settings and benchmark knobs currently have no instruction-step segmentation knobs.
  Evidence: `cookimport/config/run_settings.py` and `cookimport/bench/knobs.py` contain no `instruction_step_*` fields.


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


## Outcomes & Retrospective


Pending implementation.

Target completion outcome:

- Stage outputs show improved instruction boundaries for long-blob inputs while retaining deterministic behavior.
- Section header handling (`For the X:` style) stays stable and visible in both section artifacts and JSON-LD grouping.
- All run settings and benchmark surfaces report the selected segmentation mode/backend in run config artifacts.


## Context and Orientation


Current instruction shaping in stage conversion:

- `cookimport/staging/draft_v1.py`
  - Converts instruction items to text.
  - Removes variation-prefixed lines into `recipe.variants`.
  - Removes instruction section headers via `extract_instruction_sections(...)`.
  - Parses each remaining line with `parse_instruction(...)`.
  - Does not split long instruction blobs.

- `cookimport/staging/jsonld.py`
  - Converts instruction items to `HowToStep` payload rows.
  - Removes detected section headers and, if multiple section keys exist, emits `HowToSection` groups.
  - Does not split long instruction blobs.

- `cookimport/staging/writer.py`
  - `write_section_outputs(...)` currently section-extracts directly from raw `candidate.instructions`.

Current run-settings and wiring surfaces:

- Canonical settings model: `cookimport/config/run_settings.py`
- Interactive editor metadata: `run_settings_ui_specs()` in same file; rendered by `cookimport/cli_ui/toggle_editor.py`
- Stage/prediction adapters: `cookimport/config/run_settings_adapters.py`
- Stage CLI entrypoint: `cookimport/cli.py::stage(...)`
- Benchmark/prediction generation entrypoints:
  - `cookimport/cli.py::labelstudio_benchmark(...)`
  - `cookimport/labelstudio/ingest.py::generate_pred_run_artifacts(...)`
  - `cookimport/bench/pred_run.py::build_pred_run_for_source(...)`
- Sweep knobs registry: `cookimport/bench/knobs.py`

Current tests already guarding adjacent behavior:

- `tests/staging/test_draft_v1_variants.py`
- `tests/staging/test_section_outputs.py`
- `tests/parsing/test_recipe_sections.py`
- `tests/llm/test_run_settings.py`
- `tests/bench/test_bench.py`


## Plan of Work


### Milestone 0: Baseline behavior capture

Capture a before-state that shows current long-blob instruction behavior.

Work:

1. Add a minimal fixture or inline candidate test case where instructions are one long paragraph with multiple actions and one `For the sauce:` header line.
2. Confirm current behavior leaves the paragraph unsplit in draft output.
3. Record baseline evidence in `Progress` with exact test command and output path.

Acceptance:

- Baseline test demonstrates unsplit long instruction behavior.
- Baseline artifact path is recorded.


### Milestone 1: Run settings and CLI wiring

Add explicit policy/backend controls in the same style as existing deterministic run settings.

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

Introduce one shared parsing helper that performs fallback segmentation deterministically.

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

Apply the same effective instruction text list in all stage conversion surfaces.

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

Expose the new settings in benchmark tuning surfaces.

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

Add focused tests and keep docs aligned with delivered behavior.

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

Implement and validate focused changes:

    python -m pytest -q tests/parsing/test_step_segmentation.py tests/staging/test_draft_v1_variants.py tests/staging/test_section_outputs.py tests/llm/test_run_settings.py tests/bench/test_bench.py

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


Expected code changes:

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

Expected tests:

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


Change note (2026-02-27_22.24.59): Rewrote this ExecPlan from a stale pre-implementation draft to a current, code-verified plan. The previous file referenced non-existent wiring/backends and did not match today’s run-settings/staging/bench architecture.
