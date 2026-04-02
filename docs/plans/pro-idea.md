This spec preserves the same core intent as your direct-batch plan: read the full assignment once, make all decisions in one pass, keep deterministic validation authoritative, remove bad helper affordances, and repair inside the same oriented run rather than restarting cold. The main difference is only the transport: immutable packet in, tiny structured JSON out.

Important clarification: in this spec, a "repair run" is not a fresh `codex exec` call with no memory. The happy path is one non-interactive Codex session per assignment, and follow-up repair prompts use `codex exec resume <SESSION_ID>` so the same session continues with the validator feedback and failing-row subset. The same rule applies to the knowledge stage's second semantic pass: if nonrecipe classification keeps any rows, the grouping prompt resumes the same assignment session instead of starting a new agent.

# High-level design spec: structured packet + JSON output worker architecture

## 1. Goal

Replace the editable-task-file worker contract for `line_role`, `nonrecipe_classify`, and `knowledge_group` with a structured execution model:

* orchestrator builds one immutable assignment packet
* model reads the full packet once
* model returns one tiny JSON result
* deterministic code validates
* if needed, deterministic code issues a repair packet against the same prior attempt
* deterministic code writes authoritative outputs and advances stages

This is a sibling experiment to your direct-batch file plan, not a prompt-tuning project.

## 2. Core design principles

1. **Single-pass cognition**
   The model should see the whole shard at once and label it as a whole, not queue-step through rows.

2. **Tiny output contract**
   The first-pass output should contain only the fields needed for deterministic downstream work.

3. **Deterministic authority boundary**
   The model proposes semantic answers. Repo code owns shape validation, coverage validation, tag validation, stage transitions, persistence, and scoring.

4. **Repair by subset, same resumed session**
   Validation failures should produce a repair packet that contains only the failing rows plus validator complaints, not the whole shard again unless the error is truly global. That repair prompt is sent by resuming the same Codex session, not by spawning a fresh session.

5. **No writable worker contract**
   For these stages, the model should not be asked to edit `task.json`, write `answers.json`, or invent local scripts as part of the happy path.

6. **Transport is swappable**
   The semantic contract is “packet in / JSON out.” The transport may be inline prompt text or one read-only packet file, but the packet schema and validator behavior must be identical either way.

## 3. Scope

### In scope

* `line_role`
* `nonrecipe_classify`
* `knowledge_group`
* shared structured runner
* structured validators and repair loop
* artifact logging for debugging
* shard sizing / token budgeting

### Out of scope

* recipe correction pass
* benchmark logic changes except adding this runner path
* ontology redesign
* quality retuning beyond simplifying the contract
* broad repo-wide compatibility shims

## 4. End-to-end architecture

### 4.1 Initial run

1. Upstream deterministic code produces a shard.
2. A packet builder converts that shard into a read-only structured assignment packet.
3. The structured runner invokes Codex with:

   * one stable stage prompt
   * one packet
   * one output schema
4. The model returns JSON only.
5. The validator parses and checks:

   * schema
   * row coverage
   * enum/tag validity
   * stage invariants
6. If valid, deterministic code writes authoritative outputs and advances the pipeline.
7. If invalid, deterministic code creates a repair packet and resumes the same Codex session with only the failing portion.

### 4.2 Repair run

1. Preserve the original assignment identity.
2. Build a repair packet containing:

   * the original stage instructions
   * only the failing rows or failing groups
   * prior answers for those rows
   * validator errors, expressed clearly and deterministically
3. Resume the same Codex session and ask for corrected JSON only.
4. Merge corrected rows into the previous valid result set.
5. Revalidate.
6. Stop after a small fixed max repair count.

### 4.3 Finalization

Once a stage validates:

* line-role writes shard outputs as today
* nonrecipe classification writes kept/dropped decisions and tag grounding
* if any rows are kept, grouping packet generation begins in the same resumed assignment session for that shard
* grouping validates and writes final grouped knowledge outputs

## 5. Worker contract

## 5.1 Happy-path contract

For these structured stages, the worker contract is:

* read one assignment packet
* return one JSON object
* no shell scripting
* no file rewriting
* no helper commands
* no explanations unless explicitly requested in the schema

For knowledge shards, this same assignment session may later be resumed for the grouping pass after classification validates and some rows survive as kept knowledge.

## 5.2 Repair contract

For repair runs, the worker contract is:

* resume the same assignment session
* read the repair packet
* correct only the specified rows or groups
* return only corrected JSON payloads in the same schema family
* do not relabel untouched rows

## 6. Common packet schema

Use one common top-level packet shape for all structured stages.

```json
{
  "schema_version": "structured_worker.v1",
  "stage_key": "line_role | nonrecipe_classify | knowledge_group",
  "assignment_id": "book123.stageX.shard07",
  "run_mode": "initial | repair",
  "prompt_version": "line_role.v1",
  "book_context": {
    "book_id": "book123",
    "source_name": "example-cookbook"
  },
  "stage_context": {
    "ontology_version": "knowledge-tags.v3",
    "allowed_labels": [],
    "allowed_tag_keys": []
  },
  "units": [],
  "repair_context": null
}
```

Rules:

* `units` are immutable input facts
* model never edits packet content
* all stage-specific fields live under `stage_context`
* `repair_context` is null on initial runs

## 7. Stage-specific packet and output contracts

## 7.1 Line role

### Input unit shape

```json
{
  "id": "42",
  "text": "2 tablespoons olive oil",
  "context": {
    "block_index": 42,
    "prev_text": "For the dressing:",
    "next_text": "1 teaspoon mustard",
    "recipe_window_hint": "recipe_local"
  }
}
```

### Output shape

```json
{
  "answers": [
    { "id": "42", "label": "INGREDIENT_LINE" }
  ]
}
```

### Invariants

* every input `id` appears exactly once
* no extra ids
* `label` must be in allowed enum
* no rationale field in normal mode

## 7.2 Nonrecipe classify

Assumption: `reviewer_category` and `retrieval_concept` are gone by the time this lands.

### Input unit shape

```json
{
  "id": "884",
  "text": "Salt every stage of cooking so flavor develops inside the food.",
  "context": {
    "block_index": 884,
    "prev_text": "When I first started cooking...",
    "next_text": "Taste again before serving.",
    "section_hint": "nonrecipe_candidate"
  }
}
```

### Output shape

```json
{
  "answers": [
    { "id": "884", "keep": 1, "tag_key": "seasoning.layering" },
    { "id": "885", "keep": 0, "tag_key": null }
  ],
  "proposed_tags": [
    {
      "tag_key": "heat.carryover_resting",
      "label": "Carryover cooking and resting",
      "description": "Knowledge about resting food so residual heat finishes cooking."
    }
  ]
}
```

### Invariants

* every input `id` appears exactly once
* `keep` is `0` or `1`
* `keep=0` requires `tag_key=null`
* `keep=1` requires `tag_key`
* `tag_key` must either exist in allowed ontology or appear in `proposed_tags`
* proposed tag keys must be unique
* proposed tags are only allowed if at least one answer references them

## 7.3 Knowledge grouping

Grouping remains a second semantic phase, as in your direct-batch plan.

Clarification: `nonrecipe_classify` and `knowledge_group` are two prompts in one knowledge-shard session, not two different agents. The classification packet starts the session. If deterministic validation accepts the classification result and any rows survive as kept knowledge, deterministic code builds a grouping packet for only those kept rows and resumes the same session id for the grouping prompt. If classification needs repair first, that repair also happens in the same resumed session before grouping begins.

### Input unit shape

Only kept rows go into grouping.

```json
{
  "id": "884",
  "text": "Salt every stage of cooking so flavor develops inside the food.",
  "tag_key": "seasoning.layering"
}
```

### Output shape

```json
{
  "groups": [
    {
      "group_id": "seasoning.layering.g1",
      "tag_key": "seasoning.layering",
      "unit_ids": ["884", "891", "902"],
      "summary": "Season gradually during cooking instead of salting only at the end."
    }
  ]
}
```

### Invariants

* every kept row appears in exactly one group
* no dropped rows may appear
* every group has at least one unit
* all units inside a group must share a compatible `tag_key`
* no duplicate unit ids across groups

## 8. Prompt contract

## 8.1 Initial prompt pattern

Each structured stage prompt should say, in plain language:

* read the full packet once before answering
* reason over the whole assignment, not one row at a time
* return JSON only
* do not include prose, markdown, code fences, or scripts
* do not invent helper files or tools
* cover every row exactly once
* obey the provided schema exactly

## 8.2 Repair prompt pattern

Repair prompt should say:

* you are resuming the same assignment session
* you already answered this assignment
* deterministic validation found the following exact issues
* correct only the listed rows or groups
* preserve valid prior work
* return JSON only in the repair schema

## 8.3 No-rationale default

Normal-path prompts should not ask for explanations. If you want debugging signals, use an optional debug mode that is disabled in production.

## 9. Validation design

Validation must be split into clear layers.

## 9.1 Parse validation

* valid JSON
* top-level keys exactly as expected
* no trailing prose

## 9.2 Schema validation

* required fields present
* field types correct
* enums valid

## 9.3 Coverage validation

* every input row covered exactly once
* no duplicate ids
* no unknown ids

## 9.4 Domain validation

Stage-specific semantic-structure checks:

* line-role labels in allowed set
* keep/tag consistency
* ontology keys valid or proposed
* grouping membership valid
* grouping uses only kept rows

## 9.5 Soft anomaly checks

These should warn, not fail:

* 98% of rows got same label
* zero kept knowledge rows on a packet that looks rich
* huge flood of proposed tags
* every row tagged to same ontology key
* suspiciously empty groups

Warnings should be logged for debugging and benchmark review.

## 10. Repair loop design

## 10.1 Repair trigger

Repairs happen only on deterministic validation failure.

## 10.2 Repair packet shape

```json
{
  "schema_version": "structured_worker.v1",
  "stage_key": "nonrecipe_classify",
  "assignment_id": "book123.nonrecipe.shard07",
  "run_mode": "repair",
  "prompt_version": "nonrecipe_classify.v1",
  "original_packet_digest": "sha256:...",
  "failing_units": [
    {
      "id": "884",
      "text": "Salt every stage of cooking so flavor develops inside the food.",
      "prior_answer": { "id": "884", "keep": 1, "tag_key": null },
      "errors": [
        "keep=1 requires a non-null tag_key"
      ]
    }
  ]
}
```

## 10.3 Repair rules

* repair packet should include only failing rows unless the failure is global
* global failures include invalid top-level JSON shape, missing entire output arrays, or completely broken schema
* repair prompts are sent with `codex exec resume <SESSION_ID>`, not a fresh `codex exec`
* merge corrected rows back into the last valid partial result
* max repair rounds: 2 or 3
* after max failures, mark shard failed and persist full artifacts

## 11. Token and shard budgeting

This architecture only works if shard sizing is conservative.

## 11.1 Shard sizing rules

Budget for:

* input packet tokens
* prompt tokens
* structured output tokens
* one repair round

Use a shard estimator based on:

* number of rows
* average row text length
* stage type
* expected output density

## 11.2 Output minimization

Normal outputs should be tiny:

* line-role: `id + label`
* nonrecipe classify: `id + keep + tag_key`
* grouping: `group_id + tag_key + unit_ids + short summary`

Do not emit:

* rationales
* copied source text
* verbose explanations
* duplicated ontology metadata on every row

## 11.3 Repair minimization

Repairs should never resend the full shard unless absolutely necessary.

## 11.4 Transport rule

Implement the contract so packet transport can be:

* inline JSON in prompt for small/medium shards
* single read-only packet file for large shards

Both must use the exact same packet schema, output schema, validator, and artifact format.

## 12. Artifacts and observability

For every run, persist:

* `input_packet.json`
* `prompt.txt`
* `raw_stdout.txt`
* `parsed_output.json`
* `validation_report.json`
* `repair_packet_round_1.json`
* `repair_stdout_round_1.txt`
* `final_authoritative_output.json`
* `run_summary.json`

`run_summary.json` should include:

* stage
* shard id
* prompt version
* attempt count
* token estimates
* validation outcome
* anomaly warnings
* elapsed time
* final status

This is crucial for debugging without having to interpret agent logs.

## 13. Integration with current codebase

Your uploaded plan already identifies the current seams around task files, prompts, same-session handoff, and workspace enforcement. This structured architecture should reuse the same deterministic authority but move it out of editable-worker-file assumptions.

### 13.1 New shared modules

Add these new modules or equivalent:

* `cookimport/llm/structured_packets.py`

  * builds stage packets
  * serializes prompt-safe packet text
  * owns schema versions

* `cookimport/llm/structured_output_schemas.py`

  * JSON Schema definitions for each stage

* `cookimport/llm/structured_runner.py`

  * invokes codex exec
  * records the initial session id
  * resumes the same session id for repair prompts and knowledge grouping follow-up prompts
  * captures stdout
  * parses JSON
  * logs artifacts

* `cookimport/llm/structured_validation.py`

  * shared parse/schema/coverage validation
  * stage hooks for domain validation

* `cookimport/llm/structured_repair.py`

  * builds repair packets
  * merges corrected subsets
  * controls retry policy

### 13.2 Stage adapters

* `cookimport/parsing/canonical_line_roles/structured_stage.py`
* `cookimport/llm/knowledge_stage/structured_classify_stage.py`
* `cookimport/llm/knowledge_stage/structured_group_stage.py`

These should:

* build packets from existing deterministic upstream data
* call the structured runner
* validate results
* keep one session id per knowledge shard across classification, repair, and grouping
* hand successful outputs to existing downstream writers

### 13.3 Refactor target

Extract pure validation/transition logic from any current handoff modules that assume editable task files, so the logic can be reused here without shell-command workflow assumptions.

### 13.4 Temporary coexistence

Because you want to compare this architecture against the direct-batch file contract, implement it as a top-level selectable runner for the targeted stages only. Keep the fork isolated at the stage-runner boundary, not spread throughout the repo.

Suggested setting:

```python
worker_contract = "direct_batch" | "structured_exec"
```

Once you decide the winner, delete the loser instead of preserving both long-term.

## 14. Testing plan

## 14.1 Unit tests

* packet builder produces stable packet shape
* schema validator catches malformed outputs
* coverage validator catches missing/duplicate ids
* nonrecipe validator catches bad tag usage
* grouping validator catches overlap and dropped-row leakage
* repair merge logic preserves untouched valid rows

## 14.2 Golden tests

For a small labeled fixture:

* line-role structured run parses and validates
* nonrecipe classify structured run parses and validates
* grouping structured run parses and validates

Use mocked model outputs for deterministic tests.

## 14.3 Failure tests

* prose before/after JSON
* malformed JSON
* missing ids
* duplicate ids
* invalid label enum
* `keep=1` with null tag
* proposed tag referenced but missing definition
* grouping includes unkept row

## 14.4 Artifact tests

Verify every run writes the expected debugging artifacts.

## 14.5 Benchmark compare tests

Add runner-level comparison harness so the same gold shard can be executed via:

* current direct-batch file mode
* structured packet mode

Compare:

* strict validity rate
* repair rate
* final accuracy
* anomaly rate
* token estimate

## 15. Acceptance criteria

This architecture is accepted when all of the following are true:

1. `line_role`, `nonrecipe_classify`, and `knowledge_group` can run with no editable `task.json` contract.
2. The model’s happy path is packet read + JSON return only.
3. Deterministic validation remains authoritative.
4. Repair operates on failing subsets by resuming the same session, instead of restarting the whole shard in a new session.
5. Grouping still remains a distinct second semantic phase.
6. For knowledge shards, classification and grouping use the same resumed Codex session rather than separate agents.
7. Raw artifacts are sufficient to debug failures without reading freeform agent logs.
8. Structured mode is benchmark-comparable against direct-batch mode.
9. No stage in this mode depends on `answers.json`, queue helpers, or writable worker files.

## 16. Copy/paste implementation brief for Codex



Implement a new structured execution path for line_role, nonrecipe_classify, and knowledge_group.

Goal:
Replace editable task-file worker behavior with immutable assignment packets and tiny JSON-only model outputs. Preserve deterministic validation, same-session repair, and existing downstream authoritative writers.

Key rules:
- The model reads one full packet and returns one JSON object.
- No writable task.json, no answers.json, no helper workflow commands on the happy path.
- Validation is deterministic and authoritative.
- Repairs operate on only failing rows/groups unless the failure is global, and they must resume the same `codex exec` session id rather than starting a fresh agent.
- Keep grouping as a second semantic phase after successful nonrecipe classification.
- For each knowledge shard, classification and grouping must use the same resumed session/agent when grouping is needed.
- Support two packet transports with identical semantics: inline prompt packet and read-only packet file.
- Output contracts must be tiny:
  - line_role: answers[{id,label}]
  - nonrecipe_classify: answers[{id,keep,tag_key}], proposed_tags[]
  - knowledge_group: groups[{group_id,tag_key,unit_ids,summary}]
- Persist debugging artifacts for every run.
- Implement this as a selectable runner path for comparison against the current direct-batch file contract.
- Keep the fork isolated at the stage-runner boundary, not spread across the repo.
- Reuse existing deterministic output writers/transition logic where possible by extracting pure functions from editable-task-file assumptions.

Suggested modules:
- cookimport/llm/structured_packets.py
- cookimport/llm/structured_output_schemas.py
- cookimport/llm/structured_runner.py
- cookimport/llm/structured_validation.py
- cookimport/llm/structured_repair.py
- stage adapters under parsing canonical line roles and knowledge_stage

Do not broaden scope into recipe correction, ontology redesign, or benchmark retuning.

Revision note (2026-04-01): clarified that repair and knowledge grouping are resumed-session follow-ups using `codex exec resume <SESSION_ID>`, not fresh agent invocations. This was added so the transport description matches the intended "same oriented run" behavior for repair and for the two-pass knowledge flow.
