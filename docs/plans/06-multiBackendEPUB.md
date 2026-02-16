# Add multi-backend “race and auto-pick best output” for EPUB, integrated with per-run RunSettings

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository includes `PLANS.md` at the repository root. This ExecPlan must be maintained in accordance with `PLANS.md` (same path).

## Purpose / Big Picture

EPUB import quality is currently fragile, and choosing the “least bad” extractor/segmentation path is a manual, time-consuming process. The trick that saves time is to **run multiple backends for the same input**, score their outputs deterministically, and **auto-pick the best** — while keeping full traceability so you can later see which backend won, why, and how often.

After this change:

- Importing an EPUB can be configured (per-run, via the existing Run Settings chooser/editor) to use **single-backend** mode or **auto-best-of** mode.
- In auto-best-of mode, the system runs multiple EPUB extraction backends (initially: `legacy` vs `unstructured`, but extensible), computes a deterministic **QualityScoreV1**, and selects the best candidate.
- The selection decision and candidate scores are recorded in the per-file report JSON (and surfaced in history/dashboard), so you can benchmark and compare permutations without guesswork.
- You also get a developer-facing “race” command to compare backends on one EPUB and produce a compact, inspectable report.

This plan explicitly integrates with the already-implemented **per-run RunSettings selector/editor + runConfig persistence** (see the implemented ExecPlan “Add per-run Run Settings selector + toggle editor, with runConfig persistence”). We will build on that system rather than reinventing settings/traceability.

## Progress

- [x] (2026-02-16) Prerequisite confirmed: per-run `RunSettings` model + chooser/editor + runConfig hash/summary persistence already exist and are wired into reports/CSV/dashboard.
- [ ] (2026-02-16) Add `QualityScoreV1` deterministic heuristic scorer and persist it into conversion reports.
- [ ] Add a generic “backend race” engine with failure-tolerant candidate execution + stable tie-breaking + structured race report.
- [ ] Wire EPUB importer to support “single backend” vs “race and pick best” using RunSettings fields, and record selection details into report JSON.
- [ ] Ensure split-job EPUB runs behave safely (initially: warn/disable race in split mode; later: add probe-based preflight selection so all jobs use one chosen backend).
- [ ] Surface key race outputs in analytics (CSV + dashboard) for visibility across runs.
- [ ] Add `cookimport backend-race …` developer command (and/or `cookimport inspect …` enhancement) to run race on one EPUB and print/emit comparison artifacts.
- [ ] Add tests (unit + integration-ish) covering scoring stability, race selection determinism, report field presence, and “add a new backend” guardrails.
- [ ] Update docs: “How to add a backend candidate”, “How scoring works”, and “How to run sweeps / interpret dashboards”.

## Surprises & Discoveries

- None yet. As implementation proceeds, capture surprises with evidence (test output, logs, or small excerpts).

## Decision Log

- Decision: Reuse the existing canonical per-run `RunSettings` system as the source of truth for enabling/disabling backend racing and for ensuring runConfig traceability.
  Rationale: The project already has a strong “one canonical place” contract for run knobs and reporting; backend racing should be another knob, not a parallel configuration stack.
  Date/Author: 2026-02-16 / assistant

- Decision: Introduce a deterministic heuristic “QualityScoreV1” for auto-selection, rather than requiring Label Studio gold data or an LLM judge.
  Rationale: Auto-selection must work for brand-new books without ground truth and must be cheap and reproducible. Gold-based eval remains valuable for benchmarking, but should not be required to run the pipeline.
  Date/Author: 2026-02-16 / assistant

- Decision: Record backend-race results (candidates + scores + selected backend) as structured report data, not only as console output.
  Rationale: The pipeline’s core value includes traceability and visibility. If the system picks a backend automatically, you must be able to audit that decision later.
  Date/Author: 2026-02-16 / assistant

## Outcomes & Retrospective

- Not started. At completion, summarize what was achieved, what remains, and what you would do differently.

## Context and Orientation

This repository is a Python 3.12 CLI-first recipe import pipeline. It supports multiple source formats through a plugin architecture and converges into shared staging/writing/reporting.

Key existing components this plan builds on:

1) Per-run settings and traceability (already implemented)
- `cookimport/config/run_settings.py` defines the canonical `RunSettings` model with:
  - typed fields representing run knobs,
  - UI metadata so the toggle-table editor can render settings rows automatically,
  - `stable_hash()` and `summary()` used to persist config identity into run artifacts.
- `cookimport/config/last_run_store.py` persists “last run settings” separately for `import` vs `benchmark`.
- Interactive flows in `cookimport/cli.py` route Import/Benchmark through a “Run Settings mode” chooser (global / last / edit), then print the chosen summary before running.
- Conversion reports JSON, the performance history CSV, and the dashboard collector/renderer already carry `run_config_hash` + `run_config_summary`, and reports store the structured `runConfig` snapshot.

2) EPUB import path (current architecture)
- The EPUB importer lives under `cookimport/plugins/epub.py` and implements the standard importer protocol (`detect`, `inspect`, `convert`).
- Conversion returns a `ConversionResult` containing recipes/tips/topics/non-recipe blocks/raw artifacts plus a per-file `ConversionReport`.
- Staging orchestration occurs in `cookimport/cli.py` and `cookimport/cli_worker.py` and writes outputs + report JSON via `cookimport/staging/writer.py`.
- EPUB inputs may be split into spine-based jobs for parallelism (split-job planning/merge behavior is part of ingestion/staging).

Terms used in this plan:

- Backend: An alternative implementation that produces the same “kind” of intermediate output. For this plan, it initially means “EPUB extraction backend” (e.g., `legacy` vs `unstructured`) but the design should generalize to other toggles later.
- Candidate: One backend run option within a race (backend id + any RunSettings overrides applied).
- Race: Running multiple candidates on the same input (or a representative probe), scoring each result, and selecting the best deterministically.
- QualityScoreV1: A deterministic heuristic score computed from a `ConversionResult` (primarily recipe candidate shape + missing fields + warnings) used for auto-selection.

## Plan of Work

### Milestone 1: Add deterministic QualityScoreV1 and persist it into the report

At the end of this milestone, every conversion report contains a numeric “quality score” and a small breakdown of signals that produced it. This score is computed deterministically from the conversion output and is cheap enough to run for every file.

Work:

1) Create a small quality scoring module, suggested path:
- `cookimport/quality/scoring_v1.py`

2) Define a Pydantic model for scoring output, suggested:

- `QualityScoreV1`
  - `overall: float` (0–100)
  - `signals: dict[str, float]` (named components; stable keys)
  - `notes: list[str]` (human explanations, stable-ish but can evolve)
  - `version: str = "v1"`

3) Implement `score_conversion_result_v1(result: ConversionResult) -> QualityScoreV1` using only deterministic signals that exist without ground truth. The initial scoring recipe should prioritize:
- Penalize missing critical recipe fields (name, ingredients, instructions).
- Reward a higher fraction of “well-formed recipes” (recipes having name + >=1 ingredient + >=1 instruction).
- Penalize pathological segmentation signals:
  - absurd recipe count relative to block count or extracted char count (use conservative heuristics),
  - extremely high duplicate-title rate,
  - extremely low average ingredient/instruction counts.
- Penalize conversion errors/warnings recorded in the report (if those exist).
- If candidate segmentation score/confidence already exists, incorporate it as a gentle positive signal (do not make it dominate).

Important constraints:
- Scoring must be stable across runs (no randomness).
- If the result has 0 recipes, score should be low but not crash.
- If some metrics are missing for certain importers, treat them as “unknown” rather than failing.

4) Persist the score into the report schema:
- Update `cookimport/core/models.py` where `ConversionReport` is defined (or wherever report schema lives).
- Add optional fields:
  - `qualityScoreV1: float | None`
  - `qualitySignalsV1: dict[str, float] | None`
  - `qualityNotesV1: list[str] | None`
  - `qualityVersion: str | None` (to allow future versions)
- Ensure defaults are None so older reports remain readable.

5) Populate these fields in the conversion/report-building path:
- Find the “report builder” location used by the active stage writer (per docs, this is not necessarily the legacy `core/reporting.py`).
- After conversion completes but before report JSON is written, compute `QualityScoreV1` and attach fields to the report.

Proof/acceptance:

- Run `cookimport stage data/input/some.epub` and inspect the written report JSON:
  - it contains `qualityScoreV1` and `qualitySignalsV1`.
- Unit test proves scoring determinism:
  - calling `score_conversion_result_v1` twice on the same fixture result yields identical output.

### Milestone 2: Implement a generic backend race engine (candidate runner + scorer + stable selection)

At the end of this milestone, there is a reusable “race” helper that can run N candidates, tolerate failures, score each candidate, and choose the winner deterministically while producing a structured race report.

Work:

1) Create a backend race module, suggested path:
- `cookimport/backends/race.py`

2) Define Pydantic models to persist race outcomes (these will be embedded into the conversion report):

- `BackendRaceCandidateReport`
  - `candidateId: str` (stable id like `epub:legacy`)
  - `backendId: str` (e.g., `legacy`, `unstructured`)
  - `runConfigHash: str` and `runConfigSummary: str` (the candidate’s effective settings identity)
  - `qualityScoreV1: float | None`
  - `qualitySignalsV1: dict[str, float] | None`
  - `status: Literal["ok","error"]`
  - `errorType: str | None`, `errorMessage: str | None` (short; keep long trace in logs, not report)
  - `timingSeconds: float | None` (optional but useful)

- `BackendRaceReport`
  - `mode: str` (e.g., `auto_best`)
  - `candidates: list[BackendRaceCandidateReport]`
  - `selectedCandidateId: str | None`
  - `selectedBackendId: str | None`
  - `selectionRationale: str` (short: “highest QualityScoreV1; tie-break by fewer errors then stable candidate order”)
  - `raceVersion: str = "v1"`

3) Implement a helper function that is generic and easy to reuse:

- `run_backend_race_v1(...) -> tuple[selected_result, BackendRaceReport]`

Inputs should be:
- `base_settings: RunSettings`
- `candidates: list[BackendCandidateSpec]` where each spec has:
  - `backend_id: str`
  - `settings_overrides: dict[str, object]` (usually just `{ "epub_extractor": "legacy" }`)
  - `candidate_id: str` (derived, stable)
- `run_one(settings: RunSettings) -> ConversionResult` (calls into the actual importer/pipeline)
- `score_one(result: ConversionResult) -> QualityScoreV1`

Selection algorithm must be deterministic:
- Exclude errored candidates unless all candidates error.
- Prefer the highest `qualityScoreV1.overall`.
- If tie, prefer fewer report errors/warnings if available; else stable order.
- If all error, raise the “best” error but include the race report in logs (and, where possible, attach to report for post-mortem).

4) Add `BackendRaceReport` as an optional field on `ConversionReport` (or nested under a new `backendSelection`/`backendRace` field). The report JSON should be sufficient to answer:
- what candidates were tried,
- how they scored,
- which one was selected,
- and whether any candidate failed.

Proof/acceptance:

- Add unit tests with a fake `run_one` that returns synthetic `ConversionResult`-like objects and a fake scorer:
  - proves stable tie-breaking,
  - proves failure-tolerant behavior (one candidate errors, another wins),
  - proves that candidate ordering is stable and deterministic.

### Milestone 3: Wire EPUB importer to use backend racing based on RunSettings (single vs auto-best)

At the end of this milestone, EPUB conversion supports auto-best-of mode and records a backend race report into the output report JSON. Only the selected candidate’s outputs are written as the run outputs.

Work:

1) Extend `RunSettings` with the knobs needed to enable racing:
- In `cookimport/config/run_settings.py`, add fields (names are suggestions; keep consistent with existing naming style):

  - `epub_backend_mode`: enum with at least:
    - `single` (default)
    - `auto_best` (race multiple backends and pick best)
  - `epub_backend_candidates`: optional “preset selector” OR keep it implicit for v1.
    - For v1, simplest: hardcode candidates `[legacy, unstructured]` when mode is `auto_best`.
    - If you add a selector, keep it as a simple enum like:
      - `legacy_vs_unstructured` (default)
      - `legacy_only`
      - `unstructured_only`
  - `backend_race_debug_dump`: bool default False (whether to write small candidate debug artifacts)
  - `backend_race_max_probe_spine_items`: int default 0 (0 means “no probing; run full candidate conversions”; used in Milestone 4)

Each new field must:
- have UI metadata so it appears in the toggle-table editor,
- be included in `RunSettings.to_run_config_dict()`,
- be included in `RunSettings.summary()` in a compact way,
- and be part of `stable_hash()` identity (because it materially changes behavior).

2) In `cookimport/plugins/epub.py`, identify where the backend is chosen today.
- There is currently an `epub_extractor` knob (per prior work). Factor the extractor choice into a dedicated function if it is not already:
  - `_convert_with_extractor(path, mapping, progress_callback, extractor_id, ...) -> ConversionResult`
- Ensure each backend has a stable id string that matches `RunSettings.epub_extractor` values.

3) Implement racing in the EPUB conversion path:
- If `run_settings.epub_backend_mode == "single"`:
  - run exactly one backend (the existing behavior).
- If `auto_best`:
  - build candidate list (v1: legacy + unstructured),
  - run `run_backend_race_v1` to obtain the selected `ConversionResult` and `BackendRaceReport`,
  - attach `BackendRaceReport` into the selected result’s report fields,
  - also attach the selected backend id somewhere obvious in report fields, e.g.:
    - `selectedBackendId: "unstructured"` or `epubSelectedExtractor: "unstructured"`.

Important: avoid output duplication
- Candidate conversions must not cause the stage writer to write drafts for losing candidates.
- The easiest safe approach is: run candidate conversions *inside* the importer and return only the selected `ConversionResult` to the stage writer.

4) Console visibility:
- During auto-best selection, print a compact summary (via Rich) such as:

    EPUB backend race (2 candidates):
      legacy: score=62.3 (ok)
      unstructured: score=79.0 (ok)
    Selected: unstructured (score=79.0)

This should happen regardless of interactive/non-interactive mode, because it is an important behavioral difference.

5) Failure handling:
- If one backend crashes, record it in the race report and continue.
- If all backends crash, raise, but ensure the exception message tells the user:
  - “All EPUB backends failed; see logs; race report recorded in … (if possible).”

Proof/acceptance:

- Run an EPUB import in interactive mode, set `epub_backend_mode=auto_best`, and observe:
  - console prints candidate scores and the selected backend.
  - report JSON includes backend race data.
- Re-run with the same file and settings and confirm the selected backend is stable.

### Milestone 4: Make racing safe and useful in split-job EPUB runs (probe-based selection)

At the end of this milestone, enabling `auto_best` does not create “mixed backend per job” behavior. Instead, the system either:
- (initially) disables race with a warning when split-job mode is active, or
- (preferred final) runs a small probe for each backend to choose one backend for the whole book, then uses that backend for all jobs.

Work:

1) Identify split-job planning for EPUB:
- Search for EPUB job planning modules (likely near `cookimport/staging/pdf_jobs.py` or similar).
- Find where EPUB jobs are planned and where worker jobs are executed/merged.

2) Implement “probe selection” when split jobs are active:
- If `run_settings.epub_backend_mode == auto_best` and `epub_split_workers > 1` (or equivalent):
  - If `backend_race_max_probe_spine_items == 0`:
    - Print a warning and fall back to single-backend mode (use the configured `epub_extractor`).
  - Else:
    - For each candidate backend:
      - run a conversion only over the first N spine items (or first job range), where N comes from `backend_race_max_probe_spine_items`.
      - score the probe results using `QualityScoreV1`.
    - Choose the best backend and use it for the full split run (all jobs use the same chosen backend).
    - Record in `BackendRaceReport` whether the race was “probe-based” and what N was.

3) Ensure report correctness:
- The final per-file report must clearly show:
  - race was probe-based,
  - which backend was selected,
  - candidate probe scores.

Proof/acceptance:

- Run a split-job EPUB stage (configure split workers > 1).
- Confirm:
  - selection occurs once,
  - all jobs use the same backend,
  - report JSON includes probe-based selection details.

### Milestone 5: Visibility and benchmarking surfaces (CSV + dashboard + quick “inspect” tools)

At the end of this milestone, you can see backend choices and quality scores across many runs without opening raw JSON.

Work:

1) Update perf history CSV append logic:
- In `cookimport/analytics/perf_report.py`, add columns populated from the per-file report JSON:
  - `quality_score_v1`
  - `selected_backend` (or `epub_selected_backend`)
  - `backend_race_mode` (optional)
- Keep columns stable and simple. Avoid exploding candidate lists into CSV.

2) Update dashboard ingestion/rendering:
- In `cookimport/analytics/dashboard_schema.py` and collector/renderer modules, ingest and render:
  - quality score and selected backend per run.
- Add at least one way to filter/group by:
  - run_config_hash (already exists),
  - selected backend (new).

3) Add a CLI helper for one-file inspection:
- Add a new command:
  - `cookimport backend-race <path-to-epub> --output-dir <...>`
- Behavior:
  - runs conversion in `auto_best` mode regardless of global defaults,
  - prints candidate comparison,
  - writes a small `backend_race.json` artifact in a predictable place (either under the run root or under a `debug/` subfolder),
  - does not write full drafts unless explicitly requested (default should be “report-only” for speed).

Proof/acceptance:

- Run the command on one EPUB and confirm:
  - console output shows candidate scores and winner,
  - a JSON artifact exists with the race report,
  - perf report and dashboard show quality score + selected backend for normal stage runs.

### Milestone 6: Guardrails and tests (stability + “add new backend” rules)

At the end of this milestone, it is difficult to regress the race/scoring system silently.

Work:

1) Unit tests:
- `tests/test_quality_scoring_v1.py`:
  - scoring is deterministic for a synthetic conversion result.
  - scoring handles edge cases (0 recipes, missing fields) without crashing.
- `tests/test_backend_race.py`:
  - deterministic tie-breaking,
  - failure-tolerance (one candidate errors),
  - “all fail” behavior.
- Extend existing `tests/test_run_settings.py` to ensure new fields have UI metadata and are included in summary/hash behavior.

2) Integration-ish test:
- If there are EPUB fixture tests, add one that runs the importer in auto_best mode with a tiny fixture EPUB and asserts:
  - report includes `backendRace`,
  - `selectedBackendId` is set,
  - `qualityScoreV1` is present.

3) Doc update:
- Add a section to the relevant docs README (or a new doc under `docs/03-ingestion/`):
  - “How to add a new EPUB backend candidate”
    - implement extractor function,
    - give it a stable id,
    - add it to the candidate list for auto_best (or to the preset enum),
    - ensure tests cover it.
  - “How QualityScoreV1 works (and what it does not measure)”
  - “How to run backend-race and interpret its report”.

Proof/acceptance:

- Running `pytest -q` passes.
- Removing a required UI metadata key from a new RunSettings field should fail the run-settings tests (then revert).

## Concrete Steps

These steps are written so a novice can execute them while implementing. Run commands from the repository root.

1) Locate the existing RunSettings model and how it is used in stage/import:

    ls cookimport/config
    python -c "import cookimport.config.run_settings as rs; print(rs.RunSettings)"

    (If the module path differs, search for `class RunSettings` and `stable_hash`.)

2) Locate report schema and where reports are written:

    python -c "import cookimport.core.models as m; print([n for n in dir(m) if 'Report' in n])"
    (Then open the file and find `ConversionReport`.)

3) Add QualityScoreV1 and wire it into report writing:
- Run a single EPUB stage and inspect the report JSON.
- Expect to see new keys.

4) Add backend race engine:
- Run unit tests for the new module.

5) Wire EPUB importer:
- Run `cookimport stage data/input/some.epub` in `auto_best` mode (via Run Settings editor).
- Confirm console prints candidate comparison and selection.

6) Add analytics fields:
- Run a stage.
- Run `cookimport perf-report`.
- Inspect `data/output/.history/performance_history.csv` for the new columns.

7) Generate dashboard (if applicable in this repo):

    cookimport stats-dashboard
    (Open the generated HTML and confirm the new fields appear.)

## Validation and Acceptance

This work is accepted when all of the following are demonstrably true:

1) Auto-best behavior:
- With `epub_backend_mode=auto_best`, importing an EPUB tries multiple backends and selects one deterministically.
- The selection is visible in console output and recorded in the per-file report JSON.

2) Traceability:
- The report JSON contains:
  - `runConfig`/`runConfigHash`/`runConfigSummary` (existing),
  - `qualityScoreV1` + `qualitySignalsV1`,
  - `backendRace` (or equivalent) containing candidate list, per-candidate status, scores, and selected backend.

3) Visibility:
- `performance_history.csv` contains `quality_score_v1` and `selected_backend` for each staged file.
- The dashboard (if used) can display/filter by selected backend and show quality score.

4) Safety:
- If one backend errors, the run continues with remaining candidates and records the failure.
- If all backends error, the failure is explicit and actionable, not silent.

5) Extensibility:
- Adding a new backend candidate requires edits in a small, obvious set of places (backend implementation + candidate registration), and tests fail if it is miswired.

## Idempotence and Recovery

- Auto-best should not mutate global defaults. It is purely per-run behavior controlled through RunSettings, consistent with the existing per-run settings design.
- Race candidate execution should not write drafts for losing candidates. Only the selected candidate’s conversion result should flow into the normal writer path.
- If `backend_race_debug_dump` writes artifacts, they should be written under the run root and should be safe to overwrite on rerun (use stable file names and atomic writes where appropriate).
- Backward compatibility: new report fields must be optional so older report JSON files remain readable by the dashboard/perf report tools.

## Artifacts and Notes

Example console output (illustrative):

    EPUB backend race (mode=auto_best, candidates=2)
      legacy: score=61.8 (ok)
      unstructured: score=78.9 (ok)
    Selected backend: unstructured (score=78.9)

Example report JSON fragment (illustrative shape):

    {
      "runConfigHash": "a1b2c3d4e5f6",
      "runConfigSummary": "epub_backend_mode=auto_best | ...",
      "qualityScoreV1": 78.9,
      "qualitySignalsV1": {
        "well_formed_recipe_share": 0.82,
        "missing_fields_penalty": -5.0,
        "duplicate_title_penalty": -2.0
      },
      "backendRace": {
        "raceVersion": "v1",
        "mode": "auto_best",
        "selectionRationale": "Highest QualityScoreV1; tie-break by stable candidate order",
        "selectedBackendId": "unstructured",
        "selectedCandidateId": "epub:unstructured",
        "candidates": [
          { "candidateId": "epub:legacy", "backendId": "legacy", "status": "ok", "qualityScoreV1": 61.8, "runConfigHash": "...", "runConfigSummary": "..." },
          { "candidateId": "epub:unstructured", "backendId": "unstructured", "status": "ok", "qualityScoreV1": 78.9, "runConfigHash": "...", "runConfigSummary": "..." }
        ]
      }
    }

## Interfaces and Dependencies

This plan introduces (or requires) the following interfaces/types.

In `cookimport/quality/scoring_v1.py`:

    class QualityScoreV1(BaseModel):
        version: str = "v1"
        overall: float
        signals: dict[str, float] = {}
        notes: list[str] = []

    def score_conversion_result_v1(result: ConversionResult) -> QualityScoreV1:
        ...

In `cookimport/backends/race.py`:

    class BackendCandidateSpec(BaseModel):
        candidate_id: str
        backend_id: str
        settings_overrides: dict[str, object] = {}

    class BackendRaceCandidateReport(BaseModel):
        candidateId: str
        backendId: str
        runConfigHash: str
        runConfigSummary: str
        qualityScoreV1: float | None = None
        qualitySignalsV1: dict[str, float] | None = None
        status: Literal["ok","error"]
        errorType: str | None = None
        errorMessage: str | None = None
        timingSeconds: float | None = None

    class BackendRaceReport(BaseModel):
        raceVersion: str = "v1"
        mode: str
        candidates: list[BackendRaceCandidateReport]
        selectedCandidateId: str | None = None
        selectedBackendId: str | None = None
        selectionRationale: str

    def run_backend_race_v1(
        *,
        base_settings: RunSettings,
        candidates: list[BackendCandidateSpec],
        run_one: Callable[[RunSettings], ConversionResult],
        score_one: Callable[[ConversionResult], QualityScoreV1],
    ) -> tuple[ConversionResult, BackendRaceReport]:
        ...

In `cookimport/config/run_settings.py`:

- Add fields described in Milestone 3 and ensure each has UI metadata.

In `cookimport/core/models.py` (`ConversionReport`):

- Add optional fields described in Milestone 1 and Milestone 2:
  - quality score/breakdown fields,
  - backend race report field.

No new third-party dependencies are required for the core race/scoring system. (If you add a sweep command later that reads YAML, that would be a new dependency; prefer Python-defined plans in v1.)

---

Change note (2026-02-16):

This ExecPlan is a revision of the earlier “multi-backend auto-pick” plan to explicitly integrate with the now-implemented per-run `RunSettings` selector/editor and runConfig persistence. The new plan removes duplicated work around run configuration plumbing and instead uses RunSettings as the canonical knob layer for backend racing, while extending report/analytics visibility to cover race decisions and quality scoring.
