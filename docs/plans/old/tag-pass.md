# Add codex-farm tag assignment pass for recipes (catalog-driven, LLM-optional)

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan must be maintained in accordance with `docs/PLANS.md` from the repository root.

## Purpose / Big Picture

After this change, a user can run an **optional** codex-farm-powered tagging pass that assigns recipe tags from an existing **tag catalog** (~200 tags), producing auditable tag suggestions per recipe (and optionally proposing new tags for human review). This adds a high-recall tagging capability for categories that are hard to capture with deterministic regex rules (cuisine, dietary, vibe, season, etc.) while keeping the system deterministic-first and safe-by-default.

You will be able to see it working in two ways:

1) Via the existing tagging CLI:
   - Running `cookimport tag-recipes suggest --draft-dir ... --catalog-json ... --llm` will now perform a real codex-farm LLM second pass (instead of a mock/no-op) and emit additional tag suggestions for categories the deterministic engine left empty.

2) Via the staging pipeline (optional integration, gated):
   - Running `cookimport stage <path> --llm-tags-pipeline codex-farm-tags-v1 --tag-catalog-json data/tagging/tag_catalog.json` will produce new tag artifacts under the stage run folder, alongside the existing `final drafts/` outputs.

The default behavior remains unchanged: no LLM calls and no tag artifacts unless explicitly enabled.

## Progress

- [ ] (2026-02-25) Read and understand current tagging subsystem and codex-farm runner/orchestrator surfaces (files listed in “Context and Orientation”).
- [ ] (2026-02-25) Decide the concrete “tag output contract” (what file(s) are written, where, and their JSON shape) and document it in this plan.
- [ ] (2026-02-25) Add codex-farm pipeline pack assets for tags (`recipe.tags.v1`: pipeline JSON, prompt, output schema) and extend pack asset tests.
- [ ] (2026-02-25) Implement a codex-farm-backed LLM provider for tagging (batchable), wire it into `cookimport/tagging/llm_second_pass.py`.
- [ ] (2026-02-25) Add deterministic + codex-farm tag suggestion “orchestrator” function that can process a folder of draft JSONs.
- [ ] (2026-02-25) (Optional but recommended) Integrate the tagging pass into `cookimport stage` behind `--llm-tags-pipeline`, writing tag artifacts into the stage output run folder.
- [ ] (2026-02-25) Add/extend unit tests using `cookimport/llm/fake_codex_farm_runner.py` so tests are deterministic and do not require external codex-farm access.
- [ ] (2026-02-25) Update docs: `docs/10-llm/10-llm_README.md`, add a new `docs/10-llm/tags_pass.md` (analog to `knowledge_harvest.md`), and update `docs/09-tagging/09-tagging_README.md` and/or `docs/plans/I4.1-Auto-tag.md` notes.
- [ ] (2026-02-25) Run full relevant test slices and capture evidence in this plan.

## Surprises & Discoveries

- Observation: (fill in during implementation)
  Evidence: (paste a short snippet of failing/passing test output or a log line)

## Decision Log

- Decision: Implement tags as a separate codex-farm “pass” (`recipe.tags.v1`) rather than expanding `recipe.final.v1` output schema.
  Rationale: Keeps recipe codex-farm parsing correction policy-lock (`llm_recipe_pipeline=off`) untouched, avoids re-generating entire drafts just to add tags, and keeps tagging optionally runnable on top of deterministic stage outputs.
  Date/Author: (fill in)

- Decision: LLM may propose “new tags”, but the system will not auto-create DB tags or auto-apply unknown tags; it will only emit proposals into an artifact for human review.
  Rationale: Tag assignment DB writes are insert-only and there is no safe automatic removal; auto-creating tags increases long-term taxonomy risk.
  Date/Author: (fill in)

## Outcomes & Retrospective

- (fill in at milestone completion / end)

## Context and Orientation

This repository has two relevant subsystems that already exist:

1) Tagging subsystem (`cookimport/tagging/`), described in:
   - `docs/09-tagging/09-tagging_README.md`
   - `docs/plans/I4.1-Auto-tag.md` (older plan; treat as background and reuse what still matches current code)

   Key points from the existing tagging design:
   - The tag catalog is exported from Postgres (tables: `public.recipe_tag_categories`, `public.recipe_tags`) to a JSON snapshot, typically at `data/tagging/tag_catalog.json`.
   - Deterministic rules are keyed by `tag.key_norm` so rules are stable across DB tag UUID changes.
   - There is already an `llm_second_pass.py` scaffold that is currently not truly wired (it uses a mock/no-op provider).
   - The CLI already has:
     - `cookimport tag-catalog export ...`
     - `cookimport tag-recipes suggest ... --llm`
     - `cookimport tag-recipes apply ... --llm`

2) Codex-farm LLM integration (`cookimport/llm/`), described in:
   - `docs/10-llm/10-llm_README.md`
   - `docs/10-llm/knowledge_harvest.md` (pass4 example pattern)

   Key points from the existing codex-farm design:
   - Codex-farm is invoked via subprocess with configurable command/root/workspace (`codex_farm_cmd`, `codex_farm_root`, `codex_farm_workspace_root`).
   - Pipeline “pack assets” live under `llm_pipelines/`:
     - `llm_pipelines/pipelines/*.json` (pipeline specs)
     - `llm_pipelines/prompts/*.prompt.md` (prompt templates)
     - `llm_pipelines/schemas/*.output.schema.json` (strict output JSON schema)
   - There is an actionable runner boundary:
     - `cookimport/llm/codex_farm_runner.py` (subprocess boundary)
     - `cookimport/llm/fake_codex_farm_runner.py` (deterministic test runner)
   - Stage already supports an optional codex-farm pass4 “knowledge harvest” behind `--llm-knowledge-pipeline`.

Important constraint to preserve:
- `llm_recipe_pipeline` is policy-locked to `off`. This plan must not require turning it on. Tagging must be a separate, explicitly enabled lane.

Terminology used in this plan (define once, use consistently):
- Tag catalog: the set of allowed tags (and categories) exported from DB or provided as JSON. Each tag has a stable `key_norm` like `instant-pot`.
- Tag suggestion: a proposed assignment of a catalog tag to a recipe, with a confidence score and evidence text.
- Codex-farm “pass” (in this plan): a codex-farm pipeline spec + prompt + output schema that can be invoked to produce a structured result. We will add `recipe.tags.v1` as a new pipeline in the pack.

## Plan of Work

This work is split into milestones that each result in something demonstrably working.

### Milestone 1: Define the tag-pass output contract and where artifacts live

By the end of this milestone, you will have a written contract (in this plan) for:
- What inputs the tag pass receives (recipe text + shortlist candidates).
- What the tag pass outputs (selected tags + optional new tag proposals).
- Where artifacts are written for:
  - CLI `tag-recipes suggest`
  - Optional stage integration
- How to validate the outputs are correct (schema + runtime validation).

Work:
- Read `cookimport/tagging/render.py` and current report output format (it already writes `tagging_report.json`).
- Decide whether to:
  - Keep the existing `*.tags.json` per-recipe output shape and add LLM metadata fields, or
  - Introduce a new `*.tags.v1.json` output while preserving backward compatibility.

Strong recommendation:
- Preserve the existing artifact naming from I4.1 where possible:
  - A per-workbook `tagging_report.json`
  - Optional per-recipe `r{n}.tags.json`
- Add minimal, additive fields:
  - `source: "deterministic" | "llm"`
  - `llm_pipeline_id`
  - `catalog_fingerprint` (already exists in catalog snapshot)
  - `new_tag_proposals` (separate list)

Acceptance for this milestone:
- The contract is clearly written in this ExecPlan and can be implemented without “design questions”.

### Milestone 2: Add codex-farm pipeline assets for `recipe.tags.v1`

By the end of this milestone, the repo will contain a new codex-farm pipeline in `llm_pipelines/` with:
- A pipeline spec JSON
- A prompt template markdown
- An output schema JSON
and the existing pipeline-pack tests will pass.

Work:
- Create these new files (names are important and should match patterns used elsewhere):
  - `llm_pipelines/pipelines/recipe.tags.v1.json`
  - `llm_pipelines/prompts/recipe.tags.v1.prompt.md`
  - `llm_pipelines/schemas/recipe.tags.v1.output.schema.json`

- Use the knowledge pass and/or recipe passes as templates (do not invent a new pack structure):
  - Follow the existing fields in `llm_pipelines/pipelines/recipe.knowledge.v1.json` for prompt and schema path wiring.
  - Keep prompt templates as `*.prompt.md` (not `.txt`).

Prompt content guidance (must be explicit so the model behaves safely):
- The model must select tags only from the provided candidates.
- The model must not hallucinate additional tags into `selected_tags`.
- The model may propose new tags only in a separate list (`new_tag_proposals`) with display names and rationale.
- The model must keep evidence short and “machine-auditable” (for example, quote a short phrase or point to “ingredient list mentions X”).

Output schema guidance:
- Require:
  - `selected_tags`: array of objects with:
    - `tag_key_norm` (string)
    - `category_key_norm` (string)
    - `confidence` (number 0..1)
    - `evidence` (string, short)
- Optional:
  - `new_tag_proposals`: array with:
    - `proposed_category` (string; either an existing category key_norm or freeform “new-category”)
    - `display_name` (string)
    - `rationale` (string)

Tests:
- Run the existing pack asset tests and update them if they require enumerating pipeline files:
  - `pytest tests/llm -q`
  - Specifically ensure `tests/test_llm_pipeline_pack.py` and `tests/test_llm_pipeline_pack_assets.py` (names may differ; locate the actual files in `tests/llm/`) pass.

Acceptance:
- The new `recipe.tags.v1` assets exist.
- Pack tests pass with no external codex-farm dependency.

### Milestone 3: Implement codex-farm-backed LLM provider for the tagging second pass

By the end of this milestone, `cookimport tag-recipes suggest --llm` will perform a real second pass using codex-farm (when enabled/configured), and otherwise fall back safely.

Work:
- Read these files to find the current LLM scaffold and its boundary:
  - `cookimport/tagging/llm_second_pass.py`
  - `cookimport/llm/codex_farm_runner.py`
  - `cookimport/llm/fake_codex_farm_runner.py`

- Implement a new provider module, recommended path:
  - `cookimport/tagging/codex_farm_tags_provider.py`

Provider responsibilities:
- Batch operation: given N recipes that need LLM fill, write N input JSON files into an `in/` directory, run codex-farm once, and read N outputs.
- Use the existing candidate shortlist approach from I4.1:
  - Only run LLM for categories that deterministic tagging left empty.
  - For each missing category, pass a shortlist (for example top 10 candidates).
  - Keep shortlists category-scoped so the model cannot pick a “cuisine” tag as a “dietary” tag.

Input JSON shape (example; actual field names should match what your prompt expects):
  - recipe_id (string)
  - title (string)
  - description (string|null)
  - ingredients (array of strings)
  - instructions (array of strings)
  - notes (string|null)
  - missing_categories (array of category_key_norm strings)
  - candidates_by_category (object mapping category_key_norm -> array of candidate tag objects)
    - candidate tag object should include:
      - tag_key_norm
      - display_name

In this plan, avoid including the entire 200-tag catalog in every prompt. Always shortlist.

Validation logic (must be implemented in Python, not just “in the prompt”):
- Parse codex-farm outputs with a strict schema validator (Pydantic model and/or JSON schema validation).
- For each `selected_tags[]` entry:
  - Ensure the tag exists in the loaded catalog by `key_norm`.
  - Ensure the category matches the catalog’s category for that tag.
  - Ensure the tag was in the provided candidate shortlist for that category.
  - Ensure confidence is in 0..1.
- Any invalid entries must be dropped and recorded in the tagging report under a `llm_validation` section with counts.

Failure handling:
- Respect existing codex-farm failure mode semantics (see run setting `codex_farm_failure_mode`):
  - `fail`: tagging run errors if codex-farm cannot run or outputs are invalid beyond a small threshold.
  - `fallback`: warn once and return deterministic-only suggestions.

Wire-up:
- Update `cookimport/tagging/llm_second_pass.py` to call your new provider instead of the mock.
- Ensure the `--llm` flag behavior remains “disabled by default”.

Acceptance:
- With a working codex-farm setup, `cookimport tag-recipes suggest --llm` produces additional suggestions for LLM-reserved categories.
- Without codex-farm installed, running with `--llm` produces:
  - a clear warning
  - deterministic-only output (no crash) when failure mode is fallback
  - a clear failure when failure mode is fail

### Milestone 4: Optional stage integration behind `--llm-tags-pipeline`

By the end of this milestone, `cookimport stage` can optionally emit tag artifacts as part of a stage run, without changing default behavior.

Work:
- Add new run settings fields in `cookimport/config/run_settings.py` with UI metadata so interactive mode can edit them:
  - `llm_tags_pipeline` (default `off`, allowed: `off|codex-farm-tags-v1`)
  - `codex_farm_pipeline_pass5_tags` (default `recipe.tags.v1`)
  - `tag_catalog_json` (default `data/tagging/tag_catalog.json`, or unset with explicit CLI requirement)

- Add stage CLI flags (in `cookimport/cli.py`) mirroring the knowledge pipeline pattern:
  - `--llm-tags-pipeline TEXT` (default `off`)
  - `--codex-farm-pipeline-pass5-tags TEXT` (default `recipe.tags.v1`)
  - `--tag-catalog-json PATH` (default `data/tagging/tag_catalog.json`)

- Find the current knowledge harvesting integration point by searching for `llm_knowledge_pipeline` usage in stage flow:
  - `ripgrep "llm_knowledge_pipeline" -n cookimport`
  - Mirror that call pattern to invoke the tagging pass after final drafts are written.

Where to write stage artifacts:
- Under the stage run root (`data/output/<timestamp>/`), add:
  - `tags/<workbook_slug>/tagging_report.json`
  - `tags/<workbook_slug>/r{index}.tags.json` (or similar per-recipe artifacts)
  - Optional: `tags/tags_index.json` listing which workbooks have tag outputs
- Under raw LLM IO for audit (mirror knowledge structure):
  - `raw/llm/<workbook_slug>/pass5_tags/in/*.json`
  - `raw/llm/<workbook_slug>/pass5_tags/out/*.json`
  - `raw/llm/<workbook_slug>/pass5_tags_manifest.json`

Ensure stage remains safe and idempotent:
- If tag catalog JSON is missing and tagging is enabled:
  - Fail fast with a clear message (recommended), or
  - Warn and skip tagging (only if you document why).
- Re-running stage creates a new timestamp run folder anyway; do not overwrite prior runs.

Acceptance:
- Running:
    - `cookimport stage <path> --llm-tags-pipeline codex-farm-tags-v1 --tag-catalog-json data/tagging/tag_catalog.json`
  writes tag outputs into that run folder.
- Running without `--llm-tags-pipeline` produces no tag artifacts and behaves exactly as before.

### Milestone 5: Tests and documentation updates

By the end of this milestone, the new functionality is covered by deterministic tests and documented for future maintainers.

Tests:
- Extend `cookimport/llm/fake_codex_farm_runner.py` so it can simulate running `recipe.tags.v1`.
  - The fake runner should write deterministic outputs based on simple keywords in the input (for example, “taco” -> cuisine/mexican).
  - Keep the fake runner purely local and stable.

- Add unit tests under the appropriate domain folder (likely `tests/tagging/` and `tests/llm/`):
  - One test that ensures the codex-farm provider validates outputs and rejects tags not in candidates.
  - One test that ensures a “missing categories” recipe gets filled by LLM suggestions and then policies are applied.
  - One test that ensures failure-mode fallback yields deterministic-only.

- Ensure existing tagging gold tests still pass:
  - `pytest tests/tagging -q`

Docs:
- Update `docs/10-llm/10-llm_README.md` to mention:
  - `recipe.tags.v1` assets
  - the new `llm_tags_pipeline` gate
  - the new pass id setting `codex_farm_pipeline_pass5_tags`
- Add a new doc file:
  - `docs/10-llm/tags_pass.md` (format like `knowledge_harvest.md`), including:
    - how to run
    - required prerequisites (tag catalog JSON)
    - output locations
    - pipeline assets paths
- Update `docs/09-tagging/09-tagging_README.md` to note that `llm_second_pass.py` is now wired via codex-farm (and how to enable).
- Optionally add a short “superseded notes” section to `docs/plans/I4.1-Auto-tag.md` clarifying what changed since that older plan (do not delete historical content).

Acceptance:
- `pytest tests/tagging tests/llm -q` passes.
- Docs clearly tell a novice how to run the feature and where outputs go.

## Concrete Steps

All commands below are from the repository root.

1) Baseline: export a tag catalog snapshot (one-time, if you have DB access):
    - `source .venv/bin/activate`
    - `cookimport tag-catalog export --db-url "$COOKIMPORT_DATABASE_URL" --out data/tagging/tag_catalog.json`

   Expected result:
    - `data/tagging/tag_catalog.json` exists and contains categories, tags, and a `catalog_fingerprint`.

2) Add pipeline assets:
    - Create:
      - `llm_pipelines/pipelines/recipe.tags.v1.json`
      - `llm_pipelines/prompts/recipe.tags.v1.prompt.md`
      - `llm_pipelines/schemas/recipe.tags.v1.output.schema.json`

3) Run pack tests:
    - `pytest tests/llm -q`

   Expected result:
    - all tests pass (no codex-farm required).

4) Run tagging tests:
    - `pytest tests/tagging -q`

5) Manual CLI smoke test (requires codex-farm configured):
    - Stage a small input to get draft JSONs:
      - `cookimport stage data/input/<small_book>.epub`
    - Then run tag suggestions with LLM:
      - `cookimport tag-recipes suggest --draft-dir "data/output/<ts>/final drafts/<workbook_slug>/" --catalog-json data/tagging/tag_catalog.json --llm --explain`

   Expected result:
    - output includes deterministic suggestions plus additional LLM-sourced suggestions for previously empty categories, and the report records the pipeline id `recipe.tags.v1`.

6) Manual stage integration smoke test (if implemented):
    - `cookimport stage data/input/<small_book>.epub --llm-tags-pipeline codex-farm-tags-v1 --tag-catalog-json data/tagging/tag_catalog.json`

   Expected result:
    - Under `data/output/<ts>/tags/<workbook_slug>/` there is:
      - `tagging_report.json`
      - `r0.tags.json` (and so on)
    - Under `data/output/<ts>/raw/llm/<workbook_slug>/pass5_tags/` there is:
      - `in/` and `out/` JSONs
      - `pass5_tags_manifest.json`

## Validation and Acceptance

Behavior is accepted when all of the following are true:

- Deterministic default remains unchanged:
  - Running `cookimport stage <path>` with no tagging flags produces no new `tags/` output directory and makes no codex-farm calls.

- Codex-farm tagging via CLI works (when enabled):
  - `cookimport tag-recipes suggest ... --llm` produces a `tagging_report.json` that includes:
    - catalog fingerprint
    - counts for deterministic vs LLM suggestions
    - a reference to the effective pipeline id (`recipe.tags.v1`)
  - Suggested tags must all exist in the provided catalog JSON.
  - LLM suggestions must be limited to the candidate shortlists.

- Failure-mode semantics are correct:
  - With `codex_farm_failure_mode=fallback`, missing codex-farm should not crash; it should warn and continue deterministic-only.
  - With `codex_farm_failure_mode=fail`, missing codex-farm should fail with a clear, actionable error.

- Tests pass:
  - `pytest tests/tagging tests/llm -q` is green.

## Idempotence and Recovery

- Catalog export is safe to rerun; it overwrites the JSON snapshot at the chosen output path.
- Tag application to DB (existing behavior) must remain insert-only and safe to rerun (`ON CONFLICT DO NOTHING`).
- Tag suggestion outputs are safe to rerun because:
  - CLI writes to a user-specified output directory (or prints to console).
  - Stage writes to a new timestamped run folder each time.

Recovery guidance:
- If codex-farm outputs fail schema validation, capture one failing output JSON in `Surprises & Discoveries`, tighten the prompt and/or schema, and add a deterministic fake-runner test that reproduces the failure shape.

## Artifacts and Notes

Example output shape for a per-recipe tags artifact (illustrative; update to match the final implemented contract):

    {
      "recipe_id": "urn:recipeimport:excel:...:r0",
      "title": "Instant Pot Chicken Chili",
      "catalog_fingerprint": "<sha256>",
      "suggestions": [
        {
          "tag_key_norm": "instant-pot",
          "category_key_norm": "cooking-style",
          "confidence": 0.80,
          "evidence": "Title contains 'instant pot'",
          "source": "deterministic"
        },
        {
          "tag_key_norm": "mexican",
          "category_key_norm": "cuisine",
          "confidence": 0.62,
          "evidence": "Ingredients include chili powder, cumin; instructions reference tacos/tortillas",
          "source": "llm",
          "llm_pipeline_id": "recipe.tags.v1"
        }
      ],
      "new_tag_proposals": [
        {
          "proposed_category": "vibe",
          "display_name": "game day",
          "rationale": "Chili is commonly served for game day gatherings"
        }
      ]
    }

Keep evidence strings short and non-narrative. The goal is auditability, not an essay.

## Interfaces and Dependencies

New/updated user-facing interfaces (keep additive, backward-compatible):
- `cookimport tag-recipes suggest/apply --llm` should now run the codex-farm tagging pass when configured.
- (If stage integration is implemented) `cookimport stage` adds:
  - `--llm-tags-pipeline off|codex-farm-tags-v1`
  - `--codex-farm-pipeline-pass5-tags` (default `recipe.tags.v1`)
  - `--tag-catalog-json` (path to catalog snapshot)

New pipeline pack assets:
- `llm_pipelines/pipelines/recipe.tags.v1.json`
- `llm_pipelines/prompts/recipe.tags.v1.prompt.md`
- `llm_pipelines/schemas/recipe.tags.v1.output.schema.json`

Runtime dependencies:
- No new Python dependencies should be required.
- Codex-farm remains an external tool dependency only when the feature is enabled; default runs must not require it.

Key internal modules expected to be touched:
- Tagging:
  - `cookimport/tagging/llm_second_pass.py`
  - (new) `cookimport/tagging/codex_farm_tags_provider.py`
- LLM/codex-farm:
  - Possibly extend `cookimport/llm/codex_farm_contracts.py` with tag pass models, or add tagging-specific contracts in tagging module.
  - `cookimport/llm/fake_codex_farm_runner.py` for deterministic tests
- Stage (optional):
  - `cookimport/config/run_settings.py`
  - `cookimport/cli.py` and/or `cookimport/cli_worker.py`
  - Possibly `cookimport/staging/writer.py` if you centralize writing tag artifacts there

Documentation to update:
- `docs/10-llm/10-llm_README.md`
- (new) `docs/10-llm/tags_pass.md`
- `docs/09-tagging/09-tagging_README.md`
- Optionally annotate `docs/plans/I4.1-Auto-tag.md` with what changed