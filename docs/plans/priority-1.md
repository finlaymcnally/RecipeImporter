---
summary: "ExecPlan for Priority 1: deterministic recipe-likeness scoring and confidence gating across all importers."
read_when:
  - "When implementing accept/partial/reject gating for recipe candidates"
  - "When adding recipe-likeness reporting or debug artifacts"
  - "When introducing optional benchmark permutations tied to recipe-likeness"
---

# Build Priority 1: Deterministic Recipe-Likeness Gates Across Importers


This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository includes `docs/PLANS.md` at the repository root. This plan must be maintained in accordance with that file.


## Purpose / Big Picture


After this change, every importer will produce a deterministic recipe-likeness result for each candidate and apply explicit confidence gates before deciding whether to keep, keep-as-partial, or reject that candidate.

The user-visible outcome is simple and testable: low-quality candidate recipes stop polluting recipe outputs, while their underlying text still remains available as non-recipe content for tip/topic/chunk flows.

You can verify behavior by running `cookimport stage` on the same input before and after the change and observing all of the following in output artifacts:

1. Every emitted recipe includes a structured `recipeLikeness` payload (score, tier, backend/version, reasons).
2. The workbook report contains a `recipeLikeness` summary (counts by tier, thresholds, score distribution, rejected count).
3. Rejected candidates do not appear in recipe outputs but do appear in `nonRecipeBlocks` (or equivalent preserved text records for record-first importers).
4. The run writes a raw debug artifact with one line per accepted/rejected candidate decision.


## Progress


- [x] (2026-02-27_21.17.56) Ran docs discovery (`npm run docs:list`) and read required docs: `docs/PLANS.md`, `docs/AGENTS.md`, `docs/03-ingestion/03-ingestion_readme.md`, `docs/05-staging/05-staging_readme.md`, and `docs/02-cli/02-cli_README.md`.
- [x] (2026-02-27_21.17.56) Audited current Priority 1 draft against repo reality (`cookimport/core/scoring.py`, importer call sites, model/report contracts, split merge behavior).
- [x] (2026-02-27_21.17.56) Rebuilt `docs/plans/priority-1.md` as a current, self-contained ExecPlan with explicit core milestones and optional permutation milestones.
- [x] (2026-02-27_21.58.34) Implemented core recipe-likeness contracts in `cookimport/core/models.py` and `cookimport/core/scoring.py` (`RecipeLikenessTier`, `RecipeLikenessResult`, gate action mapping, report summary helper, debug-row helper, legacy float scorer compatibility).
- [x] (2026-02-27_22.00.11) Integrated scoring/gating across all importer families (`text`, `excel`, `epub`, `pdf`, `paprika`, `recipesage`) with reject-path preservation in `nonRecipeBlocks` and raw `recipe_scoring_debug.jsonl` artifact output.
- [x] (2026-02-27_22.00.48) Wired run settings through worker and Label Studio prediction paths so importers receive scoring thresholds consistently (`cookimport/cli_worker.py`, `cookimport/plugins/base.py`, `cookimport/labelstudio/ingest.py`, `cookimport/config/run_settings_adapters.py`).
- [x] (2026-02-27_22.01.27) Added/updated focused tests for scoring, importer gate behavior, and split-merge raw artifact preservation.
- [x] (2026-02-27_22.02.29) Captured stage-run evidence via `cookimport stage tests/fixtures/simple_text.txt --out /tmp/priority1-evidence --no-write-markdown --workers 1 --pdf-split-workers 1 --epub-split-workers 1`; verified report `recipeLikeness` payload and raw `recipe_scoring_debug.jsonl`.
- [x] (2026-02-27_22.03.15) Closed remaining regressions: PDF `json` import, WorkbookInspection fallback contract in Paprika/RecipeSage, fixture-independent Paprika/RecipeSage tests, and min-ingredient default parity (`1`) across stage/benchmark run settings.
- [ ] Optional permutation lane (Milestone 6) remains future work by design; core Priority-1 acceptance criteria are complete without optional backends.


## Surprises & Discoveries


- Observation: `docs/plans/priority-1.md` was a verbatim copy of `docs/plans/OGplan/priority-1.md`, which made the “active” plan indistinguishable from the archive copy.
  Evidence: `cmp -s docs/plans/priority-1.md docs/plans/OGplan/priority-1.md` returned identical.

- Observation: The previous draft referenced `BIG PICTURE UPGRADES.md`, but that file does not exist in this repository.
  Evidence: `sed -n '1,220p' "BIG PICTURE UPGRADES.md"` failed with “No such file or directory”.

- Observation: Recipe codex-farm parsing remains policy-locked off at run-settings normalization and must stay off for this work.
  Evidence: `cookimport/config/run_settings.py` contains `RECIPE_CODEX_FARM_PIPELINE_POLICY` and coercion to `llm_recipe_pipeline=off`.

- Observation: Paprika and RecipeSage tests were coupled to `docs/template/examples/*`, but that folder is not present in this workspace.
  Evidence: `ls -la docs/template/examples` returned “No such file or directory”.

- Observation: `WorkbookInspection` is strict (`extra="forbid"`), so top-level `warnings=[...]` in importer inspect fallback paths causes validation failures.
  Evidence: failing tests raised `ValidationError ... WorkbookInspection ... warnings Extra inputs are not permitted`.

- Observation: scorer defaults and run-settings defaults can diverge if `recipe_score_min_ingredient_lines` is changed only inside `core/scoring.py`.
  Evidence: `core/scoring.py` default was `1` while run-settings/CLI/pred-run call surfaces still defaulted to `2` before parity patching.


## Decision Log


- Decision: Implement Priority 1 in two tracks: a required deterministic core lane and an optional permutation lane.
  Rationale: Core gating/reporting is the product requirement; optional libraries are benchmark options and must not block core delivery.
  Date/Author: 2026-02-27_21.17.56 / Codex GPT-5

- Decision: Build on existing `cookimport/core/scoring.py` and extend it with richer recipe-likeness outputs, rather than introducing a parallel primary scorer path.
  Rationale: All importer families already call this module, so extending it minimizes integration churn.
  Date/Author: 2026-02-27_21.17.56 / Codex GPT-5

- Decision: Keep report/output contract additive only (`RecipeCandidate.recipeLikeness` and `ConversionReport.recipeLikeness`), preserving existing fields such as `confidence`.
  Rationale: Existing dashboards/tests consume current fields; additive changes reduce regression risk.
  Date/Author: 2026-02-27_21.17.56 / Codex GPT-5

- Decision: Reject-path content preservation is mandatory for every importer family.
  Rationale: Priority 1 must reduce recipe false positives without starving downstream knowledge/tip/topic extraction.
  Date/Author: 2026-02-27_21.17.56 / Codex GPT-5

- Decision: Set `recipe_score_min_ingredient_lines` default to `1` across `RunSettings`, `stage`, and Label Studio benchmark/pred-run entrypoints.
  Rationale: Keeps CLI-driven runs behaviorally aligned with scorer defaults and avoids over-rejecting short but valid recipes.
  Date/Author: 2026-02-27_22.03.15 / Codex GPT-5

- Decision: Replace file-path-dependent Paprika/RecipeSage tests with local tmp fixtures.
  Rationale: Removes hidden dependency on a missing docs folder and keeps ingestion tests deterministic in any workspace clone.
  Date/Author: 2026-02-27_22.03.15 / Codex GPT-5


## Outcomes & Retrospective


Core outcome (implemented):

- Mandatory Priority-1 delivery is complete: all importers now attach `recipeLikeness`, apply deterministic gate actions, preserve rejected content in non-recipe flow, emit scoring debug rows, and write report-level recipe-likeness summary.
- Focused validation passed in `.venv`:
  - `pytest -q tests/core/test_recipe_likeness_scoring.py tests/ingestion/test_text_importer.py tests/ingestion/test_excel_importer.py tests/ingestion/test_epub_importer.py tests/ingestion/test_pdf_importer.py tests/ingestion/test_paprika_importer.py tests/ingestion/test_recipesage_importer.py tests/staging/test_split_merge_status.py`
  - Result: all selected tests passed.
- Stage artifact evidence captured at `/tmp/priority1-evidence/2026-02-27_22.02.29`:
  - report: `/tmp/priority1-evidence/2026-02-27_22.02.29/simple_text.excel_import_report.json` includes `recipeLikeness` summary with tier counts and thresholds.
  - raw debug: `/tmp/priority1-evidence/2026-02-27_22.02.29/raw/text/b62452244ef1739762a70bd1bf93f14f977d6fa51ce612223b0c2dbe07ce17f8/recipe_scoring_debug.jsonl`.

Scope left intentionally open:

- Optional permutation lane (Milestone 6) is not implemented in this pass; no optional dependencies/backends were added.


## Context and Orientation


Current ingestion architecture converges every importer into `ConversionResult` (`cookimport/core/models.py`) and then writes outputs via staging writers.

Key model and report surfaces:

- `cookimport/core/models.py`
  - `RecipeCandidate` now carries both `confidence` and additive `recipeLikeness`.
  - `ConversionReport` now supports additive `recipeLikeness` summary.
  - `ConversionResult` includes `recipes`, `nonRecipeBlocks`, `rawArtifacts`, and `report`.

Current scoring behavior:

- `cookimport/core/scoring.py` exposes `score_recipe_likeness(...)`, `recipe_gate_action(...)`, `summarize_recipe_likeness(...)`, and `build_recipe_scoring_debug_row(...)`.
- `score_recipe_candidate(...) -> float` remains as compatibility wrapper.
- Importers set `confidence = recipeLikeness.score` and use gate actions to keep/reject candidates.

Current importer integration points:

- Record-first: `cookimport/plugins/text.py`, `cookimport/plugins/excel.py`
- Structured-first: `cookimport/plugins/paprika.py`, `cookimport/plugins/recipesage.py`
- Block-first: `cookimport/plugins/epub.py`, `cookimport/plugins/pdf.py`
- Every family now writes raw `recipe_scoring_debug.jsonl` artifacts and report-level `recipeLikeness` summary.

Split-merge and raw-artifact behavior:

- `cookimport/cli.py` handles split merge and raw artifact movement via `_merge_split_jobs(...)` and `_merge_raw_artifacts(...)`.
- Raw artifact filename collisions are resolved with deterministic `job_<index>_` prefixes.
- Split-merge now preserves per-job scoring debug artifacts and includes merged report `recipeLikeness` summary.

Terminology used below:

- Recipe-likeness result: structured scoring payload with numeric score, tier, reasons, and backend/version metadata.
- Gate action: importer decision derived from tier (`keep_full`, `keep_partial`, `reject`).
- Partial keep: emit recipe candidate but do not synthesize missing ingredient/instruction content.


## Plan of Work


### Milestone 0: Baseline and guardrails

Before editing scoring logic, capture baseline behavior and confirm that codex-farm parsing stays off.

Work:

1. Run focused baseline tests that currently cover importer behavior and report output shape.
2. Run one baseline stage example from `data/input` and keep the report for before/after comparison.
3. Confirm baseline report currently has no `recipeLikeness` key and importer outputs include ungated candidates.

Acceptance:

- Baseline command outputs are recorded in `Progress`.
- Baseline run artifact path is recorded for later comparison.


### Milestone 1: Add structured recipe-likeness models and deterministic gate primitives

Implement the primary contract in `cookimport/core/models.py` and `cookimport/core/scoring.py`.

Work:

1. In `cookimport/core/models.py`, add:
   - `RecipeLikenessTier` enum: `gold`, `silver`, `bronze`, `reject`.
   - `RecipeLikenessResult` model with fields:
     - `score` (`0.0..1.0`),
     - `tier`,
     - `backend`,
     - `version`,
     - `features` (`dict[str, float | int | bool | str]`),
     - `reasons` (`list[str]`).
   - Optional `recipe_likeness` on `RecipeCandidate` with alias `recipeLikeness`.

2. In `cookimport/core/scoring.py`, keep backward compatibility while adding richer APIs:
   - Keep `score_recipe_candidate(...) -> float` for legacy callers.
   - Add `score_recipe_likeness(...) -> RecipeLikenessResult`.
   - Add `recipe_gate_action(...) -> Literal["keep_full", "keep_partial", "reject"]`.

3. Deterministic `heuristic_v1` feature set:
   - ingredient count/density,
   - instruction count/density,
   - title quality,
   - optional heading-anchor hints,
   - short/long length penalties,
   - noise penalty inputs (initially from simple deterministic heuristics; optional dedupe backend later).

4. Tier thresholds are explicit and configurable (default values live in run settings in Milestone 2).

Acceptance:

- New model serialization works with `model_dump(by_alias=True)`.
- Scorer returns deterministic output for fixed inputs.
- Existing callers of `score_recipe_candidate` continue to function.


### Milestone 2: Extend run settings and report summary contracts

Add configuration and report surfaces so scoring decisions are visible and reproducible.

Work:

1. Extend `RunSettings` in `cookimport/config/run_settings.py` with additive fields and UI metadata:
   - `recipe_scorer_backend` (default `heuristic_v1`),
   - `recipe_score_gold_min`,
   - `recipe_score_silver_min`,
   - `recipe_score_bronze_min`,
   - `recipe_score_min_ingredient_lines`,
   - `recipe_score_min_instruction_lines`.

2. Add these fields to settings summary/hash ordering where appropriate so benchmark comparisons can detect meaningful config drift.

3. Extend `ConversionReport` in `cookimport/core/models.py` with optional `recipe_likeness` alias `recipeLikeness`.

4. Add helper in `cookimport/core/scoring.py` (or `cookimport/core/reporting.py`) to produce report summary payload:
   - backend/version,
   - thresholds,
   - counts by tier,
   - score min/p50/p90/max,
   - `rejected_candidate_count`.

Acceptance:

- Report JSON includes `recipeLikeness` when scoring runs.
- Existing report keys remain unchanged.


### Milestone 3: Integrate scoring and gate actions into record-first and structured-first importers

Wire the new scoring result into `text`, `excel`, `paprika`, and `recipesage` conversion flows.

Work:

1. Replace float-only scoring assignment with:
   - `recipe.recipeLikeness = score_recipe_likeness(...)`,
   - `recipe.confidence = recipe.recipeLikeness.score` for compatibility.

2. Apply gate actions per candidate:
   - `keep_full`: append to `recipes` unchanged.
   - `keep_partial`: append to `recipes` without synthesizing missing ingredient/instruction content.
   - `reject`: do not append to `recipes`; preserve rejected source text into `nonRecipeBlocks` with deterministic provenance fields.

3. Report updates per importer:
   - Track per-tier counts and rejected candidate count.
   - Add warning entries only for truly exceptional parse failures, not normal reject decisions.

Acceptance:

- New tests show one accepted and one rejected candidate for text and excel fixtures.
- Structured importers retain deterministic ordering and IDs while now emitting recipe-likeness data.


### Milestone 4: Integrate scoring and gate actions into block-first importers and split-merge flows

Wire the same logic into EPUB/PDF span-based candidate extraction and ensure split-job behavior remains deterministic.

Work:

1. In `cookimport/plugins/epub.py` and `cookimport/plugins/pdf.py`, score each candidate span before final append.
2. Apply gate action:
   - `reject` spans are excluded from `recipes` and preserved in `nonRecipeBlocks`.
   - accepted spans continue through tip/topic extraction as today.
3. Preserve span provenance in both accepted and rejected scoring debug rows.
4. Ensure split-job merge still behaves correctly when each job produced scoring debug raw artifacts.

Acceptance:

- Stage runs for EPUB/PDF emit tier counts and rejected span counts.
- Split merge runs keep deterministic merged output and correctly move raw scoring artifacts.


### Milestone 5: Add deterministic raw scoring debug artifact

Capture one reproducible line per candidate decision.

Work:

1. Emit `RawArtifact` entries that produce `recipe_scoring_debug.jsonl` under `raw/<importer>/<source_hash>/`.
2. One JSON line per candidate decision includes:
   - candidate identity,
   - span/location metadata,
   - scorer backend/version,
   - score/tier/reasons/features,
   - final gate action.
3. For split jobs, rely on existing merge collision rules so no debug output is lost.

Acceptance:

- `recipe_scoring_debug.jsonl` exists for representative runs and includes both accepted and rejected decisions.


### Milestone 6: Optional permutation lane (additive only)

These are explicit options, not replacements. They should be implemented only after Milestones 0-5 are stable.

Work packages:

1. Near-duplicate noise backend (`datasketch`) as an optional scorer signal source.
2. Segmentation metrics (`segeval`) in benchmark/eval reports for threshold tuning.
3. Additional HTML-ish extractors (`trafilatura`, `readability-lxml`, optional `jusText`, `BoilerPy3`, `goose3`, `newspaper3k`) as selectable extraction lanes.
4. Schema-first lane (`extruct`) as selectable candidate source with the same scoring gates.
5. Optional advanced scorer backends (`transitions`, CRF-related libs, `skweak`) behind explicit backend switches.
6. Optional PDF structure extractors (`Docling`, `PyMuPDF4LLM`, `Marker`, `MinerU`) as selectable backends.

Rules for this milestone:

- Every optional backend fails fast with a clear install hint.
- Default behavior remains unchanged when optional deps are absent.
- No path may enable recipe codex-farm parsing.

Acceptance:

- Optional backends are benchmark-selectable and skip/fail gracefully when dependencies are missing.


### Milestone 7: Tests, docs, and closure

Finalize with behavior evidence and documentation updates.

Work:

1. Add unit tests for scoring tiers and gate decisions.
2. Add importer integration tests for reject/partial/accept behavior.
3. Add split-merge coverage for scoring debug artifacts.
4. Update docs minimally:
   - `docs/03-ingestion/03-ingestion_readme.md`
   - `docs/05-staging/05-staging_readme.md`
   - `docs/02-cli/02-cli_README.md` (if new run settings are exposed)
5. Update this ExecPlan `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` with final evidence.

Acceptance:

- Tests pass in `.venv` with dev dependencies installed.
- Docs describe new behavior without contradicting runtime.


## Concrete Steps


Run from repo root:

    cd /home/mcnal/projects/recipeimport
    source .venv/bin/activate
    PIP_CACHE_DIR=/tmp/.pip-cache python -m pip install -e '.[dev]'

Re-run docs index before and after code/doc changes:

    npm run docs:list

Baseline and focused validation commands:

    pytest -q tests/ingestion/test_pdf_importer.py tests/ingestion/test_epub_importer.py tests/ingestion/test_text_importer.py tests/ingestion/test_excel_importer.py

Add and run new scoring tests:

    pytest -q tests/core/test_recipe_likeness_scoring.py

Run stage smoke check on one known input:

    cookimport stage data/input --limit 3

Inspect resulting artifacts in newest `data/output/<YYYY-MM-DD_HH.MM.SS>/` run folder:

    <workbook>.excel_import_report.json
    raw/<importer>/<source_hash>/recipe_scoring_debug.jsonl

If split-run behavior is touched, run split-merge staging tests:

    pytest -q tests/staging/test_split_merge_status.py


## Validation and Acceptance


This plan is accepted when all of the following are true.

1. All importers attach `recipeLikeness` to emitted recipes and preserve `confidence` compatibility.
2. Gate actions are applied consistently (`keep_full`, `keep_partial`, `reject`) and rejected content is preserved as non-recipe material.
3. Workbook reports include `recipeLikeness` summary payload with deterministic counts/stats.
4. Raw debug artifact exists and includes reproducible decision evidence for accepted and rejected candidates.
5. Optional backends, when implemented, are additive and do not change default behavior in environments without those dependencies.
6. Codex-farm recipe parsing remains disabled.


## Idempotence and Recovery


- Scoring and gating must be deterministic: no randomness, no network calls, no time-dependent thresholds.
- Re-running stage with the same input and run settings must produce the same tier assignments and gate decisions.
- Optional backend imports must fail with actionable messages and never break default paths.
- If one optional backend fails, fallback to default backend should be explicit and reported.
- Split-job raw artifact collisions rely on existing deterministic collision prefixing (`job_<index>_...`).


## Artifacts and Notes


Expected report section (illustrative shape):

    {
      "recipeLikeness": {
        "backend": "heuristic_v1",
        "version": "2026-02-28",
        "thresholds": {
          "gold": 0.75,
          "silver": 0.55,
          "bronze": 0.35
        },
        "counts": {
          "gold": 4,
          "silver": 2,
          "bronze": 1,
          "reject": 3
        },
        "scoreStats": {
          "min": 0.21,
          "p50": 0.67,
          "p90": 0.88,
          "max": 0.94
        },
        "rejectedCandidateCount": 3
      }
    }

Expected JSONL line in `recipe_scoring_debug.jsonl` (illustrative):

    {"candidate_id":"urn:...","gate_action":"reject","result":{"score":0.31,"tier":"reject","backend":"heuristic_v1","version":"2026-02-28","reasons":["missing_instructions"],"features":{"ingredient_count":2,"instruction_count":0}},"location":{"start_block":120,"end_block":138}}


## Interfaces and Dependencies


Required interfaces to exist after Milestones 1-5.

In `cookimport/core/models.py`:

    class RecipeLikenessTier(str, Enum):
        gold = "gold"
        silver = "silver"
        bronze = "bronze"
        reject = "reject"

    class RecipeLikenessResult(BaseModel):
        score: float
        tier: RecipeLikenessTier
        backend: str
        version: str
        features: dict[str, Any]
        reasons: list[str]

    class RecipeCandidate(BaseModel):
        recipe_likeness: RecipeLikenessResult | None = Field(default=None, alias="recipeLikeness")

    class ConversionReport(BaseModel):
        recipe_likeness: dict[str, Any] | None = Field(default=None, alias="recipeLikeness")

In `cookimport/core/scoring.py`:

    def score_recipe_likeness(candidate: RecipeCandidate, *, settings: RunSettings | None = None) -> RecipeLikenessResult: ...

    def score_recipe_candidate(candidate: RecipeCandidate) -> float: ...

    def recipe_gate_action(result: RecipeLikenessResult, *, settings: RunSettings | None = None) -> str: ...

    def summarize_recipe_likeness(results: Sequence[RecipeLikenessResult], rejected_count: int, *, settings: RunSettings | None = None) -> dict[str, Any]: ...

Dependency policy:

- Core lane (Milestones 0-5) uses no new mandatory dependencies.
- Optional lane dependencies are grouped as extras and must remain optional.


## Revision Notes


- 2026-02-27_21.17.56 (Codex GPT-5): Replaced the previous duplicated Priority 1 draft with a current ExecPlan that matches real code paths, adds required docs front matter, removes references to missing files, and separates required delivery from optional backend permutations.
- 2026-02-27_22.03.15 (Codex GPT-5): Updated the plan from design state to implementation-complete core state with concrete test/stage evidence, final decisions/discoveries, and explicit deferral of the optional permutation lane.
