# Implement Priority 1: recipe-likeness score + confidence gates for all recipe candidates

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan must be maintained in accordance with `PLANS.md` at the repository root.

## Purpose / Big Picture

After this change, every importer that produces `RecipeCandidate` objects will also produce a deterministic `recipe_likeness_score` (0.0–1.0) plus a confidence tier (“gold / silver / bronze / reject”) and will use those gates to decide whether to emit a full recipe, emit a partial recipe, or reject the candidate and keep its blocks as non-recipe content.

You will be able to prove it works by running `cookimport stage ...` on any input and observing:

1) The stage report includes a recipe-likeness summary (counts by tier, score distribution, thresholds, scorer backend/version).
2) Each emitted `RecipeCandidate` has a stored score/tier (and optional per-candidate feature breakdown).
3) Rejected candidates do not appear as recipes, but their source blocks remain available under `non_recipe_blocks` so downstream tip/topic/chunking is not starved.
4) Optional “new baseline” tools mentioned for Priority 1 are available as additional selectable options (not replacements) so your benchmark harness can evaluate permutations:
   - `datasketch` (near-duplicate suppression option)
   - `segeval` (segmentation metrics option in eval/bench)
   - HTML-ish extraction options: `trafilatura`, `readability-lxml`, and optional `jusText`, `BoilerPy3`, plus `goose3` and `newspaper3k` as additional baselines
   - schema-first option via `extruct`
   - optional control-structure/model options: `transitions`, `Chaine`, `python-crfsuite`, `sklearn-crfsuite`, `skweak`
   - optional PDF structure recovery options: `Docling`, `PyMuPDF4LLM`, `Marker`, `MinerU`

## Progress

- [ ] (2026-02-25) Read `BIG PICTURE UPGRADES.md` Priority 1 and map required behaviors + mentioned tools to concrete repo edits.
- [ ] (2026-02-25) Add recipe-likeness scoring primitives (models, config, heuristic scorer v1) with unit tests.
- [ ] (2026-02-25) Add a stable place to store score/tier on `RecipeCandidate` and in `ConversionResult.report`, and write optional raw artifacts.
- [ ] (2026-02-25) Wire scoring + gates into Text/Excel importers (record-first) and Paprika/RecipeSage importers (structured-first).
- [ ] (2026-02-25) Wire scoring + gates into EPUB/PDF importers (block-first), ensuring rejected spans are preserved as `non_recipe_blocks`.
- [ ] (2026-02-25) Add `datasketch` near-duplicate suppression as an optional selectable backend for PDF/EPUB block streams, feeding `noise_rate` and stability.
- [ ] (2026-02-25) Add HTML-ish extraction backends as *new options* (`trafilatura`, `readability-lxml`, optional `jusText`/`BoilerPy3`, plus `goose3`/`newspaper3k`) and an “ensemble select best by recipe-likeness” mode.
- [ ] (2026-02-25) Add `extruct` schema-first extraction as a *new option* and gate schema-derived candidates with the same recipe-likeness logic.
- [ ] (2026-02-25) Add `segeval` metrics to Label Studio eval / offline bench to measure boundary quality and tune scoring thresholds deterministically.
- [ ] (2026-02-25) Add optional advanced scorer backends (`transitions` state machine option; CRF options via `Chaine` or `python-crfsuite` / `sklearn-crfsuite`, with weak supervision via `skweak`) as selectable benchmark permutations.
- [ ] (2026-02-25) Add optional PDF structure recovery extractors (`Docling`, `PyMuPDF4LLM`, `Marker`, `MinerU`) as selectable backends and (optionally) an ensemble mode scored by recipe-likeness.

## Surprises & Discoveries

- Observation:
  Evidence:

## Decision Log

- Decision: Implement a pluggable scoring interface with a deterministic heuristic backend (`heuristic_v1`) as the default, and treat all new libraries as optional “extras” selectable via config.
  Rationale: Priority 1 requires deterministic gating everywhere; optional backends must be additive to preserve benchmarking permutations without destabilizing the default install.
  Date/Author: 2026-02-25 / ExecPlan author

- Decision: Store a compact summary in the stage report and write verbose per-candidate feature breakdowns to a raw artifact file instead of bloating the report.
  Rationale: Keeps report readable and stable for dashboards while still providing full reproducibility via artifacts.
  Date/Author: 2026-02-25 / ExecPlan author

## Outcomes & Retrospective

- (Fill in at milestone completion.)

## Context and Orientation

This repository’s Python package is `cookimport/`. The ingestion stage converts a source file into a `ConversionResult` that includes (at minimum) `recipes` (a list of `RecipeCandidate`) plus optional `non_recipe_blocks`, `tip_candidates`, `topic_candidates`, `raw_artifacts`, and a `report` dict. The main end-to-end entrypoint is `cookimport stage ...` via `cookimport/cli.py`, which calls importer plugins under `cookimport/plugins/` and then writes outputs with `cookimport/staging/writer.py`.

Importers fall into three “families”:

1) Block-first importers (`cookimport/plugins/epub.py`, `cookimport/plugins/pdf.py`):
   They build an ordered stream of `Block` objects, run shared enrichment (`signals.enrich_block(...)`) and deterministic role assignment (`assign_block_roles(...)` in `cookimport/parsing/block_roles.py`), then segment candidate spans and extract recipe fields.

2) Recipe-record-first importers (`cookimport/plugins/text.py`, `cookimport/plugins/excel.py`):
   They build `RecipeCandidate` records directly from text sections or spreadsheet rows.

3) Structured-import-first importers (`cookimport/plugins/paprika.py`, `cookimport/plugins/recipesage.py`):
   They map near-structured exports into `RecipeCandidate`.

A “Block” is the program’s internal representation of an ordered piece of source text (often paragraph-level) with provenance (page/spine indices) and derived signals/roles (such as `ingredient_line`, `instruction_line`, `recipe_title`, etc.). A “candidate span” is a contiguous range of blocks that the importer believes corresponds to one recipe.

Priority 1 requires a single, shared contract: every time the system creates a recipe candidate (from blocks, from text sections, from spreadsheet rows, or from structured exports), it must attach a `recipe_likeness_score` and apply explicit confidence gates:
- Gold: proceed normally
- Silver: proceed but lower confidence / emit extra debug
- Bronze (partial): emit partial recipe candidate (do not invent missing sections)
- Reject: do not output a recipe; preserve content as `non_recipe_blocks` for tip/topic/chunk flows

## Plan of Work

### Milestone 1: Define the scoring contract and implement deterministic heuristic scorer v1

At the end of this milestone, the repo will have a new shared scoring module that can score (a) a block span or (b) an already-constructed `RecipeCandidate`, producing a deterministic score + tier + feature breakdown. Unit tests will prove determinism and tiering decisions.

Work:

1) Create `cookimport/parsing/recipe_scoring.py` and define:
   - A `RecipeLikenessTier` enum: `gold`, `silver`, `bronze`, `reject`.
   - A `RecipeLikenessResult` model containing:
     - `score: float` (0..1)
     - `tier: RecipeLikenessTier`
     - `features: dict[str, float|int|bool]` (small, JSON-serializable)
     - `reasons: list[str]` (reason codes for debug, e.g. `missing_instructions`, `too_short`, `high_noise`)
     - `backend: str` (e.g. `heuristic_v1`)
     - `version: str` (scoring version string so future changes don’t silently drift)

2) Implement feature extraction for a block span using already-existing semantics:
   - `ingredient_line_density` = (# blocks role=ingredient_line) / (# blocks in span)
   - `instruction_line_density`
   - `section_coverage` = 0, 0.5, or 1 based on presence of plausible ingredient and instruction sections
   - `heading_anchors_present` = bool or graded score if headings like “Ingredients”, “Instructions”, “Method”, “Directions”, “Notes” appear (prefer using existing signal flags/patterns if they exist; otherwise add a small deterministic heading regex list)
   - `noise_rate` = fraction of blocks considered boilerplate/noise (initially: stoplist-based; later milestones add near-duplicate detection via `datasketch`)
   - `length_penalties` = deterministic penalty flags for “too short to be a recipe” or “absurdly long without structure”

3) Implement tiering logic (explicit gates):
   - Gold if ingredient section and instruction section are both present with minimum line counts and densities above configurable thresholds and noise below threshold.
   - Silver if both sections present but weaker densities/anchors.
   - Bronze if only one section present but meets a minimum strength threshold.
   - Reject otherwise.

4) Compute final `score` from features + penalties with a deterministic formula, clamp to [0, 1], and include the final decision thresholds in the result’s `features` or `reasons` so debugging can reproduce “why tier X”.

5) Add unit tests under `tests/` (choose a folder consistent with current conventions, e.g. `tests/parsing/test_recipe_scoring.py`):
   - Construct minimal fake blocks (or use real `Block` model if easy) with set `block_role` values and text content.
   - Verify:
     - Score is deterministic across runs.
     - Gold/Silver/Bronze/Reject tiering matches expected outcomes for synthetic examples.
     - `noise_rate` and length penalties affect score/tier as expected.

Acceptance:

- Running `pytest -m "not slow"` includes the new tests and they pass.
- A small doctest-like snippet in `recipe_scoring.py` (or in test) shows that the same input yields the same score.

### Milestone 2: Store score/tier on candidates and in reports, and write optional raw artifacts

At the end of this milestone, `RecipeCandidate` objects (regardless of importer) can carry recipe-likeness data, and stage output reports include summary stats. A raw artifact file records per-candidate scoring detail for reproducibility.

Work:

1) Locate `RecipeCandidate` model definition (likely under `cookimport/core/`).
   - Use `rg -n "class RecipeCandidate|RecipeCandidate" cookimport/core cookimport` to find the authoritative model.
   - Add an optional field:
     - preferred: `recipe_likeness: RecipeLikenessResult | None`
     - acceptable fallback (if model constraints make nested models hard): `recipe_likeness_score: float | None`, `recipe_likeness_tier: str | None`, `recipe_likeness_features: dict | None`, `recipe_likeness_backend: str | None`, `recipe_likeness_version: str | None`

   Keep it optional to preserve backwards compatibility with existing serialized fixtures and partial flows.

2) Update any serialization/deserialization paths that assume strict schemas (Pydantic `extra="forbid"` scenarios). If any tests fail due to “unexpected field”, update model configs or explicit field lists accordingly.

3) Extend `ConversionResult.report` contract:
   - Identify `ConversionResult` model and where `report` is built in each importer.
   - Define a shared helper in `cookimport/parsing/recipe_scoring.py` (or `cookimport/core/reporting.py` if that’s already the home for report helpers) that can merge a “recipe-likeness summary” into an existing report dict:
     - scorer backend/version
     - thresholds used
     - count by tier
     - min/median/p90/max of scores for emitted candidates
     - count of rejected candidates/spans

4) Add a raw artifact to capture detailed per-span scoring:
   - File name: `recipe_scoring_debug.jsonl`
   - Each JSON line should include:
     - `source_path` or `source_hash` (whatever is standard)
     - `importer` name
     - candidate identity (ID or location)
     - span bounds (block indices/pages/spines if available)
     - `RecipeLikenessResult` (score/tier/features/reasons/backend/version)

   Implement it in the same way other raw artifacts are stored:
   - For single-file stage runs: include it in `ConversionResult.raw_artifacts` and let `cookimport/staging/writer.py:write_raw_artifacts` write it.
   - For split jobs (PDF/EPUB): ensure worker paths write artifacts into `.job_parts/.../raw/...` and merge keeps all lines (append/concat) deterministically.

Acceptance:

- Running `cookimport stage <some input>` produces the normal outputs plus:
  - report JSON includes a new `recipe_likeness` section with counts and thresholds
  - `raw/.../recipe_scoring_debug.jsonl` exists and includes lines for each emitted candidate and each rejected span (if any)
- No existing stage report keys are removed (additive only).

### Milestone 3: Apply scoring + gates in record-first and structured-first importers

At the end of this milestone, Text/Excel/Paprika/RecipeSage conversions set recipe-likeness on each candidate and apply gates consistently. Reject/bronze behaviors are observable.

Work:

1) Text importer (`cookimport/plugins/text.py`):
   - Identify where multi-recipe splitting and section extraction happens.
   - After each candidate is built (or right before appending to `recipes`), call the shared scorer using a “candidate input” path (pseudo-block observation based on ingredient/instruction line lists).
   - Apply gates:
     - Gold/Silver: keep as recipe.
     - Bronze: keep as recipe but do not auto-fill missing sections; ensure missing section lists remain empty.
     - Reject: do not add to `recipes`. If the importer has a notion of `non_recipe_blocks` for text, add the source text blocks/lines there; otherwise add a `report` entry that a candidate was rejected and ensure tip/topic extraction still sees this content (prefer preserving it as non-recipe content if the pipeline supports it).

2) Excel importer (`cookimport/plugins/excel.py`):
   - Compute score from the candidate’s ingredient/instruction fields similarly.
   - Reject low-quality empty rows that accidentally form “recipes”.
   - Ensure row-based deterministic ordering and ID generation are unchanged.

3) Paprika + RecipeSage importers:
   - Score each recipe from structured fields:
     - ingredient lines come from structured ingredient list or text; instructions from steps list.
   - Reject obviously empty/invalid recipes, but keep a report row about the rejection (and optionally keep the raw export in `raw_artifacts` as today).
   - These importers often act as “gold”; expect most to score gold/silver, but still apply the same gates so the contract holds everywhere.

4) Add integration tests:
   - Add a minimal `.txt` fixture in `tests/fixtures/` with:
     - One valid recipe-like section (ingredients + instructions).
     - One narrative-only section that should be rejected.
   - Test that `text` importer returns exactly one recipe candidate and that report indicates a rejection and/or preserved non-recipe content.
   - Add a minimal in-memory Excel fixture (or a small `.xlsx` test file) to test one accepted and one rejected row.

Acceptance:

- `pytest -m "ingestion and not slow"` passes.
- The new tests demonstrate reject vs accept behavior deterministically.

### Milestone 4: Apply scoring + gates in block-first importers (EPUB/PDF) and add `datasketch` dedupe option

At the end of this milestone, EPUB/PDF candidate creation attaches recipe-likeness and gates candidates based on the scored block spans, with rejected spans preserved as `non_recipe_blocks`. A new optional near-duplicate suppression backend exists via `datasketch` as an additional selectable option.

Work (EPUB):

1) In `cookimport/plugins/epub.py`, identify the candidate detection/extraction flow:
   - Candidate detection: `_detect_candidates(...)`
   - Candidate field extraction: `_extract_fields(...)` and/or `_extract_title(...)`
   - Confirm where `assign_block_roles(...)` is called (it must be before scoring).

2) Score each proposed candidate span:
   - Call scorer on the span blocks and attach the resulting `RecipeLikenessResult` onto the candidate.
   - Apply gates before finalizing output lists:
     - Reject: do not append to `recipes`; add span blocks into `non_recipe_blocks` (or keep them there if already tracked).
     - Bronze: emit candidate with only the detected sections; do not synthesize missing sections.

3) Add the optional raw artifact lines for rejected spans as well as accepted candidates.

Work (PDF):

4) In `cookimport/plugins/pdf.py`, identify where block streams are built and candidates assembled.
5) Apply the same scoring + gate logic as EPUB.

Add `datasketch` option:

6) Add `cookimport/parsing/near_duplicate.py` implementing a backend interface:
   - `find_near_duplicate_block_ids(blocks, *, backend, config) -> set[int]`
   - Backends:
     - `none` (default): returns empty set.
     - `exact_v1`: exact string match normalization (no external deps).
     - `datasketch_minhash_v1`: uses `datasketch` MinHash+LSH to cluster near-duplicates.

7) Feed duplicates into scoring:
   - Mark duplicate blocks as noise for `noise_rate`.
   - Optionally (configurable), remove duplicates from candidate spans before scoring and/or before candidate extraction (keep original blocks for provenance, but score on “effective blocks”).
   - Ensure determinism: fixed shingling strategy, fixed thresholds, no randomness.

8) Add config keys (see Milestone 5 for full config plan) so your benchmark harness can choose `near_duplicate_backend = none|exact_v1|datasketch_minhash_v1` as a permutation.

Dependencies:

- Add `datasketch` as an optional extra dependency (see “Interfaces and Dependencies”).

Acceptance:

- Run:
  - `cookimport epub candidates <file> --out <dir>` and confirm candidate previews include score/tier (in JSON or preview markdown).
  - `cookimport stage <epub/pdf>` and confirm report + raw artifact reflect tier counts and rejected spans preserved.
- Unit test for `near_duplicate.py`:
  - For `exact_v1`, verify duplicates are found deterministically.
  - For `datasketch_minhash_v1`, add a conditional test that is skipped if `datasketch` is not installed.

### Milestone 5: Add HTML-ish extraction options and schema-first option as additive backends

At the end of this milestone, the system supports additional extraction permutations for HTML-ish sources (especially EPUB XHTML) and can optionally select the best extractor output using recipe-likeness scoring. Schema-first extraction via `extruct` is available as a separate selectable lane.

HTML-ish extraction backends (additive options):

1) Identify the EPUB extractor abstraction (`cookimport/parsing/epub_extractors.py` and related selection code like `cookimport/parsing/epub_auto_select.py`).
2) Add new extractor backends as additional choices (do not remove existing `unstructured`, `markitdown`, `markdown`, `beautifulsoup`):
   - `readability_lxml_v1` (uses `readability-lxml`)
   - `trafilatura_v1` (uses `trafilatura`)
   - Optional additional baselines:
     - `justext_v1` (uses `jusText`)
     - `boilerpy3_v1` (uses `BoilerPy3`)
     - `goose3_v1` (uses `goose3`)
     - `newspaper3k_v1` (uses `newspaper3k`)

3) Implement these in a new module `cookimport/parsing/html_extractors.py` that accepts a raw HTML string and returns extracted main-text (or paragraph list), then convert into the existing `Block` representation in a deterministic way (e.g., one block per paragraph).

4) Add an “ensemble select best” mode:
   - New EPUB extractor setting: `epub_extractor=ensemble_recipe_score_v1`
   - Behavior: run a configured list of backends (default: existing ones + a small subset of new ones), score each backend’s output by recipe-likeness:
     - Run standard enrichment + role assignment + candidate detection.
     - Compute a backend score such as:
       - `max_candidate_score` and `sum_top_k_candidate_scores` (k configurable, default 3).
       - Penalize huge noise_rate / too few blocks.
     - Select the backend with the highest backend score, tie-break using existing extraction quality score (`cookimport/parsing/extraction_quality.py:score_blocks(...)`) so we don’t pick garbage that happens to match a recipe pattern by accident.
   - Write a raw artifact (or extend existing `epub_race_report.json`) with per-backend rationale and scores.

Schema-first option via `extruct` (additive option):

5) Implement `cookimport/parsing/schema_extraction.py`:
   - Use `extruct` to extract embedded structured data from HTML (JSON-LD / microdata / RDFa).
   - Find schema.org Recipe-like objects (items where `@type` contains `Recipe`).
   - Convert schema fields to a `RecipeCandidate` (minimal mapping):
     - Ingredients: `recipeIngredient` (list of strings)
     - Instructions: `recipeInstructions` which may be strings, `HowToStep`, or `HowToSection` → flatten deterministically
     - Yield/time fields (store if candidate model supports; otherwise keep in candidate metadata)
   - Score schema-derived candidates with the same recipe-likeness gates:
     - If the schema candidate is gold/silver (configurable), prefer it.
     - Otherwise fall back to heuristic block-based extraction.

6) Add config knobs to choose:
   - `schema_extractor_backend = none|extruct_v1`
   - `schema_prefer_min_tier = gold|silver` (default: gold)
   - The list of HTML extraction backends used in the ensemble mode.

Dependencies:

- Add as optional extras:
  - `trafilatura`
  - `readability-lxml`
  - `jusText`
  - `BoilerPy3`
  - `goose3`
  - `newspaper3k`
  - `extruct`

Acceptance:

- When optional deps are installed, running the EPUB extractor race/ensemble produces different backends and selects deterministically.
- When optional deps are not installed, selecting those backends produces a clear error message telling the user which extra to install (and default runs remain unaffected).

### Milestone 6: Add `segeval`-powered metrics to evaluation and benchmarking

At the end of this milestone, Label Studio eval and/or offline benchmark reports include segmentation metrics that help tune recipe-likeness gating thresholds and splitting behavior.

Work:

1) Add optional dependency `segeval` as an extra.
2) Identify where Label Studio eval computes metrics (`cookimport/labelstudio/...` and/or `cookimport/bench/...`).
3) Implement a small adapter `cookimport/bench/segmentation_metrics.py`:
   - Convert predicted recipe segmentation into a segmentation representation:
     - If you have N ordered blocks, represent segmentation as a list of segment sizes (counts of blocks per segment) or as a boundary set, whichever `segeval` API prefers.
   - Convert gold segmentation similarly from Label Studio canonical block labels or gold spans (whichever is currently exported).
   - Compute:
     - Pk
     - WindowDiff
     - boundary similarity (if available/appropriate)
   - Store these metrics in the eval report under a clear key, e.g. `segmentation_metrics`.

4) Add a CLI-visible proof:
   - `cookimport labelstudio-eval ...` should print a short segmentation summary and write the full metrics into the JSON report artifact.
   - Ensure metrics computation is deterministic and does not require network calls.

Acceptance:

- A focused eval run writes `segmentation_metrics` into its report JSON and includes at least one `segeval`-derived metric.
- Tests: add a unit test with a tiny synthetic segmentation example and verify `segeval` returns the expected value (skip if `segeval` not installed).

### Milestone 7: Add optional advanced scorer backends (FSM + CRF) as benchmark permutations

This milestone is explicitly “optional/bigger bet”, but it is included because the Priority 1 writeup names these tools as valid approaches for P1–P3. The key requirement is that these remain *options*, not replacements.

Work (FSM option via `transitions`):

1) Add optional dependency `transitions`.
2) Implement `cookimport/parsing/section_fsm.py` using `transitions` as a clean, deterministic section state tracker:
   - States: `outside`, `in_ingredients`, `in_instructions`, `in_notes`, etc.
   - Transitions triggered by heading anchors and block roles/signals.
3) Add scorer backend `heuristic_fsm_v1` that uses FSM-derived section coverage features instead of (or in addition to) simple role counts.
4) Add config `recipe_scorer_backend = heuristic_v1|heuristic_fsm_v1|...`.

Work (CRF options via `Chaine` or `python-crfsuite` / `sklearn-crfsuite`, with weak supervision via `skweak`):

5) Add optional dependencies:
   - `python-crfsuite` (pycrfsuite)
   - `sklearn-crfsuite`
   - `skweak`
   - `Chaine` (if available as an installable package; confirm the package name and pin it; if not easily installable, treat as “supported in principle” but do not block the rest of the milestone)

6) Implement `cookimport/parsing/recipe_scoring_crf.py`:
   - Define a feature extractor from block streams to per-block feature dicts (deterministic):
     - token/shape features (lowercase, contains_digit, bullet prefix, etc.)
     - heading anchor flags
     - existing signals from `signals.enrich_block`
     - relative position features (e.g., normalized index)
   - CRF predicts per-block labels (ingredient_line, instruction_line, header, noise, other).
   - Convert predicted labels into the same observation features used by the gating logic, then compute score/tier.
   - Load model from a path in config; if missing, raise a clear error.

7) Add a training script under `cookimport/bench/`:
   - `cookimport/bench/train_recipe_crf.py` reads a labeled dataset (start with Label Studio export if available in your repo workflow).
   - If full labels are not available, support weak supervision:
     - Use `skweak` labeling functions wrapping existing heuristics to produce weak labels.
     - Train CRF on weak labels and export a model artifact under a deterministic filename containing:
       - training data hash
       - feature extractor version
       - model hyperparameters
   - Record training run metadata in a JSON next to the model.

8) Add benchmark permutations:
   - Ensure `cookimport bench sweep` and/or “all-method benchmark” can vary `recipe_scorer_backend` and model path, skipping combos when optional deps aren’t installed.

Acceptance:

- You can run a smoke command that loads a CRF model (even a toy one) and scores a synthetic block stream deterministically.
- Optional backends fail gracefully when deps/models are missing, and default behavior is unchanged.

### Milestone 8: Add optional PDF structure recovery backends (Docling / PyMuPDF4LLM / Marker / MinerU) as selectable extractors

This milestone is explicitly optional and should be implemented as additive extraction backends, allowing you to benchmark “structure recovery” permutations upstream of recipe scoring.

Work:

1) Add optional extra dependencies for:
   - `Docling`
   - `PyMuPDF4LLM`
   - `Marker`
   - `MinerU`

   Important: confirm the correct pip package names and pin versions; record decisions in the Decision Log.

2) Implement `cookimport/parsing/pdf_extractors_extra.py`:
   - Provide wrappers that accept a PDF path and return a canonical block stream.
   - Each wrapper must:
     - be deterministic
     - capture provenance (page numbers if possible)
     - produce blocks compatible with existing enrichment + role assignment

3) Extend PDF importer to accept a new config key `pdf_extractor_backend` with options:
   - existing default backend(s)
   - new optional backends: `docling_v1`, `pymupdf4llm_v1`, `marker_v1`, `mineru_v1`
   - optional: `pdf_extractor_backend=ensemble_recipe_score_v1` that runs multiple backends and selects the best by recipe-likeness scoring (similar to EPUB ensemble mode)

4) Ensure each new backend is a *new option* only; do not remove current PDF parsing.

Acceptance:

- With extras installed, running `cookimport stage <pdf>` with `pdf_extractor_backend=<new backend>` works and produces output.
- Without extras, selecting a new backend produces a clear “install extra” error, and default remains unchanged.

## Concrete Steps

All commands are from the repo root unless stated otherwise.

1) Set up env and install dev deps:

    source .venv/bin/activate
    python -m pip install -e .[dev]

2) Before edits, find the relevant definitions:

    rg -n "class RecipeCandidate|RecipeCandidate" cookimport/core cookimport
    rg -n "class ConversionResult|ConversionResult" cookimport/core cookimport
    rg -n "assign_block_roles|block_roles" cookimport/parsing cookimport/plugins
    rg -n "_detect_candidates|_extract_fields|_extract_title" cookimport/plugins/epub.py
    rg -n "convert\\(" cookimport/plugins

3) Implement Milestone 1 and run targeted tests:

    pytest -q tests/parsing/test_recipe_scoring.py

4) Implement Milestone 2 and run ingestion/staging slices:

    pytest -m "ingestion and not slow"
    pytest -m "staging and not slow"

5) Run a real stage sanity (pick any small input fixture you have available):

    cookimport stage data/input/<somefile> --out data/output

   Then inspect:
   - data/output/<timestamp>/<workbook_slug>.report.json (or whatever the canonical report file name is)
   - data/output/<timestamp>/raw/.../recipe_scoring_debug.jsonl

6) If implementing optional extras, install them explicitly and run focused smoke checks:

    python -m pip install -e '.[recipe_scoring]'
    python -m pip install -e '.[html_extractors]'
    python -m pip install -e '.[schema_extractors]'
    python -m pip install -e '.[pdf_structure]'
    python -m pip install -e '.[ml_scoring]'

   Then rerun:
    cookimport epub candidates data/input/<some.epub> --out data/output/<tmp>
    cookimport stage data/input/<some.epub> --out data/output/<tmp>

## Validation and Acceptance

This work is accepted when all are true:

1) For each importer (EPUB, PDF, Text, Excel, Paprika, RecipeSage), stage conversion:
   - attaches recipe-likeness score/tier to each emitted `RecipeCandidate`,
   - uses gates to reject low-confidence candidates (they do not appear as recipes),
   - and preserves rejected content in `non_recipe_blocks` (where applicable) so downstream tip/topic/chunk flows still have the material.

2) Stage report contains a stable `recipe_likeness` summary section including:
   - backend/version,
   - thresholds,
   - counts by tier,
   - and score distribution stats.

3) A raw artifact exists that enables reproducibility of “why” a candidate was accepted/partial/rejected (per-candidate features and reasons).

4) All new tool/library mentions from Priority 1 are incorporated as *additive options* (not replacements):
   - `datasketch` is selectable for near-duplicate suppression.
   - `segeval` is selectable/used in evaluation metrics.
   - `trafilatura`, `readability-lxml`, optional `jusText`, `BoilerPy3`, plus `goose3` and `newspaper3k` exist as selectable HTML-ish extraction backends and/or ensemble participants.
   - `extruct` exists as a selectable schema-first extraction backend.
   - `transitions` exists as a selectable deterministic FSM-based scoring backend (optional).
   - `Chaine` and `python-crfsuite` / `sklearn-crfsuite` exist as selectable CRF-based scoring backends (optional).
   - `skweak` exists as an optional weak-supervision training path (optional).
   - `Docling`, `PyMuPDF4LLM`, `Marker`, `MinerU` exist as selectable PDF structure recovery backends (optional).

5) Test suite remains healthy:
   - Run `pytest` and ensure failures are not introduced by this feature.
   - Any optional-dependency tests are correctly skipped when deps are missing.

## Idempotence and Recovery

- All scoring is deterministic: no randomness, no time-dependent behavior, no reliance on network calls.
- Re-running stage on the same inputs with the same config must produce the same tiers/scores and report counts.
- Optional backends must fail fast with actionable error messages when their optional dependencies are not installed; default backends remain available.
- Raw artifacts should be append-only and merge-safe for split jobs; if merge collisions occur, follow existing raw artifact collision-prefix patterns rather than overwriting.

## Artifacts and Notes

Example expected report snippet (illustrative; exact path/key names must match repo conventions):

  {
    "importer": "epub",
    "recipe_likeness": {
      "backend": "heuristic_v1",
      "version": "2026-02-25",
      "thresholds": {
        "gold_min_score": 0.75,
        "silver_min_score": 0.55,
        "bronze_min_score": 0.35
      },
      "counts": {
        "gold": 4,
        "silver": 1,
        "bronze": 2,
        "reject": 3
      },
      "score_stats": {
        "min": 0.22,
        "p50": 0.71,
        "p90": 0.88,
        "max": 0.93
      }
    }
  }

Example JSONL line in `recipe_scoring_debug.jsonl`:

  {"candidate_id":"...","span":{"start_block":120,"end_block":198},"result":{"score":0.81,"tier":"gold","features":{"ingredient_line_density":0.14,"instruction_line_density":0.18,"section_coverage":1,"heading_anchors_present":true,"noise_rate":0.05},"reasons":[],"backend":"heuristic_v1","version":"2026-02-25"}}

## Interfaces and Dependencies

### New/updated interfaces

1) In `cookimport/parsing/recipe_scoring.py`, define:

  - enum RecipeLikenessTier(str, Enum):
      gold = "gold"
      silver = "silver"
      bronze = "bronze"
      reject = "reject"

  - class RecipeLikenessResult(BaseModel or dataclass):
      score: float
      tier: RecipeLikenessTier
      features: dict[str, Any]
      reasons: list[str]
      backend: str
      version: str

  - def score_block_span(blocks, start_idx: int, end_idx: int, *, config) -> RecipeLikenessResult
  - def score_candidate(candidate: RecipeCandidate, *, config) -> RecipeLikenessResult

2) Extend `RecipeCandidate` to store the result (prefer nested model) as `recipe_likeness`.

3) Add a shared report helper:

  - def build_recipe_likeness_summary(results: list[RecipeLikenessResult], rejected_count: int, *, config) -> dict

### Config keys (additive)

Add new config settings under `cookimport/config/` following existing patterns (env vars, interactive editor, benchmark knobs):

- `recipe_scorer_backend`: default `heuristic_v1`
- `recipe_score_gold_min`: float
- `recipe_score_silver_min`: float
- `recipe_score_bronze_min`: float
- `recipe_score_min_ingredient_lines`: int
- `recipe_score_min_instruction_lines`: int
- `near_duplicate_backend`: default `none`, options `none|exact_v1|datasketch_minhash_v1`
- `epub_extractor`: add options without removing existing, including `ensemble_recipe_score_v1`
- `schema_extractor_backend`: `none|extruct_v1`
- `schema_prefer_min_tier`: `gold|silver`
- `pdf_extractor_backend`: add options without removing existing, including optional `ensemble_recipe_score_v1`

### Optional dependencies (extras)

Edit `pyproject.toml` to add optional dependency groups consistent with existing extras like `epubdebug`.

Proposed extras (names can be adjusted to fit repo conventions, but keep them stable and documented):

- `recipe_scoring`:
  - datasketch
  - segeval

- `html_extractors`:
  - trafilatura
  - readability-lxml
  - jusText
  - BoilerPy3
  - goose3
  - newspaper3k

- `schema_extractors`:
  - extruct

- `ml_scoring`:
  - transitions
  - python-crfsuite
  - sklearn-crfsuite
  - skweak
  - Chaine (only if installable; otherwise record as “planned backend” with TODO and do not block CI)

- `pdf_structure`:
  - Docling
  - PyMuPDF4LLM
  - Marker
  - MinerU

For every optional backend, implement the import with a guarded import and raise an explicit error:

  "Backend 'trafilatura_v1' requires extras [html_extractors]. Install with: pip install -e '.[html_extractors]'"

### Documentation updates

Update the following docs (keep them minimal and contract-focused):

- `docs/03-ingestion/03-ingestion_readme.md`: add a short section describing recipe-likeness scoring, tiers, and how rejected content is handled.
- CLI docs (`docs/02-cli/02-cli_README.md`): document new config keys and new extractor/scorer backends as additional options.
- Any benchmark “knobs” docs: include new dimensions (scorer backend, near-duplicate backend).

---

Plan change notes:

- 2026-02-25: Initial plan drafted to implement Priority 1 (“recipe-likeness score + confidence gates everywhere candidates are created”) and to incorporate all Priority-1-mapped tool/library options as additive benchmarkable backends.