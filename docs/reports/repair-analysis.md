# Repair Attempts: Plain-English Detailed Walkthrough - by codex

There are 3 LLM stages:

1. `line-role`
2. `recipe refine`
3. `nonrecipe finalize / knowledge`

And there are 2 transport styles:

1. `taskfile`
2. `inline-json`

Important first point: `recipe refine` is still `taskfile` only right now. It does not have an `inline-json` path yet.

## The Main Idea

When the program says "try again," that can mean two different things:

1. `repair`
   The model answered, but the answer did not pass deterministic validation, so the program asks it to fix the answer.
2. `recovery`
   The worker did not really finish properly. Maybe it crashed, got watchdog-killed, or exited without producing the expected durable result. In that case, the program may try reopening the work in a new session or with a new worker.

These are different.

`repair` means:
- "your answer exists, but it is malformed, incomplete, or not promotable"

`recovery` means:
- "the worker session itself did not finish cleanly enough"

This distinction matters because a stage can do both:
- first it might try to repair a bad answer
- and separately it might also be allowed to restart a clean session if the worker stopped awkwardly

## The Three Layers Of "Another Try"

Across the program, there are really three different "another try" layers:

1. Same-session repair
   The worker is still effectively on the same assignment, and the repo asks it to fix the bad parts.

2. Fresh-session retry
   The first session ended, but enough useful state was left behind that the repo thinks "start a new session and continue from here" is worth trying.

3. Fresh-worker replacement
   The first worker is treated as too broken or too risky to continue from, so the repo restores the original assignment and hands it to a fresh worker/session.

So when we talk about "how many retries" a stage has, we have to be careful:
- repair budget is one thing
- restart budget is another thing

## Taskfile Mode: How It Works

In `taskfile` mode, the worker is given a `task.json` file to edit. The important idea is:

- the repo owns the job definition
- the worker edits only the answer fields
- the repo helper validates the edited file
- the repo decides whether to accept it, rewrite it into repair mode, advance it to another step, or fail it

So `taskfile` mode is a little like a worksheet:

1. The repo writes the assignment into `task.json`.
2. The worker fills in answers.
3. The worker runs the helper.
4. The helper checks whether the edited file is structurally acceptable.
5. The helper either:
   - finishes the job
   - rewrites the file into repair mode
   - advances the file to the next stage of the same workflow
   - or gives up

### What "repair mode" means in taskfile

When a taskfile worker fails validation, the repo does not usually say "start over."

Instead it does something more focused:

1. It figures out which units failed.
2. It builds a new repair version of the task file.
3. That repair file keeps only the failed units active.
4. It also carries feedback about what was wrong.
5. The worker is expected to reopen that rewritten file and fix only those named problems.

So taskfile repair is not a vague "please try better."
It is more like:

- "these specific answer rows were invalid"
- "here is the narrowed repair version of the task"
- "fix those and rerun the helper"

### Default taskfile repair limit

The normal taskfile rule is:

- one same-session repair rewrite

That means:

1. Initial answer pass happens.
2. If it fails in a repairable way, the helper rewrites `task.json` into repair mode.
3. The worker gets one repair pass.
4. If that repaired file still fails, the state becomes `repair_exhausted`.

In plain English:
- taskfile mode usually allows one focused fix pass, not endless back-and-forth

### Fresh-session retry in taskfile mode

Taskfile mode also has a separate "fresh session retry" idea.

This is not "your answer was invalid."
It is more:

- "the worker exited cleanly enough"
- "there is useful progress left behind"
- "the helper did not reach a completed state"
- "so reopening this same workspace in a new session might salvage the run"

This happens only if the program thinks the unfinished workspace still contains meaningful progress.

Examples of useful progress:
- answers were edited
- the helper already made some transitions
- the workspace is not clearly poisoned

Taskfile fresh-session retry budget:
- up to 1

### Fresh-worker replacement in taskfile mode

There is also a more drastic recovery option:

- throw away the damaged active worker state
- restore the original repo-authored assignment
- run a fresh worker against the reset workspace

This is used when the first worker looks catastrophically bad, such as:
- watchdog kill
- boundary failure
- retryable runner crash
- other "this worker cannot be trusted to continue safely" conditions

Fresh-worker replacement budget:
- up to 1

So, at a high level, taskfile mode usually has:

- 1 same-session repair rewrite
- up to 1 fresh-session retry
- up to 1 fresh-worker replacement

Those are different budgets serving different problems.

## Inline-JSON Mode: How It Works

In `inline-json` mode, there is no editable `task.json`.

Instead the repo sends a structured JSON packet directly to the model and expects a structured JSON reply back.

The cycle is:

1. Repo builds packet.
2. Model replies with JSON.
3. Repo validates the JSON.
4. If valid, it is promoted.
5. If invalid but repairable, the repo sends another packet describing what needs fixing.

So inline-json repair is:

- "send another structured follow-up call"

not:

- "rewrite `task.json` and continue editing a file"

### What inline-json repair usually looks like

The repo tries to preserve any good work it already got.

So a repair follow-up is usually narrower than the original prompt:
- it may include only unresolved rows
- it may include validation errors
- it may include accepted rows or previously validated answers as fixed context
- it asks only for the remaining broken part

That means inline-json repair is more packet-driven and incremental.

## Stage By Stage

## 1. Recipe Refine

`recipe refine` is currently `taskfile` only.

There is no inline-json recipe path right now.

### Recipe refine taskfile flow

The recipe stage works like this:

1. The repo builds a task file containing one or more recipe correction tasks.
2. The worker edits answer objects for those tasks.
3. The helper validates the edited answers.
4. If valid, the repo expands those answers into final per-task outputs.
5. If invalid, the helper may rewrite the task file into repair mode containing only the failed units.

### Recipe repair behavior

Recipe taskfile repair is focused and bounded:

- the failed recipe units are isolated
- previous answers are preserved as context
- validation feedback is attached
- the worker gets one repair pass

If the repair-mode file still fails validation:
- the run is marked `repair_exhausted`

So recipe does not keep looping on repair forever.

### Recipe recovery behavior

Separately from repair:

- recipe can do one fresh-session retry if useful progress exists but the session did not fully complete
- recipe can do one fresh-worker replacement if the original worker died in a catastrophic or retryable way

So recipe has:
- one same-session repair pass
- one possible fresh-session retry
- one possible fresh-worker replacement

## 2. Line-Role

Line-role supports both `taskfile` and `inline-json`.

It is also a little special because, in addition to repair, it has a watchdog retry path for certain kinds of worker stoppage.

That watchdog retry is a recovery path, not the normal answer-repair path.

### Line-role in taskfile mode

Taskfile line-role works much like recipe:

1. Repo writes a line-role task file.
2. Worker edits the answer rows.
3. Helper validates.
4. If valid, shard outputs are written.
5. If invalid in a repairable way, the helper rewrites the file into repair mode.
6. Worker gets one repair pass.
7. If that still fails, the run ends as repair exhausted / repair failed.

So the core taskfile repair rule is the same:
- one same-session repair rewrite

### Line-role taskfile recovery behavior

Line-role taskfile can also do:

- one fresh-session retry
- one fresh-worker replacement

And it has another special path:

- watchdog retry

This watchdog retry is used when the worker did not produce usable output because it got stopped for certain watchdog reasons. Instead of saying "the answer was invalid, repair it," the repo does a strict retry attempt targeted at finishing the shard.

So line-role taskfile has three distinct follow-up ideas:

1. normal same-session repair
2. fresh-session or fresh-worker recovery
3. watchdog retry after certain kill reasons

### Line-role in inline-json mode

This is much thinner.

The flow is:

1. Send one initial packet for the shard.
2. Validate the reply.
3. If the reply is invalid in a repairable structural way, figure out which rows were already accepted and which rows are unresolved.
4. Build a repair packet containing only the unresolved rows.
5. Reuse the same structured session and send one repair follow-up.
6. Merge accepted rows from the first attempt with any newly accepted rows from the repair attempt.
7. If all rows are now covered, the shard is valid.
8. If not, the shard fails.

This is important:

- line-role inline-json keeps accepted rows from the initial response
- it only re-asks for the unresolved rows
- it gets at most one repair follow-up

So line-role inline-json is:
- initial packet
- at most 1 repair packet

### Line-role inline-json recovery behavior

Inline-json line-role also has a watchdog retry path for some "worker got killed before it finished" cases.

That path is not the same as repair.

Repair means:
- the answer came back, but validation failed

Watchdog retry means:
- the worker got stopped before giving a usable answer

So line-role inline-json can have:
- one repair follow-up for invalid output
- and, in some cases, a watchdog retry for missing output due to watchdog failure

## 3. Knowledge / Nonrecipe Finalize

Knowledge is the most complex of the three stages.

That is because it is really a two-step semantic workflow:

1. classification
   Decide whether each kept block is `knowledge` or `other`

2. grouping
   For the blocks that were kept as knowledge, group related ideas together

So knowledge does more than one kind of LLM decision, and that means its repair flow has more branches.

## Knowledge in taskfile mode

Taskfile knowledge starts with classification.

### Classification step

1. Repo writes a classification task file.
2. Worker answers category plus grounding.
3. Helper validates.
4. If classification is valid and everything is `other`, the stage may complete without grouping.
5. If classification is valid and some rows are `knowledge`, the helper advances the task file into grouping mode.
6. If classification is invalid in a repairable way, the helper rewrites the file into repair mode.

So classification can get:
- one same-session repair rewrite

### Grouping step

If classification keeps some knowledge rows, the repo does not always group everything in one giant batch.

Instead it can split grouping into deterministic batches.

For each grouping batch:

1. Repo writes the grouping version of the task file.
2. Worker fills in grouping answers.
3. Helper validates.
4. If valid, the workflow either:
   - advances to the next grouping batch
   - or completes and writes final outputs
5. If invalid in a repairable way, the helper rewrites that grouping task into repair mode.

So each grouping batch can also get:
- one same-session repair rewrite

That means knowledge taskfile mode is not just "one repair total."
It is more like:

- classification gets one repair chance
- each grouping batch gets one repair chance

### Knowledge taskfile completion behavior

If everything succeeds:
- final shard outputs are written
- the same-session state is marked completed

If repair mode fails on a second pass:
- that branch becomes `repair_exhausted`

### Knowledge taskfile recovery behavior

Knowledge taskfile also has the same two recovery families:

- one fresh-session retry
- one fresh-worker replacement

So far, that sounds similar to recipe and line-role.

But knowledge has one extra wrinkle.

### Extra post-taskfile repair for knowledge

After the taskfile workflow is done, the runtime still looks at the final shard output.

If a final output file exists but is still invalid for promotion, the runtime can do one extra packet-style repair attempt on that shard.

This is a different repair layer from the same-session taskfile rewrite.

So for knowledge taskfile mode, there are really two repair surfaces:

1. same-session taskfile repair during classification/grouping
2. one later packet-style repair attempt if the final shard output still fails validation

That is why knowledge feels more complicated than recipe and line-role.

## Knowledge in inline-json mode

Knowledge inline-json is the most iterative of all the inline-json paths.

Instead of editing task files, it runs a structured session made of packets.

### Classification in inline-json mode

The flow is:

1. Build classification packet.
2. Send initial classification call.
3. Parse and validate the response.
4. Keep any answers that already validate.
5. If some units failed, build a repair packet containing only the failed units plus validation feedback.
6. Send another repair follow-up.
7. Merge newly validated answers with the already accepted answers.
8. Revalidate the full reconstructed answer set.

This can repeat up to 3 repair follow-ups.

So classification inline-json budget is:
- 1 initial call
- up to 3 repair follow-ups

The important part is that it is cumulative:
- the repo does not throw away already good units
- it keeps the valid answers and only re-asks for the failed units

### Grouping in inline-json mode

Grouping uses the same general idea, but per grouping batch.

For each grouping batch:

1. Build grouping packet.
2. Send initial grouping call.
3. Validate.
4. If needed, build a repair packet only for the failed grouping units.
5. Retry.
6. Merge accepted answers.
7. Repeat up to the repair cap.

Grouping inline-json budget per batch is:
- 1 initial call
- up to 3 repair follow-ups

So knowledge inline-json is far more iterative than line-role inline-json.

### Why knowledge inline-json gets more repair attempts

In plain language:

- line-role is a smaller, tighter classification surface, so the repair strategy is stingier
- knowledge has more structure and more ways to be partially right, so the runtime keeps salvaging valid pieces and re-asking for only the broken parts

That is why knowledge inline-json allows several bounded follow-ups instead of just one.

## What Counts As "Repairable"

At a high level, the repo tries to repair when the model did something close enough to useful that a focused correction seems worth it.

Examples of the kinds of things that can trigger repair:
- malformed JSON shape
- missing required rows
- invalid labels or grouping fields
- incomplete coverage
- structurally bad output that still looks like a near miss rather than total nonsense

In contrast, recovery paths are used when the issue is not "bad answer shape" but "the worker session itself did not finish correctly."

Examples:
- watchdog kill
- forbidden command behavior
- worker stopped without durable output
- runner exception

So a useful mental model is:

- repair is about fixing the answer
- recovery is about salvaging or restarting the worker session

## Comparison Table

| Stage | Transport | Main repair style | Normal repair budget | Other recovery budget | Notes |
| --- | --- | --- | --- | --- | --- |
| Recipe refine | Taskfile | Rewrite `task.json` into repair mode | 1 same-session repair rewrite | Up to 1 fresh-session retry, up to 1 fresh-worker replacement | No inline-json path right now |
| Line-role | Taskfile | Rewrite `task.json` into repair mode | 1 same-session repair rewrite | Up to 1 fresh-session retry, up to 1 fresh-worker replacement, plus watchdog retry in some cases | Watchdog retry is recovery, not normal repair |
| Line-role | Inline-json | Send a repair packet for unresolved rows | 1 repair follow-up packet | Watchdog retry in some missing-output cases | Keeps accepted rows from the first attempt |
| Knowledge | Taskfile | Rewrite task file into repair mode during classification/grouping | 1 repair rewrite for classification, and 1 repair rewrite per grouping batch | Up to 1 fresh-session retry, up to 1 fresh-worker replacement | Also has one extra packet-style repair attempt later if final shard output still fails validation |
| Knowledge | Inline-json | Send structured repair follow-up packets | Up to 3 repair follow-ups for classification, and up to 3 per grouping batch | Structured session resume within the same shard session | Keeps validated answers and only re-asks for failed units |
| Recipe refine | Inline-json | Not supported | None | None | No inline-json recipe path yet |

## Short Practical Summary

If you want the shortest honest version:

- `recipe refine` is the simplest: taskfile, one repair pass, plus possible session restart/replacement recovery.
- `line-role` is split: taskfile gets one repair pass, inline-json gets one repair follow-up packet.
- `knowledge` is the most layered: classification and grouping are separate, taskfile can repair each step once, and inline-json can do up to 3 repair follow-ups per step or batch.
- Taskfile stages and inline-json stages both have bounded behavior. None of them are meant to loop forever.
- The program is generally trying to salvage partial good work when it can, but it puts a hard ceiling on how much fixing it will attempt before failing closed.

## Best Mental Model

The easiest way to think about the whole system is:

- `taskfile` mode repairs by rewriting the assignment file and asking the worker to fix named bad parts.
- `inline-json` mode repairs by sending another smaller structured packet.
- `recipe` is the narrowest and most conservative.
- `line-role` is still conservative, but has one packet-repair path and a separate watchdog-retry path.
- `knowledge` is the most elaborate because it has two semantic stages and is built to preserve partially valid work across several bounded follow-ups.


# thoughts from ChatGPT pro
I read [repair-analysis.md](sandbox:/mnt/data/repair-analysis.md) and [AI_context.md](sandbox:/mnt/data/AI_context.md).

My honest take: this is **not** spaghetti in the bad sense. It already has a real architecture. The good bones are clear: you separate **repair** from **recovery**, you keep retries bounded, you try to salvage accepted work instead of nuking everything, and deterministic validation/promotion remains the authority surface. That is a sane foundation, especially for a system where accepted structured LLM output becomes live stage truth after validation.  

What feels messy is something narrower: the retry policy is expressed as **stage-specific case law** instead of one explicit decision model. Recipe is conservative, line-role has taskfile and inline-json variants plus watchdog behavior, and knowledge has the most layered behavior with classification/grouping, per-step repair, and extra packet-style repair after taskfile completion. All of those choices are individually defensible, but together they make the system harder to reason about and tune for token efficiency. 

The biggest missing concept is this:

**you have “same agent + partial repair” and “fresh agent + full retry,” but you do not seem to have “fresh agent + partial repair” as a first-class, universal mode.**

That missing quadrant is exactly what you want when:

* the broken part is localizable,
* the existing agent is probably poisoned or anchored wrong,
* and redoing the whole task would waste tokens.

That is the main unification I would add.

## My verdict in one sentence

Your current design is **thoughtful but over-specialized**. The next step is not “rewrite everything”; it is to make every stage choose from the same small set of retry actions, using stage-specific profiles.

## The model I would unify around

Think of every “try again” decision as answering two questions:

1. **How much needs to be redone?**

   * only the broken units
   * or the whole task/batch

2. **Should the same agent keep going?**

   * yes, keep its context
   * or no, start fresh

That gives you four semantic actions:

```text
                     Same agent                 Fresh agent
Broken part only     partial repair             partial repair   <- add this
Whole task/batch     full rethink (rare)        full retry/reset
```

And then keep **resume existing workspace** as a separate recovery action for infra failures only.

Right now your system strongly supports:

* same-agent partial repair
* fresh-agent full retry/reset
* some workspace resume/recovery

The missing, high-value primitive is:

* **fresh-agent partial repair**

## Why that matters for your goals

Your goals are:

* best quality
* lowest token cost
* avoid unnecessary rework
* keep same-agent context only when it is genuinely helpful
* abandon poisoned paths quickly

The cheapest successful repair is usually:

1. **same-agent partial repair**, when the problem is local and the agent just needs a precise correction.
2. **fresh-agent partial repair**, when the problem is local but the agent is anchored wrong.
3. **fresh-agent full retry**, when the whole thing is compromised.

What you want to avoid is the hidden money pit:

* repeated same-agent patching after the agent has already shown it does not understand the failure.

That is where token burn climbs without much quality gain.

## The decision rule I would use

For every failed attempt, compute four things:

1. **Failure type**

   * no durable output / crash / watchdog / boundary failure
   * invalid but usable output
   * partial output with localized defects
   * globally incoherent output

2. **Locality**

   * can the validator name the exact broken units?
   * or is the failure global and entangled?

3. **Context carry value**

   * did the agent build a lot of understanding that would be expensive to recreate?
   * or can the needed context be cheaply repackaged for a new agent?

4. **Poison risk**

   * repeated same error after explicit feedback
   * new weird mistakes on repair
   * touching already-good units
   * stubborn contract violations
   * evidence it misunderstood the task, not just the format

Then choose the next action like this:

* **Infra failure, no meaningful answer yet**
  Use recovery, not repair. Resume the current workspace only if progress exists and the workspace is still trustworthy. Otherwise reset to a clean snapshot.

* **Localized defect, low poison, high carry value**
  Use same-agent partial repair.

* **Localized defect, medium/high poison**
  Use fresh-agent partial repair.

* **Global defect or nonlocal entanglement**
  Use full retry, usually fresh-agent.

* **Same-agent full repair**
  Keep this as a rare escape hatch, not a default. In practice it is often the worst of both worlds.

## The strongest unifying rule

**Freeze accepted units aggressively.**

Your architecture already treats validated outputs as authoritative once promoted, rather than advisory overlays. That means accepted rows/units should become read-only as early as possible, and every retry should focus only on unresolved units unless there is a real dependency reason to reopen more scope. 

This is the most important cost-control lever in the whole system.

## What I would change structurally

I would create one transport-agnostic retry layer with three objects:

```text
FailureAnalysis
- failure_type
- localizable_units
- poison_signals
- progress_so_far
- context_cost_estimate

RepairPlan
- scope: broken_units_only | whole_batch
- session_mode: same_agent | fresh_agent | resume_workspace
- state_source: current_workspace | clean_repair_snapshot | original_assignment
- frozen_accepted_units
- unresolved_units
- validator_feedback_bundle

AttemptOutcome
- accepted_units_before/after
- unresolved_units_before/after
- tokens_in/out
- error_fingerprint
- progress_delta
```

Then:

* taskfile becomes one renderer/executor of a `RepairPlan`
* inline-json becomes another renderer/executor of the same `RepairPlan`

That is the real unification. Not “everything must use the same transport,” but “everything uses the same retry semantics.”

## What I would *not* do first

I would **not** start by forcing recipe refine into inline-json just for symmetry. Recipe being taskfile-only is not the main problem. The main problem is policy fragmentation, not transport asymmetry. 

## Stage-by-stage defaults I’d recommend

### Line-role

This is the easiest place to be aggressive with delta repair. The units are small, stable, and highly localizable. Accepted rows are already preserved in inline-json mode.  

Default ladder:

* initial attempt
* one same-agent partial repair
* if same error pattern repeats, switch to fresh-agent partial repair
* full retry only if the shard is broadly bad

So for line-role, I would prefer:
**repair small, repair fresh quickly if anchored wrong.**

### Recipe refine

Recipe tasks have higher context value and more coupling inside a recipe. Same-agent context is worth more here than in line-role, because the model may already understand the recipe structure and subtleties. But if it keeps making the same class of semantic mistake, do not make it patch forever. Recipe is where same-agent repair makes the most sense first, but it should still escalate cleanly.  

Default ladder:

* initial attempt
* one same-agent partial repair at recipe-task scope
* then fresh-agent partial repair at recipe-task scope if poisoned
* full fresh retry only when the recipe task is globally misconceived

### Knowledge classification

This is highly salvageable because the units are more independent. Multiple repairs can make sense **only if the unresolved set is shrinking materially**. Your current up-to-3 inline-json follow-ups are reasonable as a local rule, but I would make them progress-gated rather than fixed by folklore. 

Rule:

* keep going only if each repair meaningfully reduces unresolved units
* if the error fingerprint repeats with little shrinkage, switch to fresh-agent partial repair

### Knowledge grouping

This is more coupled than classification. If grouping is wrong, repeated patching can create brittle, inconsistent group structure. I would treat the **grouping batch** as the atomic repair unit. That means:

* one repair pass is fine
* after that, restart the batch fresh rather than endlessly patching partial group structure

This is where I would be stricter than the current “up to 3 follow-ups” instinct.

## The one new primitive I’d add

If I could only add one thing, it would be:

**Fresh-agent delta repair**

Mechanically, it looks like this:

* repo creates a clean narrowed task for only failed units
* accepted units are frozen and passed as read-only context
* minimal evidence windows are included
* validator feedback is condensed
* new agent fixes only the unresolved part

That gives you:

* lower token cost than full restart
* less anchoring than same-session repair
* less regression risk because accepted units are locked

It is the missing bridge between “fix it here” and “start over.”

## How to detect “poisoned” without vibes

You do not need perfect detection. You just need deterministic enough triggers.

I would switch away from the current agent when any of these happen:

* same validation fingerprint twice in a row
* no meaningful reduction in unresolved units
* new error categories appear after precise feedback
* the agent modifies frozen/previously accepted material
* repeated contract violations after the validator explicitly named them

That is enough to make fresh-agent partial repair principled instead of fuzzy.

## How to stop wasting tokens

Do not make retry counts the main knob. Make **repair yield** the main knob.

Track:

* newly accepted units per attempt
* unresolved units removed per attempt
* tokens spent per newly accepted unit
* repeated error fingerprints

Then use a simple stop rule:

* if the last repair did not produce meaningful progress, escalate or stop

You already have analytics and token-tracking surfaces in the broader architecture, so this can plug into your existing observability rather than becoming another hidden subsystem. 

## What I think is actually “messy” today

Not the existence of different budgets. That part is fine.

The messy part is that the following concepts are not first-class and universal:

* repair scope
* session freshness
* poison detection
* progress-based escalation
* frozen accepted set
* clean starting snapshot

Because those are not modeled centrally, they show up as:

* knowledge-only extra repair layers
* transport-specific semantics
* stage-by-stage exceptions
* hardcoded counts that are hard to compare

That is what makes it feel spaghetti-adjacent.

## The refactor order I’d recommend

1. **Add a common FailureAnalysis / RepairPlan layer.**
2. **Implement fresh-agent partial repair.**
3. **Move knowledge’s extra packet-style repair into that generic action instead of leaving it as a knowledge-specific oddity.**
4. **Make “up to 3 repairs” progress-gated rather than purely fixed-count.**
5. **Only after that, consider transport changes like recipe inline-json.**


