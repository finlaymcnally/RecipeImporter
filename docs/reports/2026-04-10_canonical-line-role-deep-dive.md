# Deep Dive: Canonical Line Role Orchestration & Shard Runtime
**Date:** 2026-04-10
**Author:** Gemini CLI
**Subject:** Technical Analysis of `cookimport/parsing/canonical_line_roles/`

## 1. Executive Summary
This report details an architectural deep dive into the Canonical Line Role (CLR) system. The CLR system is responsible for assigning semantic labels (e.g., `RECIPE_TITLE`, `INGREDIENT_LINE`, `NONRECIPE_CANDIDATE`) to atomic text fragments. It represents a sophisticated hybrid of deterministic heuristics and LLM-backed refinement ("Route V2").

Key findings include a highly resilient sharding and recovery mechanism, a strict validation boundary that prevents LLM "hallucinations" from corrupting row IDs, and a complex state management system that handles asynchronous worker execution.

## 2. Scope of Investigation
The investigation focused on:
- **Core Entry Point:** `label_atomic_lines` and its internal coordination logic.
- **Deterministic Baseline:** The rule-based labeling pass in `policy.py`.
- **LLM Orchestration:** Shard planning (`planning.py`), runtime execution (`runtime.py`), and the worker interface (`runtime_workers.py`).
- **Validation & Recovery:** How the system handles invalid LLM outputs and transient failures (`validation.py`, `runtime_recovery.py`, `runtime_watchdog.py`).

## 3. Architecture: The Two-Phase Pipeline

### Phase 1: Deterministic Labeling
Before any LLM is contacted, the system executes a deterministic pass.
1. **Atomization:** Raw blocks are split into `AtomicLineCandidate` objects.
2. **Rule Application:** `_deterministic_label` uses regex and keyword matching (defined in `policy.py`) to assign a baseline label.
3. **Contextual Refinement:** Heuristics look at neighboring lines (e.g., an ingredient line followed by another ingredient-like line increases confidence).
4. **Result:** A `deterministic_baseline` mapping is created. This serves as a "safety net" if the LLM phase fails or is disabled.

### Phase 2: LLM (Route V2) Orchestration
If `line_role_pipeline=codex-line-role-route-v2`, the system attempts refinement:
1. **Sharding:** `_build_line_role_canonical_plans` partitions candidates into contiguous shards. The system aims for a `target_count` (default 5 shards per book) rather than fixed line counts, allowing for dynamic scaling.
2. **Prompt Construction:** For each shard, a prompt is built using a "compact" format. Crucially, the system now hides the `atomic_index` from the model to prevent the model from rewriting or skipping IDs. It provides an ordered list of strings and expects an ordered list of labels.
3. **Direct-Exec Runtime:** The system uses `CodexExecRunner` to manage "workspaces." This is a high-level abstraction that handles the creation of `task.json` files, subprocess management, and watchdog monitoring.

## 4. Upstream and Downstream Data Flow

### Upstream: Atomization
The system depends heavily on `recipe_block_atomizer.py`. If the atomizer fails to split a `NOTE:` prefix from an ingredient line, the CLR system receives a "dirty" candidate. My analysis shows the atomizer is quite aggressive, splitting on `YIELD` prefixes and `TO MAKE` headings, which simplifies the labeling task.

### Downstream: Span Grouping
The labels produced here are the *sole authority* for `recipe_span_grouping.py`.
- If a title is mislabeled as `HOWTO_SECTION`, the grouping logic will likely fail to start a new recipe span.
- The transition from `within_recipe_span=None` (pre-grouping) to `True/False` (post-grouping) is a major state change. The CLR system handles this by providing "sanitized" predictions that are later updated once boundaries are firm.

## 5. Deep Dive: Shard Validation and "Fail-Closed" Logic
One of the most impressive parts of the codebase is `validation.py`. The system does not blindly accept LLM output.

**The Validation Loop:**
1. **Structural Check:** Does the returned `labels` array match the number of rows sent?
2. **Identity Check:** The system maps the 0-indexed labels back to the internal `atomic_index`. This "zipping" process is the primary defense against the model losing its place in the book.
3. **Legal Label Check:** Only labels in `CANONICAL_LINE_ROLE_ALLOWED_LABELS` are accepted.
4. **Pathology Guard:** If a shard returns nearly 100% of the same label (e.g., all `KNOWLEDGE`) while the baseline suggested variety, the `pathology_guard` triggers a rejection.

## 6. Identified "Sharp Edges" and Potential Bugs

### Edge 1: The "None" State Ambiguity
In `contracts.py`, `within_recipe_span` is a tri-state: `True`, `False`, or `None`.
**Potential Issue:** Several downstream functions check `if prediction.within_recipe_span:`. If the state is `None` (pre-grouping), this evaluates to `False`. While logically consistent (it's not *known* to be in a span), it can cause "False Negative" behavior in heuristics that expect a binary state.

### Edge 2: Race Condition in Watchdog Telemetry
The `_LineRoleCohortWatchdogState` uses a `threading.Lock` to protect `durations_ms` and `successful_examples`.
**Observation:** While the list updates are thread-safe, the `snapshot()` method creates a shallow copy of the examples. If another thread modifies an example dictionary *in-place* after it's added to the list but before the snapshot is finished, the snapshot could see inconsistent data. However, since the examples are converted to `dict(example_payload)` (a new copy) during recording, this risk is mitigated.

### Edge 3: Shard Boundary Context "Blindness"
Shards are contiguous. The system provides `context_before_rows` and `context_after_rows`.
**Potential Bug:** If a recipe title is the last line of Shard A and the ingredients are the first lines of Shard B, the LLM in Shard B only sees the title as "context." If the context window is too small (it defaults to immediate neighbors), the model might lack the "Recipe-ness" signal needed to correctly label the first few lines of Shard B.

### Edge 4: Deterministic Fallback on Partial Shard Failure
In `_run_line_role_phase_runtime`, if a shard is invalid, the entire shard's rows fall back to the deterministic baseline.
**Refinement Opportunity:** The system has logic for "partial authority," but in the "Route V2" implementation, it seems to prefer "All-or-Nothing" for a shard's labels to maintain semantic consistency. If an LLM labels 19/20 lines perfectly but hallucinates the 20th, the 19 good labels are currently discarded in favor of the baseline.

## 7. Conclusion
The Canonical Line Role system is a robust, battle-tested component of the `recipeimport` pipeline. Its design prioritizes **Data Integrity** over **LLM Creativity**. By stripping IDs from the model's view and using a deterministic "Baseline" as both a pre-filter and a safety net, it avoids the most common pitfalls of LLM-based parsing.

The complexity of the `runtime_watchdog` and `runtime_recovery` modules suggests that "real-world" LLM performance is often erratic, and the codebase has evolved to be extremely defensive. Future work should focus on the "Shard Boundary Context" issue to ensure semantic continuity across large books.
