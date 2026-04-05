---
summary: "Onboarding file for web-based AI chatbots that can't see the code"
read_when:
  - AI Coding agents, DO NOT READ
  - This is for providing to web-based AI's who can not see the codebase. THEY ONLY GET THIS FILE AND NOTHING ELSE.
---

# AI Context: `cookimport` (code-verified on 2026-04-02)

This file is for web-based AI systems that cannot inspect the repository directly but still need enough real architectural context to discuss or design sensible changes.

This is intentionally more technical than a product summary. It is meant to answer questions like:

- what the actual runtime pipeline is right now
- where truth is decided
- which artifacts downstream tools trust
- which modules own which responsibilities
- where a proposed feature should attach if it is meant to fit the current codebase instead of an older design

If you only need a lightweight overview, this file is overkill. If you want to propose changes that line up with the current code rather than stale historical mental models, this is the right file.

This document is intended to stand alone. Assume the reader gets this file and nothing else.

When this document names files, modules, or artifact paths, that is to communicate ownership and runtime structure. It is not an instruction to go open those files.

## How to use this document

Treat this as the standalone architecture explainer for the repo state that matters most for high-level design. It is strongest on:

- current runtime shape
- authority boundaries
- artifact contracts
- command surfaces
- high-value invariants
- module ownership
- what old mental models to avoid

It is weaker on:

- individual function signatures
- low-level helper details
- every single run setting
- long historical rationale

When you design new features from this document, bias toward:

- reusing the existing stage/runtime/artifact seams
- preserving current authority boundaries
- adding new outputs or behavior in the owning subsystem rather than inventing cross-cutting side channels

## Executive reality check

The single most important fact about the current codebase is this:

`cookimport` is no longer primarily an importer-driven recipe extractor.

It is now a source-first pipeline that:

1. normalizes many source types into one canonical source model
2. runs one shared stage-owned semantic pipeline over that source model
3. writes recipe outputs, non-recipe outputs, benchmark evidence, Label Studio artifacts, and analytics artifacts from that shared staged result

That means:

- importers are source normalizers, not final truth owners
- stage artifacts are the current authority surface
- benchmark and Label Studio flows are supposed to reuse staged truth, not build parallel truth models
- when downstream tools disagree, staged artifacts and manifest/index files are the first things to trust

If you remember only one sentence, remember this one:

The repo has moved from importer-first truth to stage-owned truth.

## What the project is

`cookimport` is a local Python CLI for turning cookbook-like sources into structured recipe outputs plus evidence/debug artifacts.

The project currently includes:

- importer support for Excel, text/markdown/DOCX, PDF, EPUB, Paprika exports, RecipeSage exports, and schema-like web/html inputs
- a shared five-stage runtime that decides recipe boundaries, recipe semantics, and outside-recipe authority
- optional Codex-backed semantic review/correction surfaces
- freeform Label Studio task generation, export, and evaluation
- benchmark tooling, external review handoff packets, and deterministic follow-up tooling
- analytics/history/dashboard tooling built from stage and benchmark artifacts

User-facing output language is roughly:

- intermediate recipe outputs: `schema.org Recipe JSON`
- final recipe outputs: `cookbook3`

Internal model names may still say things like `RecipeDraftV1`, but that is implementation vocabulary, not the best product-facing language.

## Core design philosophy

The repo has a strong philosophy about deterministic code versus LLMs.

Deterministic code is supposed to own:

- source normalization
- IDs
- path conventions
- artifact writing
- shard planning
- validation
- promotion and rejection
- report generation
- benchmark scoring
- final output assembly

LLMs are supposed to own:

- fuzzy semantic judgment
- line-role correction when deterministic labels are uncertain
- recipe refinement/correction inside accepted recipe boundaries
- semantic `knowledge` versus `other` calls for outside-recipe material
- freeform Label Studio prelabel suggestions

The project explicitly does not want deterministic code to become a fake semantic judge. In repo terms:

- deterministic code packages evidence
- LLMs make fuzzy calls
- deterministic code validates outputs and preserves clean authority boundaries
- deterministic code should not silently overwrite or “correct” ambiguous LLM outputs just because the author of the code thinks the model is wrong

That philosophy is not abstract. It shows up in the current runtime shape, validation rules, and artifact model.

## The current top-level runtime

The current processing story is:

1. `cookimport stage` or a related flow chooses an input source
2. the importer registry picks the best importer for the path
3. the source may run as one job or many split jobs
4. split jobs are merged back into one whole-book canonical source model
5. one shared five-stage semantic runtime runs on that merged source model
6. deterministic writers emit recipe outputs, non-recipe outputs, benchmark evidence, summaries, manifests, and optional LLM/raw/debug artifacts

This runtime is owned primarily by:

- CLI and top-level orchestration:
  - `cookimport/cli.py`
  - `cookimport/cli_commands/stage.py`
  - `cookimport/cli_support/stage.py`
  - `cookimport/cli_worker.py`
- shared stage runtime:
  - `cookimport/staging/import_session.py`
  - `cookimport/staging/import_session_flows/output_stage.py`
  - `cookimport/staging/import_session_flows/authority.py`
  - `cookimport/staging/pipeline_runtime.py`
  - `cookimport/staging/writer.py`
- run indexing:
  - `cookimport/runs/manifest.py`
  - `cookimport/runs/stage_observability.py`

The five explicit stage-owned runtime steps are:

1. `extract`
2. `recipe-boundary`
3. `recipe-refine`
4. `nonrecipe-route`
5. `nonrecipe-finalize`

This five-stage model is the real runtime center of the product.

Older pass-slot or numbered-stage language may still exist in historical docs, fixtures, or compatibility readers, but it is not the right model for new work.

## Source conversion and importers

### Importer contract

Importers implement the shared importer protocol and are selected by score through the importer registry.

Key code:

- importer protocol:
  - `cookimport/plugins/base.py`
- registry:
  - `cookimport/plugins/registry.py`

Importer output converges on a `ConversionResult` with these authoritative fields:

- `source_blocks`
- `source_support`
- `raw_artifacts`
- `report`

Important current constraint:

For normal stage-backed flows, importers are not supposed to publish final recipe or non-recipe truth. In practice that means importer results are source-first and usually return:

- `recipes=[]`
- `chunks=[]`
- `non_recipe_blocks=[]`

That is deliberate. The shared stage session owns recipe and non-recipe authority later.

### Importer families

Active importer families currently include:

- Excel
- Text / Markdown / DOCX
- PDF
- EPUB
- Paprika
- RecipeSage
- Web Schema / schema-like HTML or JSON

Conceptually they split into three shapes:

- block-first: PDF, EPUB
- record-first: Excel, text-like importers
- structured-export-first: Paprika, RecipeSage, web/schema importers

The durable rule is:

Importer-specific extraction can differ a lot, but canonical handoff to the rest of the system is still source-first.

### EPUB and PDF specifics

EPUB and PDF are the most important split-job cases.

EPUB:

- active importer: `cookimport/plugins/epub.py`
- extractor helpers live under `cookimport/parsing/epub_*`, `unstructured_adapter.py`, `markitdown_adapter.py`, and related modules
- explicit extractor modes:
  - `unstructured`
  - `beautifulsoup`
  - `markdown`
  - `markitdown`
- `unstructured` is the default
- `markitdown` is whole-book only and cannot use spine-range splits

PDF:

- importer: `cookimport/plugins/pdf.py`
- supports page-range execution
- extracts text via PyMuPDF
- can OCR via docTR when policy allows

OCR support lives under `cookimport/ocr/`.

### Source support versus truth

`source_support` is intentionally non-authoritative.

That is an important architectural idea. Importers are allowed to propose hints such as candidate recipe ranges, but those hints are not current runtime truth. They are evidence for later stage review.

If you are designing a new importer feature, ask:

- is this publishing source facts?
- or is this trying to sneak semantic authority in through importer outputs?

Only the first one fits the current architecture.

## Split jobs and merge behavior

Large PDF and EPUB inputs can split for source conversion, but semantic authority is still decided once on the merged whole-book result.

This matters a lot because it means:

- split work is an implementation optimization for early source extraction
- later semantic stages still reason over the merged whole source, not isolated shards pretending to be books

Key modules:

- planning:
  - `cookimport/staging/job_planning.py`
- worker-side execution:
  - `cookimport/cli_worker.py`
- merge helpers and ID reassignment:
  - `cookimport/cli_support/stage.py`
  - `cookimport/staging/pdf_jobs.py`

Current split rules:

- PDF can split by page range
- EPUB can split by spine range
- `markitdown` EPUB stays whole-book only
- other sources generally stay single-job

Worker execution writes temporary raw artifacts under:

- `<run_root>/.job_parts/<workbook_slug>/job_<index>/raw/...`

Then main-process merge:

- sorts successful job payloads in source order
- offsets and concatenates `source_blocks`
- rebases and concatenates `source_support`
- rebuilds merged `full_text.json`
- moves raw artifacts into final `raw/...`
- deletes `.job_parts/...` on success

If any split job fails:

- merge is skipped for that source
- debugging artifacts are preserved
- `.job_parts` is intentionally left behind

That failure-preserving behavior is important for real debugging and should generally be preserved when redesigning split execution.

## The five-stage semantic runtime

This is the most important section for anyone proposing changes.

### Stage input/output mental model

At a high level, the five stages can be understood as a strict consume/produce chain:

- `extract`
  - consumes: merged importer `ConversionResult`
  - produces: one normalized internal book bundle with canonical block/line coordinates
- `recipe-boundary`
  - consumes: extracted book bundle
  - produces: authoritative labeled lines, authoritative block labels, accepted recipe spans, recipe-boundary diagnostics
- `recipe-refine`
  - consumes: accepted recipe spans plus the shared book bundle
  - produces: canonical recipe semantics and the explicit recipe block ownership contract
- `nonrecipe-route`
  - consumes: final recipe ownership plus authoritative block labels
  - produces: outside-recipe candidate queue and obvious-junk exclusions
- `nonrecipe-finalize`
  - consumes: nonrecipe candidates
  - produces: final outside-recipe `knowledge` vs `other` authority plus optional knowledge groups

That chain is important because it tells you where a new feature can legally and conceptually attach.

Examples:

- if a feature changes which text is considered recipe-owned, it belongs before or inside `recipe-boundary` or in the ownership-divestment seam of `recipe-refine`
- if a feature changes how outside-recipe prose is semantically categorized, it belongs in `nonrecipe-finalize`, not `nonrecipe-route`
- if a feature changes only how final outputs are written, it belongs after stage authority, not inside importer logic

### Stage 1: `extract`

This is where importer output becomes one shared internal book shape.

Runtime object:

- `ExtractedBookBundle` in `cookimport/staging/pipeline_runtime.py`

Purpose:

- normalize the source model into one common internal coordinate system
- establish one canonical ordered block view
- establish one atomic line view for line-role reasoning
- carry forward source support as support, not truth

If a new feature depends on recipe, non-recipe, Label Studio, or benchmark reasoning, it should generally consume data after this stage rather than reaching back into importer-specific structures.

### Stage 2: `recipe-boundary`

This is where recipe ownership becomes authoritative.

This stage is label-first.

It starts by building authoritative labels through the parser-owned and stage-owned boundary system:

- `cookimport/parsing/label_source_of_truth.py`
- `cookimport/parsing/recipe_span_grouping.py`
- `cookimport/staging/import_session_flows/authority.py`

Artifacts written here include:

- `label_deterministic/<workbook_slug>/labeled_lines.jsonl`
- `label_deterministic/<workbook_slug>/block_labels.json`
- `label_refine/<workbook_slug>/...` when line-role Codex refinement is enabled
- `recipe_boundary/<workbook_slug>/recipe_spans.json`
- `recipe_boundary/<workbook_slug>/span_decisions.json`
- `recipe_boundary/<workbook_slug>/authoritative_block_labels.json`

Important facts:

- recipes do not become runtime truth inside importers
- grouped recipe spans and authoritative block labels are the current recipe/non-recipe authority boundary
- accepted spans need both a title-like anchor and recipe-body proof
- titleless structured runs may still appear in diagnostics as rejected pseudo-recipes, but they do not become accepted recipes
- title-only shells and title-plus-note junk are rejected
- if the stage yields zero recipes, that zero is the answer until span artifacts prove otherwise

This is also where the repo’s current anti-false-positive posture really shows up. Cookbook sources contain lots of recipe-shaped junk:

- contents pages
- sidebars
- shopping lists
- chapter taxonomy
- memoir/explanatory prose with headings

The current runtime intentionally makes recipe acceptance stricter here instead of letting later stages quietly rescue weak candidates.

### Stage 3: `recipe-refine`

This stage turns accepted recipe spans into actual recipe objects and canonical recipe semantics.

Important modules:

- `cookimport/staging/draft_v1.py`
- `cookimport/staging/jsonld.py`
- `cookimport/staging/recipe_ownership.py`
- recipe Codex facade:
  - `cookimport/llm/codex_farm_orchestrator.py`
- recipe stage owners:
  - `cookimport/llm/recipe_stage/planning.py`
  - `cookimport/llm/recipe_stage/runtime.py`
  - `cookimport/llm/recipe_stage/validation.py`
  - `cookimport/llm/recipe_stage/promotion.py`
  - `cookimport/llm/recipe_stage/reporting.py`

This stage owns:

- title normalization
- ingredient parsing
- instruction parsing
- yield/time extraction
- temperature extraction
- ingredient-to-step linking
- tag handling
- canonical semantic payload generation

Current semantic stage observability names for recipe work are:

- `recipe_build_intermediate`
- `recipe_refine`
- `recipe_build_final`

The single most important recipe artifact is:

- `recipe_authority/<workbook_slug>/authoritative_recipe_payloads.json`

That is the canonical semantic handoff from recipe refinement into later staging/writing.

A second critical artifact is:

- `recipe_authority/<workbook_slug>/recipe_block_ownership.json`

This is the canonical block ownership contract.

Important invariant:

`recipe-refine` may improve recipe content, but it may only shrink recipe ownership through explicit divestment recorded on the ownership contract.

That means downstream runtime logic should not re-derive recipe ownership from raw provenance, recipe text ranges, or old importer hints. The ownership artifact is the intended authority surface.

### Stage 4: `nonrecipe-route`

This stage handles everything outside recipe ownership after recipe refinement has settled the ownership contract.

Important modules:

- `cookimport/staging/nonrecipe_seed.py`
- `cookimport/staging/nonrecipe_routing.py`
- `cookimport/staging/nonrecipe_stage.py`

This stage:

- consumes authoritative block labels plus the final recipe block ownership contract
- excludes obvious junk immediately
- keeps worthwhile survivors in one category-neutral candidate queue for later review
- records why rows survived or were excluded

Critical current rule:

Only blocks that are unowned by recipe, or explicitly divested from recipe ownership, may enter the non-recipe route.

That is a real authority boundary, not a suggestion.

Key artifacts:

- `08_nonrecipe_route.json`
- `08_nonrecipe_exclusions.jsonl`

`08_nonrecipe_route.json` is not the final semantic knowledge truth file. It is the route/candidate/exclusion ledger.

### Stage 5: `nonrecipe-finalize`

This is the final semantic owner of reviewable outside-recipe material.

Important modules:

- `cookimport/staging/nonrecipe_authority_contract.py`
- `cookimport/staging/nonrecipe_authority.py`
- `cookimport/staging/nonrecipe_finalize_status.py`
- knowledge/LLM owners:
  - `cookimport/llm/codex_farm_knowledge_orchestrator.py`
  - `cookimport/llm/knowledge_stage/planning.py`
  - `cookimport/llm/knowledge_stage/runtime.py`
  - `cookimport/llm/knowledge_stage/recovery.py`
  - `cookimport/llm/knowledge_stage/promotion.py`
  - `cookimport/llm/knowledge_stage/reporting.py`
  - `cookimport/llm/codex_farm_knowledge_jobs.py`

This stage decides:

- whether outside-recipe candidates are final `knowledge` or final `other`
- how kept `knowledge` rows are grouped into related idea groups

Important artifacts:

- `09_nonrecipe_authority.json`
- `09_nonrecipe_knowledge_groups.json`
- `09_nonrecipe_finalize_status.json`

These are not interchangeable.

Their roles are:

- `09_nonrecipe_authority.json`: final machine-readable truth for outside-recipe `knowledge` versus `other`
- `09_nonrecipe_knowledge_groups.json`: promoted related-idea grouping output
- `09_nonrecipe_finalize_status.json`: finalized and unresolved candidate status information

Reviewer-facing prose output may also appear under:

- `knowledge/<workbook_slug>/knowledge.md`
- `knowledge/knowledge_index.json`

But the final machine-readable semantic truth is `09_nonrecipe_authority.json`, not `knowledge.md`.

## Artifact glossary

This section exists because many design mistakes come from confusing nearby artifacts that sound similar but mean different things.

### `source_blocks`

Canonical ordered source units emitted by importers and later merged into a shared whole-book source model.

What they are for:

- preserving source order
- carrying importer-normalized source text
- anchoring later block-level reasoning

What they are not:

- final recipe truth
- final non-recipe truth

### `source_support`

Non-authoritative support data emitted by importers.

What it is for:

- carrying helpful hints and evidence
- preserving source-local structure that later stages may consult

What it is not:

- a truth override surface

### `label_deterministic/...`

Deterministic first-pass authoritative labeling artifacts.

What they are for:

- reproducible baseline labels
- evidence trail for line/block labeling
- a stable handoff into optional line-role Codex correction

### `label_refine/...`

Final authoritative label artifacts after line-role Codex review, when that review is enabled.

What they are for:

- replacing the deterministic label set with the accepted corrected label set
- preserving diffs and corrected route truth

### `recipe_boundary/<workbook_slug>/recipe_spans.json`

Accepted recipe spans only.

What it is for:

- telling later stages which spans were accepted as real recipes

What it is not:

- a mixed accepted/rejected diagnostic dump

### `recipe_boundary/<workbook_slug>/span_decisions.json`

Compact reviewer/debug rollup for both accepted and rejected span candidates.

What it is for:

- explaining why pseudo-recipes were rejected
- explaining why accepted spans survived

### `recipe_authority/<workbook_slug>/authoritative_recipe_payloads.json`

Canonical recipe semantics handoff.

What it is for:

- acting as the recipe meaning contract after `recipe-refine`
- feeding intermediate/final recipe output writing

### `recipe_authority/<workbook_slug>/recipe_block_ownership.json`

Canonical recipe block ownership contract.

What it is for:

- telling downstream systems which blocks recipe still owns
- telling nonrecipe routing which blocks are even eligible to become outside-recipe candidates

What it is not:

- something downstream code should try to “reconstruct” from prose or provenance

### `08_nonrecipe_route.json`

Deterministic route/candidate ledger for outside-recipe material.

What it is for:

- showing what survived to semantic review
- showing what was excluded immediately

What it is not:

- final `knowledge` authority

### `08_nonrecipe_exclusions.jsonl`

Row-level explanation ledger for upstream obvious-junk vetoes.

What it is for:

- explaining where candidate rows disappeared before semantic review
- debugging route pressure and over-exclusion

### `09_nonrecipe_authority.json`

Final machine-readable authority for outside-recipe `knowledge` versus `other`.

What it is for:

- semantic truth for outside-recipe material
- benchmark and downstream structured reuse

### `09_nonrecipe_knowledge_groups.json`

Promoted grouping output for kept knowledge rows.

What it is for:

- related-idea grouping
- reviewer/debug understanding

What it is not:

- the category-authority file

### `09_nonrecipe_finalize_status.json`

Status file for finalized and unresolved nonrecipe candidates.

What it is for:

- preserving incompleteness or unresolved work without polluting the authority file

### `stage_observability.json`

Run-level semantic stage index.

What it is for:

- telling other systems which stages existed and what the current semantic stage model is
- preventing downstream tools from reconstructing stage truth from old folder assumptions

### `run_manifest.json`

Run-level artifact index and source identity surface.

What it is for:

- source identity
- artifact pointer discovery
- downstream manifest-based resolution

### `.bench/<workbook_slug>/stage_block_predictions.json`

Primary scored prediction artifact for stage-backed benchmark evidence.

What it is for:

- downstream benchmark scoring
- authoritative block-level label evidence

## Common wrong assumptions

This section exists because a web AI that lacks code access is especially vulnerable to making plausible but incorrect assumptions.

### Wrong assumption 1: “Importers probably still emit recipes and later stages just clean them up.”

That is not the current architecture.

In normal stage-backed flows, importers are source normalizers. Recipe truth starts in the label-first authority flow, not in importer output.

### Wrong assumption 2: “If a run has zero recipes, the importer probably missed them and later stages can recover from importer hints.”

That is not the intended current debugging model.

If a run yields zero accepted recipes, the primary debugging surface is the boundary artifacts, especially:

- `recipe_spans.json`
- `span_decisions.json`

The repo no longer treats importer recipe candidates as the authoritative fallback answer.

### Wrong assumption 3: “`nonrecipe-route` is just the first half of a classifier, so routing artifacts are basically final semantics.”

No.

`nonrecipe-route` packages candidates and exclusions.

`nonrecipe-finalize` is the final semantic owner for outside-recipe `knowledge` versus `other`.

### Wrong assumption 4: “Reviewer markdown probably reflects the true state.”

Maybe, but that is not the contract.

Markdown summaries are human-oriented convenience surfaces. Machine-readable truth lives in the explicit authority and manifest artifacts.

### Wrong assumption 5: “Benchmark code can safely infer the real answer from old path conventions if a manifest is missing or weird.”

That is the wrong direction for new design.

The modern architecture wants explicit pointers and semantic-stage-first contracts, not guessing from old layouts.

### Wrong assumption 6: “The LLM is still just an advisory overlay on top of deterministic labels.”

Not on the main accepted runtime path.

For accepted line-role and knowledge outputs, structurally valid worker outputs are current first-authority after validation. Repo code validates ownership, completeness, and structure, but it is not supposed to silently semantic-veto them back to baseline.

### Wrong assumption 7: “Knowledge means any cooking-adjacent sentence outside recipes.”

That is too broad.

Current knowledge logic is aiming at portable, reusable cooking knowledge worth later retrieval, not just any true or relevant sentence.

## Design cookbook

This section is intended to help a web AI translate a product idea into the correct architectural landing zone.

### New importer feature

Good examples:

- preserve richer source coordinates
- preserve better table structure
- emit new source-support hints
- improve EPUB or PDF extraction quality

Typical landing zones:

- importer file under `cookimport/plugins/`
- importer-specific parsing helper
- split-job planning or merge support if the feature changes range execution

What to preserve:

- source-first handoff
- no importer-owned semantic truth

### Better recipe boundary detection

Good examples:

- improve title recall
- reduce pseudo-recipe acceptance
- better handle cookbook sidebars or chapter furniture
- better bridge one stray misclassified block inside a real recipe

Typical landing zones:

- deterministic line/block labeling logic
- recipe span grouping logic
- label-first authority stage flow

What to preserve:

- recipe acceptance still needs title anchor plus body proof
- accepted boundary artifacts stay the authority surface

### Better recipe semantics inside accepted recipes

Good examples:

- improve ingredient parsing edge cases
- improve instruction metadata extraction
- improve yield or time extraction
- improve tag selection and normalization
- improve Codex recipe correction contract

Typical landing zones:

- parsing helpers
- recipe semantic shaping
- recipe Codex planning/validation/promotion

What to preserve:

- recipe semantics should project through canonical recipe authority payloads
- recipe block ownership changes must remain explicit divestment, not accidental side effects

### Better nonrecipe logic

First decide which of these you actually mean:

- route/exclusion improvement
- semantic `knowledge` vs `other` improvement
- better grouping of kept knowledge rows

If it is route/exclusion:

- it belongs near `nonrecipe-route`

If it is final semantic categorization:

- it belongs near `nonrecipe-finalize`

If it is grouping:

- it belongs in the knowledge grouping part of finalize, not route

### Better benchmarking or external review

Good examples:

- new benchmark view
- new compare report
- new upload bundle slice
- better follow-up export
- new diagnostics around unresolved candidates or route/finalize mismatch

Typical landing zones:

- benchmark scoring or artifact rendering
- follow-up/export tooling
- manifest enrichment
- stage prediction artifact builders when the benchmark issue is really upstream evidence quality

What to preserve:

- benchmark logic should consume authoritative prediction artifacts and explicit pointers
- do not build parallel semantic inference in benchmark-only code

### Better Label Studio workflow

Good examples:

- better segment shaping
- better context windows
- better prelabel reliability
- better export normalization

Typical landing zones:

- freeform task generation
- prelabel
- export/eval normalization

What to preserve:

- freeform scope
- offset integrity
- shared truth model with stage-backed artifacts

### Better analytics/dashboard

Good examples:

- new compare/control dimension
- new dashboard metric
- better token usage accounting
- better history summarization

Typical landing zones:

- analytics collectors and schema
- compare/control backend
- benchmark/stage manifest enrichment

What to preserve:

- history CSV and manifest-backed enrichment remain the stable data story

## Failure and debugging model

This section is useful because good feature design often starts by understanding how the current system expects failures to be localized.

### Symptom: zero recipes in a run

Primary likely seam:

- `recipe-boundary`

Best current interpretation:

- either the line/block labeling failed to create a viable recipe scaffold
- or span grouping rejected all candidate spans as pseudo-recipes or bodyless title shells

What that usually does not mean anymore:

- “trust importer recipes instead”

### Symptom: a block looks like recipe in one artifact but outside-recipe in another

Primary likely seam:

- recipe ownership contract drift, or misuse of non-authoritative artifacts

The intended answer is:

- recipe ownership comes from `recipe_block_ownership.json`
- downstream systems should not guess from separate provenance or recipe text spans

### Symptom: knowledge markdown looks right but benchmark says otherwise

Primary likely seam:

- confusion between reviewer-facing prose and machine-readable authority

The intended truth surface is:

- `09_nonrecipe_authority.json`

not the markdown summary.

### Symptom: benchmark output disagrees with staged truth

Primary likely seam:

- benchmark pointer resolution or projection logic

The intended answer is not:

- infer alternate files from path folklore

The intended answer is:

- follow the authoritative prediction artifact and manifest/index story

### Symptom: line-role behavior seems inconsistent with deterministic baseline

Primary likely seam:

- misunderstanding of the live accepted LLM contract

Accepted worker labels are not supposed to be silently collapsed back to deterministic baseline just because baseline looked cleaner.

### Symptom: nonrecipe candidates vanish before semantic review

Primary likely seam:

- route/exclusion logic

The explanatory artifact is:

- `08_nonrecipe_exclusions.jsonl`

not the final authority file.

## Pressure points and likely improvement zones

This section is not a bug list. It is a map of areas where a web AI could plausibly suggest meaningful improvements.

### 1. Boundary quality is high leverage

Many downstream outcomes get much better or worse depending on whether `recipe-boundary` correctly distinguishes:

- real recipes
- pseudo-recipes
- outside-recipe knowledge
- obvious junk

This is high leverage because mistakes here cascade into recipe refinement, nonrecipe routing, benchmark scoring, and Label Studio projections.

### 2. Large coordinator seams still exist

The repo has improved ownership splits, but some understanding still bottlenecks through larger composition roots and cross-package coordination seams.

That means proposals that improve boundary clarity, smaller owner modules, or cleaner contract surfaces can still be valuable if they preserve current semantics.

### 3. Read-side compatibility remains a tax

Some tooling still has to tolerate historical outputs or narrow compatibility paths.

That means new work should usually move toward:

- semantic-stage-first outputs
- manifest/index pointers
- explicit authority artifacts

not toward adding more fallback guessing.

### 4. Knowledge remains intrinsically hard

Outside-recipe `knowledge` versus `other` is semantically harder than many recipe-local decisions.

That means improvements around:

- candidate shaping
- ontology grounding
- grouping quality
- clearer unresolved-state handling

are all likely high-value areas.

### 5. Benchmark and review tooling is part of the product

This repo is not just a recipe extractor. It also invests heavily in:

- benchmark comparisons
- external review handoffs
- deterministic follow-up
- dashboard and compare/control analysis

That means improvements to observability, failure explanation, and artifact clarity are often first-class product improvements, not merely dev tooling.

## The current authority boundaries

If you are designing features, these boundaries are the ones you must not accidentally blur.

### Boundary 1: importer truth versus stage truth

Importers normalize source material and preserve evidence.

They do not own:

- final recipe boundaries
- final recipe semantics
- final outside-recipe `knowledge` vs `other`

### Boundary 2: recipe ownership versus recipe semantics

`recipe-boundary` owns recipe acceptance and recipe block ownership.

`recipe-refine` owns recipe semantics inside accepted boundaries.

That distinction matters because recipe Codex is not supposed to invent entirely new recipe ownership by editing semantics. Ownership changes must be explicit divestment through the ownership contract.

### Boundary 3: route versus final non-recipe meaning

`nonrecipe-route` owns candidate queueing and obvious-junk exclusion.

`nonrecipe-finalize` owns final semantic `knowledge` versus `other`.

Do not design systems that treat routed candidates as if they were already final knowledge.

### Boundary 4: stage truth versus benchmark projection

Benchmarks score from authoritative prediction artifacts.

They are not supposed to rerun semantic inference in a parallel universe.

### Boundary 5: reviewer-facing summaries versus machine-readable truth

Human-friendly files exist, but the authoritative machine-readable seams are the contract surfaces named above.

When in doubt, trust:

- `run_manifest.json`
- `stage_observability.json`
- recipe/nonrecipe authority artifacts
- benchmark pointer metadata

before trusting markdown summaries or older convenience files.

## LLM integration: current live facts

LLM use is optional. Deterministic/off is still the baseline and the safe fallback posture.

Current live Codex-backed surfaces:

- recipe correction:
  - `codex-recipe-shard-v1`
- line-role review:
  - `codex-line-role-route-v2`
- non-recipe knowledge finalize:
  - `codex-knowledge-candidate-v2`
- Label Studio freeform prelabel:
  - `prelabel.freeform.v1`

### Transport styles

Recipe correction currently stays on the taskfile worker contract.

Line-role and non-recipe finalize can use:

- `taskfile-v1`
- `inline-json-v1`

Those transport details matter, but they do not change the authority boundary:

- deterministic code still plans shards
- deterministic code still validates shape/coverage/ownership
- deterministic code still promotes accepted results into final artifacts

### Worker architecture

The direct `codex exec` path is heavily controlled.

Important current facts:

- worker sessions run in sterile mirrored workspaces
- taskfile workers see repo-written `task.json` plus `AGENTS.md`
- repo-owned artifacts such as manifests, debug copies, outputs, telemetry, and status files live outside the worker-visible contract
- Linux taskfile workers run inside a filesystem-fenced environment to prevent wandering through unrelated repo or home directories
- validated `workers/*/out/*.json` files are authoritative for taskfile stages
- prose-only final agent messages are telemetry, not truth

Shared worker/runtime foundations:

- `cookimport/llm/phase_worker_runtime.py`
- `cookimport/llm/codex_exec_runner.py`
- `cookimport/llm/editable_task_file.py`

### Recipe LLM contract

Recipe Codex no longer sprays overrides into multiple downstream seams.

The current contract is:

1. deterministic code builds intermediate recipe candidates
2. recipe Codex refines accepted recipe tasks
3. deterministic validation and promotion produce one canonical semantic payload per recipe
4. writers project outputs from that canonical payload

Promotion lands in:

- `recipe_authority/<workbook_slug>/authoritative_recipe_payloads.json`

Current recipe task outcomes can explicitly represent things like:

- repaired/promoted
- fragmentary
- not a recipe
- locally skipped without an LLM round-trip when scaffold logic already knows the semantic outcome

Those non-promoted states remain visible in manifests/audits. They are not supposed to disappear into silent fallback.

### Line-role LLM contract

Canonical line-role is now one LLM labeling pass followed by deterministic grouping, not a complicated multi-pass recipe-region architecture.

Important parsing/line-role modules:

- `cookimport/parsing/canonical_line_roles/contracts.py`
- `cookimport/parsing/canonical_line_roles/planning.py`
- `cookimport/parsing/canonical_line_roles/runtime.py`
- `cookimport/parsing/canonical_line_roles/validation.py`
- `cookimport/parsing/canonical_line_roles/artifacts.py`
- `cookimport/parsing/canonical_line_roles/policy.py`

Important facts:

- line-role workers operate on stable atomic line ids
- taskfile workers edit only answer fields in `task.json`
- raw row text is the main evidence surface
- accepted worker labels are first-authority on the live route path after structural validation
- repo code no longer silently substitutes deterministic baseline labels on the happy path just because it dislikes a valid worker answer

This is one of the biggest conceptual differences from older “LLM as advisory overlay” designs.

### Knowledge LLM contract

Knowledge classification is now ontology-grounded and outcome-first.

Roughly:

- deterministic code plans candidate shards from outside-recipe rows
- the model decides block-by-block `knowledge` vs `other`
- kept `knowledge` rows can then be grouped
- deterministic code validates ownership, coverage, ordering, grounding shape, and allowed enum/category/tag structure
- deterministic code promotes accepted results into stage-owned final artifacts

Important current idea:

`knowledge` is meant to mean portable, reusable cooking knowledge worth storing and later retrieving, not merely “some cooking-adjacent sentence.”

That ontology-grounded posture matters for new feature design.

## Parsing and deterministic semantic support

The parsing package is broad. It does far more than ingredient parsing.

Important areas:

- ingredients:
  - `cookimport/parsing/ingredients.py`
- instructions:
  - `cookimport/parsing/instruction_parser.py`
- yield extraction:
  - `cookimport/parsing/yield_extraction.py`
- step segmentation:
  - `cookimport/parsing/step_segmentation.py`
- ingredient-to-step linking:
  - `cookimport/parsing/step_ingredients.py`
- section detection:
  - `cookimport/parsing/section_detector.py`
- multi-recipe splitting:
  - `cookimport/parsing/multi_recipe_splitter.py`
- chunks/highlights:
  - `cookimport/parsing/chunks.py`
  - `cookimport/parsing/tips.py`
- table extraction:
  - `cookimport/parsing/tables.py`
- label-first logic:
  - `cookimport/parsing/label_source_of_truth.py`
  - `cookimport/parsing/recipe_span_grouping.py`
- canonical line-role:
  - `cookimport/parsing/canonical_line_roles/`

Important parsing facts that affect system design:

- ingredient parsing has multiple backends and deterministic repair/normalization logic
- instruction parsing extracts time and temperature metadata
- deterministic section and step segmentation feed staging outputs
- parser-owned chunking/highlight logic exists, but it is not the final semantic owner of knowledge
- parser-owned line-role heuristics and grouping are intentionally conservative in areas prone to cookbook false positives

One recurring principle:

Deterministic parsing can support later semantic decisions, but it should not quietly become the semantic authority for ambiguous cookbook prose.

## Output, artifacts, and path conventions

### Timestamp format

The repo-wide timestamp format is critical:

- `YYYY-MM-DD_HH.MM.SS`

Current implementation uses:

- `strftime("%Y-%m-%d_%H.%M.%S")`

This convention is used by stage runs, prediction/import runs, and benchmark outputs.

### Primary roots

Important roots:

- inputs:
  - `data/input/`
- stage outputs:
  - `data/output/<timestamp>/`
- Label Studio and benchmark artifacts:
  - `data/golden/...`
- analytics history/dashboard:
  - `.history/`

### Important stage artifacts

Key run-level files:

- `run_manifest.json`
- `stage_observability.json`
- `run_summary.json`
- `run_summary.md` when markdown writing is enabled
- `processing_timeseries.jsonl`

Key recipe and non-recipe authority files:

- `recipe_authority/<workbook_slug>/authoritative_recipe_payloads.json`
- `recipe_authority/<workbook_slug>/recipe_block_ownership.json`
- `08_nonrecipe_route.json`
- `08_nonrecipe_exclusions.jsonl`
- `09_nonrecipe_authority.json`
- `09_nonrecipe_knowledge_groups.json`
- `09_nonrecipe_finalize_status.json`

Key stage-debugging/authority files:

- `label_deterministic/<workbook_slug>/...`
- `label_refine/<workbook_slug>/...`
- `recipe_boundary/<workbook_slug>/recipe_spans.json`
- `recipe_boundary/<workbook_slug>/span_decisions.json`

Key user-facing recipe output files:

- `intermediate drafts/<workbook_slug>/r{index}.jsonld`
- `final drafts/<workbook_slug>/r{index}.json`
- `sections/<workbook_slug>/...`
- `tables/<workbook_slug>/...`
- `chunks/<workbook_slug>/...` when present

Key raw/debug/LLM files:

- `raw/source/<workbook_slug>/source_blocks.jsonl`
- `raw/source/<workbook_slug>/source_support.json`
- `raw/<importer>/<source_hash>/...`
- `raw/llm/<workbook_slug>/recipe_manifest.json`
- `raw/llm/<workbook_slug>/recipe_phase_runtime/...`
- `raw/llm/<workbook_slug>/nonrecipe_finalize/...`
- `raw/llm/<workbook_slug>/knowledge_manifest.json`

### IDs and provenance

Stage recipe IDs use the `urn:recipeimport:*` namespace.

Label Studio freeform task IDs use deterministic segment URNs like:

- `urn:cookimport:segment:{source_hash}:{start_block_index}:{end_block_index}`

The system is careful about stable-ish provenance and IDs because benchmark comparison, Label Studio reuse, and split-job merge correctness depend on them.

## Stage-block predictions and benchmark scoring

The primary scored prediction artifact is:

- `.bench/<workbook_slug>/stage_block_predictions.json`

This is not just a convenience file. It is the main benchmark evidence seam downstream tools are expected to trust.

Owned builders:

- recipe-local evidence:
  - `cookimport/staging/recipe_block_evidence.py`
- non-recipe knowledge evidence:
  - `cookimport/staging/knowledge_block_evidence.py`
- conflict/priority resolution:
  - `cookimport/staging/block_label_resolution.py`
- final assembly:
  - `cookimport/staging/stage_block_predictions.py`

Important scoring modes:

- `stage-blocks`
- `canonical-text`

Benchmarking has three active surfaces:

- `cookimport bench ...`
- `cookimport labelstudio-benchmark`
- `cf-debug ...`

### `cookimport bench`

This is the offline benchmark and artifact-retention suite.

Important active commands include:

- `bench speed-discover`
- `bench speed-run`
- `bench speed-compare`
- `bench quality-discover`
- `bench quality-run`
- `bench quality-leaderboard`
- `bench quality-compare`
- `bench eval-stage`
- `bench gc`
- `bench oracle-upload`
- `bench oracle-followup`

Important constraints:

- `bench quality-run` is deterministic-only
- live Codex speed benchmarking requires explicit confirmation and is blocked in agent-run shells
- crash-safe resume exists for quality and speed runs

### `labelstudio-benchmark`

This is the active single-run benchmark primitive. It can:

- generate predictions
- evaluate against freeform gold
- upload tasks when allowed
- compare baseline/candidate runs
- run offline with `--no-upload`

Important current rule:

Prediction generation and evaluation are supposed to reuse authoritative staged artifacts and manifest pointer pairs, not infer files from ad hoc path guesses.

### `cf-debug`

This is the deterministic follow-up CLI for `upload_bundle_v1`.

It is designed for:

- building request templates
- selecting/exporting cases
- auditing line-role joins and prompt links
- auditing knowledge evidence
- generating additive `followup_dataN/` packets

This matters for feature design because reviewer follow-up is now a first-class supported workflow, not a one-off manual debugging habit.

## Label Studio model

Label Studio is freeform-only now. The active scope is:

- `freeform-spans`

Important commands:

- `labelstudio-import`
- `labelstudio-export`
- `labelstudio-eval`
- `labelstudio-benchmark`

Key owners:

- `cookimport/labelstudio/ingest_flows/prediction_run.py`
- `cookimport/labelstudio/ingest_flows/upload.py`
- `cookimport/labelstudio/ingest_support.py`
- `cookimport/labelstudio/export.py`
- `cookimport/labelstudio/eval_freeform.py`
- `cookimport/labelstudio/freeform_tasks.py`
- `cookimport/labelstudio/canonical_line_projection.py`
- `cookimport/labelstudio/prelabel.py`

### Task contract

Freeform tasks are segment-based.

Important payload ideas:

- `segment_text` is the labelable focus window
- `source_map.blocks[*]` preserves authoritative block offsets
- `context_before_blocks` and `context_after_blocks` are prompt-only context, not label targets

Resume/idempotence is based on deterministic segment IDs, not Label Studio’s internal task IDs.

### Prelabel

Prelabel is its own Codex surface. It is not merely a side effect of recipe or benchmark settings.

Current facts:

- prelabel can operate in `block` or `span` granularity
- it uses pipeline `prelabel.freeform.v1`
- it requires explicit Label Studio write approval plus Codex approval
- it writes its own reports and prompt log artifacts

### Export and eval

Export writes canonical text and span artifacts that benchmarks then consume.

Key outputs include:

- `freeform_span_labels.jsonl`
- `freeform_segment_manifest.jsonl`
- `canonical_text.txt`
- `canonical_block_map.jsonl`
- `canonical_span_labels.jsonl`
- `canonical_manifest.json`

This matters because Label Studio export is not just “annotation output.” It is part of the benchmark gold data pipeline.

## Analytics and dashboard

Analytics is a real subsystem, not an afterthought.

Primary modules:

- `cookimport/analytics/perf_report.py`
- `cookimport/analytics/dashboard_collect.py`
- `cookimport/analytics/dashboard_render.py`
- `cookimport/analytics/dashboard_renderers/`
- `cookimport/analytics/benchmark_manifest_runtime.py`
- `cookimport/analytics/compare_control_engine.py`
- `cookimport/analytics/compare_control_fields.py`
- `cookimport/analytics/compare_control_filters.py`
- `cookimport/analytics/compare_control_analysis.py`

Current analytics includes:

- per-file conversion reports
- cross-run history CSV
- static dashboard site
- compare/control backend utilities

Important artifacts:

- per-file report:
  - `<run_dir>/<file_slug>.excel_import_report.json`
- history CSV:
  - `.history/performance_history.csv`
- dashboard:
  - `.history/dashboard/index.html`
  - `.history/dashboard/assets/dashboard_data.json`
  - `.history/dashboard/assets/dashboard_ui_state.json`

Important behavior:

- stage and benchmark flows append history rows
- dashboard refresh is a best-effort follow-on behavior
- benchmark rows now preserve real metric and token usage surfaces used by dashboard/compare-control workflows

If you design new metrics or new benchmark artifacts, analytics is part of the product surface that needs to stay coherent.

## CLI surface and entrypoints

Primary entrypoints:

- `cookimport = cookimport.cli:app`
- `cf-debug = cookimport.cf_debug_cli:app`
- `C3imp = cookimport.c3imp_entrypoint:main`

Running `cookimport` with no subcommand enters interactive mode.

Current `cookimport --help` commands are:

- `stage`
- `inspect`
- `labelstudio-import`
- `labelstudio-export`
- `labelstudio-eval`
- `debug-epub-extract`
- `labelstudio-benchmark`
- `perf-report`
- `stats-dashboard`
- `benchmark-csv-backfill`
- `bench`
- `compare-control`
- `epub`

Important code ownership split:

- `cookimport/cli.py` is the Typer composition root
- command-family ownership lives under `cookimport/cli_commands/`
- shared command helpers live under `cookimport/cli_support/`
- interactive UI flows live under `cookimport/cli_ui/`

This means new command work should usually attach in the relevant command owner module, not by piling more business logic into `cookimport/cli.py`.

## Package map

At a high level, the current repository is organized like this:

```text
cookimport/
├── cli.py                     # Typer composition root
├── cf_debug_cli.py            # Follow-up/debug CLI for upload bundles
├── c3imp_entrypoint.py        # Interactive wrapper entrypoint
├── cli_commands/              # Command owners
├── cli_support/               # Shared CLI/runtime helpers
├── cli_ui/                    # Interactive run-settings/menu flows
├── config/                    # Run settings and runtime config decisions
├── core/                      # Shared models, source model, reporting, timing, scoring
├── plugins/                   # Importers and registry
├── parsing/                   # Label-first logic, parsing, chunking, EPUB support
├── staging/                   # Shared stage runtime, authority contracts, writers
├── runs/                      # Run manifests and stage observability
├── llm/                       # Codex orchestration, prompt artifacts, worker runtime
├── labelstudio/               # Freeform task import/export/eval/prelabel
├── bench/                     # Benchmarking, upload bundles, follow-up helpers
├── analytics/                 # Perf reports, dashboard, compare/control
├── tagging/                   # Recipe tagging contract surfaces
├── epubdebug/                 # EPUB diagnostics
└── ocr/                       # OCR backends
```

A second useful mental map is ownership-by-subsystem:

- ingestion/importers:
  - `plugins/`
  - `staging/job_planning.py`
  - `cli_worker.py`
- stage runtime and outputs:
  - `staging/`
  - `runs/`
- parsing and label-first behavior:
  - `parsing/`
- LLM integration:
  - `llm/`
- human annotation + gold data:
  - `labelstudio/`
- scoring/review/follow-up:
  - `bench/`
- analytics/history/dashboard:
  - `analytics/`

## Invariants and anti-patterns for new design work

If you are a web AI proposing a new feature, these are the most important things not to get wrong.

### Do not put final recipe truth back into importers

Importer hints are fine.

Importer-owned final recipe truth is not aligned with current architecture.

### Do not create a second recipe ownership system

Use:

- `recipe_boundary/...`
- `recipe_authority/.../recipe_block_ownership.json`

Do not re-derive ownership from provenance, prompt spans, or old importer candidates.

### Do not collapse route and finalize into one outside-recipe classifier

The repo deliberately split:

- `nonrecipe-route`
- `nonrecipe-finalize`

Keep that distinction.

### Do not treat reviewer/debug artifacts as canonical truth

Files like markdown summaries and human-readable audits are useful, but machine-readable authority lives in the explicit authority/index/manifest artifacts.

### Do not rely on old numbered-stage topology

Use semantic stage names and current artifacts. Avoid re-teaching old stage numbering in new outputs.

### Do not silently degrade valid LLM outputs back to deterministic guesses

Current live contracts are structured around validation and fail-closed behavior, not silent semantic override.

### Do not bypass manifest/index plumbing

Benchmarks, analytics, and follow-up tooling increasingly depend on:

- `run_manifest.json`
- `stage_observability.json`
- explicit artifact pointers

New features should extend that pattern, not work around it.

### Do not invent ad hoc path conventions

Timestamp and artifact naming conventions are important across:

- stage outputs
- Label Studio imports/exports
- benchmark runs
- analytics collectors

## Where new high-level features should attach

This section is meant to help a web AI propose changes that make architectural sense.

### If the feature changes source extraction

Attach it to:

- the relevant importer in `cookimport/plugins/`
- importer-specific parsing helpers in `cookimport/parsing/`
- source-job planning/merge if needed

Do not attach it to:

- recipe authority outputs
- non-recipe authority outputs

unless the feature truly changes stage-owned semantics.

### If the feature changes recipe acceptance or recipe ownership

Attach it to:

- label-first logic in `parsing/label_source_of_truth.py`
- recipe span grouping in `parsing/recipe_span_grouping.py`
- stage-owned recipe-boundary flow under `staging/import_session_flows/authority.py` and `staging/pipeline_runtime.py`

Do not attach it to:

- downstream writers only
- benchmark-only projection code

### If the feature changes recipe content/structure

Attach it to:

- deterministic recipe shaping in `staging/draft_v1.py`, `staging/jsonld.py`, and parsing helpers
- recipe Codex contracts/runtime if it is truly semantic refinement work

### If the feature changes outside-recipe knowledge behavior

Attach it to:

- `nonrecipe-route` if it is really about eligibility, exclusion, or queueing
- `nonrecipe-finalize` and knowledge-stage modules if it is really about semantic `knowledge` versus `other` or grouping

### If the feature changes benchmark scoring or handoff packets

Attach it to:

- `bench/`
- authoritative prediction artifact builders in `staging/`
- manifest pointer producers in prediction/eval flows

Do not solve benchmark issues by inventing shadow prediction logic in benchmark-only code when the real issue is upstream staged truth.

### If the feature changes human annotation workflows

Attach it to:

- `labelstudio/`

but remember that Label Studio flows are meant to reuse the same staged truth model.

### If the feature changes analytics or dashboard behavior

Attach it to:

- `analytics/`

and make sure the new behavior uses stable manifest/CSV/artifact contracts rather than scraping ad hoc file layouts.

## Historical note

Some archived docs, fixtures, or local-only readers may still use older naming. Treat that as history input, not as the live architecture.

For new design work, stay on the current contract:

- stage-owned truth, not importer-owned truth
- semantic stage names, not numbered pass-slot topology
- explicit route/finalize split for outside-recipe work
- manifest and stage-observability pointers, not guessed artifact paths
- validated accepted LLM outputs as live semantic authority on the active path, not universal advisory diffs against deterministic baseline

## What a good proposed feature sounds like

A proposal is probably aligned if it sounds like:

- “Add a new source-support hint in the EPUB importer, then let recipe-boundary decide whether it matters.”
- “Extend `recipe_block_ownership.json` consumers rather than re-deriving recipe ownership from draft provenance.”
- “Add a new benchmark projection or follow-up export that reads `stage_block_predictions.json` and manifest pointers.”
- “Add a new analytics field by extending benchmark/stage manifest enrichment and dashboard schema.”
- “Add a new knowledge-category grounding rule in the knowledge-stage contract, preserving the route/finalize split.”

A proposal is probably misaligned if it sounds like:

- “Have the importer directly emit final recipes again.”
- “Let benchmark code infer the real answer from a different path when staged outputs look strange.”
- “Add a second recipe boundary detector downstream of staging.”
- “Treat knowledge markdown summaries as the machine-readable authority.”
- “Have deterministic code auto-correct model semantics if they seem off.”

## Short version for answering architecture questions

If you need a compact answer from all of this:

- importers normalize source material
- `recipe-boundary` is the authority for recipe ownership
- `recipe-refine` is the authority for recipe semantics inside accepted recipe ownership
- `nonrecipe-route` builds the outside-recipe candidate/exclusion ledger
- `nonrecipe-finalize` is the authority for outside-recipe `knowledge` versus `other`
- staged artifacts, manifests, and semantic stage indices are the main truth surface
- Label Studio, benchmarks, follow-up tools, and analytics are supposed to reuse that truth surface rather than invent parallel ones
