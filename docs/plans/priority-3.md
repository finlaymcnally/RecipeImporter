# ExecPlan: Priority 3 — Multi-recipe splitting as a first-class case

This ExecPlan follows the repo’s ExecPlan rules in `PLANS.md` (single fenced `md` block; required sections; prose-first).:contentReference[oaicite:0]{index=0}:contentReference[oaicite:1]{index=1}

Source docs used (as provided by you):

- `BIG PICTURE UPGRADES.md` :contentReference[oaicite:2]{index=2}
- `2026-02-25_18.22.10_recipeimport-docs-summary.md` :contentReference[oaicite:3]{index=3}
- `PLANS.md` :contentReference[oaicite:4]{index=4}


## Purpose / Big Picture

Implement **Priority 3** from `BIG PICTURE UPGRADES.md`: make **multi-recipe splitting** (multiple recipes merged into one detected span) a **first-class, explicit, testable** behavior across importers, distinct from split-job/page-range parallelism.:contentReference[oaicite:5]{index=5}

What will exist after this work that does not exist today:

- A **shared multi-recipe splitter** that runs *after* block roles/signals are enriched, detects repeated recipe-unit patterns (title-like → ingredients → instructions), and splits one candidate span into multiple candidates when appropriate.:contentReference[oaicite:6]{index=6}
- The splitter is **configurable and benchmarkable**: existing behavior remains available as a “legacy” option; each new library/tool that overlaps existing capability is added as a **new selectable backend** (not a replacement), enabling permutations for your benchmarking harness.
- Guardrails are preserved/expanded, especially the “**For the X**” heuristic (e.g., “For the frosting”) treated as an ingredient subsection header rather than a new recipe title trigger.:contentReference[oaicite:7]{index=7}
- A minimal **segmentation evaluation harness** (boundary metrics + optional `segeval`) so you can measure multi-recipe splitting quality, not just block-label quality, without waiting for Priority 8’s full evaluator rollout.:contentReference[oaicite:8]{index=8}:contentReference[oaicite:9]{index=9}


## Progress

- [ ] (YYYY-MM-DD) Add run-settings + CLI plumbing for `multi_recipe_splitter` and related knobs (all execution lanes).
- [ ] (YYYY-MM-DD) Implement shared `MultiRecipeSplitter` core (rules backend) + trace artifacts.
- [ ] (YYYY-MM-DD) Integrate shared splitter into EPUB/PDF candidate postprocessing and Text importer (preserving legacy option).
- [ ] (YYYY-MM-DD) Add `transitions` FSM backend + boundary proposer interface (TextTiling / ruptures / textsplit / DeepTiling).
- [ ] (YYYY-MM-DD) Add optional “ML-ish” backend scaffolds (CRF + weak labeling), kept fully optional.
- [ ] (YYYY-MM-DD) Add optional pre/post processors that materially affect split quality (datasketch dedupe; PDF structure recovery; HTML boilerplate/schema lanes).
- [ ] (YYYY-MM-DD) Add segmentation eval tooling + tests + bench integration hooks.
- [ ] (YYYY-MM-DD) Update docs/runbook + add golden fixtures for multi-recipe split regression tests.


## Surprises & Discoveries

None yet (plan written before implementation). Update this section as unexpected constraints appear (e.g., pickling limits in split workers, missing stable block-role signals for some formats, dependency conflicts).


## Decision Log

1. **Default behavior remains unchanged**: introduce `multi_recipe_splitter=legacy` as the default, so current outputs remain stable unless explicitly enabled for EPUB/PDF or switched for Text. This preserves the project’s “deterministic default” posture used elsewhere (e.g., optional lanes are opt-in).:contentReference[oaicite:10]{index=10}
2. **Shared splitter operates on block streams** (not format-specific raw text): EPUB/PDF already produce blocks + roles; Text importer will be adapted to produce a block-like stream for this step, while keeping its current heuristic splitter as `legacy`. (This directly matches Priority 3’s “after block_roles/signals are enriched” requirement.):contentReference[oaicite:11]{index=11}
3. **All new libraries become selectable backends** via run settings. No replacement of existing functionality; only additive options to enable benchmarking permutations (user requirement).
4. **Evaluation MVP uses explicit boundary files + unit fixtures**, then optional bench integration if/when golden boundary data exists. This avoids coupling Priority 3 delivery to a full Label Studio boundary annotation workflow.


## Outcomes & Retrospective

(To be filled after implementation.) Include: what shipped, what was cut, measured impact on merged-recipe cases, and which backends were worth keeping.


## Context and Orientation

### Where this fits in the repo

Ingestion/stage converts source files into `ConversionResult` with `recipes` (candidates), tips, topic candidates, non-recipe blocks (block-first formats), raw artifacts, and a report. Primary entrypoint is `cookimport stage ...` in `cookimport/cli.py`, and importers live under `cookimport/plugins/` (including `epub.py`, `pdf.py`, `text.py`).:contentReference[oaicite:12]{index=12}

Shared parsing primitives already exist for cleaning, signals, patterns, adapters, and block roles (notably `cookimport/parsing/signals.py` and `cookimport/parsing/block_roles.py`).:contentReference[oaicite:13]{index=13}

### Current behavior relevant to Priority 3

- The system can detect multiple candidates in one EPUB, but is not explicitly looking for “multiple recipes merged into one span” patterns; this is distinct from split-job (page/spine range) parallelism.:contentReference[oaicite:14]{index=14}
- Text importer already has multi-recipe splitting heuristics (headings, yield markers, numbered titles, delimiter lines), which Priority 3 explicitly calls out for upgrade to use section coverage/densities derived from signals/block roles.:contentReference[oaicite:15]{index=15}:contentReference[oaicite:16]{index=16}
- Priority 3 also calls for adding analogous split heuristics into EPUB/PDF candidate postprocessing after signals/roles enrichment, and emphasizes the “For the X” guardrail (already present as an EPUB fix).:contentReference[oaicite:17]{index=17}

### “New option” wiring discipline

Whenever adding new run settings / processing options, the repo has an explicit wiring checklist: definition + interactive selection; runtime propagation (stage + benchmark paths + parallel planner parity); analytics persistence; and ensuring both execution lanes (import lane + prediction-generation lane) are wired.:contentReference[oaicite:18]{index=18}

We will follow that checklist for all new knobs introduced by multi-recipe splitting.


## Plan of Work

This work is easiest to deliver as incremental milestones. Each milestone ends with verifiable behavior (tests + an end-to-end stage command).

### Milestone 1 — Core shared splitter (rules backend) + wiring knob

Goal: implement Priority 3’s concrete steps 1–3 using a deterministic rules backend, while preserving the existing Text importer splitter as `legacy`.:contentReference[oaicite:19]{index=19}

At the end of this milestone:

- There is a shared module (new file) that can split a candidate span into multiple candidate spans based on repeated recipe-unit patterns.
- EPUB + PDF importers call it as candidate postprocessing when enabled.
- Text importer can optionally route through it (new mode), but still defaults to legacy behavior.

Proof:

- Unit tests for the splitter pass.
- A small fixture input that contains two recipes in one file produces two outputs when the knob is enabled, and one output when disabled.

### Milestone 2 — FSM backend + boundary proposer interface (benchmarkable)

Goal: add the `transitions`-based FSM backend and a boundary-proposer interface so we can trial “topic segmentation / change-point” approaches as *optional* boundary suggestion engines that are validated by the rule system.

This milestone explicitly incorporates Priority 3–related tools from `BIG PICTURE UPGRADES.md`: `transitions`, `NLTK TextTilingTokenizer`, `ruptures`, `textsplit`, and `DeepTiling`, all as optional backends. :contentReference[oaicite:20]{index=20}:contentReference[oaicite:21]{index=21}

Proof:

- `cookimport stage ... --multi-recipe-splitter fsm_v1` runs and yields deterministic splits on fixtures.
- `--multi-recipe-boundary-proposer texttiling` (or `ruptures`) runs when installed, and falls back with a clear error message when dependencies are missing.

### Milestone 3 — Segmentation evaluation MVP (+ `segeval` when installed)

Goal: enable measuring “did we split correctly?” with boundary metrics, and optionally compute `Pk`/`WindowDiff` style metrics via `segeval` (Priority 3 primary).:contentReference[oaicite:22]{index=22}:contentReference[oaicite:23]{index=23}

Proof:

- A new CLI command (or bench subcommand) evaluates predicted boundaries against provided gold boundaries for fixture sources and prints/writes a report.
- Unit tests cover the evaluator on fixtures.

### Milestone 4 — Optional quality levers that affect multi-recipe splitting

Goal: add optional “input quality” backends and preprocessors that directly influence multi-recipe splitting (all selectable, benchmarkable). These are explicitly called out as relevant to Priority 2–3 / 1–3 in `BIG PICTURE UPGRADES.md`, so they must appear in this plan as optional options/backends.

Included tool families (all optional, all as new selectable backends):

- **Near-duplicate suppression**: `datasketch` (Priority 2–3 secondary) to detect/remove repeated headers/footers (especially PDFs) that can create false split patterns.:contentReference[oaicite:24]{index=24}
- **HTML-ish boilerplate removal**: `trafilatura`, `readability-lxml`, optionally `jusText`, `BoilerPy3`, plus alternate extractors `goose3` and `newspaper3k` (Priority 1–3). These become additional extractors, not replacements.:contentReference[oaicite:25]{index=25}:contentReference[oaicite:26]{index=26}
- **Schema extraction**: `extruct` + `pyld` (Priority 2–3 primary) to extract multiple schema Recipe objects from a single document and treat them as multiple recipe candidates (a structured form of multi-recipe splitting).:contentReference[oaicite:27]{index=27}:contentReference[oaicite:28]{index=28}
- **PDF/EPUB structure recovery**: `Docling`, `PyMuPDF4LLM`, `Marker`, `MinerU`, and layout tools `pdfplumber`, `pdftotree`, `pdf2htmlEX`, `LayoutParser` (Priority 2–3). These become alternative “block builders” that feed the same splitter.:contentReference[oaicite:29]{index=29}

Proof:

- Each optional dependency is installable as an extra.
- Selecting an uninstalled backend yields a helpful “install extras” error.
- At least one backend per family has a smoke test on a small fixture.

### Milestone 5 — Optional “ML-ish” segmentation backends (kept experimental)

Goal: incorporate `Chaine` or `python-crfsuite`/`sklearn-crfsuite` and `skweak` as optional segmentation/splitting approaches, behind explicit run settings, for your permutation benchmarking. They must be added as *options*, not replacements.:contentReference[oaicite:30]{index=30}

Proof:

- Training/evaluation scaffolding exists (even if limited to fixtures initially).
- Backends are selectable but remain non-default and clearly labeled experimental.


## Concrete Steps

### 1) Add run settings + CLI options (all lanes, per wiring checklist)

Create/extend run-settings fields (names are proposals; adjust to match existing naming conventions):

- `multi_recipe_splitter`: enum string with at least `legacy`, `off`, `rules_v1`, `fsm_v1`, `crf_v0` (experimental).
- `multi_recipe_boundary_proposer`: enum string with at least `off`, `texttiling`, `ruptures`, `textsplit`, `deeptiling`.
- `multi_recipe_trace`: bool; when true writes trace artifacts for each candidate (for debugging/benchmark introspection).
- `multi_recipe_min_ingredient_lines`, `multi_recipe_min_instruction_lines`: ints.
- `multi_recipe_require_section_coverage`: bool; enforce “each split unit must have both ingredients and instructions” (Priority 3’s “section-coverage”).:contentReference[oaicite:31]{index=31}
- `multi_recipe_for_the_guardrail`: bool (default true when using new splitters), implementing the “For the X” behavior.:contentReference[oaicite:32]{index=32}

Wire all surfaces together, following the repo’s “New pipeline-option wiring checklist”:

- Definition + selection:
  - Add fields to `cookimport/config/run_settings.py`.
  - Expose in interactive selector/editor flows under `cookimport/cli_ui/run_settings_flow.py` and `cookimport/cli_ui/toggle_editor.py` as needed.:contentReference[oaicite:33]{index=33}
- Runtime propagation:
  - Thread through `cookimport/cli.py` stage and benchmark paths.
  - Keep split-planner parity with Label Studio ingest job planning (`cookimport/labelstudio/ingest.py:_plan_parallel_convert_jobs(...)`) and stage split planner (`cookimport/cli.py:_plan_jobs(...)`).:contentReference[oaicite:34]{index=34}
- Analytics persistence:
  - Ensure run-config summary/hash includes these knobs and surfaces in stage/benchmark artifacts and dashboards, following existing patterns for other knobs.:contentReference[oaicite:35]{index=35}
- Both execution lanes:
  - Import lane (`cookimport stage`).
  - Prediction-generation lane (`labelstudio-benchmark` / `bench run`), since eval-only commands do not rerun pipeline options.:contentReference[oaicite:36]{index=36}

Implementation caution: keep run-setting values as pickle-safe primitives to avoid split-worker failures (do not store module objects or callables in run config).:contentReference[oaicite:37]{index=37}

Acceptance for this step:

- `cookimport stage --help` shows the new flags.
- Interactive Run Settings UI shows and saves the new options.
- The chosen values appear in stage report/run-config summaries.

### 2) Create shared splitter module and data contracts

Add a new module:

- `cookimport/parsing/multi_recipe_splitter.py` (new)

Define a small, stable interface:

- `class MultiRecipeSplitConfig: ...` (constructed from RunSettings)
- `class SplitDecision: ...` (boundary index, reason(s), score/confidence, backend)
- `class SplitTrace: ...` (optional; serializable JSON payload)
- `def split_candidate(blocks, candidate_span, config) -> list[candidate_span]`

Key design goal: **all backends return the same output** (a list of spans + optional trace) so the importer can remain agnostic.

Also add “candidate metadata” support:

- Extend `cookimport/core/models.py` candidate type(s) to include optional fields like:
  - `multi_recipe_parent_candidate_id`
  - `multi_recipe_split_backend`
  - `multi_recipe_split_reasons`
  - `multi_recipe_split_confidence`
These should be additive fields to avoid breaking existing JSON readers.

Acceptance:

- Unit tests can create synthetic blocks and verify splitting without invoking full importers.
- The trace payload is JSON-serializable.

### 3) Implement `rules_v1` backend (Priority 3 concrete implementation)

Implement a deterministic rules engine that detects repeated “recipe units” within one candidate span:

The primary trigger patterns to support (per Priority 3):

- Title-like heading → ingredient cluster → instruction cluster repeated.
- Repeated Ingredients→Instructions cycles within one candidate span.:contentReference[oaicite:38]{index=38}

Implementation details (in your own code; no external docs required):

- Identify ingredient clusters and instruction clusters from existing block roles/signals. (Use the same role taxonomy already used by EPUB/PDF pipelines; if Text importer doesn’t have it, create a small “line-to-block” adapter so it can.)
- Compute “section coverage” for a proposed subspan:
  - has_ingredients: at least `min_ingredient_lines` ingredient-role blocks
  - has_instructions: at least `min_instruction_lines` instruction-role blocks
- Identify “title-like heading” candidates:
  - Reuse existing title extraction heuristics if available; otherwise implement a conservative detector:
    - short-ish line
    - mostly title-case or not sentence-like
    - not equal to common section headers like “Ingredients”, “Instructions”, “Directions”
- Proposed split boundaries:
  - candidate boundaries may be placed at:
    - the start of a title-like heading preceding a new ingredient cluster, or
    - the start of an ingredient cluster when a new unit begins without a clear title.
  - validate each split by ensuring both adjacent spans meet section coverage and that the boundary is not inside a single section (e.g., not splitting in the middle of a contiguous ingredient cluster).

Guardrails:

- Implement the “For the X” rule:
  - If a heading matches `^for the\b` (case-insensitive) and is followed by ingredient blocks and you are already inside an active recipe unit, treat it as an ingredient subsection header, not a new recipe start.:contentReference[oaicite:39]{index=39}
- Avoid false positives from repeated page headers/footers:
  - (In Milestone 4) we’ll add datasketch-based dedupe, but in rules_v1 we can also add a simple “repeated exact line N times” suppression inside a candidate span.

Trace:

- When `multi_recipe_trace=true`, write per-candidate trace artifacts under raw artifacts (e.g., `raw/multi_recipe_split/<slug>/candidate_<id>.json`) including:
  - detected clusters (indices)
  - proposed boundaries + validation outcome
  - final selected boundaries and reasons

Acceptance:

- A synthetic fixture with two obvious recipes gets split into two.
- A fixture containing “For the frosting” does not create an extra recipe candidate.

### 4) Integrate into importers (EPUB/PDF/Text) without breaking legacy behavior

#### 4.1 EPUB and PDF (candidate postprocessing)

Priority 3 explicitly wants split heuristics in EPUB/PDF candidate postprocessing after roles/signals enrichment.:contentReference[oaicite:40]{index=40}

Implementation approach:

- In `cookimport/plugins/epub.py` and `cookimport/plugins/pdf.py`:
  - locate the point where candidates are finalized (after blocks are extracted, cleaned, and enriched by signals/roles).
  - for each candidate span, if `multi_recipe_splitter` is not `legacy`/`off`, call `split_candidate(...)`.
  - replace that one candidate with the returned list (stable ordering preserved).
  - attach candidate metadata (parent id, reasons).

Keep split-job semantics unchanged: this feature is not about page/spine range splits for parallelism.:contentReference[oaicite:41]{index=41}

#### 4.2 Text importer (upgrade + preserve legacy option)

Text importer currently has heuristics for multi-recipe splitting, and Priority 3 wants them upgraded to use section coverage/densities from roles/signals.:contentReference[oaicite:42]{index=42}:contentReference[oaicite:43]{index=43}

Implementation approach:

- Keep the current splitter as `legacy` behavior.
- Add a code path for `multi_recipe_splitter=rules_v1|fsm_v1|...`:
  - Convert text into a block-like sequence (line blocks or paragraph blocks).
  - Run the shared cleaning + signals/roles enrichment where feasible (at minimum, enough to identify ingredient-like and instruction-like lines).
  - Run shared `split_candidate` over the full file span (or over an initial candidate span if Text importer already creates candidates).
  - For each resulting subspan, run existing section extraction to produce recipe records.

Acceptance:

- Running Text importer in `legacy` mode matches previous output count.
- Running with `rules_v1` uses section-coverage validation and is deterministic.

### 5) Add `transitions` FSM backend (`fsm_v1`)

Add optional dependency `transitions` and implement a backend that models segmentation as a finite state machine:

- States: `OUTSIDE`, `IN_TITLE`, `IN_INGREDIENTS`, `IN_INSTRUCTIONS`, optionally `IN_OTHER`.
- Transitions occur based on block role detections and boundary heuristics.
- A new recipe start is recognized when the FSM completes a unit and then sees a new unit start (title/ingredients) far enough from the previous.

This backend must be selectable via run settings and must not replace `rules_v1`.:contentReference[oaicite:44]{index=44}

Acceptance:

- Same fixtures as rules_v1 pass.
- FSM trace logs show state transitions in trace artifacts (when enabled).

### 6) Add boundary proposer interface and optional proposers

Add an interface that proposes candidate boundary indices, and then validate boundaries with the same “section coverage + guardrails” rules.

Optional proposer backends (all new options):

- `NLTK TextTilingTokenizer`
- `ruptures`
- `textsplit`
- `DeepTiling`:contentReference[oaicite:45]{index=45}

Implementation notes (self-contained approach):

- Each proposer receives a sequence of “units” (e.g., block texts) and returns a list of boundary indices.
- For libraries with unknown API specifics, implement each backend behind a small adapter and use module introspection in a scratch script:
    python -c "import ruptures, inspect; print(dir(ruptures)[:50])"
  Then write the adapter using only what you can validate locally (no external docs required).

Acceptance:

- When proposer dependency is missing, selecting it yields a clear error:
  - what extra to install
  - how to fall back
- When installed, proposer yields boundaries that are filtered/validated by rules and do not violate guardrails.

### 7) Add segmentation evaluation MVP (+ `segeval`)

Add `cookimport/bench/eval_segmentation.py` (new) or a new bench subcommand that evaluates predicted recipe boundaries vs gold boundaries.

Minimal gold format (fixture-friendly and versionable):

- `data/golden/segmentation/<source_slug>.boundaries.json`
  - contains:
    - `source_file` / `source_hash` identifiers
    - total block count
    - list of gold recipe start indices (or boundary indices)
    - optional notes

Evaluation outputs:

- Boundary precision/recall/F1 on predicted boundaries
- Optional `segeval` metrics (Pk, WindowDiff) if `segeval` installed and usable (guard with import).:contentReference[oaicite:46]{index=46}:contentReference[oaicite:47]{index=47}

Bench integration (optional but recommended):

- If bench already generates `stage_block_predictions.json` and copies it into prediction-run roots, keep that contract and add an *additional* segmentation report artifact rather than changing existing evaluators.:contentReference[oaicite:48]{index=48}

Acceptance:

- `pytest` includes tests that validate evaluator output on fixtures.
- Running the command on fixtures writes:
  - `segmentation_eval_report.json`
  - `segmentation_eval_report.md`

### 8) Add optional “input quality” backends (all selectable, all optional)

These are incorporated because `BIG PICTURE UPGRADES.md` explicitly ties them to Priority 3 (directly or via 2–3 / 1–3 mapping).:contentReference[oaicite:49]{index=49}:contentReference[oaicite:50]{index=50}

#### 8.1 `datasketch` near-duplicate suppression (PDF headers/footers)

Add optional dependency `datasketch` and implement a preprocessor:

- Input: list of blocks with text + page metadata (PDF).
- Output: same blocks, but mark/remove blocks that are near-duplicates repeated across many pages (header/footer).
- Apply before multi-recipe splitting so repeated headers don’t create false “title-like heading” signals.

Keep it as a new option (e.g., `pdf_dedupe_repeated_blocks=off|datasketch_v1`).:contentReference[oaicite:51]{index=51}

#### 8.2 HTML-ish extractors (boilerplate removal and alternates)

Add optional extraction options (new backends, not replacements):

- `trafilatura`
- `readability-lxml`
- optionally `jusText`
- optionally `BoilerPy3`
- alternate: `goose3`, `newspaper3k`:contentReference[oaicite:52]{index=52}:contentReference[oaicite:53]{index=53}

Where to integrate (minimal and Priority-3-relevant):

- Extend Text importer to accept `.html`/`.htm` inputs (if not already) and add `html_extractor_backend` run setting:
  - `legacy` (current behavior)
  - `trafilatura`
  - `readability`
  - `justext`
  - `boilerpy3`
  - `goose3`
  - `newspaper3k`
- After extraction, convert to block stream and run the shared multi-recipe splitter as usual.

#### 8.3 Schema extraction (`extruct` + `pyld`) as a structured multi-recipe source

Add optional schema-first path for HTML-ish inputs:

- Use `extruct` to extract microdata/JSON-LD and `pyld` to normalize JSON-LD.
- If multiple Recipe objects are found, produce multiple candidates directly (a structured multi-recipe split), otherwise fall back to text extraction + shared splitter.:contentReference[oaicite:54]{index=54}:contentReference[oaicite:55]{index=55}

This is explicitly called out as a “future-proof lane” and is relevant to multi-recipe cases on web pages or scraped HTML.:contentReference[oaicite:56]{index=56}

#### 8.4 PDF structure recovery backends

Add optional PDF “block builder” backends (new options, not replacements):

- Structure recovery: `Docling`, `PyMuPDF4LLM`, `Marker`, `MinerU`
- Layout tools: `pdfplumber`, `pdftotree`, `pdf2htmlEX`, `LayoutParser`:contentReference[oaicite:57]{index=57}

Integration approach:

- Define `PdfBlockBuilderBackend` interface returning your internal Block list.
- Implement one backend at a time, each behind an optional extra and run-setting selection.
- Feed produced blocks into the same downstream enrichment + candidate detection + multi-recipe splitter.

Acceptance:

- Selecting these backends works when installed.
- Output is still in your internal block format, so downstream remains unchanged.

### 9) Optional ML-ish backends (CRF + weak labels), fully experimental

Add optional experiment backends:

- CRF/sequence labeling: `Chaine` or `python-crfsuite`/`sklearn-crfsuite`
- Weak supervision: `skweak`:contentReference[oaicite:58]{index=58}

Keep them as additional selectable `multi_recipe_splitter` values (e.g., `crf_v0`, `skweak_crf_v0`) and do not make them defaults.

Minimal scope for Priority 3:

- Training can start from small fixtures or from existing label exports if available.
- Feature extraction uses existing block roles/signals as inputs.

Acceptance:

- Backend can be selected and run (even if only on fixtures initially).
- Missing model files produce a clear error and fallback guidance.


## Validation and Acceptance

You should be able to prove Priority 3 is implemented with these concrete checks:

1. Text multi-recipe splitting:
   - With default settings (`multi_recipe_splitter=legacy`), a known multi-recipe text fixture produces the same number of recipes as before.
   - With `multi_recipe_splitter=rules_v1`, it still splits, but now refuses “splits” that produce a span missing ingredients or instructions (section coverage), and emits traces when enabled.:contentReference[oaicite:59]{index=59}

2. EPUB/PDF multi-recipe splitting:
   - With `multi_recipe_splitter=legacy`, behavior matches current baseline.
   - With `multi_recipe_splitter=rules_v1`, a candidate containing two recipes merged together is split into two candidates, using repeated unit patterns as triggers.:contentReference[oaicite:60]{index=60}

3. Guardrail:
   - A case containing “For the frosting” or “For the sauce” does not create an extra recipe candidate. Confirm via unit tests + end-to-end stage output count.:contentReference[oaicite:61]{index=61}

4. Benchmarkability:
   - Run settings let you switch between backends (`rules_v1`, `fsm_v1`, proposer combinations, etc.) and the run-config summary/hash reflects the choices.
   - The new knobs are wired through both stage and prediction-generation lanes (per the wiring checklist).:contentReference[oaicite:62]{index=62}

5. Segmentation evaluation:
   - `cookimport ... eval-segmentation ...` (or equivalent) runs on fixture golden boundaries and outputs boundary precision/recall/F1.
   - If `segeval` is installed, the report also includes Pk/WindowDiff (or whatever metrics you decide to expose).:contentReference[oaicite:63]{index=63}:contentReference[oaicite:64]{index=64}

Recommended command examples (adjust flags to match your CLI conventions):

- Run stage with legacy (baseline):
    cd <repo>
    cookimport stage data/input/two_recipes.txt --multi-recipe-splitter legacy

- Run stage with new splitter + trace:
    cd <repo>
    cookimport stage data/input/two_recipes.txt --multi-recipe-splitter rules_v1 --multi-recipe-trace

- Run segmentation eval on fixtures:
    cd <repo>
    cookimport bench eval-segmentation --gold-dir data/golden/segmentation --pred-run <path>


## Idempotence and Recovery

- All new behaviors are gated behind run settings; default `legacy` avoids surprising output drift.
- Trace artifacts are additive under `raw/` and can be safely deleted between runs.
- If a new optional backend dependency causes issues:
  - switching the run setting back to `legacy` returns to baseline behavior immediately,
  - missing optional dependencies should never crash baseline runs; they should raise a targeted “install extras” error only when that backend is selected.
- When working with split jobs (PDF/EPUB parallelism), ensure any new config values are primitives and that merge logic does not assume a fixed candidate count; merging should remain deterministic and stable across retries.:contentReference[oaicite:65]{index=65}
