---
summary: "Merged ExecPlan for codex-farm transport integrity, fail-safe fallback policy, pass2 evidence normalization, and debug projection honesty."
read_when:
  - "When implementing or reviewing the combined Pro3 transport + fail-safe codex-farm plan."
  - "When replacing docs/plans/OGplan/Pro3-1.md and Pro3-2.md workstreams with one executable plan."
---

# Stabilize codex-farm recipe extraction with transport integrity, fail-safe acceptance, and honest diagnostics

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Maintain this document in accordance with `docs/PLANS.md` from the repository root.

## Purpose / Big Picture

After this change, codex-farm should stop underperforming for mechanical reasons. The pipeline must not silently drop pass1-selected blocks before pass2, must not accept degraded pass2/pass3 outputs as valid recipes, and must stop attributing outside-span diagnostics to unrelated prompt rows.

A novice should be able to prove success locally without live model calls by running focused pytest suites and a fixture-backed replay script for the known SeaAndSmoke regressions (`c0`, `c6`, `c7`, `c8`, `c9`, `c12`). The replay should show exact transport matches and zero outside-span fallback prompt joins.

## Progress

- [x] (2026-03-03 17:08 America/Toronto) Original fail-safe ExecPlan drafted (`Pro3-2.md`).
- [x] (2026-03-03 17:10 America/Toronto) Original transport+bridge integrity ExecPlan drafted (`Pro3-1.md`).
- [x] (2026-03-03 17:45 America/Toronto) Merged both plans into this single ExecPlan (`Pro3.md`) and retired split Pro3 docs.
- [ ] Replace inclusive-span transport assembly in runtime with one authoritative helper used by orchestrator and replay tooling.
- [ ] Add strict transport audit enforcement that aborts pass2/pass3 when expected-vs-payload blocks mismatch.
- [ ] Add recipe-level degradation reasons and gate pass2/pass3 promotion on evidence quality.
- [ ] Make pass3 deterministic fallback start from `state.recipe`, not pass2 schema output.
- [ ] Harden pass3 acceptance (reject empty mappings, empty steps, placeholder-only steps, and instruction-degraded inputs).
- [ ] Add copied-view normalization for pass2 input (split quantity continuation joins and page-marker cleanup) while preserving authoritative membership.
- [ ] Add upstream multiline splitting for recipe-like text in `unstructured_adapter.py` with stable provenance keys.
- [ ] Replace outside-span fallback prompt-row join behavior in bridge/projection path with explicit unattributed/archive-only statuses.
- [ ] Fix line-role projection to preserve `within_recipe_span` for URN recipe IDs.
- [ ] Add regression fixtures and tests, run targeted suites, run replay script, then rerun benchmark entrypoint and record observed deltas.

## Surprises & Discoveries

- Observation: The observed codex quality drop is strongly mechanical, not only prompt quality.
  Evidence: Case-level transport traces show severe shrinkage between pass1 selected spans and pass2 payload (`c0: 36 -> 1`, `c6: 30 -> 13`, `c8: 32 -> 16`, `c9: 48 -> 24`, `c12: 25 -> 13`, `c7: 42 -> 21`).

- Observation: Inclusive span contract appears mismatched with runtime iteration semantics.
  Evidence: Runtime pseudocode references `range(start_block_index, end_block_index)` while artifacts and summaries treat `end_block_index` as inclusive.

- Observation: Existing transport auditing is not sufficiently protective.
  Evidence: Current audit compares data built from the same selected-index path, so pre-audit span damage can still pass through without forcing a hard failure.

- Observation: Current deterministic fallback is not deterministic enough.
  Evidence: Fallback logic starts from pass2 schema recipe material, meaning degraded pass2 state can poison the fallback baseline.

- Observation: Outside-span diagnostics are being misattributed in debug/export projection.
  Evidence: Wrong outside-span lines are tagged `joined_with_archive_only`, and fallback prompt-row behavior can attach unrelated recipe call IDs.

- Observation: Multiline evidence loss is contributing to pass2 damage in addition to transport gaps.
  Evidence: Existing newline splitting is primarily list-item scoped; recipe-like narrative/title multiline blocks remain fused and reduce usable evidence.

## Decision Log

- Decision: Consolidate the two Pro3 plans into one canonical plan file.
  Rationale: Implementation workstreams are interdependent; one living plan avoids divergence and contradictory completion state.
  Date/Author: 2026-03-03 / assistant

- Decision: Fix transport invariants before any prompt tuning.
  Rationale: Model quality cannot be fairly judged if the model never receives the full selected recipe evidence.
  Date/Author: 2026-03-03 / assistant

- Decision: Enforce fail-safe acceptance for degraded pass2/pass3 outputs.
  Rationale: In uncertain or damaged evidence states, preserving deterministic baseline output is safer than accepting low-confidence LLM drafts.
  Date/Author: 2026-03-03 / assistant

- Decision: Keep normalization split between authoritative membership and copied pass2 view.
  Rationale: Text cleanup helps pass2, but it must not hide transport defects or mutate span membership truth.
  Date/Author: 2026-03-03 / assistant

- Decision: Remove outside-span fallback prompt attribution.
  Rationale: Debug/export diagnostics must be honest; borrowed prompt rows obscure root-cause analysis.
  Date/Author: 2026-03-03 / assistant

- Decision: Include the URN span-preservation projection fix now.
  Rationale: It is small and low risk, and prevents latent regressions when line-role projection paths are enabled.
  Date/Author: 2026-03-03 / assistant

## Outcomes & Retrospective

Current state: this merged plan is authored; implementation has not started yet.

Expected completed outcome:

1. Pass2 receives exactly the pass1-selected inclusive span minus explicit exclusions, or runtime marks `transport_invariant_failed` and safely falls back.
2. Degraded pass2/pass3 outputs are rejected, and deterministic fallback is generated from `state.recipe` with guarded enrichments.
3. Outside-span canonical diagnostics no longer inherit unrelated prompt context; unresolved rows are explicitly archive-only or unattributed.
4. Targeted replay and tests prove the behavior on known regressions, and benchmark rerun evidence is recorded in this section.

When implementation finishes, update this section with exact test transcripts, replay summary, benchmark command, and observed metric deltas.

## Context and Orientation

The codex-farm runtime is a three-pass extraction flow. Pass1 selects recipe span boundaries. Pass2 extracts schema.org-style recipe structure and evidence-derived ingredients/instructions. Pass3 maps pass2 output into final `draft_v1` structure with ingredient-step mappings.

In this plan, “transport” means assembling the pass2 payload from pass1 span selection using an inclusive end index contract. “Authoritative span membership” means the truth set of block IDs selected by pass1 span minus explicit exclusions. “Normalization-on-copy” means pass2 text cleanup on a derivative view that does not mutate authoritative membership.

“Degraded recipe” means one with insufficient evidence fidelity to trust pass2/pass3 promotion. Signals include severe span-loss ratios, missing instructions, or warning buckets that imply structural corruption (`missing_instructions`, `split_line_boundary`, `ingredient_fragment`, `ocr_or_page_artifact`).

“Projection bridge” means debug/export code that joins canonical lines with prompt rows, pass spans, and archive rows. This is diagnostic tooling, not core extraction generation, but it must not invent false lineage.

Primary files and modules involved:

- `cookimport/llm/codex_farm_orchestrator.py`
- `cookimport/llm/codex_farm_transport.py` (new)
- `cookimport/debug/codex_bridge_projection_policy.py` (new)
- bridge/projection builder file currently referenced as `<bridge_builder_file>` until discovered in repo
- `cookimport/parsing/unstructured_adapter.py`
- `cookimport/parsing/canonical_line_projection.py`
- potential supporting projection/export modules (`eval_canonical_text.py`, `cutdown_export.py`) depending on repository layout
- new tests under `tests/llm/` and `tests/debug/`
- fixtures under `tests/fixtures/`
- replay helper `scripts/replay_seaandsmoke_codex_transport.py`

## Milestones

### Milestone 1: Authoritative pass1-to-pass2 transport with inclusive semantics and hard audit

Create a single helper path for pass2 block selection that merges available blocks by global index, applies inclusive `end_block_index`, applies explicit exclusions, preserves index order, and returns both selected blocks and a typed transport audit. Build pass2 payload only from this path. If audit mismatches remain (missing or extra blocks), mark recipe failure (`transport_invariant_failed`) and skip pass2/pass3 LLM promotion for that recipe.

### Milestone 2: Fail-safe pass2/pass3 promotion and deterministic fallback fidelity

Add recipe-state metrics for raw-vs-clamped span loss and pass2/pass3 acceptance reasons. Degrade recipes when evidence collapse or warning buckets indicate insufficient instruction fidelity. Only non-degraded recipes can advance to pass3. Rewrite fallback to start from `state.recipe`, then apply guarded enrichments from pass2 only when non-empty and non-placeholder quality checks pass.

### Milestone 3: Evidence cleanup without mutating authoritative membership

Add copied-view pass2 normalization helpers that can join obvious quantity-continuation split lines and remove standalone page markers while preserving source block ID provenance metadata. In parallel, improve unstructured multiline splitting for recipe-like cues in title/narrative/uncategorized text categories with deterministic stable-key suffixes.

### Milestone 4: Honest outside-span projection and URN span-preservation fix

Move prompt-row selection policy into a small helper that never assigns fallback prompt rows for outside-span lines. Emit explicit statuses (`outside_span_archive_only`, `outside_span_unattributed`) with null prompt context where appropriate. In canonical projection, preserve `within_recipe_span` from incoming prediction instead of recomputing from fragile recipe-id parsing.

### Milestone 5: Regression proof and benchmark rerun evidence

Add fixture-backed regression tests for transport, pass2 normalization, pass3 rejection/fallback behavior, and projection policy. Run targeted suites and replay script to prove known regressions are fixed without model calls. Then rerun the benchmark entrypoint and record outputs, deltas, and remaining gaps.

## Plan of Work

Begin with transport and acceptance policy in `codex_farm_orchestrator.py` so later improvements are measured on truthful evidence flow. Introduce `codex_farm_transport.py` for testable selection/audit logic and make orchestrator consume that helper as the single source of truth.

Next, wire degradation-reason computation before pass3 input assembly, and gate promotion accordingly. Update deterministic fallback so it anchors on `state.recipe` and validates final draft payloads before use.

Then add copied-view pass2 normalization and upstream multiline splitting. Keep these changes conservative, deterministic, and provenance-preserving.

After runtime behavior is stable, patch debug/projection honesty: outside-span rows cannot borrow unrelated prompt rows, and line-role projection must preserve existing span membership flags.

Finally, add fixtures/tests and run replay + benchmark evidence capture. Update all living sections in this plan after each milestone.

## Concrete Steps

Run from repository root.

1. Discover concrete file paths and replace placeholders.

    pwd
    rg -n "run_codex_farm_recipe_pipeline|_included_indices_for_state|_build_transport_audit" cookimport
    rg -n "joined_with_archive_only|select_prompt_rows\(|emit_trace_row\(|resolve_recipe_for_line\(" .
    git ls-files '*codex_farm_orchestrator.py' '*unstructured_adapter.py' '*canonical_line_projection.py' '*eval_canonical_text.py' '*cutdown_export.py'

2. Create and wire transport/policy helper modules.

    ${EDITOR:-vi} cookimport/llm/codex_farm_transport.py
    ${EDITOR:-vi} cookimport/debug/codex_bridge_projection_policy.py
    ${EDITOR:-vi} cookimport/llm/codex_farm_orchestrator.py
    ${EDITOR:-vi} <bridge_builder_file>

3. Add tests and fixtures.

    ${EDITOR:-vi} tests/llm/test_codex_farm_transport.py
    ${EDITOR:-vi} tests/llm/test_codex_farm_pass2_normalization.py
    ${EDITOR:-vi} tests/llm/test_codex_farm_orchestrator_failsafe.py
    ${EDITOR:-vi} tests/debug/test_codex_bridge_projection_policy.py
    ${EDITOR:-vi} tests/parsing/test_unstructured_adapter_multiline_split.py
    ${EDITOR:-vi} tests/parsing/test_canonical_line_projection_within_span.py
    ${EDITOR:-vi} tests/fixtures/codex_transport_cases.json
    ${EDITOR:-vi} tests/fixtures/codex_outside_span_bridge.json
    ${EDITOR:-vi} scripts/replay_seaandsmoke_codex_transport.py

4. Run targeted tests.

    python -m pytest tests/llm/test_codex_farm_transport.py -q
    python -m pytest tests/llm/test_codex_farm_pass2_normalization.py -q
    python -m pytest tests/llm/test_codex_farm_orchestrator_failsafe.py -q
    python -m pytest tests/debug/test_codex_bridge_projection_policy.py -q
    python -m pytest tests/parsing/test_unstructured_adapter_multiline_split.py -q
    python -m pytest tests/parsing/test_canonical_line_projection_within_span.py -q

5. Run replay proof.

    python scripts/replay_seaandsmoke_codex_transport.py --all

    Expected shape:

    c0 expected=36 actual=36 missing=0 extra=0 exact_match=yes
    c6 expected=28 actual=28 missing=0 extra=0 exact_match=yes joined_quantity_lines=1 dropped_page_markers=1
    c7 expected=42 actual=42 missing=0 extra=0 exact_match=yes tail_block_ge_314=yes
    c8 expected=32 actual=32 missing=0 extra=0 exact_match=yes
    c9 expected=48 actual=48 missing=0 extra=0 exact_match=yes
    c12 expected=25 actual=25 missing=0 extra=0 exact_match=yes
    outside_span rows_with_fallback_prompt=0 outside_span_archive_only_rows=<N>

6. Discover and rerun benchmark entrypoint used for SeaAndSmoke, then capture transcript.

    rg -n "need_to_know_summary.json|single-offline-benchmark|benchmark-vs-golden|line-role-pipeline" .

    Run discovered command with same relevant settings as baseline (`llm_recipe_pipeline=codex-farm-3pass-v1`, plus baseline toggles used in the compared run) and append transcript + deltas to this plan.

## Validation and Acceptance

Acceptance is complete only when all checks below are true.

1. Transport integrity

- `c0` delivers all `b67..b102` (36 blocks).
- `c6` delivers expected 28 blocks after explicit exclusions `b264,b265`, including tail through `b292`.
- `c7` delivers 42 blocks and includes at least one payload block index `>= 314`.
- `c8` delivers 32 blocks; `c9` delivers 48; `c12` delivers 25.
- Every case has `missing=0` and `extra=0` in audit/replay.

2. Runtime fail-safe behavior

- Orchestrator does not promote pass2/pass3 when transport audit fails.
- Degraded pass2 recipes are marked with explicit reasons and do not silently continue.
- Deterministic fallback starts from `state.recipe` and validates output.

3. Pass3 acceptance strictness

- Reject when `ingredient_step_mapping` is empty.
- Reject when normalized steps list is empty.
- Reject when placeholder instruction `See original recipe for details.` is the only/fundamental step content.
- Reject when upstream pass2 degradation indicates missing instruction evidence.

4. Normalization and splitting behavior

- Copied-view pass2 normalization joins quantity continuation pairs and removes standalone page markers while retaining source block IDs.
- Unstructured multiline recipe-like text is split deterministically with preserved order and stable-key suffixes.

5. Projection/debug honesty

- Outside-span lines with no recipe span do not inherit fallback prompt context (`prompt_row=None`).
- Such rows emit explicit statuses (`outside_span_archive_only` or `outside_span_unattributed`).
- `within_recipe_span` remains true for URN-style recipe IDs when it was true on input predictions.

6. End-to-end evidence

- Targeted pytest suites pass.
- Replay script output matches expected shape (zero fallback prompt joins, exact transport for known cases).
- Benchmark rerun evidence is recorded with command, output root, and key metric deltas.

## Idempotence and Recovery

All added tests, fixtures, and helper modules are additive and safe to rerun. Replay tooling must be deterministic and read-only against committed fixtures.

If midpoint implementation fails, run targeted test subsets first and repair per milestone. Do not proceed to benchmark rerun until transport and fail-safe tests are green.

If rerun artifacts use timestamped output roots, only delete the newly created retry root when needed; preserve historical run folders.

When transport invariants fail at runtime, degrade per-recipe and continue batch processing rather than crashing the entire run.

## Artifacts and Notes

Baseline evidence to preserve in tests and comments:

    c0 span 67..102 inclusive, observed old pass2 payload [b67]
    c6 span 263..292 inclusive with exclusions [b264,b265], old payload stopped at b277
    outside-span old behavior borrowed prompt context from unrelated recipe rows

Expected transport audit shape:

    {
      "start_block_index": 67,
      "end_block_index_inclusive": 102,
      "excluded_block_ids": [],
      "expected_block_ids": ["b67", "...", "b102"],
      "payload_block_ids": ["b67", "...", "b102"],
      "missing_block_ids": [],
      "extra_block_ids": [],
      "exact_match": true
    }

After implementation, append concise command transcripts for pytest, replay script, and benchmark rerun.

## Interfaces and Dependencies

Define explicit, testable interfaces in new helper modules.

In `cookimport/llm/codex_farm_transport.py`:

    @dataclass(frozen=True)
    class TransportAudit:
        start_block_index: int
        end_block_index_inclusive: int
        excluded_block_ids: tuple[str, ...]
        expected_block_ids: tuple[str, ...]
        payload_block_ids: tuple[str, ...]
        missing_block_ids: tuple[str, ...]
        extra_block_ids: tuple[str, ...]
        missing_indices: tuple[int, ...]
        exact_match: bool

    @dataclass(frozen=True)
    class NormalizedPass2Line:
        source_block_ids: tuple[str, ...]
        text: str

    def merge_blocks_by_index(blocks_before, blocks_candidate, blocks_after):
        ...

    def select_blocks_for_pass2(state, full_blocks_by_index):
        ...

    def build_normalized_pass2_lines(selected_blocks):
        ...

In `cookimport/llm/codex_farm_orchestrator.py` add explicit helpers for span loss and acceptance policy:

    def _compute_span_loss_metrics(...):
        ...

    def _compute_pass2_degradation_reasons(...):
        ...

    def _pass3_rejection_reasons(...):
        ...

In `cookimport/debug/codex_bridge_projection_policy.py`:

    @dataclass(frozen=True)
    class PromptContextChoice:
        prompt_row: object | None
        trace_status: str
        recipe_id: str | None
        call_id: str | None
        pass_name: str | None

    def choose_prompt_context_for_line(...):
        ...

Dependency policy:

- Reuse repository block/state models and current Pydantic contracts.
- Do not add third-party dependencies for this work.
- Keep pass contract schemas stable unless tests prove a mandatory schema correction.

Revision note: 2026-03-03 / assistant. Merged `docs/plans/OGplan/Pro3-1.md` and `docs/plans/OGplan/Pro3-2.md` into one canonical ExecPlan so transport integrity, fail-safe acceptance, and projection-honesty workstreams are tracked together.
