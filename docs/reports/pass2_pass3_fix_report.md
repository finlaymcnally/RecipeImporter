# Pass2/Pass3 Repair Plan for CodexFarm

## Objective

Replace the fragile pass2 -> pass3 handoff with a source-grounded assembly-and-repair flow that preserves the good parts of the current design (extractive discipline, optional conservative ingredient-step mapping) while removing the biggest sources of information loss, empty outputs, and fallback churn.

The goal is not “make the model more creative.” The goal is to make it much harder for the system to hand a good model broken, partial, or semantically degraded inputs.

## Executive diagnosis

The current system is paying a high handoff tax. The benchmark packet shows that pass3 is the dominant cost center, but it is not the dominant source of gains. At the same time, representative failures show that pass2 and pass3 often run on degraded or contradictory intermediates.

This means the primary implementation problem is orchestration integrity, not raw model capability.

The most likely failure classes are:

1. Source-to-intermediate loss. Information present in the selected recipe span does not reliably survive into pass2 and pass3 payloads.
2. Transport contract drift. Stage outputs appear internally inconsistent in ways that suggest boundary, inclusion, or serialization bugs.
3. Over-decomposition. Pass2 and pass3 divide responsibility in a way that introduces failure surfaces larger than the reasoning savings they once provided.
4. Wrong runtime mode. The prompt samples show traces consistent with an agentic/docs-list/tool-seeking mode contaminating recipe extraction and finalization calls.
5. Missing invariant checks. Degraded payloads are allowed to continue through the pipeline instead of being rejected, retried, or rebuilt from source.

## What to preserve from the original design

The original split was conceptually sound for the models available at the time.

Pass2 had a good purpose: build a conservative structured recipe package from the selected span, ideally extractively, without inventing unsupported details.

Pass3 also had a good purpose: ingredient-to-step linkage is genuinely hard, especially with repeated ingredients, nested sections, and multi-component recipes. A conservative mapping stage that prefers omission over fabrication is still the right philosophy.

Do not throw away those values. Preserve:

- extractive grounding
- authority of source text over model guesses
- omission over hallucination
- optional/partial ingredient-step mapping rather than forced total mapping

What should change is not the epistemology. What should change is the stage architecture.

## Root-cause framework

### Cause class A: the model is often not given a clean recipe-repair task

Symptoms from the packet:

- Prompt samples show reasoning traces about documentation scripts and `docs-list` in pass1, pass2, and pass3.
- Pass3 samples show payloads with empty `extracted_ingredients`, corrupted instruction text, split instruction fragments, or only one “instruction” that is actually narrative prose.

Effect:

A strong model that would succeed on “fix this recipe JSON minimally” is instead asked to solve a different problem:

- infer recipe structure from partial shards
- obey a narrow output schema
- preserve broken intermediates verbatim
- optionally map ingredients to steps without enough evidence
- do all of this while apparently operating in a tool- or agent-oriented runtime mode

Fix:

Run pass2/pass3 work in a plain structured-output mode with no tool affordances and no agentic shell behavior. Make the task explicitly about reconciling source span and draft artifacts into one canonical output.

### Cause class B: stage interfaces are lossy or inconsistent

Symptoms from the packet:

- There are cases where pass1 selected a span but pass2 reports `input_block_count: 0` while still emitting extracted ingredients and instructions.
- There are cases where pass1 selected only one block, had heavy clamped loss, and pass2 then hard-failed with `missing_instructions`.
- The bridge debug packet shows a pass1 -> pass2 pseudocode path that uses `range(start_block_index, end_block_index)`, which is a classic inclusive/exclusive boundary hazard and must be audited.

Effect:

Downstream stages are being asked to repair information that may already have been dropped by transport, span slicing, normalization, or serialization. This creates fake “LLM failures” that are actually interface failures.

Fix:

Before changing prompts, make stage boundaries auditable and invariant-checked. Audit inclusive/exclusive semantics end-to-end. Build a transport verifier that proves the source span and pass2/pass3 payloads are consistent.

### Cause class C: pass2 and pass3 now decompose the problem too aggressively

Symptoms from the packet:

- Pass3 often routes to LLM mode under `pass2_ok_requires_llm` and returns `empty_mapping=true`.
- Pass3 is expensive and frequently adds no usable linkage.
- Hard-degradation paths for pass2 lead to fallback instead of source-grounded recovery.

Effect:

You pay the cost of multiple stages without reliably gaining additional information. Every stage boundary is another place for dropped rows, broken encoding, duplicated sections, split lines, or title/description skew.

Fix:

Merge pass2 and pass3 into a single assembly-and-repair stage whenever there is a contiguous candidate recipe span and the system has enough source evidence to do meaningful work.

### Cause class D: there are not enough fail-fast guards

Symptoms from the packet:

- Empty ingredient arrays proceed to final draft construction.
- Split instructions such as `about` / `inch/2 mm thick.` are allowed through.
- Corrupted characters proceed into pass3.
- Narration-only “instructions” are treated as authoritative steps.

Effect:

The pipeline normalizes garbage into official intermediates, and later stages are forbidden from rewriting enough to fix them.

Fix:

Validate aggressively before every expensive LLM step. If the payload violates structural sanity, stop and rebuild from source instead of asking the model to rescue it indirectly.

## Recommended target architecture

## Keep pass1, replace pass2 -> pass3 with one merged stage for good spans

Do not collapse the whole pipeline into one giant prompt.

Keep pass1 (or whichever boundary-selection stage currently works best), because you still need a narrow candidate span for cost control and provenance.

But once you have a contiguous candidate recipe span, replace the current pass2 -> pass3 handoff with a single stage I would describe as:

source-grounded assembly + repair + optional mapping

This stage should receive:

- the authoritative source span or authoritative source rows
- the current extractive ingredients/instructions if they exist
- the current schema.org draft if it exists
- the current final-draft/canonical recipe object if it exists
- any existing section metadata or line-role annotations as hints, not as law

It should return one canonical recipe object plus optional ingredient-step mapping and warnings.

The key design principle is:

source span is authority; drafts are hints

Do not ask the model to “make both schema.org and final draft correct” as independent coequal outputs. That doubles inconsistency risk.

Instead:

1. Choose one canonical internal recipe representation.
2. Have the merged stage emit only that canonical object plus optional mapping and warnings.
3. Deterministically derive schema.org and any other export shapes from that canonical object afterward.

If the current final internal format is richer than schema.org, make the internal final format canonical and derive schema.org from it.

## When not to use the merged stage

Keep a deterministic fast path for simple recipes.

If the current logic can confidently produce a correct result without LLM mapping, preserve that path. The benchmark packet suggests many successful cases already route deterministically and do not need LLM linkage.

So the runtime policy should be:

- easy contiguous recipe with clean sectioning and no ambiguous repeated ingredient problem: deterministic path
- contiguous recipe with ambiguous ingredient-to-step linkage or draft inconsistencies: merged repair stage
- broken or insufficient source payload: stop, re-window, or fail fast with diagnostics

## Concrete implementation guidance

## 1. Introduce a canonical merged-stage contract

Create a new internal contract for the merged replacement stage.

Suggested input shape:

- `recipe_id`
- `source_span_blocks` or `source_rows`
- `line_roles` / section spans / provenance hints
- `current_extracted_ingredients`
- `current_extracted_instructions`
- `current_schemaorg_recipe`
- `current_final_recipe`
- `repair_mode`
- `mapping_mode`

Suggested output shape:

- `canonical_recipe`
- `ingredient_step_mapping`
- `warnings`
- `repair_actions` (optional debug field, can be dropped from production artifacts if needed)
- `source_coverage_summary` (optional debug field)

Make sure the output contract makes omissions explicit. Mapping may be partial. Empty mapping is acceptable only if the payload clearly justifies it.

## 2. Define strict authority ordering

The merged stage should obey this order:

1. Authoritative source span text
2. Explicit section structure inferred from source
3. Existing drafts as repair hints
4. Existing mapping as a hint only

This prevents stale or broken drafts from outranking the source.

The prompt and the orchestrator should say this plainly. Do not leave the model to infer which artifact is authoritative.

## 3. Build a transport verifier before merging logic

Before implementing the merged stage, add a reusable verifier that checks every stage payload against the source span.

It should validate at least:

- source span block count
- inclusive/exclusive boundary consistency
- every extracted ingredient line appears in source span after normalization
- every extracted instruction line appears in source span after normalization
- every instruction fragment is whole enough to be meaningful
- ingredient and instruction order are monotonic relative to source order
- no payload is allowed to claim success with zero source rows unless explicitly tagged as synthetic fallback

This verifier should run:

- after pass1 span selection
- before merged-stage invocation
- after merged-stage output if the output claims extractive fidelity

This one subsystem will likely explain a large share of your current weirdness.

## 4. Audit boundary semantics aggressively

The debug packet’s pseudocode strongly suggests an area to inspect: inclusive vs exclusive span endpoints in the pass1 -> pass2 transport.

Do not assume the debug pseudocode is the whole truth. But do treat it as a serious lead.

The coding model should audit:

- span schema meaning in prompt contracts
- runtime meaning in state objects
- slicing semantics in Python ranges
- transport audit semantics
- archive/provenance semantics
- any off-by-one behavior in overlap resolution, dedupe, or block exclusion

Rule of thumb:

A span representation must choose one convention and enforce it everywhere. If pass1 emits inclusive end indices, every consumer must either use inclusive logic directly or convert once, explicitly, at the boundary.

Do not let some components interpret spans as inclusive and others as half-open.

## 5. Refuse to run expensive repair on bad payloads

Add preflight guards. The merged stage should not run when the input is clearly nonsensical.

Hard-stop or re-window on conditions such as:

- zero source rows
- zero ingredients and zero instructions
- multiple ingredients but zero instructions when source span clearly contains imperative cooking text
- instruction fragments that look severed mid-measurement or mid-sentence
- corrupted characters or invalid encoding in authoritative step text
- section headers present without corresponding section bodies

When a guard trips, do not mark the case “ok, requires LLM.” Mark it as transport failure or degraded source selection and route to a dedicated recovery path.

## 6. Implement a source-grounded recovery path instead of hard fallback

For cases like `missing_instructions`, do not immediately drop to hard fallback.

Instead implement one recovery stage that re-derives ingredients and instructions directly from the contiguous source span with a narrow objective:

- identify ingredient lines
- identify instruction lines
- ignore previous broken intermediate state
- emit a fresh canonical recipe attempt

This recovery path should be simpler than the normal merged stage and should not reuse suspect extracted fields.

## 7. Make mapping partial, conservative, and source-evidenced

Do not require a total ingredient-step mapping.

Require only a partial high-confidence mapping. If a repeated ingredient cannot be disambiguated, omission is correct. But when mapping is omitted, the stage should say why in machine-readable warnings.

A good mapping contract is:

- map only when source evidence is explicit or strongly local
- repeated ingredient references may map to multiple steps if clearly reused
- if ambiguous, omit the edge, not the whole recipe
- never return an empty mapping silently when high-quality step text exists and the recipe obviously uses some ingredients directly

The important change is “omit ambiguous edges,” not “return the whole mapping object empty.”

## 8. Make outputs derivable, not parallel

A recurring design trap is maintaining multiple “final” artifacts.

Avoid this by making schema.org derivation deterministic from the canonical recipe object. Likewise, ingredient-step mapping should decorate the canonical object, not be an independent alternative truth.

This greatly reduces drift between stages and simplifies testing.

## 9. Remove agentic runtime behavior from extraction/finalization calls

The prompt samples strongly suggest the model is sometimes in an agentic or tool-seeking mode unrelated to recipe processing.

The coding model should inspect the codex execution wrapper, system prompt stack, tool configuration, and request mode for pass1/pass2/pass3 calls. The objective is simple:

recipe extraction/finalization calls must be plain JSON-in / JSON-out structured calls with no tool affordances and no environment cues that invite tool use.

Even if those docs-list traces are partially a logging artifact, the safe move is the same: make the runtime mode unambiguously non-agentic for extraction and repair tasks.

## 10. Preserve auditability with better artifacts

Every merged-stage call should write a compact audit artifact with:

- source span indices
- source text hash
- normalized source rows
- preflight validation results
- authority-ranked input summary
- canonical output summary
- mapping edge count
- warning codes
- whether output came from normal path, recovery path, or fallback

You do not need giant raw dumps for every run, but you do need enough to explain failures without re-running the world.

## Suggested implementation sequence

## Phase 1: observability and invariants first

Before changing main behavior:

- add transport verifier
- add span-semantics audit tests
- add preflight validators
- add structured warning codes
- add runtime-mode logging for pass calls

Acceptance for Phase 1:

You can point to a failing case and say exactly whether it failed because of source selection, span slicing, payload loss, encoding damage, or model reasoning.

## Phase 2: merged stage behind a feature flag

Add a new pipeline mode, something like:

`codex-farm-2stage-repair-v1`

Flow:

- pass1 selects/refines span
- deterministic extractor builds initial hints if available
- merged stage assembles + repairs + optionally maps
- deterministic derivation emits schema.org and downstream formats

Keep the old path available for A/B comparison.

## Phase 3: recovery path for degraded spans

For cases currently marked `missing_instructions`, implement a recovery pass that rebuilds from source span directly.

Only after this exists should you remove current hard-fallback behavior in most cases.

## Phase 4: routing cleanup

Once the merged stage is stable:

- narrow deterministic fast path
- narrow recovery path
- remove legacy pass3-only routing for cases now better handled by merged repair

## What the coding model should specifically inspect in the codebase

Because the coding model can see the repository, I would tell it to inspect these areas first, in this order:

1. The codex-farm orchestrator that builds pass2/pass3 payloads and routes between deterministic and LLM paths.
2. The data structures that represent recipe spans, especially start/end semantics and excluded blocks.
3. The transport/audit builder that converts selected spans into pass2 input.
4. The execution wrapper and any system prompt / runtime configuration that could enable tool use or agentic behavior.
5. Any normalization layer that rewrites, splits, or drops instruction lines before pass3.
6. The deterministic derivation code that currently promotes pass2 results into final drafts and pass3 mapping requests.

The audit question for each subsystem is always the same:

Can this layer lose or distort information that was present in the authoritative source span?

If yes, either remove that layer, make it lossless, or add a verifier that blocks degraded payloads.

## Test strategy

Do not rely on aggregate benchmark score alone.

Add focused tests at three levels.

### Unit tests

- span inclusive/exclusive semantics
- excluded block handling
- transport verifier normalization rules
- instruction fragment detector
- corrupted text detector
- canonical derivation from canonical recipe -> schema.org

### Scenario tests

Use real benchmark fixtures for at least these classes:

- repeated ingredient recipe that used to require pass3
- `empty_mapping=true` case with otherwise valid steps
- `missing_instructions` hard-fallback case
- case with sectioned sub-recipes or multi-component recipe
- case with narrative prose near the recipe that should not become instructions

### A/B evaluation

Compare old vs new pipeline on:

- inside active recipe span accuracy
- fallback rate
- `empty_mapping` rate
- average mapping edge count for recipes that should map non-trivially
- number of cases with zero instructions after pass processing
- tokens / latency / estimated cost

The new pipeline does not need to win every edge case immediately. But it should clearly reduce:

- impossible payloads
- silent empty mappings
- hard fallbacks due to missing instructions
- expensive calls on broken inputs

## Acceptance criteria

The implementation is successful when all of the following are true:

1. A contiguous recipe span can be turned into one canonical recipe object without requiring a fragile pass2 -> pass3 artifact handoff.
2. If the source span contains usable instructions, the pipeline does not end up with `extracted_instruction_count = 0` unless the source selection itself was genuinely wrong.
3. Empty ingredient-step mappings become rare, explainable, and usually limited to truly ambiguous cases.
4. Schema.org and final recipe outputs are deterministically derived from one canonical representation.
5. The system can prove, via transport artifacts and tests, that authoritative source information was not silently dropped between stages.
6. Extraction/finalization calls no longer show evidence of agentic tool-seeking runtime contamination.
7. The new path is measurably cheaper or measurably more accurate than the current pass2 -> pass3 design, ideally both.

## Non-goals

Do not try to solve every remaining benchmark issue in this change.

In particular, line-role problems and outside-span title/promotional errors are real, but they are not the main target of this implementation. This plan is specifically about fixing pass2/pass3 architecture and handoff integrity.

If the coding model starts broadening the scope, it should stop and protect the main objective: make recipe assembly and mapping source-grounded, auditable, and hard to corrupt.

## Final advice to the implementer

Treat this as a data-contract repair project, not a prompt-writing project.

The old design assumed the decomposition would help the model. The current evidence suggests the decomposition is now hurting more than helping. Modern models are good enough that once you have a contiguous recipe span, one careful repair pass with strong authority rules is often safer than two narrower passes with a brittle seam between them.

So do not ask, “How can I make pass3 smarter?”

Ask instead:

“How can I make it impossible for pass3’s replacement to receive a broken view of the recipe?”

That question will lead to the right code.
