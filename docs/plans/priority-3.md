---
summary: "ExecPlan for Priority 3: shared deterministic multi-recipe splitting across importers with section-detector-aware guardrails and legacy-safe rollout."
read_when:
  - "When implementing shared multi-recipe splitting for Text/EPUB/PDF importers"
  - "When adding multi-recipe splitter run settings or CLI wiring"
  - "When debugging merged recipe spans and For the X subsection behavior"
---

# Build Priority 3: Shared Deterministic Multi-Recipe Splitting


This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository includes `docs/PLANS.md` at the repository root. This plan must be maintained in accordance with that file.


## Purpose / Big Picture


After this change, the pipeline can deterministically split a single detected candidate span into multiple recipes when that span clearly contains multiple recipe units.

User-visible outcomes:

1. Default behavior remains stable (`multi_recipe_splitter=legacy`), so existing runs do not drift unexpectedly.
2. Enabling `multi_recipe_splitter=rules_v1` allows Text, EPUB, and PDF importers to split merged recipe spans using one shared implementation.
3. Component subsection headers like `For the frosting` stay inside the same recipe instead of triggering false recipe boundaries.
4. Run artifacts and `runConfig` show which splitter backend produced the output, so benchmark and stage comparisons are reproducible.

This priority is deterministic only. No codex-farm recipe parsing or LLM-based parsing/cleaning is introduced.


## Progress


- [x] (2026-02-27_22.25.43) Ran docs discovery (`npm run docs:list`) and read required planning/doc workflow files: `docs/AGENTS.md` and `docs/PLANS.md`.
- [x] (2026-02-27_22.25.43) Audited Priority 3 implementation gaps across importer logic (`cookimport/plugins/text.py`, `cookimport/plugins/epub.py`, `cookimport/plugins/pdf.py`) and run-settings/CLI wiring (`cookimport/config/run_settings.py`, `cookimport/config/run_settings_adapters.py`, `cookimport/cli.py`, `cookimport/labelstudio/ingest.py`).
- [x] (2026-02-27_22.25.43) Rebuilt `docs/plans/priority-3.md` from stale duplicated content.
- [x] (2026-02-27_22.37.24) Re-ran docs discovery and re-read Priority-3 read_when docs: `docs/PLANS.md`, `docs/understandings/2026-02-27_22.25.43-priority3-current-state-audit.md`, and `docs/understandings/2026-02-27_21.16.59-priority-plan-overlap-parallelization-map.md`.
- [x] (2026-02-27_22.37.24) Re-audited current runtime after shared section-detector rollout (`cookimport/parsing/section_detector.py`, importer call sites, all-method variant builder, and tests) and confirmed multi-recipe splitter wiring is still missing.
- [x] (2026-02-27_22.37.24) Refreshed this ExecPlan to include section-detector reuse points and current benchmark wiring expectations.
- [x] (2026-02-27_23.18.00) Implemented Milestone 0 baseline grounding using existing multi-recipe fixtures (`tests/fixtures/multi_recipe.md`, `tests/fixtures/serves_multi.txt`) and importer-local behavior assertions in ingestion tests.
- [x] (2026-02-27_23.18.00) Implemented Milestone 1 shared splitter core in `cookimport/parsing/multi_recipe_splitter.py` with deterministic `rules_v1`, `legacy|off` passthrough, section-detector-backed component-header guardrails, and optional trace payload.
- [x] (2026-02-27_23.18.00) Implemented Milestone 2 run-settings and pipeline wiring: added `multi_recipe_*` fields and `MultiRecipeSplitter` enum in `cookimport/config/run_settings.py`, wired stage and benchmark prediction-generation paths through `cookimport/cli.py`, `cookimport/config/run_settings_adapters.py`, and `cookimport/labelstudio/ingest.py`.
- [x] (2026-02-27_23.18.00) Implemented Milestone 3 Text importer integration with backend selection (`legacy|off|rules_v1`) and optional `multi_recipe_split_trace` raw artifact in `cookimport/plugins/text.py`.
- [x] (2026-02-27_23.18.00) Implemented Milestone 4 EPUB/PDF post-candidate splitter integration in `cookimport/plugins/epub.py` and `cookimport/plugins/pdf.py`, including split provenance metadata and trace artifacts.
- [x] (2026-02-27_23.20.08) Implemented Milestone 5 validation/docs pass: added parser/ingestion/CLI/run-settings/benchmark tests, fixed `rules_v1` coverage regression, updated docs (`docs/02-cli/02-cli_README.md`, `docs/03-ingestion/03-ingestion_readme.md`, `docs/04-parsing/04-parsing_readme.md`, `docs/07-bench/07-bench_README.md`, `cookimport/parsing/README.md`), and added understanding note `docs/understandings/2026-02-27_23.20.08-priority3-rules-v1-coverage-signal-thresholds.md`.
- [x] (2026-02-27_23.20.08) Validation completed for focused Priority 3 suite:
  - `tests/parsing/test_multi_recipe_splitter.py`
  - `tests/ingestion/test_text_importer.py`
  - `tests/ingestion/test_epub_importer.py`
  - `tests/ingestion/test_pdf_importer.py`
  - `tests/llm/test_run_settings.py`
  - `tests/cli/test_run_settings_adapters.py`
  - `tests/cli/test_cli_output_structure.py`
  - `tests/labelstudio/test_labelstudio_benchmark_helpers.py`
- [ ] Milestone 6 (deferred): optional extension lane (FSM/proposer/segmentation-eval/ML-ish backends) after core behavior is stable.


## Surprises & Discoveries


- Observation: Short but valid recipe units were rejected in `rules_v1` when coverage counts considered only content-like lines.
  Evidence: `tests/ingestion/test_text_importer.py::test_convert_multi_recipe_rules_v1_backend` failed with `left_section_coverage_below_threshold` at boundary `# Recipe Two` until coverage switched to ingredient/instruction signal-line counting (content + header signals).

- Observation: Reusing shared section detection for splitter guardrails prevented duplicate `For the X` heuristic stacks across importers.
  Evidence: `multi_recipe_splitter.py` now calls `detect_sections_from_lines(...)` and blocks non-main section headers via `component_header_indices`; importer-level custom guard logic did not need to be reimplemented.

- Observation: All-method matrix growth for splitter comparisons needed to stay explicit to avoid accidental runtime blowups.
  Evidence: `cookimport/cli.py:_build_all_method_variants(...)` adds `multi_recipe_splitter` as a dimension only when non-legacy, preserving base run size unless an experiment explicitly opts in.

- Observation: Splitter trace artifacts were critical for fast debugging and regression triage.
  Evidence: `multi_recipe_split_trace` directly surfaced accepted/rejected boundary reasons and made the threshold regression reproducible without stepping through importer code.


## Decision Log


- Decision: Keep Priority 3 deterministic and LLM-free.
  Rationale: Project policy keeps recipe codex-farm parsing off; splitter behavior should be reproducible and benchmarkable without AI parsing.
  Date/Author: 2026-02-27_22.25.43 / Codex GPT-5

- Decision: Ship shared splitting as an additive backend with `legacy` default.
  Rationale: Existing behavior is importer-specific and in use; keeping a legacy default minimizes regression risk during rollout.
  Date/Author: 2026-02-27_22.25.43 / Codex GPT-5

- Decision: Integrate shared splitting after importer candidate detection, not by replacing each importer’s initial anchor detector first.
  Rationale: This scopes change to the merged-span split problem and avoids destabilizing existing recipe-anchor discovery in one step.
  Date/Author: 2026-02-27_22.25.43 / Codex GPT-5

- Decision: Reuse shared section-detector outputs/signals for splitter guardrails instead of creating a second independent `For the X` rule stack.
  Rationale: Section behavior is already being standardized in Priority 2 surfaces; reusing that logic reduces drift and false-split regressions.
  Date/Author: 2026-02-27_22.37.24 / Codex GPT-5

- Decision: Keep all-method matrix growth explicit and opt-in for Priority 3.
  Rationale: Section backend dimensions already add permutations in some runs; auto-expanding by splitter backend can multiply runtime unexpectedly.
  Date/Author: 2026-02-27_22.37.24 / Codex GPT-5

- Decision: Treat segmentation-eval/`segeval` work as an optional later lane coordinated with Priority 8.
  Rationale: Core Priority 3 value is shared splitter behavior and reproducible wiring; evaluation-surface expansion should avoid duplicate commands.
  Date/Author: 2026-02-27_22.37.24 / Codex GPT-5

- Decision: Coverage thresholds in `rules_v1` should count ingredient/instruction signal lines, not only content-like lines.
  Rationale: Deterministic short recipe blocks with clear section headers can contain instruction text that classifier heuristics mark as neutral; signal-line counting keeps default `min_* = 1` practical while preserving threshold gating.
  Date/Author: 2026-02-27_23.20.08 / Codex GPT-5

- Decision: Keep `legacy` as default and add `off` passthrough to isolate regressions during rollout.
  Rationale: This gives a strict no-split control for comparison/debug while preserving historical behavior by default in existing runs.
  Date/Author: 2026-02-27_23.20.08 / Codex GPT-5


## Outcomes & Retrospective


Core Priority 3 rollout is complete.

Delivered outcomes:

- Shared deterministic splitter module exists (`cookimport/parsing/multi_recipe_splitter.py`) with selectable `legacy|off|rules_v1` behavior and optional trace payloads.
- Text/EPUB/PDF importers now support shared splitter selection from run settings while preserving legacy defaults.
- `For the X` component-header behavior is preserved through shared section-detector guardrails.
- Stage and benchmark prediction-generation flows now persist `multi_recipe_*` settings in run config/report surfaces.
- Focused parser/ingestion/CLI/benchmark tests for this priority pass after the coverage-threshold fix.
- Priority docs and parsing notes now document the new interfaces and trace/debug behavior.

Remaining scope:

- Milestone 6 optional extension lane is intentionally deferred (FSM/proposer/segmentation-eval/ML-ish experiments).


## Context and Orientation


### Current importer behavior

Text importer (`cookimport/plugins/text.py`) now selects split behavior by run settings:
- `legacy`: existing `_split_recipes(...)` path,
- `off`: one candidate span passthrough,
- `rules_v1`: shared splitter over text lines.

EPUB importer (`cookimport/plugins/epub.py`) and PDF importer (`cookimport/plugins/pdf.py`) keep their existing candidate detectors (`_detect_candidates(...)`) and now apply optional post-candidate shared splitting when `multi_recipe_splitter=rules_v1`.

### Current shared parsing behavior relevant to Priority 3

`cookimport/parsing/section_detector.py` is the shared deterministic section engine and is used by the shared multi-recipe splitter guardrail to suppress non-main component header boundaries (`For the X` patterns). `cookimport/parsing/multi_recipe_splitter.py` provides shared deterministic split logic and trace surfaces consumed by Text/EPUB/PDF.

### Current run settings and execution-lane wiring

`RunSettings` (`cookimport/config/run_settings.py`) now includes:
- `multi_recipe_splitter`,
- `multi_recipe_trace`,
- `multi_recipe_min_ingredient_lines`,
- `multi_recipe_min_instruction_lines`,
- `multi_recipe_for_the_guardrail`.

These fields are wired through stage and benchmark prediction-generation paths (`cookimport/cli.py`, `cookimport/config/run_settings_adapters.py`, `cookimport/labelstudio/ingest.py`) and persist to run config/report summaries.

`cookimport/cli.py:_build_all_method_variants(...)` now carries `multi_recipe_splitter` as an explicit dimension when non-legacy.

### Current tests and fixtures relevant to Priority 3

Current coverage now includes:

- shared splitter unit tests in `tests/parsing/test_multi_recipe_splitter.py`;
- Text importer backend integration tests in `tests/ingestion/test_text_importer.py`;
- EPUB/PDF post-candidate split integration tests in `tests/ingestion/test_epub_importer.py` and `tests/ingestion/test_pdf_importer.py`;
- run-settings/CLI/benchmark propagation tests in:
  - `tests/llm/test_run_settings.py`
  - `tests/cli/test_run_settings_adapters.py`
  - `tests/cli/test_cli_output_structure.py`
  - `tests/labelstudio/test_labelstudio_benchmark_helpers.py`.

Still out of scope for this priority:
- dedicated segmentation-eval metrics/command expansion (deferred to optional lane aligned with Priority 8).


## Plan of Work


### Milestone 0: Baseline and fixture grounding

Capture baseline behavior before changing split logic.

Work:

1. Run focused baseline tests for text/epub/pdf candidate segmentation behavior.
2. Run baseline stage conversions for representative fixtures and record recipe counts.
3. Add at least one merged-span fixture (or synthetic block test) that represents two recipes packed inside one candidate span for EPUB/PDF-style block flows.

Acceptance:

- baseline recipe counts and test status are recorded in `Progress`;
- at least one reproducible merged-span fixture is available for before/after validation.


### Milestone 1: Shared deterministic splitter core (`rules_v1`)

Create a shared module that can split one candidate span into multiple spans when repeated recipe structure is detected.

Work:

1. Add `cookimport/parsing/multi_recipe_splitter.py` with explicit contracts:
   - `MultiRecipeSplitConfig`,
   - span/boundary result model (with reason codes),
   - optional trace payload model.
2. Implement deterministic `rules_v1` logic on block-like inputs:
   - detect title-like starts and ingredient/instruction clusters from existing parsing signals,
   - enforce section-coverage thresholds,
   - reuse section-detector-aware component-header guardrails (`For the X`) to suppress false starts.
3. Add focused unit tests in `tests/parsing/test_multi_recipe_splitter.py`.

Acceptance:

- shared splitter behavior is deterministic for fixed input;
- unit tests cover split-positive, split-negative, and component-header guardrail cases.


### Milestone 2: Run settings and pipeline wiring

Expose splitter selection end-to-end and persist it in run artifacts.

Work:

1. Add multi-recipe settings in `cookimport/config/run_settings.py`:
   - `multi_recipe_splitter` (`legacy`, `off`, `rules_v1`),
   - `multi_recipe_trace` (bool),
   - `multi_recipe_min_ingredient_lines` (int),
   - `multi_recipe_min_instruction_lines` (int),
   - `multi_recipe_for_the_guardrail` (bool).
2. Wire fields through:
   - stage path (`cookimport/cli.py`, `cookimport/cli_worker.py`),
   - prediction-generation path (`cookimport/config/run_settings_adapters.py`, `cookimport/labelstudio/ingest.py`).
3. Include the fields in run-settings summary/hash surfaces and interactive UI metadata.
4. Ensure `runConfig` / `runConfigSummary` persist the new values.

Acceptance:

- new options appear in stage and benchmark execution surfaces;
- run artifacts persist selected splitter settings consistently across lanes.


### Milestone 3: Text importer integration with legacy fallback

Add shared splitter support without breaking current text behavior.

Work:

1. Keep `TextImporter._split_recipes(...)` as the `legacy` path.
2. Add `rules_v1` path that maps text chunks into block-like units and runs shared splitter.
3. Keep downstream recipe parsing and recipe-likeness gating unchanged.
4. Add tests verifying:
   - `legacy` preserves current counts on existing fixtures,
   - `rules_v1` splits known merged spans deterministically.

Acceptance:

- text importer behavior is unchanged under `legacy`;
- `rules_v1` path works and is test-covered.


### Milestone 4: EPUB/PDF post-candidate split integration

Apply shared splitting after existing candidate detection for block-first importers.

Work:

1. In `cookimport/plugins/epub.py` and `cookimport/plugins/pdf.py`, add optional postprocessing per detected candidate span:
   - when backend is `legacy` or `off`, preserve current behavior,
   - when backend is `rules_v1`, invoke shared splitter and replace one candidate span with multiple spans when warranted.
2. Record split metadata in candidate provenance and optional raw trace artifacts.
3. Preserve split-job merge determinism and ordering guarantees.
4. Add importer tests for merged-span splitting and component-header guard behavior.

Acceptance:

- EPUB/PDF can split merged candidate spans with shared backend;
- component headers remain inside the correct recipe span;
- no split-job merge ordering regressions are introduced.


### Milestone 5: Validation, benchmark visibility, and docs

Finish core Priority 3 rollout with reproducible verification and docs updates.

Work:

1. Add/adjust tests for parser-level splitter behavior, importer integration, and run-settings propagation.
2. Ensure benchmark outputs can differentiate backend choices via run-config fields.
3. Update docs to match delivered behavior:
   - `docs/03-ingestion/03-ingestion_readme.md`,
   - `docs/04-parsing/04-parsing_readme.md`,
   - `docs/02-cli/02-cli_README.md`,
   - `docs/07-bench/07-bench_README.md` if benchmark dimensions/reporting changed.
4. Add a short understanding note for any non-obvious behavior discovered during implementation.

Acceptance:

- tests and run artifacts make backend comparisons reproducible;
- documentation reflects implemented contracts and flags.


### Milestone 6: Optional extension lane (deferred)

After core rollout stabilizes, optionally add advanced backends and evaluation extras as additive options only.

Scope candidates:

- FSM backend (`transitions`) and boundary proposers (`texttiling`, `ruptures`, `textsplit`, `deeptiling`);
- optional segmentation-eval metrics lane (`segeval`) coordinated with Priority 8;
- experimental ML-ish backends (CRF/weak labels).

Acceptance:

- optional dependencies remain opt-in and do not alter default behavior;
- missing optional dependencies produce explicit install guidance only when selected.


## Concrete Steps


Run these commands from repository root (`/home/mcnal/projects/recipeimport`).

1. Prepare environment.

    source .venv/bin/activate
    python -m pip install -e ".[dev]"
    npm run docs:list

2. Capture baseline importer behavior.

    pytest -q tests/ingestion/test_text_importer.py tests/ingestion/test_epub_importer.py tests/ingestion/test_pdf_importer.py

3. Capture baseline stage evidence on a known multi-recipe fixture.

    cookimport stage tests/fixtures/multi_recipe.md --out /tmp/priority3-baseline --workers 1 --pdf-split-workers 1 --epub-split-workers 1 --no-write-markdown

4. Implement Milestones 1-4 and run focused validation.

    pytest -q tests/parsing/test_multi_recipe_splitter.py tests/ingestion/test_text_importer.py tests/ingestion/test_epub_importer.py tests/ingestion/test_pdf_importer.py tests/llm/test_run_settings.py tests/cli/test_run_settings_adapters.py tests/cli/test_cli_output_structure.py tests/labelstudio/test_labelstudio_benchmark_helpers.py

5. Validate shared splitter behavior once flags exist.

    cookimport stage tests/fixtures/multi_recipe.md --out /tmp/priority3-rules --workers 1 --pdf-split-workers 1 --epub-split-workers 1 --no-write-markdown --multi-recipe-splitter rules_v1 --multi-recipe-trace

6. Compare baseline vs rules outputs.

    diff -u /tmp/priority3-baseline/*/reports/multi_recipe.md.report.json /tmp/priority3-rules/*/reports/multi_recipe.md.report.json

7. If `rules_v1` boundary acceptance unexpectedly fails, inspect full assertion output and rerun focused checks.

    COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1 pytest -o addopts='' -vv --tb=short --show-capture=all --assert=rewrite tests/ingestion/test_text_importer.py::test_convert_multi_recipe_rules_v1_backend
    pytest -q tests/parsing/test_multi_recipe_splitter.py tests/ingestion/test_text_importer.py::test_convert_multi_recipe_rules_v1_backend


## Validation and Acceptance


Acceptance is behavior-based.

1. Legacy compatibility:
   - running with `multi_recipe_splitter=legacy` preserves current recipe counts on known fixtures.
2. Shared splitter behavior:
   - running with `multi_recipe_splitter=rules_v1` splits known merged recipe spans for Text/EPUB/PDF scenarios.
3. Guardrail correctness:
   - `For the X` component headers remain within one recipe and do not create false boundaries.
4. Wiring completeness:
   - stage and prediction-generation paths both receive and persist splitter settings in run config.
5. Reproducibility:
   - reports and artifacts clearly indicate which splitter backend produced results.
6. Policy safety:
   - no codex-farm recipe parsing is enabled by this priority.


## Idempotence and Recovery


This rollout is additive and reversible.

- Safe re-run: milestone commands can be repeated without destructive side effects.
- Fast rollback: set `multi_recipe_splitter=legacy` (or `off`) to return to baseline behavior.
- Trace artifacts are additive and can be deleted between runs.
- If split-worker behavior regresses, disable shared splitter and keep legacy path while fixing tests.


## Artifacts and Notes


Expected `runConfig` snippet after Milestone 2:

    {
      "section_detector_backend": "shared_v1",
      "multi_recipe_splitter": "rules_v1",
      "multi_recipe_trace": true,
      "multi_recipe_min_ingredient_lines": 1,
      "multi_recipe_min_instruction_lines": 1,
      "multi_recipe_for_the_guardrail": true
    }

Expected trace artifact pattern after Milestone 4:

    raw/<importer>/<source_hash>/multi_recipe_split_trace*.json

Expected candidate provenance addition shape (example):

    {
      "multi_recipe": {
        "backend": "rules_v1",
        "split_parent": "urn:recipeimport:epub:...:c3",
        "split_reason": ["title_ingredient_instruction_cycle"],
        "split_index": 1,
        "split_count": 2
      }
    }


## Interfaces and Dependencies


Required contracts for core Priority 3 rollout.

In `cookimport/config/run_settings.py`:

    class MultiRecipeSplitter(str, Enum):
        legacy = "legacy"
        off = "off"
        rules_v1 = "rules_v1"

    class RunSettings(BaseModel):
        multi_recipe_splitter: MultiRecipeSplitter = Field(default=MultiRecipeSplitter.legacy, ...)
        multi_recipe_trace: bool = Field(default=False, ...)
        multi_recipe_min_ingredient_lines: int = Field(default=1, ge=0, ...)
        multi_recipe_min_instruction_lines: int = Field(default=1, ge=0, ...)
        multi_recipe_for_the_guardrail: bool = Field(default=True, ...)

In `cookimport/parsing/multi_recipe_splitter.py`:

    @dataclass(frozen=True)
    class MultiRecipeSplitConfig:
        backend: str
        min_ingredient_lines: int
        min_instruction_lines: int
        enable_for_the_guardrail: bool
        trace: bool

    @dataclass(frozen=True)
    class CandidateSpan:
        start: int
        end: int
        reasons: tuple[str, ...]

    def split_candidate_blocks(blocks: list[Block], *, config: MultiRecipeSplitConfig) -> list[CandidateSpan]: ...

Dependencies for core rollout:

- No new mandatory third-party dependencies.
- Optional libraries (FSM/proposers/`segeval`/ML-ish) remain deferred and opt-in.


## Revision Notes


- 2026-02-27_22.25.43 (Codex GPT-5): Replaced stale duplicated Priority 3 draft with a code-verified ExecPlan aligned to then-current importer behavior and wiring gaps.
- 2026-02-27_22.37.24 (Codex GPT-5): Rebuilt the plan against the latest repository state after section-detector rollout, added explicit reuse points for component-header guardrails, and updated benchmark/run-settings context for current all-method dimensions.
- 2026-02-27_23.20.08 (Codex GPT-5): Marked Milestones 0-5 complete after implementing shared splitter/run-settings/importer wiring and focused test coverage; updated discovery/decision/outcomes/context sections to match shipped behavior and documented the signal-line coverage threshold fix.
