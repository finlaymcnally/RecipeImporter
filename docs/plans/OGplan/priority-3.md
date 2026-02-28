---
summary: "ExecPlan for Priority 3: shared deterministic multi-recipe splitting across importers with legacy-safe rollout."
read_when:
  - "When implementing shared multi-recipe splitting for Text/EPUB/PDF importers"
  - "When adding multi-recipe splitter run settings or CLI wiring"
  - "When debugging merged recipe spans and For the X subsection behavior"
---

# Build Priority 3: Shared Deterministic Multi-Recipe Splitting


This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository includes `docs/PLANS.md` at the repository root. This plan must be maintained in accordance with that file.


## Purpose / Big Picture


After this change, the pipeline can deterministically split a single detected candidate span into multiple recipes when the span clearly contains more than one recipe.

User-visible outcomes:

1. Default behavior remains stable (`multi_recipe_splitter=legacy`), so existing runs do not drift unexpectedly.
2. Enabling `multi_recipe_splitter=rules_v1` allows Text, EPUB, and PDF importers to split merged recipe spans using one shared implementation.
3. Component subsection headers like `For the frosting` stay inside the same recipe instead of triggering false recipe boundaries.
4. Run artifacts and `runConfig` show which splitter backend was used, making benchmark comparisons reproducible.

This priority is deterministic only. No codex-farm recipe parsing or LLM-based parsing/cleaning is introduced.


## Progress


- [x] (2026-02-27_22.25.43) Ran docs discovery (`npm run docs:list`) and read required planning/doc workflow files: `docs/AGENTS.md` and `docs/PLANS.md`.
- [x] (2026-02-27_22.25.43) Audited current implementation state for Priority 3 across importer logic (`cookimport/plugins/text.py`, `cookimport/plugins/epub.py`, `cookimport/plugins/pdf.py`), run-settings/CLI wiring (`cookimport/config/run_settings.py`, `cookimport/config/run_settings_adapters.py`, `cookimport/cli.py`, `cookimport/labelstudio/ingest.py`), and tests.
- [x] (2026-02-27_22.25.43) Rebuilt `docs/plans/priority-3.md` as a current, self-contained ExecPlan aligned to actual repository state.
- [ ] Milestone 0: capture baseline behavior and evidence for existing importer-local multi-recipe heuristics.
- [ ] Milestone 1: implement shared deterministic splitter core (`rules_v1`) with explicit section-coverage checks.
- [ ] Milestone 2: add multi-recipe run settings and full stage + prediction-generation wiring.
- [ ] Milestone 3: integrate shared splitter into Text importer while preserving current splitter as `legacy`.
- [ ] Milestone 4: integrate shared splitter into EPUB/PDF candidate postprocessing with guardrails.
- [ ] Milestone 5: add focused tests, docs updates, and benchmark visibility for backend selection.
- [ ] Milestone 6: optional extension lane (FSM/proposer/segmentation-eval/ML-ish backends) after core behavior is stable.


## Surprises & Discoveries


- Observation: Active and archived Priority 3 plans were identical and stale.
  Evidence: `cmp -s docs/plans/priority-3.md docs/plans/OGplan/priority-3.md` returned identical.

- Observation: The previous draft contained invalid citation placeholders and referenced missing external source files, so it was not self-contained.
  Evidence: `docs/plans/priority-3.md` included `:contentReference[oaicite:...]` markers and references to files not present in this workspace.

- Observation: No shared multi-recipe splitter wiring exists yet in run settings, CLI flags, or adapters.
  Evidence: no `multi_recipe_splitter` fields/options in `cookimport/config/run_settings.py`, `cookimport/cli.py`, `cookimport/config/run_settings_adapters.py`, or `cookimport/labelstudio/ingest.py`.

- Observation: Multi-recipe handling is currently importer-local and heuristic-based.
  Evidence: `TextImporter._split_recipes(...)` in `cookimport/plugins/text.py`; EPUB/PDF candidate detection is in `cookimport/plugins/epub.py:_detect_candidates(...)` and `cookimport/plugins/pdf.py:_detect_candidates(...)`.

- Observation: The `For the X` subsection guard is currently EPUB-specific, not a shared cross-importer rule.
  Evidence: `_is_subsection_header(...)` and related tests exist in `cookimport/plugins/epub.py` and `tests/ingestion/test_epub_importer.py`.

- Observation: Segmentation-eval design overlaps with Priority 8 planning and should be staged to avoid duplicate command/report surfaces.
  Evidence: `docs/understandings/2026-02-27_21.16.59-priority-plan-overlap-parallelization-map.md` identifies Priority 3/8 segmentation-eval overlap.


## Decision Log


- Decision: Keep Priority 3 deterministic and LLM-free.
  Rationale: Project policy keeps recipe codex-farm parsing off; splitter behavior should be reproducible and benchmarkable without AI parsing.
  Date/Author: 2026-02-27_22.25.43 / Codex GPT-5

- Decision: Ship shared splitting as an additive backend with `legacy` default.
  Rationale: Existing behavior is importer-specific and in use; keeping a legacy default minimizes regression risk during rollout.
  Date/Author: 2026-02-27_22.25.43 / Codex GPT-5

- Decision: Integrate shared splitting after importer candidate detection, not by replacing each importer’s initial anchor detector first.
  Rationale: This scopes change to the “merged span split” problem and avoids destabilizing existing recipe-anchor discovery in one step.
  Date/Author: 2026-02-27_22.25.43 / Codex GPT-5

- Decision: Use `RecipeCandidate.provenance` plus raw trace artifacts for split metadata in first rollout.
  Rationale: `RecipeCandidate` currently uses strict `extra="forbid"`; provenance-based metadata avoids immediate broad schema churn.
  Date/Author: 2026-02-27_22.25.43 / Codex GPT-5

- Decision: Treat segmentation-eval/`segeval` work as an optional later lane and coordinate with Priority 8 rather than duplicating command surfaces early.
  Rationale: Priority 8 already owns boundary-first evaluation design; core Priority 3 value is shared splitter behavior and wiring.
  Date/Author: 2026-02-27_22.25.43 / Codex GPT-5


## Outcomes & Retrospective


Pending implementation.

Target completion outcome:

- One shared deterministic multi-recipe splitter backend exists and is selectable.
- Text/EPUB/PDF can all run with `legacy` or `rules_v1` splitter behavior.
- Existing `For the X` guard behavior is preserved and generalized.
- Run artifacts and benchmark reports can distinguish splitter backend choices.


## Context and Orientation


### Current importer behavior

Text importer (`cookimport/plugins/text.py`) currently performs multi-recipe splitting via `_split_recipes(...)` with local heuristics: yield-line starts, explicit delimiter lines (`===`), multiple markdown headers, and numbered-title starts. There is no run-setting-controlled splitter backend; this behavior is always active in text conversion.

EPUB importer (`cookimport/plugins/epub.py`) builds candidates with `_detect_candidates(...)`, `_backtrack_for_title(...)`, and `_find_recipe_end(...)`. It already contains a guard for subsection headers (`_is_subsection_header(...)`) so strings like `For the Frangipane` stay within one recipe.

PDF importer (`cookimport/plugins/pdf.py`) also uses importer-local candidate detection (`_detect_candidates(...)`) and column-aware stopping rules in `_find_recipe_end(...)`. It does not currently share EPUB’s dedicated subsection-header guard logic.

### Current run settings and execution-lane wiring

`RunSettings` (`cookimport/config/run_settings.py`) includes extractor/scorer/worker knobs but no multi-recipe splitter fields. Stage and benchmark/prediction-generation adapters (`cookimport/config/run_settings_adapters.py`) similarly have no multi-recipe splitter wiring.

`cookimport/cli.py` all-method permutations currently vary EPUB extraction dimensions, not multi-recipe segmentation dimensions (`_build_all_method_variants(...)`).

### Current tests and fixtures relevant to Priority 3

Existing coverage includes:

- Text multi-recipe fixtures and conversion expectations in `tests/ingestion/test_text_importer.py` using `tests/fixtures/multi_recipe.md` and `tests/fixtures/serves_multi.txt`.
- EPUB subsection guard tests (`test_is_subsection_header`, `test_find_recipe_end_includes_subsection_headers`) in `tests/ingestion/test_epub_importer.py`.

What is missing:

- No shared splitter module tests.
- No run-setting/CLI tests for multi-recipe backend selection.
- No segmentation-boundary evaluation command/tests for this priority yet.


## Plan of Work


### Milestone 0: Baseline and fixture grounding

Capture current behavior before changing splitter logic.

Work:

1. Run focused baseline tests for text/epub/pdf importer segmentation behavior.
2. Run baseline stage conversions for representative fixtures and record recipe counts.
3. Add one explicit fixture (or synthetic block test) that represents two recipes merged into one candidate span for EPUB/PDF-style block flows.

Acceptance:

- Baseline recipe counts and test status are recorded in `Progress`.
- There is at least one reproducible merged-span fixture ready for before/after validation.


### Milestone 1: Shared deterministic splitter core (`rules_v1`)

Create a shared module that splits one candidate span into multiple spans when repeated recipe structure is detected.

Work:

1. Add `cookimport/parsing/multi_recipe_splitter.py` with core contracts:
   - config model (`MultiRecipeSplitConfig`)
   - boundary/span result model (start/end + reasons)
   - optional trace payload model
2. Implement deterministic `rules_v1` split logic on block-like inputs:
   - detect title-like starts and ingredient/instruction clusters from existing signals
   - enforce section coverage thresholds (minimum ingredient/instruction lines)
   - apply `For the X` guardrail so subsection headers do not trigger false recipe starts
3. Add focused unit tests in `tests/parsing/test_multi_recipe_splitter.py`.

Acceptance:

- Shared splitter behavior is deterministic for fixed input.
- Unit tests cover split-positive, split-negative, and `For the X` guardrail cases.


### Milestone 2: Run settings and pipeline wiring

Expose splitter selection end-to-end and persist it in run artifacts.

Work:

1. Add multi-recipe settings in `cookimport/config/run_settings.py` (initially):
   - `multi_recipe_splitter` (`legacy`, `off`, `rules_v1`)
   - `multi_recipe_trace` (bool)
   - `multi_recipe_min_ingredient_lines` (int)
   - `multi_recipe_min_instruction_lines` (int)
   - `multi_recipe_for_the_guardrail` (bool)
2. Wire new settings through:
   - stage path (`cookimport/cli.py`, `cookimport/cli_worker.py`)
   - benchmark/prediction-generation path (`cookimport/config/run_settings_adapters.py`, `cookimport/labelstudio/ingest.py`)
3. Ensure UI metadata allows interactive toggle editor flows to surface the new settings.
4. Ensure `runConfig`, `runConfigSummary`, and hash include these fields.

Acceptance:

- New options appear in stage and benchmark execution surfaces.
- Run artifacts persist selected splitter settings consistently across lanes.


### Milestone 3: Text importer integration with legacy fallback

Add shared splitter support without breaking current text behavior.

Work:

1. Keep `TextImporter._split_recipes(...)` as the `legacy` path.
2. Add `rules_v1` path that converts text chunks (or full text) into block-like units and runs shared splitter.
3. Keep downstream recipe parsing and recipe-likeness gating unchanged.
4. Add tests that verify:
   - `legacy` preserves current counts on existing fixtures
   - `rules_v1` splits known merged spans and remains deterministic

Acceptance:

- Text importer behavior is unchanged under `legacy`.
- `rules_v1` path works and is test-covered.


### Milestone 4: EPUB/PDF post-candidate split integration

Apply shared splitting after existing candidate detection for block-first importers.

Work:

1. In `cookimport/plugins/epub.py` and `cookimport/plugins/pdf.py`, add optional postprocessing per detected candidate span:
   - when splitter backend is `legacy`/`off`, preserve current behavior
   - when `rules_v1`, invoke shared splitter and replace one candidate span with multiple spans as needed
2. Record split metadata in candidate provenance and optional raw trace artifacts.
3. Preserve split-job merge determinism and ordering.
4. Add/importer tests for merged-span splitting and subsection guard behavior.

Acceptance:

- EPUB/PDF can split merged candidate spans with shared backend.
- Existing EPUB subsection guard behavior remains intact.
- No regression in split-job merge ordering.


### Milestone 5: Validation, benchmark visibility, and docs

Finish core Priority 3 rollout with reproducible verification and docs.

Work:

1. Add/adjust tests for:
   - parser-level splitter behavior
   - importer integration behavior
   - run-settings/CLI propagation
2. Ensure benchmark reports can differentiate backend choices via run-config fields.
3. Update docs to match delivered behavior:
   - `docs/03-ingestion/03-ingestion_readme.md`
   - `docs/04-parsing/04-parsing_readme.md`
   - `docs/02-cli/02-cli_README.md`
   - `docs/07-bench/07-bench_README.md` if benchmark dimensions/reporting changed

Acceptance:

- Tests and run artifacts make backend comparisons reproducible.
- Documentation reflects implemented contracts and flags.


### Milestone 6: Optional extension lane (deferred)

After core rollout stabilizes, optionally add advanced backends and evaluation extras as additive options only.

Scope candidates:

- FSM backend (`transitions`) and boundary proposers (`texttiling`, `ruptures`, `textsplit`, `deeptiling`)
- Optional segmentation-eval metrics lane (`segeval`) coordinated with Priority 8
- Experimental ML-ish backends (CRF/weak labels)

Acceptance:

- Optional dependencies remain opt-in and do not alter default behavior.
- Missing optional deps produce explicit guidance only when selected.


## Concrete Steps


Run these from repository root (`/home/mcnal/projects/recipeimport`).

1. Prepare environment.

    source .venv/bin/activate
    python -m pip install -e ".[dev]"

2. Capture baseline importer behavior.

    pytest -q tests/ingestion/test_text_importer.py tests/ingestion/test_epub_importer.py tests/ingestion/test_pdf_importer.py

3. Capture baseline stage evidence on text fixture.

    cookimport stage tests/fixtures/multi_recipe.md --out /tmp/priority3-baseline --workers 1 --pdf-split-workers 1 --epub-split-workers 1 --no-write-markdown

4. Implement Milestones 1-4 and run focused validation.

    pytest -q tests/parsing/test_multi_recipe_splitter.py tests/ingestion/test_text_importer.py tests/ingestion/test_epub_importer.py tests/ingestion/test_pdf_importer.py tests/llm/test_run_settings.py tests/cli/test_toggle_editor.py tests/cli/test_cli_output_structure.py tests/labelstudio/test_labelstudio_ingest_parallel.py tests/labelstudio/test_labelstudio_benchmark_helpers.py

5. Validate shared splitter behavior once flags exist.

    cookimport stage tests/fixtures/multi_recipe.md --out /tmp/priority3-rules --workers 1 --pdf-split-workers 1 --epub-split-workers 1 --no-write-markdown --multi-recipe-splitter rules_v1 --multi-recipe-trace

6. Compare baseline vs rules outputs.

    diff -u /tmp/priority3-baseline/*/reports/multi_recipe.md.report.json /tmp/priority3-rules/*/reports/multi_recipe.md.report.json


## Validation and Acceptance


Acceptance is behavior-based.

1. Legacy compatibility:
   - Running with `multi_recipe_splitter=legacy` preserves current recipe counts on known fixtures.
2. Shared splitter behavior:
   - Running with `multi_recipe_splitter=rules_v1` splits known merged recipe spans for Text/EPUB/PDF scenarios.
3. Guardrail correctness:
   - `For the X` component headers remain within the same recipe and do not create false recipe boundaries.
4. Wiring completeness:
   - Stage and prediction-generation paths both receive and persist splitter settings in run config.
5. Reproducibility:
   - Reports and artifacts clearly indicate which splitter backend produced results.
6. Policy safety:
   - No codex-farm recipe parsing is enabled by this priority.


## Idempotence and Recovery


This rollout is additive and reversible.

- Safe re-run: milestone commands can be repeated without destructive side effects.
- Fast rollback: set `multi_recipe_splitter=legacy` (or `off`) to return to baseline behavior.
- Trace artifacts are additive and can be deleted between runs.
- If split-worker behavior regresses, disable shared splitter and keep legacy path while fixing tests.


## Artifacts and Notes


Expected `runConfig` snippet after Milestone 2:

    {
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


- 2026-02-27_22.25.43 (Codex GPT-5): Replaced stale duplicated Priority 3 draft with a code-verified ExecPlan that reflects current importer behavior, current wiring gaps, realistic milestone sequencing, and explicit legacy-safe rollout decisions.
