# ExecPlan: Integrate codex-farm 3-pass knowledge extraction into cookimport (recipeimport side)

IT IS INCREDIBLY IMPORTANT TO NOTE THAT YOU MUST NOT RUN THE CODEX FARM INTEGRAITON. BUILD THIS BUT DO NOT TEST IT "LIVE" BY ACTUALLY SUMMONING CODEX INSTANCES UNTIL I HAVE HAD A TIME TO THINK ABOUT HOW I WANT TO MANAGE TOKEN USE. DO NOT TEST THIS IN A WAY THAT CAUSES THE CODEX FARM PROGRAM TO USE TOKENS PLEASE!!!

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. :contentReference[oaicite:0]{index=0}

This plan must be maintained in accordance with `PLANS.md` at the repository root. :contentReference[oaicite:1]{index=1}

Primary context sources for this plan (for traceability only; the plan is self-contained):
- :contentReference[oaicite:2]{index=2} (conversation: “knowledge pipeline with codex farm”)
- :contentReference[oaicite:3]{index=3} (recipeimport/cookimport docs summary)
- :contentReference[oaicite:4]{index=4} (ExecPlan requirements / format)

## Purpose / Big Picture

After this change, a developer can run the import pipeline with an alternate “recipe/knowledge extraction mode” that uses `codex-farm` as an authoritative extractor across three narrow passes:

1) **Boundary selection (chunking)**: fix where a recipe (or other knowledge snippet span) starts/ends in the block stream, so downstream extraction is working on the right text.  
2) **Canonical text → schema.org Recipe**: produce a faithful schema.org Recipe JSON-LD from the corrected span.  
3) **schema.org → final (RecipeDraftV1) with correct ingredient↔line↔step mapping**: produce the final cookbook output model with a mapping table that can be programmatically validated.

A user can *see* it working by running `cookimport stage ... --recipe-extractor codex-farm` (with either a real codex-farm subprocess runner or a local mock runner), and observing:

- new run artifacts under the run folder:
  - `llm_jobs/pass1_chunking/`, `llm_jobs/pass2_schema/`, `llm_jobs/pass3_final/` (inputs to codex-farm)
  - `llm_out/pass1_chunking/`, `llm_out/pass2_schema/`, `llm_out/pass3_final/` (codex-farm outputs)
  - `llm_apply/` (cookimport-side validation + apply logs)
- recipe outputs (intermediate + final drafts) are produced from the codex-farm outputs when enabled, while deterministic mode remains unchanged by default.
- the per-file conversion report JSON includes a `codexFarm` section with counts, durations, and any validation warnings.

This plan implements “Phase 1 (rewrite-mode)” described in the conversation: LLM passes produce *full* outputs for each stage now (boundaries + canonical text, full schema.org, full final RecipeDraftV1), and we defer “patch-mode” until the baseline becomes mostly correct. :contentReference[oaicite:5]{index=5}

## Progress

- [ ] (2026-02-22) Milestone 0: Add cookimport-side codex-farm contracts (Pydantic models) + schema generation script + pipeline pack skeleton dirs.
- [ ] (2026-02-22) Milestone 1: Implement Pass 1 bundle export + output ingestion + span dedupe/overlap policy + recompute non-recipe blocks for chunking.
- [ ] (2026-02-22) Milestone 2: Implement Pass 2 bundle export + output ingestion + “extractive” validation checks + write schema.org intermediate drafts when enabled.
- [ ] (2026-02-22) Milestone 3: Implement Pass 3 bundle export + output ingestion + mapping integrity validation + write RecipeDraftV1 final drafts when enabled.
- [ ] (2026-02-22) Milestone 4: Wire into `cookimport stage` via RunSettings + CLI flags + ensure deterministic default behavior remains unchanged.
- [ ] (2026-02-22) Milestone 5: Add mock runner + tests + docs updates; ensure `pytest -q` passes without requiring codex-farm or network.

## Surprises & Discoveries

(Record as you implement.)

- Observation:  
  Evidence:  

## Decision Log

(Record decisions as you implement; initial plan decisions are listed so a future implementer understands why the design is shaped this way.)

- Decision: Implement three separate codex-farm passes (boundary → schema.org → final) with small, strict schemas, rather than a single “everything” pass.  
  Rationale: The conversation notes codex-farm’s strict JSON Schema contract is more reliable with smaller outputs, and staging isolates debugging to a pass. :contentReference[oaicite:6]{index=6}  
  Date/Author: 2026-02-22 / ChatGPT

- Decision: Use “rewrite-mode first, patch-mode later.”  
  Rationale: When upstream heuristics are often wrong, patch-mode assumes a mostly-correct baseline; rewrite-mode lets LLM be authoritative now, with guardrails and validations to detect hallucination. :contentReference[oaicite:7]{index=7}  
  Date/Author: 2026-02-22 / ChatGPT

- Decision: Keep deterministic pipeline as the default behavior; codex-farm mode must be explicitly enabled via RunSettings/CLI.  
  Rationale: Avoid silent regressions and keep existing users/tests stable; aligns with repo’s general stance that opt-in modes should not change defaults. (This matches patterns in other optional modes in the repo, even when those modes improve quality.)  
  Date/Author: 2026-02-22 / ChatGPT

- Decision: Cookimport will write job bundles to disk under the per-run directory, and codex-farm will be invoked in directory-in → directory-out mode; cookimport then validates/applies outputs.  
  Rationale: This matches codex-farm’s file-driven design (`{{INPUT_PATH}}`, resumable directory processing) and keeps coupling loose. :contentReference[oaicite:8]{index=8}  
  Date/Author: 2026-02-22 / ChatGPT

## Outcomes & Retrospective

(To be completed after major milestones or at completion.)

- Outcome:  
  What remains:  
  Lessons learned:  

## Context and Orientation

This repository is a Python CLI project named `cookimport` (this is the “recipeimport side” in the conversation). It ingests cookbooks/recipes from sources (EPUB/PDF/text/app exports) and emits structured outputs.

### Current deterministic pipeline (what exists today)

The current recipe path is:

1. An importer produces `RecipeCandidate` objects (heuristically segmented).  
2. `cookimport/staging/draft_v1.py` converts each candidate into:
   - schema.org-ish intermediate representation, and
   - final `RecipeDraftV1` (your cookbook3 final format), including ingredient parsing and ingredient↔step linking. :contentReference[oaicite:9]{index=9}

The current “knowledge extraction” path (non-recipe) is:

1. Importers also produce tip/topic candidates and “non-recipe blocks.”  
2. The pipeline generates knowledge chunks:
   - preferred: `chunks_from_non_recipe_blocks(non_recipe_blocks)`  
   - fallback: `chunks_from_topic_candidates(topic_candidates)` :contentReference[oaicite:10]{index=10}

This matters because **Pass 1 boundary selection must change what counts as “non-recipe blocks”**, otherwise knowledge chunks may accidentally include recipe text (or vice versa).

### Terms used in this plan (defined in plain language)

- **Block**: A small unit of extracted text (a heading, paragraph, list item, etc.) in a stable reading order. Blocks carry an index (position in the book), text, and sometimes location features (page/spine). The conversation explicitly calls out that cookimport already has a “block stream model” with indices and features, which is the anchor for evidence pointers. :contentReference[oaicite:11]{index=11}

- **Block stream**: The ordered list of Blocks for the entire source file.

- **RecipeCandidate**: A heuristically detected possible recipe span. The candidate generator should be “recall-first,” meaning it may include junk and spans that are too wide; the LLM pass will decide. :contentReference[oaicite:12]{index=12}

- **Non-recipe blocks**: Blocks not currently assigned to any recipe candidate span. Used to generate knowledge chunks.

- **Knowledge chunk (snippet)**: A span of non-recipe blocks grouped into a “useful” snippet (for tips, technique notes, etc.). In current code this is produced from non-recipe blocks. :contentReference[oaicite:13]{index=13}

- **codex-farm**: A local CLI orchestrator that runs structured Codex tasks over files in a directory, enforcing JSON Schema output contracts and providing retries/resume. Cookimport should treat it as an external tool, not a library.

- **Job bundle**: A JSON file cookimport writes to disk. One bundle corresponds to one codex-farm task (for one candidate/span). Bundles contain enough context for the model to make decisions, and enough identifiers for cookimport to apply outputs.

- **Evidence pointer**: A small reference that anchors an extracted field to the source blocks (block id/index and a short quote). This is a guardrail against hallucination; cookimport can also do deterministic checks (e.g., the extracted ingredient line must appear in canonical text). :contentReference[oaicite:14]{index=14}:contentReference[oaicite:15]{index=15}

### The 3-pass contract we are implementing (cookimport side)

We implement the “concrete 3-pass design” described in the conversation:

- Pass 1 input: blocks_before + blocks_candidate + blocks_after, plus heuristic hints.  
  Pass 1 output: is_recipe, corrected start/end block indices, title, canonical_text, excluded blocks, reasoning tags. :contentReference[oaicite:16]{index=16}

- Pass 2 input: canonical_text (and optionally blocks for evidence).  
  Pass 2 output: full schema.org Recipe JSON, extracted ingredient lines (verbatim), extracted instruction steps (verbatim), evidence pointers, warnings. :contentReference[oaicite:17]{index=17}

- Pass 3 input: schema.org JSON + extracted lines.  
  Pass 3 output: full final RecipeDraftV1 + an explicit mapping table that is easy to validate. :contentReference[oaicite:18]{index=18}

## Plan of Work

### Milestone 0: Contracts + schema generation + pipeline pack skeleton (cookimport side)

At the end of this milestone, the repo has:

- Pydantic v2 models for pass 1/2/3 input and output contracts.
- A script that writes JSON Schema files for those outputs to a committed location (used by codex-farm pipelines).
- A committed `llm_pipelines/` directory skeleton in the recipeimport repo that will be used as `CODEX_FARM_ROOT`.

This milestone is purely additive and testable without codex-farm installed.

#### Files to add

Create a new module tree (repository-relative paths):

- `cookimport/codex_farm/__init__.py`
- `cookimport/codex_farm/contracts.py`  
  Contains Pydantic models for:
  - Pass1BoundaryBundle, Pass1BoundaryResult
  - Pass2SchemaBundle, Pass2SchemaResult
  - Pass3FinalBundle, Pass3FinalResult
  Also contains:
  - small “evidence pointer” model
  - helper to build deterministic `job_id` (stable, filename-safe)
  - `schema_version` fields on all models
- `cookimport/codex_farm/schema_gen.py`  
  A small CLI-able module: `python -m cookimport.codex_farm.schema_gen` writes schema JSON files to `llm_pipelines/schemas/` and prints what it wrote.

Add the pipeline pack skeleton (repo root):

- `llm_pipelines/README.md`  
  Explain that this is the pipeline pack root and should be used as `CODEX_FARM_ROOT`.
- `llm_pipelines/schemas/`  
  Output schemas generated by `schema_gen.py`.
- `llm_pipelines/pipelines/` and `llm_pipelines/prompts/`  
  These can be empty placeholders initially in this milestone; their concrete contents are owned by the “codex farm side” work, but the directories must exist so the subprocess runner can point at the root.

#### Contract shapes (explicit, so implementers don’t guess)

All contracts should be “strict and small,” using required-but-nullable for optional data (codex-farm structured output tends to behave better when fields are required, even if nullable). :contentReference[oaicite:19]{index=19}

Pass 1 bundle (one file per candidate):

    {
      "schema_version": 1,
      "job_id": "job_3f1d... (filename-safe)",
      "source": {
        "run_id": "2026-02-22_12.34.56",
        "source_path": "data/input/book.epub",
        "source_hash": "sha256:...",
        "importer_name": "epub",
        "workbook_slug": "book_slug"
      },
      "candidate": {
        "candidate_id": "urn:recipeimport:...:c12",
        "heuristic_start_block_index": 120,
        "heuristic_end_block_index": 180,
        "heuristic_title": null
      },
      "blocks_before": [ { "block_index": 100, "block_id": "...", "text": "...", "features": { ... } }, ... ],
      "blocks_candidate": [ ... ],
      "blocks_after": [ ... ]
    }

Pass 1 result:

    {
      "schema_version": 1,
      "job_id": "job_3f1d...",
      "candidate_id": "urn:recipeimport:...:c12",
      "is_recipe": true,
      "start_block_index": 118,
      "end_block_index": 172,
      "title": "Best Pancakes",
      "reasoning_tags": ["ingredient_header_found", "next_recipe_title_detected"],
      "excluded_block_ids": ["block_...", "..."],
      "canonical_text": "string containing the recipe text to be used downstream"
    }

Pass 2 result:

    {
      "schema_version": 1,
      "job_id": "job_3f1d...",
      "recipe_job_id": "job_3f1d... (same as pass1 job id)",
      "schemaorg_recipe": { "...schema.org Recipe object..." },
      "extracted_ingredients": ["1 cup flour", "..."],
      "extracted_instructions": ["Mix the batter...", "..."],
      "field_evidence": [
        { "field": "recipeYield", "block_id": "...", "block_index": 140, "quote": "Serves 4" }
      ],
      "warnings": ["yield ambiguous", "..."]
    }

Pass 3 result:

    {
      "schema_version": 1,
      "job_id": "job_3f1d...",
      "recipe_job_id": "job_3f1d...",
      "final_recipe_draft_v1": { "...RecipeDraftV1 JSON..." },
      "mapping_table": [
        {
          "ingredient_line_id": "ing_07",
          "raw_line": "1 tsp kosher salt",
          "maps_to_final_ingredient_index": 6,
          "used_in_step_indexes": [2, 5],
          "confidence": 0.74,
          "evidence_quote": "Season with salt and pepper..."
        }
      ],
      "warnings": []
    }

### Milestone 1: Pass 1 export + ingestion + recompute non-recipe blocks

At the end of this milestone, a developer can:

- Build pass 1 bundles from an in-memory ConversionResult for a source.
- Write them to `<run_root>/llm_jobs/pass1_chunking/`.
- (Optionally) run codex-farm to produce outputs into `<run_root>/llm_out/pass1_chunking/`.
- Ingest pass 1 outputs and compute a **final, deduped list of recipe spans**.
- Recompute `non_recipe_blocks` from the final spans so chunking uses corrected spans.

This milestone is verifiable using a `MockCodexFarmRunner` (no codex-farm install required).

#### Files to add / edit

Add:

- `cookimport/codex_farm/bundles.py`  
  Contains:
  - `load_full_block_stream(...)` (how cookimport gets the full block list for the source; see below)
  - `build_pass1_bundles(blocks, recipe_candidates, context_before, context_after, run_meta) -> list[Pass1BoundaryBundle]`
  - `write_bundles(bundles, out_dir) -> manifest.json` (writes one JSON per bundle; also writes a manifest mapping `job_id -> filename`)

- `cookimport/codex_farm/results.py`  
  Contains:
  - `load_pass1_results(out_dir) -> list[Pass1BoundaryResult]`
  - `select_recipe_spans(pass1_results, blocks_len) -> list[SelectedSpan]` including:
    - validation (indices in range, start <= end)
    - dedupe and overlap resolution policy (defined below)
    - stable ordering (by start_block_index)

Add:

- `cookimport/codex_farm/mock_runner.py`  
  Implements a runner that:
  - reads bundles in a directory
  - writes valid results with “echo boundaries” behavior (use heuristic boundaries; canonical_text is join of candidate blocks)
  This is used only for tests / offline validation.

Edit stage pipeline to call pass1 span recomputation **only when codex-farm recipe extractor mode is enabled** (we’ll do the full wiring in Milestone 4, but in Milestone 1 you can wire this into a small isolated harness function first).

#### How to obtain the full block stream (critical detail)

Pass 1 needs blocks_before/candidate/after, so cookimport must obtain the full ordered block stream.

Preferred approach for this plan (simple and robust):

- For EPUB/PDF (block-first importers), ensure the importer already writes a raw artifact containing all blocks in order (“full_text” / block dump). The docs already reference that the pipeline stores raw extraction artifacts and uses Blocks as provenance anchors. :contentReference[oaicite:20]{index=20}

- Implement `load_full_block_stream(...)` to load the full block list from the raw artifact file for the current run (not by reconstructing from candidates). The exact raw artifact path conventions may differ per importer, so implement it as:
  1) First try: look up the “full block dump” file from the raw-artifacts manifest inside the per-file conversion report JSON in the run root.
  2) Fallback: infer a conventional path like `<run_root>/raw/<importer_name>/<source_hash>/full_text.json` if the manifest is unavailable.

If neither is available, codex-farm recipe extraction mode should fail fast with a clear error (“block stream not available; this importer does not support codex-farm extraction”).

#### Overlap + dedupe policy (must be deterministic)

Heuristic candidates may overlap, and pass 1 may return identical spans for multiple candidates. We need a deterministic policy so downstream doesn’t drift run-to-run.

Implement `select_recipe_spans(...)` with these rules:

1. Drop results where `is_recipe == false`.
2. Validate start/end indices:
   - If out of range, record a warning and drop that result.
3. Dedupe exact duplicates:
   - Key: `(start_block_index, end_block_index)`. Keep the first result in stable sort order of `job_id`.
4. Resolve overlaps:
   - Sort spans by `(start_block_index, end_block_index)`.
   - Greedy keep:
     - If a span does not overlap the last kept span: keep it.
     - If it overlaps:
       - Prefer the span with the earlier start and later end only if it “contains” the other span by ≥ 80% of blocks (containment ratio), else keep the earlier span and drop the later span.
   - Record every dropped overlap conflict into `<run_root>/llm_apply/pass1_overlap_conflicts.jsonl` with both spans and a reason.

This is intentionally conservative; it keeps pipeline running and leaves artifacts to audit.

#### Recompute non-recipe blocks

Once final recipe spans are selected, recompute non-recipe blocks as:

- `covered_indices = union of all [start..end] ranges` (inclusive)
- `non_recipe_blocks = [block for block in blocks if block.block_index not in covered_indices]`

This is the minimum needed to make “knowledge chunk generation” reflect corrected boundaries.

### Milestone 2: Pass 2 schema.org extraction

At the end of this milestone:

- Pass 2 bundles are generated from pass 1 results.
- Pass 2 results are ingested and validated with simple “extractive” checks:
  - each extracted ingredient line appears in canonical_text (exact or normalized)
  - each extracted instruction step appears in canonical_text (exact or normalized)
- The schema.org output is written to the same intermediate-drafts location the rest of the system expects when codex-farm mode is enabled.

This milestone is motivated by the conversation: pass 2 should be an authoritative extractor from canonical_text, and extracted_ingredients/instructions exist specifically to enable deterministic hallucination checks. :contentReference[oaicite:21]{index=21}

#### Implementation details

Add functions:

- `build_pass2_bundles(selected_spans, blocks, run_meta, hint_candidates_by_id)`  
  Each bundle includes:
  - `canonical_text` from pass 1 result
  - `blocks_in_span` (or the full span block list) so evidence pointers can reference block ids/indices
  - optional `heuristic_candidate_hint` (serialized RecipeCandidate) if available, marked as “hint only” (do not treat as authoritative)

- `validate_pass2_result(result, canonical_text) -> list[warnings]`  
  Normalize by:
  - lowercasing
  - collapsing whitespace
  - stripping punctuation lightly (use existing `normalize_text_for_matching` if available in repo, because it’s already used elsewhere). :contentReference[oaicite:22]{index=22}

Write validation warnings to `<run_root>/llm_apply/pass2_validation_warnings.jsonl`.

### Milestone 3: Pass 3 final RecipeDraftV1 + mapping integrity validation

At the end of this milestone:

- Pass 3 bundles are generated from pass 2 results.
- Pass 3 results are ingested.
- The final RecipeDraftV1 is validated using the repo’s existing Pydantic model (do not accept “almost JSON”).
- The mapping_table is validated with deterministic rules (below).
- Final drafts are written to the usual `final drafts/...` output locations when codex-farm mode is enabled.

#### Mapping validation rules (small but meaningful)

Validate `mapping_table` entries:

- `maps_to_final_ingredient_index` is within range of `final_recipe_draft_v1.ingredients`.
- Every `ingredient_line_id` is unique across mapping_table.
- `used_in_step_indexes` are integers in range `[0, len(final_recipe_draft_v1.steps)-1]`.
- Every final ingredient index referenced by mapping_table exists.
- If mapping_table is empty but the recipe has ingredients and steps, record a warning (do not hard-fail unless you decide so later).

Write mapping warnings to `<run_root>/llm_apply/pass3_mapping_warnings.jsonl`.

### Milestone 4: Wire into `cookimport stage` (RunSettings + CLI flags)

At the end of this milestone, codex-farm extraction is a first-class, opt-in pipeline mode.

#### RunSettings additions

Find the RunSettings model (search for `class RunSettings` in `cookimport/`), and add fields:

- `recipe_extractor: Literal["deterministic", "codex_farm"]` (default: deterministic)
- `codex_farm_root: str | None` (default: `"llm_pipelines"` resolved relative to repo root, or None to require env)
- `codex_farm_bin: str` (default: `"codex-farm"`)
- `codex_farm_runner: Literal["subprocess", "mock"]` (default: subprocess in real runs; tests use mock)
- `codex_farm_pipeline_pass1: str` (default: `"recipe.chunking.v1"`)
- `codex_farm_pipeline_pass2: str` (default: `"recipe.schemaorg.v1"`)
- `codex_farm_pipeline_pass3: str` (default: `"recipe.final.v1"`)
- `codex_farm_context_before_blocks: int` (default: 30)
- `codex_farm_context_after_blocks: int` (default: 30)

These defaults correspond to the 3-pass design in the conversation. :contentReference[oaicite:23]{index=23}

#### CLI wiring

Edit the stage CLI entrypoint (likely `cookimport/cli.py`) to add flags:

- `--recipe-extractor deterministic|codex-farm`
- `--codex-farm-root <path>`
- `--codex-farm-bin <cmd>`
- `--codex-farm-runner subprocess|mock`
- `--codex-farm-pipeline-pass1 <id>` (and pass2/pass3)
- `--codex-farm-context-before-blocks N`
- `--codex-farm-context-after-blocks N`

Ensure these flags populate RunSettings and are recorded in the run manifest / per-file report (do not store secrets).

#### Stage execution wiring

Locate the per-file stage processing function (often called something like `stage_one_file` in `cookimport/cli_worker.py`). The docs summary indicates the deterministic conversion uses `cookimport/staging/draft_v1.py` and writer outputs are emitted from `cookimport/staging/writer.py`. :contentReference[oaicite:24]{index=24}

Refactor gently so there is a single “post-convert” function that takes:

- `conversion_result` (recipes, non_recipe_blocks, tip/topic candidates, raw artifacts, report info)
- `run_root` (output directory for this run)
- `run_settings`

Then:

- If `recipe_extractor == "deterministic"`:
  - keep existing behavior unchanged.
- If `recipe_extractor == "codex_farm"`:
  1) Load full block stream.
  2) Run pass1→pass2→pass3 via the orchestrator (runner chosen by run_settings).
  3) Replace the “recipes to write” list with the final drafts returned from pass3.
  4) Replace `non_recipe_blocks` with recomputed blocks from selected spans before running chunking.
  5) Continue with chunking/tip/topic writing (tips/topics can remain heuristic for now; at minimum chunking must use corrected non-recipe blocks).

Write codex-farm artifacts under the run root:

- `<run_root>/llm_jobs/...`
- `<run_root>/llm_out/...`
- `<run_root>/llm_apply/...`

Update the per-file conversion report JSON to include:

    "codexFarm": {
      "enabled": true,
      "runner": "subprocess",
      "pipelines": { "pass1": "...", "pass2": "...", "pass3": "..." },
      "job_counts": { "pass1": 12, "pass2": 10, "pass3": 10 },
      "durations_seconds": { "pass1": 34.2, "pass2": 55.0, "pass3": 41.8 },
      "warnings_count": 7,
      "failures_count": 1
    }

### Milestone 5: Tests + docs updates (no network required)

At the end of this milestone, `pytest -q` passes without requiring codex-farm or any LLM credentials.

#### Tests to add

Add unit tests under `tests/`:

- `tests/test_codex_farm_contracts.py`  
  - Model validation: required-but-nullable behavior.
  - Schema generation produces JSON schema dicts.

- `tests/test_codex_farm_pass1_span_selection.py`  
  - Dedupe and overlap policy is deterministic.
  - Out-of-range indices are rejected and logged.

- `tests/test_codex_farm_orchestrator_mock.py`  
  - Use the mock runner to simulate pass outputs and ensure:
    - `llm_jobs/` and `llm_out/` folders are created
    - pass1 recomputes non-recipe blocks
    - pass3 output writes valid final drafts (for mock runner, you may produce the final draft by calling the existing deterministic converter on the heuristic candidate as a “mock LLM output,” so the JSON is valid without guessing RecipeDraftV1 fields).

Never call real codex-farm or a networked LLM in tests.

#### Docs updates

Update operator docs:

- `docs/02-cli/02-cli_README.md` (or wherever stage flags are documented)
  - explain `--recipe-extractor codex-farm`
  - list new codex-farm flags
  - describe artifact folders (`llm_jobs`, `llm_out`, `llm_apply`)
- `docs/01-architecture/01-architecture_README.md` (short addendum)
  - describe the 3-pass codex-farm lane and how it plugs in.

Also add a short note in `IMPORTANT CONVENTIONS.md`:
- never write secrets into run reports/manifests
- codex-farm root is a local path (`llm_pipelines/`) and is safe to commit.

## Concrete Steps

All commands below assume you are at the repository root.

1) Run unit tests as you build Milestones 0–3 (fast feedback):

    source .venv/bin/activate
    pytest -q tests/test_codex_farm_contracts.py tests/test_codex_farm_pass1_span_selection.py

Expected (example):

    2 passed

2) Run the end-to-end stage path using the **mock runner** (no codex-farm install required):

    source .venv/bin/activate
    rm -rf /tmp/cookimport_out
    cookimport stage tests/fixtures/sample.epub \
      --out /tmp/cookimport_out \
      --workers 1 \
      --recipe-extractor codex-farm \
      --codex-farm-runner mock

Expected observable artifacts under the new run directory `/tmp/cookimport_out/<timestamp>/`:

- `llm_jobs/pass1_chunking/` contains JSON bundles
- `llm_out/pass1_chunking/` contains JSON results produced by mock runner
- `llm_apply/` contains overlap/validation JSONLs (may be empty)
- `intermediate drafts/...` and `final drafts/...` exist (written from the mock outputs)

3) Optional: run with the **real codex-farm subprocess runner** (requires codex-farm installed and configured):

    source .venv/bin/activate
    export CODEX_FARM_ROOT="$(pwd)/llm_pipelines"
    cookimport stage data/input/<some_book>.epub \
      --workers 1 \
      --recipe-extractor codex-farm \
      --codex-farm-runner subprocess \
      --codex-farm-bin codex-farm

Expected:

- Terminal output shows codex-farm being invoked for pass1, pass2, pass3 (one directory-in → directory-out per pass).
- The run directory contains `llm_out/pass2_schema/` and `llm_out/pass3_final/` populated by codex-farm outputs.

4) Full suite check (should pass without codex-farm):

    source .venv/bin/activate
    pytest -q

Expected:

- All tests pass (or, if the repo has known pre-existing failures unrelated to this feature, the failures should be unchanged and clearly outside new test modules).

## Validation and Acceptance

Automated acceptance:

- With `--recipe-extractor deterministic` (default), `cookimport stage ...` behaves exactly as before (no new llm_* directories are required; reports unchanged aside from any intentionally-added optional fields gated behind codex-farm mode).
- With `--recipe-extractor codex-farm --codex-farm-runner mock`, stage completes offline and produces:
  - `llm_jobs/`, `llm_out/`, `llm_apply/` artifacts
  - intermediate + final drafts written from the codex-farm lane (mocked)
  - a per-file conversion report containing `codexFarm.enabled = true`.

Manual acceptance (must do at least once after implementation):

1) Run stage on a real “messy” EPUB or PDF using codex-farm subprocess runner and confirm:
   - recipe count changes in plausible ways (false positives may be removed; boundaries improved)
   - knowledge chunks do not contain recipe blocks (spot-check chunk text around recipe boundaries)
   - mapping_table warnings are near-zero for “easy” recipes and are explicitly logged for tricky ones.

2) Open the conversion report JSON for that run and confirm:
   - it records which pipelines were run
   - it records counts + durations
   - it records any invalid outputs and what fallback occurred.

## Idempotence and Recovery

Safe reruns:

- Bundle writing must be deterministic. If `<run_root>/llm_jobs/passX/...` already exists and file content matches, rewriting should be a no-op (or overwrite is allowed but should not change content).
- `MockCodexFarmRunner` reruns are safe because it overwrites its own `llm_out/...` outputs deterministically.
- For subprocess runner, `codex-farm` itself is designed for resumable directory processing; rerunning the same pass against the same `--in` and `--out` directories should be safe (and faster if codex-farm caches/resumes).

Recovery:

- If pass outputs are missing or invalid:
  - cookimport should record a failure entry in `<run_root>/llm_apply/...` and fall back per-recipe to deterministic conversion (or skip recipe with a clear report entry, depending on the repo’s existing failure policy).
- If you need to “start over” for one run:
  - delete `<run_root>/llm_out/` and rerun stage in codex-farm mode.
  - do not delete raw artifacts unless disk is a problem; raw artifacts are useful for debugging provenance.

Secrets:

- Never write any Codex/OpenAI keys into run manifests, reports, or job bundles.
- `CODEX_FARM_ROOT` is a local filesystem path and is safe to record; it must not include secret tokens.
