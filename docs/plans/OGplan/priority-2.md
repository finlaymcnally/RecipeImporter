---
summary: "ExecPlan for Priority 2: shared deterministic section detection across importers with run-setting-controlled rollout."
read_when:
  - "When implementing shared section detection for Text/Excel/EPUB/PDF importers"
  - "When adding section detector run settings or CLI wiring"
  - "When debugging For the X subsection behavior and section-aware staging outputs"
---

# Build Priority 2: Shared Deterministic Section Detection Across Importers


This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository includes `docs/PLANS.md` at the repository root. This plan must be maintained in accordance with that file.


## Purpose / Big Picture


After this change, section detection for recipe ingredients and instructions will be driven by one shared deterministic implementation instead of importer-specific copies.

User-visible outcomes:

1. `For the X` component headers behave consistently across Text, Excel, EPUB, and PDF imports.
2. Section artifacts (`sections/.../r*.sections.json`, intermediate `HowToSection`, and section-aware step linking) stay consistent regardless of importer.
3. Run reports include which section detector backend was used so benchmark and stage comparisons are reproducible.
4. The default behavior remains safe (`legacy`) until shared backend validation is complete.

This priority is deterministic only. No codex-farm recipe parsing or LLM-based parsing/cleaning is introduced.


## Progress


- [x] (2026-02-27_22.14.51) Ran docs discovery (`bin/docs-list`) and read required docs: `docs/PLANS.md`, `docs/AGENTS.md`, `docs/04-parsing/04-parsing_readme.md`, `docs/03-ingestion/03-ingestion_readme.md`, `docs/05-staging/05-staging_readme.md`, `docs/02-cli/02-cli_README.md`, `docs/06-label-studio/06-label-studio_README.md`, and `docs/07-bench/07-bench_README.md`.
- [x] (2026-02-27_22.14.51) Audited current section-detection code paths in `cookimport/parsing/sections.py`, importer call sites (`text`, `excel`, `epub`, `pdf`), staging section consumers (`jsonld`, `writer`, `draft_v1`), and run-settings propagation surfaces (`cli`, `cli_worker`, `labelstudio/ingest`, `run_settings_adapters`).
- [x] (2026-02-27_22.14.51) Rebuilt `docs/plans/priority-2.md` as a current, self-contained ExecPlan with explicit milestones tied to real repository paths and tests.
- [ ] Milestone 0: capture baseline behavior and evidence on current `legacy` path.
- [ ] Milestone 1: implement shared deterministic detector core and focused parser tests.
- [ ] Milestone 2: preserve existing `sections.py` contracts while delegating to shared core.
- [ ] Milestone 3: integrate shared detector into Text and Excel importer section extraction.
- [ ] Milestone 4: integrate shared detector into EPUB and PDF field extraction with `For the X` safeguards.
- [ ] Milestone 5: add run-setting/backend wiring across stage + prediction-generation lanes and report surfaces.
- [ ] Milestone 6: add benchmark/run-settings visibility and docs updates; validate end-to-end.


## Surprises & Discoveries


- Observation: Active and archived Priority 2 plans were identical and both stale.
  Evidence: `wc -l docs/plans/priority-2.md docs/plans/OGplan/priority-2.md` and content comparison showed the same 813-line draft.

- Observation: The old draft used invalid citation placeholders and referenced missing source material.
  Evidence: `docs/plans/priority-2.md` included `:contentReference[oaicite:...]` markers; `ls -l "BIG PICTURE UPGRADES.md"` returned missing file.

- Observation: Section grouping is already centralized downstream, but upstream extraction remains fragmented.
  Evidence: `sections.py` is consumed by `staging/jsonld.py`, `staging/writer.py`, and `staging/draft_v1.py`; importers still use local extraction logic (`plugins/text.py`, `plugins/excel.py`, `plugins/epub.py`, `plugins/pdf.py`).

- Observation: Text and Excel importers duplicate near-identical blob section parsing logic.
  Evidence: both define `_extract_sections_from_blob` with the same header mapping pattern.

- Observation: No section-detector backend run setting exists yet, and all-method permutations currently vary EPUB extractor only.
  Evidence: `RunSettings` has scorer/extractor knobs but no section-backend field; `cli.py:_build_all_method_variants(...)` dimensions are extractor-focused.


## Decision Log


- Decision: Keep Priority 2 deterministic and LLM-free.
  Rationale: Project policy keeps recipe codex-farm parsing off; section detection should be stable and benchmarkable without AI dependencies.
  Date/Author: 2026-02-27_22.14.51 / Codex GPT-5

- Decision: Introduce shared section detection as an additive backend (`legacy` + `shared_v1`) with `legacy` default.
  Rationale: Minimizes regression risk while enabling side-by-side benchmark and staged rollout.
  Date/Author: 2026-02-27_22.14.51 / Codex GPT-5

- Decision: Preserve `cookimport/parsing/sections.py` public contract and route it through shared detector internals.
  Rationale: Staging and step-linking already depend on its return shape (`SectionedLines` and header indices).
  Date/Author: 2026-02-27_22.14.51 / Codex GPT-5

- Decision: Integrate record-first importers (`text`, `excel`) before block-first importers (`epub`, `pdf`).
  Rationale: This removes existing duplicated code quickly and establishes shared line-based behavior before block-level adaptation.
  Date/Author: 2026-02-27_22.14.51 / Codex GPT-5

- Decision: Keep all-method benchmark matrix growth explicit/opt-in.
  Rationale: Automatically doubling variant combinations for a new backend can explode runtime; visibility in run settings and manual experiment patches is sufficient for initial rollout.
  Date/Author: 2026-02-27_22.14.51 / Codex GPT-5


## Outcomes & Retrospective


Pending implementation.

Target completion outcome:

- Shared section detection backend is available and validated across importer families.
- `legacy` and `shared_v1` are both runnable for controlled comparison.
- Section-aware staging artifacts and step-linking behavior remain stable or improve with explicit `For the X` coverage.


## Context and Orientation


### Current section contracts

`cookimport/parsing/sections.py` currently provides deterministic line-oriented section utilities:

- `extract_ingredient_sections(...)`
- `extract_instruction_sections(...)`
- `normalize_section_key(...)`

These functions are already consumed by:

- `cookimport/staging/jsonld.py` (HowToSection + ingredient section metadata)
- `cookimport/staging/writer.py` (sections artifacts)
- `cookimport/staging/draft_v1.py` and `cookimport/parsing/step_ingredients.py` (section-aware ingredient-step assignment)

So section context is already part of downstream contracts.

### Current importer behavior

Importer extraction is still mixed and partially duplicated:

- `cookimport/plugins/text.py`: custom `_extract_sections_from_blob` for embedded sections.
- `cookimport/plugins/excel.py`: nearly identical `_extract_sections_from_blob` implementation.
- `cookimport/plugins/epub.py`: custom `_extract_fields` and segmentation heuristics, including `_is_subsection_header` guard.
- `cookimport/plugins/pdf.py`: custom `_extract_fields` heuristics on block streams.

This is the primary Priority 2 gap: upstream section detection is not truly shared.

### Current run settings and benchmark wiring

Run-setting surfaces are centralized in `cookimport/config/run_settings.py` and propagated through:

- Stage path: `cookimport/cli.py` -> `cookimport/cli_worker.py`
- Prediction-generation path: `cookimport/cli.py:labelstudio_benchmark(...)` -> `cookimport/labelstudio/ingest.py:generate_pred_run_artifacts(...)`
- Adapter helpers: `cookimport/config/run_settings_adapters.py`

All-method benchmark variants are built in `cookimport/cli.py:_build_all_method_variants(...)` and currently vary EPUB extractor settings only.

### Existing tests that guard section behavior

Key tests already in place:

- `tests/parsing/test_recipe_sections.py`
- `tests/parsing/test_step_ingredient_linking.py`
- `tests/staging/test_section_outputs.py`
- `tests/ingestion/test_epub_importer.py` (`For the X` subsection guard)
- `tests/ingestion/test_text_importer.py`
- `tests/ingestion/test_excel_importer.py`
- `tests/ingestion/test_pdf_importer.py`

Run-settings and pipeline wiring guards:

- `tests/llm/test_run_settings.py`
- `tests/cli/test_toggle_editor.py`
- `tests/cli/test_cli_output_structure.py`
- `tests/labelstudio/test_labelstudio_ingest_parallel.py`
- `tests/labelstudio/test_labelstudio_benchmark_helpers.py`


## Plan of Work


### Milestone 0: Baseline and guardrails

Capture current behavior before any code movement.

Work:

1. Run focused baseline tests for section parsing/staging and importer behavior.
2. Stage `tests/fixtures/sectioned_components_recipe.txt` using current defaults.
3. Record output behavior for:
   - `sections/*.sections.json`
   - intermediate `HowToSection` rendering
   - step-linking section keys
4. Record current run-config surfaces (no section backend knob yet).

Acceptance:

- Baseline test pass/fail status is documented in `Progress`.
- Baseline artifact path is recorded for before/after diffing.


### Milestone 1: Shared section detector core

Create one shared deterministic detector module that supports both line-oriented and block-oriented inputs.

Work:

1. Add `cookimport/parsing/section_detector.py` with explicit detector contracts:
   - `SectionKind`
   - `SectionSpan`
   - `DetectedSections`
2. Implement `shared_v1` deterministic heuristics that reuse existing parsing signals:
   - header identification from normalized text and signal flags
   - ingredient/instruction morphology checks
   - `For the X` subsection recognition with narrative false-positive guards
3. Include helper mapping from detected spans to section keys/names compatible with existing `sections.py` consumers.
4. Add focused unit tests in `tests/parsing/test_section_detector.py`.

Acceptance:

- Detector output is deterministic for fixed input.
- Unit tests cover explicit headers, implicit clusters, and `For the X` positive/negative cases.


### Milestone 2: Preserve `sections.py` public contracts

Keep existing downstream callers stable while moving internals to the shared detector.

Work:

1. Update `cookimport/parsing/sections.py` internals to delegate to shared detector logic.
2. Preserve existing exported types and semantics:
   - `SectionedLines.lines_no_headers`
   - `SectionedLines.section_key_by_line`
   - `SectionHeaderHit.original_index`
3. Keep section key normalization behavior stable for step-linking parity.
4. Re-run and update parser/staging tests where needed.

Acceptance:

- Existing tests in `test_recipe_sections`, `test_section_outputs`, and section-aware step-linking remain green.
- No contract-breaking change in section artifact shape.


### Milestone 3: Integrate Text and Excel importers

Remove duplicate section parsing and use shared detector in record-first importers.

Work:

1. Replace per-importer `_extract_sections_from_blob` duplication with shared detector calls.
2. Keep fallback behavior unchanged when no section headers are detected.
3. Ensure embedded notes handling remains compatible with current description concatenation behavior.
4. Add/adjust ingestion tests for sectioned blobs and `For the X` section mapping.

Acceptance:

- Text and Excel importers produce the same or better section outputs for existing fixtures.
- No regression in recipe-likeness gating or report totals.


### Milestone 4: Integrate EPUB and PDF importers

Use shared section detection during candidate field extraction while preserving existing candidate-boundary safeguards.

Work:

1. Add shared-detector extraction branch in:
   - `cookimport/plugins/epub.py:_extract_fields(...)`
   - `cookimport/plugins/pdf.py:_extract_fields(...)`
2. Preserve existing segmentation guard behavior in EPUB (`_find_recipe_end`, `_is_subsection_header`).
3. Keep `legacy` extraction path available for controlled comparisons.
4. Add importer tests that assert subsection headers stay within one recipe and map to section keys correctly.

Acceptance:

- EPUB/PDF section extraction under shared backend passes focused tests.
- `For the X` no-longer causes false recipe boundaries.


### Milestone 5: Run settings and pipeline wiring

Expose backend selection end-to-end and persist it in run artifacts.

Work:

1. Add run setting in `cookimport/config/run_settings.py`:
   - `section_detector_backend` (initial values: `legacy`, `shared_v1`)
2. Add CLI options and normalization in stage + benchmark entrypoints (`cookimport/cli.py`).
3. Propagate through:
   - `cookimport/cli_worker.py`
   - `cookimport/config/run_settings_adapters.py`
   - `cookimport/labelstudio/ingest.py` prediction-generation paths
4. Ensure `runConfig`, `runConfigHash`, `runConfigSummary` include the new field.
5. Ensure interactive editor picks up the new setting via `ui_*` metadata.

Acceptance:

- Stage and benchmark reports include `runConfig.section_detector_backend`.
- UI and CLI both expose the setting.
- Prediction-generation lane receives and uses the setting.


### Milestone 6: Benchmark visibility and docs completion

Make backend choice measurable and document final contracts.

Work:

1. Ensure all-method row `dimensions` and run-config summaries can surface section backend when changed.
2. Keep automatic variant explosion off by default; document how to run backend comparisons explicitly.
3. Update docs:
   - `docs/04-parsing/04-parsing_readme.md`
   - `docs/02-cli/02-cli_README.md`
   - `docs/07-bench/07-bench_README.md` (if benchmark dimension behavior changes)
4. Add a short `docs/understandings/...` note for any non-obvious implementation discovery.

Acceptance:

- Documentation matches delivered behavior and settings.
- Benchmark and stage artifacts are sufficient to compare `legacy` vs `shared_v1`.


## Concrete Steps


Run these from repository root (`/home/mcnal/projects/recipeimport`).

1. Prepare environment.

    source .venv/bin/activate
    python -m pip install -e ".[dev]"

2. Capture baseline tests.

    pytest -q tests/parsing/test_recipe_sections.py tests/parsing/test_step_ingredient_linking.py tests/staging/test_section_outputs.py tests/ingestion/test_text_importer.py tests/ingestion/test_excel_importer.py tests/ingestion/test_epub_importer.py tests/ingestion/test_pdf_importer.py tests/llm/test_run_settings.py tests/labelstudio/test_labelstudio_ingest_parallel.py

3. Capture baseline stage artifact with existing behavior.

    cookimport stage tests/fixtures/sectioned_components_recipe.txt --out /tmp/priority2-baseline --workers 1 --pdf-split-workers 1 --epub-split-workers 1 --no-write-markdown

4. Implement Milestones 1-5, then run focused validation.

    pytest -q tests/parsing/test_section_detector.py tests/parsing/test_recipe_sections.py tests/staging/test_section_outputs.py tests/ingestion/test_text_importer.py tests/ingestion/test_excel_importer.py tests/ingestion/test_epub_importer.py tests/ingestion/test_pdf_importer.py tests/llm/test_run_settings.py tests/cli/test_toggle_editor.py tests/cli/test_cli_output_structure.py tests/labelstudio/test_labelstudio_ingest_parallel.py tests/labelstudio/test_labelstudio_benchmark_helpers.py

5. Validate shared backend behavior on a known sectioned fixture.

    cookimport stage tests/fixtures/sectioned_components_recipe.txt --out /tmp/priority2-shared --workers 1 --pdf-split-workers 1 --epub-split-workers 1 --no-write-markdown --section-detector-backend shared_v1

6. Compare baseline/shared artifacts.

    diff -u /tmp/priority2-baseline/*/sections/sectioned_components_recipe/r0.sections.json /tmp/priority2-shared/*/sections/sectioned_components_recipe/r0.sections.json

If `diff` output is empty, section grouping stayed identical for this fixture.


## Validation and Acceptance


Acceptance is behavior-based.

1. Section artifacts remain structurally valid:
   - `sections/<workbook_slug>/r0.sections.json` exists and contains expected section keys (`meat`, `gravy`) for `sectioned_components_recipe.txt`.
2. Intermediate JSON-LD still emits grouped instruction sections where applicable.
3. Step-ingredient linking continues to consume section keys without regression.
4. `stage` and `labelstudio-benchmark` reports show `runConfig.section_detector_backend`.
5. Legacy fallback remains available:
   - `--section-detector-backend legacy` preserves prior behavior.
6. No codex-farm recipe parsing is enabled as part of this priority.


## Idempotence and Recovery


This rollout is designed to be additive and reversible.

- Safe re-run: milestone commands can be repeated without destructive side effects.
- Recovery switch: force old behavior with `--section-detector-backend legacy`.
- If shared backend introduces regression, disable it and keep `legacy` default while fixing targeted tests.
- Do not remove legacy path until shared backend has stable fixture and benchmark evidence.


## Artifacts and Notes


Expected run-config evidence after Milestone 5:

    {
      "runConfig": {
        "section_detector_backend": "shared_v1",
        "epub_extractor": "unstructured",
        "recipe_scorer_backend": "heuristic_v1"
      }
    }

Expected section artifact shape (simplified):

    {
      "title": "Meat and Gravy",
      "sections": [
        {"key": "meat", "ingredients": [...], "steps": [...]},
        {"key": "gravy", "ingredients": [...], "steps": [...]} 
      ]
    }

If shared detector adds debug rows, keep them under deterministic raw artifact naming and ensure split-merge raw handling remains compatible.


## Interfaces and Dependencies


Required interfaces after Milestones 1-5.

In `cookimport/parsing/section_detector.py`:

    class SectionKind(str, Enum):
        INGREDIENTS = "ingredients"
        INSTRUCTIONS = "instructions"
        NOTES = "notes"
        OTHER = "other"

    @dataclass(frozen=True)
    class SectionSpan:
        kind: SectionKind
        key: str
        name: str
        start_index: int
        end_index: int
        header_index: int | None

    @dataclass(frozen=True)
    class DetectedSections:
        spans: list[SectionSpan]

    def detect_sections_from_lines(lines: list[str], *, overrides: ParsingOverrides | None = None) -> DetectedSections: ...

    def detect_sections_from_blocks(blocks: list[Block], *, overrides: ParsingOverrides | None = None) -> DetectedSections: ...

In `cookimport/config/run_settings.py`:

    class SectionDetectorBackend(str, Enum):
        legacy = "legacy"
        shared_v1 = "shared_v1"

    class RunSettings(BaseModel):
        section_detector_backend: SectionDetectorBackend = Field(default=SectionDetectorBackend.legacy, ...)

In `cookimport/parsing/sections.py`:

- Existing public functions remain available and backward compatible:
  - `extract_ingredient_sections(...)`
  - `extract_instruction_sections(...)`
  - `normalize_section_key(...)`

Dependency policy for this priority:

- No new mandatory third-party dependencies in core rollout.
- Optional advanced backends can be proposed later, but are out of core Priority 2 scope until baseline shared detector is stable.


## Revision Notes


- 2026-02-27_22.14.51 (Codex GPT-5): Replaced stale duplicated Priority 2 draft with a current ExecPlan aligned to real code paths, added required front matter, removed invalid citation placeholders/missing-file references, and scoped rollout to deterministic shared detection with explicit legacy fallback.
