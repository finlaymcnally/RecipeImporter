---
summary: "LLM architecture/build/fix-attempt log used to avoid repeating failed paths."
read_when:
  - When you are going in multi-turn circles on LLM behavior or implementation
  - When the human says "we are going in circles on this"
  - When you need prior architecture versions, builds, or fix attempts before trying another change
---

# LLM Build and Fix Log

Use this file for LLM debugging history that still applies to the current codebase. Retired rollout notes, removed UI paths, and old gating experiments were intentionally pruned.
Entries are dated snapshots. When a later cutover supersedes an older worker surface, older file names and loops are kept here as historical evidence, not as current contract guidance.

## 2026-03-22 workspace-worker paved-road contract converged across recipe, line-role, and knowledge

Historical note:
- this entry predates the later packet-first recipe/knowledge cutovers, so `current_task.json` here is historical evidence for the then-live surface rather than current guidance

Problem captured:
- the first worker-runtime cutover fixed the big transport problems, but the day-to-day worker contract still had too many sharp edges:
  - recipe main workers could still speak legacy verbose keys
  - final assistant messages were easy to misread as authority
  - helpers existed, but the default loop still spent too many subprocess turns
  - watchdog behavior was still being reasoned about in shell-shape terms instead of clear workspace boundaries

Durable decisions:
- main workspace-worker success is file-authoritative:
  - validated `workers/*/out/*.json` files win
  - prose or absent final chat messages are telemetry only
- the shared worker contract starts from repo-written local files, not broad queue spelunking:
  - `worker_manifest.json`
  - `current_task.json`
  - named `hints/*.md`
  - named `in/*.json`
  - mirrored `tools/`
  - `OUTPUT_CONTRACT.md`
  - `examples/`
- boundary-based watchdog policy is the stable main-worker rule:
  - tolerate bounded local shell work
  - tolerate temp roots such as `/tmp`
  - tolerate surfacing the assigned execution root itself
  - keep structured retry/repair on the stricter one-shot policy
- recipe rejects legacy verbose output keys on the live seam, and the cheap helper path for recipe/line-role is now batch `prepare* -> edit -> finalize*` rather than repeated `scaffold -> check -> install`

Evidence worth keeping:
- the March 21 and March 22 Salt Fat runs showed the exact progression:
  - wrong contract or stale final-message assumptions wasted spend
  - repo-owned helper/tool surfaces removed brittle shell improvisation
  - broader boundary-based watchdog rules then kept those helper paths alive without deleting repo-owned validation

Anti-loop note:
- if a future fix proposal starts from final assistant message formatting, stale verbose keys, or prompt wording alone, re-check the worker file/manifest/helper contract first

## 2026-03-22 recipe workspace-worker cost cuts only stuck after the repo prewrote more trustworthy state

Historical note:
- this entry captures the pre-packet recipe runtime that was later removed on 2026-03-30; `SHARD_PACKET.md`, prepared drafts, and current-task sidecars here are retained as rollout evidence only

Problem captured:
- removing the false-positive startup kill was necessary but not sufficient: recipe runs were reliable again, yet workers still spent too many session turns rereading manifests, contracts, examples, helper source, hints, and raw inputs before editing the prepared drafts
- early whole-shard deaths were also recovering through one follow-up per task even when the worker had produced nothing usable yet

Durable decisions:
- recipe startup/watchdog classification has to understand the real sterile execution root under `~/.codex-recipe/...`, not only the mirrored source worker root
- early whole-shard deaths recover through one shard-packed retry; mixed-output failures still recover per task
- at that point, the repo prewrote the state workers were repeatedly rediscovering:
  - `SHARD_PACKET.md`
  - `scratch/<task_id>.json`
  - `scratch/_prepared_drafts.json`
  - `CURRENT_TASK.md`
  - `CURRENT_TASK_FEEDBACK.md`
- at that point, the cheap recipe path was "read `SHARD_PACKET.md`, trust the prepared drafts, edit them, then `finalize-all`"; contract/example/tool-source reads were fallback-only
- the current-task helper loop was still real and useful, but it had become a recovery/debug seam:
  - `check-current` writes repo-readable validation feedback
  - `install-current` advances `current_task.json` plus `CURRENT_TASK*.md`
  - prepared-draft metadata refreshes after accepted installs
- the resulting recipe telemetry separated two waste families:
  - `recipe_contract_lookup_command`
  - `recipe_task_bundle_read_command`

Evidence worth keeping:
- the March 22 sequence mattered because it showed three distinct states in order:
  - a false-positive startup kill under the sterile execution root
  - a reliable but still chatty batch flow at `47` commands and high session-token overhead
  - the later shard-packet/current-task flow that finally made the low-readback path explicit in repo-owned files

Anti-loop note:
- if recipe token spend rises again, inspect readback loops and repo-written worker surfaces first; do not jump straight to more prompt prose or another watchdog rollback

## 2026-03-22 main workspace-worker watchdog rollback converged on executable-only enforcement

Problem captured:
- the first March 22 false-kill fix was too narrow: relaxing one knowledge-stage override did not remove the shared detector paths that were still killing workers for absolute paths, heredoc parseability, slash-heavy helper payloads, and other ordinary local shell shapes

Durable decisions:
- main `workspace_worker` sessions now die on command policy only for explicit off-contract executables plus the separate liveness guards
- path- and shell-shape heuristics are telemetry only on the main worker path:
  - absolute paths
  - parent-traversal-looking strings
  - heredocs
  - `jq //`
  - bounded inline Python helpers
  - read-only `git` inspection
- structured retry/repair attempts stay on the stricter one-shot policy; the rollback applies to the main long-lived worker path only
- the right debugging split is now:
  - `classify_workspace_worker_command(...)` for reviewer-facing telemetry
  - `detect_workspace_worker_boundary_violation(...)` for the actual kill/no-kill seam

Evidence worth keeping:
- the false-kill run family recorded `forbidden_absolute_path` and `forbidden_unparseable_python_heredoc`, which proved the problem was shared detector policy rather than a stage-local helper bug
- the narrow knowledge-only rollback was a real failed path worth remembering: it removed one override but did not touch the shared enforcement seam that still killed workers

Anti-loop note:
- if false kills return, inspect the forbidden executable list and live reason codes before reintroducing path policing or helper-specific exceptions

## 2026-03-22 knowledge runtime moved from “helper available” to true single-task authority plus snippet-copy recovery

Historical note:
- this entry captures the pre-packet knowledge current-task surface that was later replaced by packet leasing and shard-owned packet state; current-task sidecars here are retained as then-live evidence only

Problem captured:
- knowledge workers still had two expensive failure families after the initial runtime cutover:
  - they could behave like local queue schedulers instead of one-task-at-a-time workers
  - snippet-copy outputs could go straight from “worker wrote a file” to poisoned-worker skip without a narrow repair chance

Durable decisions:
- at that point, the repo owned the live knowledge loop one task at a time:
  - skinny `assigned_tasks.json`
  - authoritative `current_task.json`
  - `CURRENT_TASK.md`
  - `CURRENT_TASK_FEEDBACK.md`
  - repo advancement only after validation
- the current-task bundle must stay authoritative in both places the runtime uses:
  - the durable worker root
  - the sterile execution workspace after each validation callback
- `assigned_tasks.json` stays a queue/progress surface, not the worker's primary source of truth for "what do I do now?"
- prompt, sidecars, helper stdout, and the generated helper script all have to frame `install-current` as a reopen-and-continue handoff rather than a stopping point
- clean mid-queue exits after visible queue advancement are deterministic runtime failures, not acceptable conversational pauses; the repo now auto-resumes the remaining queue up to a small cap and persists that rescue history
- worker-local `check` / `install` and orchestrator recovery now reuse the same validation classification instead of drifting
- snippet-copy-only failures are their own near-miss family:
  - full-chunk echoes
  - copied evidence-quote snippets
- those snippet-copy-only failures now get one narrow `inline_snippet_repair` before the broad repair ladder or poisoned-worker skip logic can win
- worker poisoning still exists, but it is for repeated broader low-trust, boundary, or zero-output behavior rather than the first repairable snippet-copy miss

Evidence worth keeping:
- the March 22 benchmark evidence mattered because it showed all three failure families mechanically:
  - queue scripting was still happening
  - one run advanced `live_status.json` to task 2 while the worker-visible current-task sidecars stayed on task 1 until source-to-execution mirroring was fixed
  - later runs advanced the sidecars correctly but still ended with "If you want, I can continue..." mid-queue
- the same task family also showed why helper/sidecar wording must be shared: patching prose in one renderer but not in the generated helper script immediately reintroduced drift between `CURRENT_TASK_FEEDBACK.md` and `install-current` output

Anti-loop note:
- if knowledge workers stop after one or a few valid tasks, do not restore queue spelunking or accept a permission-seeking final message as success; inspect current-task authority/sync first, then the capped auto-resume seam
- if snippet-copy failures return, do not weaken the validator and do not skip straight to poisoned-worker logic; inspect the shared failure classifier and the narrow repair rung first

## 2026-03-22 recipe workspace spend only stabilized once the repo restored batch finalize as the default loop and failed closed on empty mappings

Historical note:
- this entry describes the older draft-sidecar recipe runtime that was later superseded by the packet-first recipe cutover on 2026-03-30

Problem captured:
- the first recipe workspace refactor improved trust surfaces, but it accidentally turned `check-current` / `install-current` into the default loop
- that created a control-flow regression:
  - repeated sidecar rereads
  - repeated per-task helper turns
  - command count and session-token overhead far above the earlier shard-packet path
- one more compact-contract gap also stayed too permissive: a repaired recipe could still look "non-empty" while carrying an empty mapping with no reason

Durable decisions:
- keep the good repo-owned trust surfaces:
  - `SHARD_PACKET.md`
  - prewritten `scratch/<task_id>.json`
  - `scratch/_prepared_drafts.json`
  - current-task sidecars
- restore the cheap default loop for healthy recipe shards:
  - read `SHARD_PACKET.md`
  - trust the prepared drafts
  - edit drafts directly
  - run one `finalize-all scratch/` at the end
- keep `check-current` / `install-current` as recovery/debug tools only, not the normal happy path
- recipe empty mappings now fail closed when the canonical recipe clearly has real structure:
  - if there are 2+ non-empty ingredients or 2+ non-empty steps, empty `m` requires a non-empty `mr` reason such as `unclear_alignment`
  - otherwise the prepared draft should fall back to `fragmentary` instead of pretending success

Evidence worth keeping:
- the March 22 regression was mechanical, not subjective:
  - command-execution count jumped from `47` to `113`
  - command-execution tokens jumped from about `536k` to about `1.33M`
  - correctness counters still stayed healthy, which proved the regression was the worker loop, not recipe validity

Anti-loop note:
- if recipe spend rises again, inspect whether worker-facing docs have drifted back toward per-task helper churn or permissive empty-map acceptance before changing prompts, validators, or watchdog policy

## 2026-03-22 line-role and knowledge spend reporting had to fail closed on missing usage instead of publishing fake zeroes

Problem captured:
- workspace-worker runs could complete useful work without a normal JSON `turn.completed` usage payload, which made downstream summaries liable to publish zero-spend lies or silently undercount line-role cost
- the missing-usage cases were especially confusing because the worker often had valid `out/*.json` files and only the accounting path was incomplete

Durable decisions:
- runtime summaries now report explicit token-accounting state:
  - `token_usage_status=partial|unavailable`
  - billed-token totals stay blank when real usage is missing
- the shared direct runner now parses the Codex CLI plain-text `Token usage: ...` footer as a recovery seam when JSON usage is absent
- completed workspace sessions now wait briefly before teardown so late usage events can still populate normal `workers/*/usage.json`
- keep raw `stdout.txt` / `stderr.txt` sidecars and per-worker telemetry so missing-usage sessions remain inspectable instead of silently normalized

Evidence worth keeping:
- the failure mode was not hypothetical: line-role benchmark accounting could lose usage while the worker still produced valid outputs, which would have made prompt-budget summaries and history backfill under-report the real spend

Anti-loop note:
- if token accounting regresses again, do not coerce missing usage to zero just to keep dashboards full; inspect footer parsing, late-event timing, and worker sidecars first

## 2026-03-22 to 2026-03-23 knowledge runtime simplified around batch-local authority, single-chunk tasks, and utility-first judgment

Problem captured:
- the knowledge stage had accumulated three different sources of waste and confusion:
  - current-task loops that encouraged extra turns instead of cheap repo-owned continuation
  - a multi-chunk packet layer on top of deterministic chunking
  - a semantic bar that still sounded too much like "cooking-adjacent and true" instead of "durable cooking leverage"

Durable decisions:
- batch-local repo-owned authority is the cheap path:
  - `CURRENT_BATCH.md` and `CURRENT_BATCH_FEEDBACK.md` are the first reads
  - `current_batch.json` is machine-readable batch-local metadata only
  - `assigned_tasks.json` stays fallback/debug inventory, not the happy-path authority
- each deterministic knowledge chunk now becomes one shard and one task:
  - no second semantic packet layer
  - compatibility-only shard-sizing knobs now warn instead of rebundling
- the public semantic taxonomy remains binary `knowledge|other`, but the decision boundary is now utility-first and explicitly fail-closed on marginal value
- accepted outputs must explain that utility judgment with compact reason codes, while richer `utility_profile` cues remain worker-local hints only
- strong negative utility plus no positive cue can bypass the model entirely as validated repo-owned `other`, but only through the narrow no-LLM fast path

Evidence worth keeping:
- the March 22 Salt Fat failures showed why this had to change:
  - mixed memoir/book-framing packets could ride along with one useful sentence
  - strong-cue scaffolds could masquerade as accepted reviewed-empty work
  - current-task wording could still spend extra turns even after validation and queue advancement worked

Anti-loop note:
- if knowledge quality or spend regresses, do not restore semantic packet bundling or broaden the positive class back to generic factuality first; check batch-local authority, one-chunk task truth, and the utility-boundary reason codes

## 2026-03-21 shared stage-progress contract and summary parity

Problem captured:
- recipe, line-role, and knowledge were telling different truths in the live UI and post-run artifacts: recipe encoded repo finalization as fake worker labels, line-role still counted parent shards instead of task packets, and only knowledge had a compact stage-local summary

Durable decisions:
- shared `stage_progress` now carries typed work-unit, worker-session, follow-up, artifact-count, and last-activity fields without breaking older payload readers
- recipe and line-role now write compact stage-local summaries (`recipe_stage_summary.json`, `line_role_stage_summary.json`) and `stage_observability.json` indexes those beside `knowledge_stage_summary.json`
- prompt-budget summaries, benchmark timeseries rows, and the live CLI should all prefer that shared typed vocabulary instead of reverse-engineering core state from `detail_lines` or ad hoc worker labels

Evidence worth keeping:
- the motivating regression was operational, not theoretical: a packet-working run could still render like `task 0/10 | running 10`, and recipe could still look like workers were active when only repo-side finalization remained

Anti-loop note:
- if a future progress fix proposal depends on parsing `active_tasks` strings again, the emitter is probably missing typed shared fields rather than the renderer needing more special cases

## 2026-03-20 knowledge runtime rebuild around packets, replay, and bounded recovery

Problem captured:
- the March 20 knowledge runs mixed real packet progress with shard-based UI, malformed/empty outputs, retry storms, worker drift, stale follow-up work, and missing stage-level explanations after interruption

Durable decisions:
- the packet ledger and replay helper are now the no-token oracle for this stage:
  - `cookimport/llm/knowledge_runtime_state.py`
  - `cookimport/llm/knowledge_runtime_replay.py`
- knowledge workers now run on repo-driven packet leasing (`current_packet.json`, `current_hint.md`, `current_result_path.txt`, `packet_lease_status.json`, `scratch/`) instead of free-form batch ownership over the whole task list
- workers own semantic packet judgments only; repo code serializes the canonical compact bundle payload after acceptance
- knowledge retry/repair prompts explicitly restate the compact row keys and strict retries are bounded by both hard subprocess timeouts and silence timeouts
- main knowledge workers should stop once owned outputs stabilize; post-write self-auditing is now a bug, not a clever extra safety step
- validate immediately, salvage only narrow mechanical noise, detect poisoned workers early, and bound retry/repair work with explicit budgets plus skip/supersede reasons
- interrupted runs now write `stage_status.json`, normalize missing finalization artifacts as `skipped_due_to_interrupt` when appropriate, and keep `knowledge_stage_summary.json` as the canonical machine-readable operator summary

Evidence worth keeping:
- the saved March 20 Salt Fat bundle was important because it proved the failure family mechanically: hundreds of packet artifacts existed while the operator-facing surface still looked shard-frozen, and stale follow-up directories survived after parent work was effectively terminal

Anti-loop note:
- do not reintroduce monolithic shard retry or let child follow-ups outlive packet truth; once packet state, worker ownership, and accepted output are repo-owned, recovery must stay subordinate to that state

## 2026-03-19 direct-exec hardening, long-lived workers, and authority cleanup

Problem captured:
- direct `codex exec` on sterile workspaces could fail immediately on trust checks, bad shards could still burn time/tokens before the repo reacted, and one-shot shard answers plus vague worker contracts kept recipe, knowledge, and line-role too brittle

Durable decisions:
- the shared runner always passes `--skip-git-repo-check`; sterile workspaces remain the right repo-visibility boundary, but the runner must acknowledge that they live outside the trusted git root
- live runner supervision is now real: stream events, quarantine malformed payloads before spend, preserve `reason_code` / `reason_detail`, and persist `workspace_manifest.json` so shard-local provenance survives
- recipe gained parity with the strict JSON stages on near-miss repair and on propagated status fields such as `preflight_rejected`, `watchdog_killed`, and repair/live-status metadata
- at this point in the rollout, main attempts across recipe, knowledge, and line-role had moved onto long-lived workspace-worker sessions with explicit `worker_manifest.json`, task/phase sidecars, `hints/*.md`, and per-task `out/*.json`; later cutovers replaced recipe and knowledge task-sidecar control files with packet-first surfaces while line-role stayed phase-first
- prompt/authority lessons from the March 19 line-role failures still apply after the worker cutover: wrapper/example JSON is not authority, stored task files are
- workspace-worker startup must name local files directly, and watchdog diagnostics must preserve the exact offending command text in `reason_detail`
- main workspace-worker watchdog policy is now intentionally boundary-based for local shell work, while structured retry/repair calls remain strict one-shot JSON paths
- worker-facing hint sidecars are first-class now, and recipe defaulted to one candidate-owned task/shard so boundary repair, tagging, and validation stay grounded in local context
- knowledge shard counts now honor the operator-selected target literally, recording warnings instead of silently widening shard count; semantically empty blanket-`u:false` knowledge outputs are seed-kept but reported as unreviewed/semantically rejected, not as reviewed-empty success

Evidence worth keeping:
- the first March 19 Salt Fat Acid Heat benchmark after the worker cutover killed all five main line-role workers for trivial `ls` / `pwd` orientation reflexes; fixing the startup contract and then replacing shell-shape policing with a boundary-based main-worker policy solved the right problem

Anti-loop note:
- if a future fix proposal tries to solve worker drift with prompt wording alone while the repo-owned authority surface is still ambiguous, fix the file/manifest contract first

## 2026-03-15 docs cleanup for current LLM surfaces

Problem captured:
- The section docs had accumulated stale rollout history that no longer matched the live CLI and prediction-run code.

Durable cleanup:
- Removed QualitySuite Codex-permutation notes because `bench quality-run` is deterministic-only now and rejects `--include-codex-farm`.
- Removed recipe-only prediction-run wording; `generate_pred_run_artifacts(...)` now plans or runs recipe Codex, knowledge-stage, line-role, and prelabel surfaces.
- Removed retired env-gate and old interactive-editor history that no longer explains current behavior.

Anti-loop note:
- If docs and CLI disagree, trust the current command boundary in `cookimport/cli.py` and `cookimport/labelstudio/ingest.py` before preserving more historical wording.

## 2026-03-16 prompt preview reconstruction and stage-key cutover

Problem captured:
- zero-token prompt preview needed to work on existing benchmark/stage roots even when no live Codex run assets were present
- prompt exports and sampled artifacts were still carrying pass-slot file/row naming in places where the runtime had already moved to semantic stage names
- prompt-budget review was hard to act on without one concrete audit of where the tokens were really going

Durable decisions:
- prompt preview reconstruction composes existing recipe job builders, knowledge job builders, and canonical line-role prompt builders rather than inventing a second preview-only prompt stack
- when `var/run_assets/<run_id>/` is absent, preview reconstruction should fall back to pipeline metadata from `llm_pipelines/`
- `prompt_budget_summary.json` and adjacent prompt-review surfaces should publish semantic `by_stage` / `knowledge` naming, not old slot-group or `fourth-stage` naming
- prompt artifact rows/files should key off semantic stage metadata only:
  - `stage_key`
  - `stage_label`
  - `stage_artifact_stem`
- the deleted all-method per-source scheduler branch was dead test coverage, not a live runtime contract

Evidence worth keeping:
- audited preview run totals came out to about `663k` input tokens on an `~86k` token book
- the first implemented cut bundle brought the same run down to about `461,865` live-like input tokens before the second cut bundle landed
- the lowest-risk savings in that run were:
  - drop recipe `draft_hint` (`~92k`)
  - trim knowledge context blocks to `2` per side (`~121k`)
  - skip noise-lane knowledge prompts (`~25k`)
  - trim line-role neighbor context outside recipe spans (`~27k` or more depending on aggressiveness)

Anti-loop note:
- if prompt preview work starts reintroducing `task1` / `task4` / `task5` names into new artifacts, the regression is in artifact naming, not the underlying prompt builders

## 2026-03-16 prompt-cut shared builder seam

Problem captured:
- it was tempting to implement prompt-volume reductions only in preview rendering, which would make token audits look better without changing live Codex cost

Durable decisions:
- recipe prompt body cuts should land in the shared serializer for `MergedRecipeRepairInput`, not only in `prompt_preview.py`
- knowledge prompt count cuts should land in `build_knowledge_jobs(...)`, because both live harvest and preview reconstruction consume that builder
- if `build_knowledge_jobs(...)` returns no work, `run_codex_farm_nonrecipe_knowledge_review(...)` must short-circuit before Codex invocation or empty-manifest writing
- the first low-risk cut bundle was intentionally conservative (`knowledge` context width `12 -> 4`, skip only `noise`, keep `draft_hint` optional but omit it when empty); the second bundle then took the next cheap cuts (`4 -> 2`, drop recipe hint provenance, blank outside-recipe line-role neighbors)

Anti-loop note:
- if preview token counts drop but live runs do not, the optimization probably landed in a preview-only seam

## 2026-03-16 knowledge bundle and low-noise prompt cut

Problem captured:
- the knowledge stage was writing one tiny Codex prompt per chunk, so wrapper overhead and repeated instructions dominated cost on large non-recipe books

Durable decisions:
- prompt-count cuts must stay in the live knowledge builder:
  - deterministic junk suppression belongs in `cookimport/parsing/chunks.py`
  - bundling belongs in `build_knowledge_jobs(...)`
- surviving chunks should be packed into local bundled jobs in block order instead of one-chunk-per-prompt, while table-heavy chunks stay isolated
- later low-risk trims tightened the shared defaults again: knowledge context `2 -> 0`, soft-gap packing across nearby spans, and pruning of tiny low-signal chunks without heading/highlight/table evidence

Evidence worth keeping:
- on the motivating `saltfatacidheatcutdown` preview:
  - knowledge prompts dropped `324 -> 91 -> 41 -> 40`
  - total estimated tokens dropped `~1,422,285 -> ~703,122 -> ~578,563 -> ~449,484`

Anti-loop note:
- if a prompt-cost fix proposal wants to change preview output without changing `build_knowledge_jobs(...)`, it is probably solving the wrong seam

## 2026-03-16 line-role transport compaction and batch widening

Problem captured:
- line-role prompt cost was inflated twice: transport wrapped saved prompt JSON back into another prompt, and the default batch shape repeated too much row-local structure

Durable decisions:
- the live line-role path now writes raw prompt text into CodexFarm instead of `{\"prompt\": ...}` envelopes
- compact line-role serialization belongs in the shared prompt builder and keeps the response schema stable:
  - batch-level label/reason legends
  - batch-level recipe-span metadata
  - compact row arrays
  - neighbor text only for rows that actually need escalation context
- shared batch defaults were widened in the live path (`40 -> 120 -> 240`) rather than only in preview reconstruction

Evidence worth keeping:
- on the same benchmark root, line-role prompts dropped `45 -> 15 -> 8`
- wrapper overhead fell from `970,123` chars to near-zero (`4,440` chars) after the raw-prompt transport fix
- line-role estimated total tokens fell from about `683k` to `~291k`, then to `~175k`

Anti-loop note:
- if line-role cost spikes again, inspect transport wrapping and per-row prompt shape before narrowing the output schema or blaming the scorer

## 2026-03-16 runner-owned Codex home default

Problem captured:
- RecipeImport CodexFarm subprocesses could silently fall back to the generic `~/.codex` home unless each caller remembered to override the environment manually

Durable decisions:
- `cookimport/llm/codex_farm_runner.py` is the one place that should inject the RecipeImport default Codex home
- RecipeImport-owned subprocesses now default to `~/.codex-recipe` via `CODEX_HOME` and `CODEX_FARM_CODEX_HOME_RECIPE`
- explicit per-call env overrides still win; the fix is a central default, not a hard lock

Anti-loop note:
- if a CodexFarm subprocess uses the wrong home again, fix the runner transport env injection instead of adding more CLI flags or shell-profile assumptions

## 2026-03-16 prompt preview tags boundary

Problem captured:
- inline tag projection was easy to misinterpret as a fourth previewable prompt family or a hidden token-cost increase

Durable decisions:
- `cf-debug preview-prompts` still reconstructs recipe, knowledge, and line-role prompts only
- embedding accepted tags into final drafts and JSON-LD is output projection work, not a separate prompt builder

Anti-loop note:
- if token accounting changes after a tags edit, prove the recipe prompt changed before blaming the tagging projection

## 2026-03-15 prompt artifact seams and Codex backend map

Problem captured:
- Prompt artifact export was too tightly coupled to the current raw CodexFarm folder layout, and some callers still acted as if the repo had mixed Codex backends.

Durable decisions:
- `prompts/full_prompt_log.jsonl` is the stable downstream prompt artifact.
- Keep discovery and rendering separate in `cookimport/llm/prompt_artifacts.py`:
  - `discover_codexfarm_prompt_run_descriptors(...)`
  - `render_prompt_artifacts_from_descriptors(...)`
  - `build_codex_farm_prompt_response_log(...)`
- The live Codex-backed surfaces are `recipe`, `line_role`, `knowledge`, and `prelabel`; recipe tags are part of the recipe surface rather than a separate Codex lane.
- `cookimport/llm/codex_exec.py` is fail-closed transition only.

Anti-loop note:
- If prompt artifact work requires renderer edits for every new raw layout, the bug is in discovery coupling, not rendering.

## 2026-03-14 merged-repair schema and trace boundary

Problem captured:
- The merged-repair path mixed together three separate failure classes: invalid structured-output schema rules, stale on-wire payload shape, and missing thinking traces that looked like exporter bugs.

Durable decisions:
- Use native nested objects for recipe payload fields on the wire.
- Keep `ingredient_step_mapping` as an array of mapping-entry objects on the wire, then normalize back into the repo's internal dict form.
- Bucket 1 fixed behavior owns first-stage hints, pass pipeline IDs, third-stage skip behavior, and retry attempt count; tests should not expect stale overrides to win.
- Missing thinking traces are usually upstream capture/classification gaps, not a markdown-rendering bug.

Anti-loop note:
- If a merged-repair run fails before useful output, inspect schema validity, fixed-behavior policy, and trace capture before rewriting prompt text.

## 2026-03-14 recipe pipeline versus knowledge-stage

Problem captured:
- `codex-farm-2stage-repair-v1` made it easy to conflate the recipe sub-pipeline with the whole Codex-backed workflow.

Durable decisions:
- `llm_recipe_pipeline` and `llm_knowledge_pipeline` are separate surfaces.
- Switching between `codex-farm-3pass-v1` and `codex-farm-2stage-repair-v1` changes only the recipe extraction path.
- Knowledge extraction remains its own later stage with the same `knowledge` artifact tree.

Anti-loop note:
- If a recipe pipeline rename seems to imply knowledge-stage moved or vanished, inspect `llm_knowledge_pipeline` wiring first.

## 2026-03-13 structural audits and new recipe-pipeline seams

Problem captured:
- Structural success/failure checks and prototype pipeline additions were easy to scatter across orchestrator code without updating the rest of the surface area.

Durable decisions:
- Keep shared structural success rules in `cookimport/llm/codex_farm_contracts.py`.
- Feed those rules from named transport/runtime audits rather than ad hoc orchestrator strings.
- Any new `llm_recipe_pipeline` must be wired through:
  - `RunSettings`
  - codex decision/approval logic
  - orchestrator planning/manifests
  - benchmark/debug expectations

Anti-loop note:
- If a new recipe pipeline works only after changing the orchestrator, assume the implementation is incomplete.

## 2026-03-06 safe defaults and human-owned Codex decision boundary

Problem captured:
- Generic CLI/helper flows could still drift into Codex-backed execution without one clear approval layer.

Durable decisions:
- Shared defaults are deterministic and safe/off.
- `cookimport/config/codex_decision.py` is the single decision and metadata layer for live Codex surfaces.
- `labelstudio-import --prelabel` is explicitly classified as its own Codex surface.
- Benchmark, stage, import, and interactive top-tier flows all rely on the same decision metadata contract.

Anti-loop note:
- If a run used Codex "mysteriously," inspect decision metadata before touching prompt or runner code.

## 2026-03-06 plan mode, compact defaults, and knowledge-stage benchmark enablement

Problem captured:
- Plan mode was initially too shallow to be useful, compact defaults were controlled in too many places, and benchmark prediction generation had dropped knowledge-stage settings.

Durable decisions:
- `--codex-execution-policy plan` runs deterministic prep first, then writes `codex_execution_plan.json` before stopping.
- Compact defaults must stay aligned across:
  - `cookimport/config/run_settings.py`
  - CLI defaults in `cookimport/cli.py`
  - canonical line-role prompt-format resolution
- Benchmark prediction generation now forwards knowledge-stage settings into shared `RunSettings`.
- `knowledge/<workbook_slug>/block_classifications.jsonl` is the primary outside-span contract; `snippets.jsonl` remains transition/reviewer evidence.

Anti-loop note:
- If compact prompts or knowledge-stage behavior look half-enabled, check control-surface alignment and shared `RunSettings` wiring before editing prompts.

## 2026-03-03 runner reliability and prompt provenance hardening

Problem captured:
- CodexFarm failures and prompt-debug artifacts were noisy, brittle, or easy to misread.

Durable decisions:
- Progress callbacks use `codex-farm process --progress-events --json` when supported, with a retry without that flag for older binaries.
- `prompts/full_prompt_log.jsonl` is the source-of-truth prompt artifact; sampled text files are convenience views only.
- `no last agent message` / `nonzero_exit_no_payload` failures are recoverable partial-output cases.
- Recipe pass extraction falls back to `full_text.lines` when cached payloads are missing `full_text.blocks`.

Anti-loop note:
- Empty pass output with populated input is often a CodexFarm precheck/auth/quota problem first, not a prompt problem.

## 2026-02-28 subprocess schema, connection, and telemetry boundary

Problem captured:
- Caller-side CodexFarm integration had drifted around model discovery, pipeline validation, schema enforcement, and process metadata capture.

Durable decisions:
- Interactive model discovery uses `codex-farm models list --json`.
- Subprocess-backed recipe and knowledge-stage flows validate pipeline IDs up front with `codex-farm pipelines list --root <pack> --json`.
- Runner resolves each pipeline's `output_schema_path` and passes it as `--output-schema`.
- When `process --json` returns a `run_id`, runner can enrich failures with `codex-farm run errors --run-id ... --json`.
- Pass metadata persists `telemetry_report`, `autotune_report`, and compact CSV `telemetry` slices.
- Telemetry/autotune ingestion is non-fatal and stays centralized in the runner.

Anti-loop note:
- Do not duplicate pipeline/schema/telemetry logic in each orchestrator; keep it centralized in `cookimport/llm/codex_farm_runner.py`.

## 2026-02-25 knowledge-stage artifact boundaries

Problem captured:
- Missing knowledge-stage artifacts were often misdiagnosed as prompt-quality problems instead of wiring regressions.

Durable decisions:
- Keep knowledge-stage table hints aligned across single-file, split-merge, and processed-output paths.
- When knowledge extraction is off, deterministic knowledge-lane chunk mapping still backfills stage knowledge labels.
- inline recipe tags now belong to the recipe-correction surface and normal draft outputs, not a separate fifth-stage/tag tree.

Anti-loop note:
- If `KNOWLEDGE=0` appears with knowledge extraction off, debug wiring and run settings before changing prompt assets.

## 2026-03-16 benchmark prompt/export and runner follow-through

Problem captured:
- benchmark single-book runs exposed several easy-to-misread seams at once:
  - older stderr progress lines looked like terminal corruption
  - missing benchmark-level `prompts/` exports looked like Codex non-execution
  - prompt budgets could lose split-token fields on the single-book manifest shape
  - reasoning models still produced zero reasoning-summary events in live traces

Durable decisions:
- `SubprocessCodexFarmRunner` should consume legacy stderr progress lines as compatibility progress/control output, not stderr noise
- benchmark prompt/export truth stays split:
  - raw execution truth lives under the linked processed stage run in `data/output`
  - reviewer-facing merged prompt exports live under benchmark `prompts/` when the export step runs
- prompt preview should reuse exact saved recipe/knowledge input payloads when available and only reconstruct locally as fallback
- preview budget output should stay reviewer-blunt: emit a heuristic budget summary plus danger warnings when rendered prompt volume or call fan-out is obviously expensive
- prompt-budget aggregation must support the single-book top-level telemetry-row layout
- missing reasoning-summary events in `.trace.json` files are usually upstream Codex CLI / CodexFarm transport behavior, not a local prompt-artifact regression

Evidence worth keeping:
- on the 2026-03-16 `saltfatacidheatcutdown` run, live spend was `231` first-pass calls (`175` recipe, `56` knowledge)
- the recipe token spike was not a retry storm; grouped span count and recipe payload inflation were the dominant drivers

Anti-loop note:
- if a benchmark run "looks missing" at the prompt layer, verify the raw processed-output artifacts before changing runner or orchestrator code

## 2026-03-16 line-role whole-book parity and preview alignment

Problem captured:
- canonical line-role had drifted into two mental models at once: "whole-book correction" in architecture language, but unresolved-only preview and prompt-volume assumptions in some tooling
- outside-span title rescue rules that helped true recipe spans could also upgrade TOC headings, pantry headings, and `How to ...` technique rows into false recipe titles

Durable decisions:
- live line-role correction and zero-token preview must both rebuild the same full ordered candidate set
- Codex line-role remains deterministic-first whole-book correction in bounded local batches or shards, not unresolved-only fanout
- outside-span title rescue must be stricter than inside-span title retention:
  - require nearby recipe-start evidence
  - ignore duplicate-title echoes and explicit note lines while scanning support
  - do not count TOC-like rows, `How to ...` headings, or generic action-heavy prose as title support
- benchmark projection may reuse recipe-local line-role labels, but outside-recipe `KNOWLEDGE` versus `OTHER` must still come from final non-recipe authority before scoring

Evidence worth keeping:
- the first broader title-rescue pass improved one book's recall but collapsed precision by promoting non-recipe headings to `RECIPE_TITLE`
- restoring separate inside-span note-prose support recovered true positives without reopening the outside-span false positives

Anti-loop note:
- if line-role token counts look suspiciously tiny or title recall shifts mostly on headings, inspect full-candidate batching and outside-span support rules before retuning Codex or scorer code

## 2026-03-16 knowledge packing and prompt-cost discoveries

Problem captured:
- knowledge preview fanout looked like a prompt-preview problem, but most of the inflation was really coming from deterministic chunking, per-span packing, and row/contract overhead

Durable decisions:
- preview and live knowledge harvest must both use the same `build_knowledge_jobs(...)` seam
- bundle contiguous chunks across neighboring seed non-recipe spans, not only within each individual seed span
- after cross-span bundling lands, remaining prompt count is mostly gap-limited by hard breaks between chunk runs, not by the bundle chunk or char caps
- deterministic chunk-count suppression matters as much as bundle size:
  - collapse tiny heading or bridge fragments before bundling
  - keep deterministic noise suppression strict
  - shorten structured-output key surfaces when they are pure transport overhead

Evidence worth keeping:
- the first cross-span bundle change dropped one preview from `324` knowledge prompts to `91`
- later chunk collapse plus tighter context plus shorter keys dropped that shape again to `41` prompts

Anti-loop note:
- if knowledge prompt counts stay high after bundling, inspect chunk fragmentation and gap breaks before chasing another bundle-cap tweak

## 2026-03-16 remaining prompt-cost boundary and runner-owned Codex home

Problem captured:
- once wrapper duplication was removed, it was easy to keep blaming transport for costs that were really in the shared row/payload shape
- RecipeImport subprocesses could still drift onto the wrong Codex home if the runner did not enforce it

Durable decisions:
- after the transport fix, line-role cost was mainly repeated per-row keys and always-on neighbor text; compact the shared row contract rather than only editing wrapper text
- after the biggest cuts, the remaining prompt budget is mostly real task payload, so future cost work should target recipe fixed overhead or stricter deterministic knowledge admission before another wrapper pass
- `cookimport/llm/codex_farm_runner.py` is the enforcement point for RecipeImport `CODEX_HOME`; do not rely on shell docs or local pack metadata to keep subprocesses on `~/.codex-recipe`

Anti-loop note:
- if prompt-preview numbers improve but live costs do not, the change probably landed in a preview-only seam or outside the shared runner/serializer boundary

## 2026-03-16 to 2026-03-17 shard-runtime model, cutover shape, and remaining runner debt

Problem captured:
- older refactor notes kept drifting toward "bigger prompt bundles" or "brand-new pipeline" language instead of the actual runtime refactor
- it was also easy to half-migrate only the live runtime and leave preview, prompt exports, upload-bundle context, or legacy-id handling on stale assumptions
- the repo-local shard runtime shape could be mistaken for proof of true reused multi-shard live sessions even though the underlying transport still shells through CodexFarm `process`

Durable decisions:
- shard-v1 is a runtime refactor over the existing label-first staged importer, not a new pipeline
- shards are ownership units and workers are bounded execution contexts; keep those concepts separate in docs, manifests, and review surfaces
- the implementation split that worked was:
  - shared runtime/config spine first
  - phase cutovers for line-role, recipe, and knowledge next
  - preview/export/upload-bundle and legacy-id cleanup as the final coordinated cutover
- keep runtime truth separate from compatibility artifacts during cutover:
  - recipe runtime artifacts live under `recipe_phase_runtime/` while per-recipe compatibility files stay under `recipe_correction/{in,out}/`
  - knowledge runtime lives in manifests, proposals, and validation, while `knowledge/{in,out}` remains a compatibility bridge for older prompt/debug readers
  - line-role runtime may need raw prompt-text worker inputs, but reviewer/export surfaces can still keep `line-role-pipeline/prompts/*`
- reviewer-friendly prompt files should stay prompt-level, but they must annotate `runtime_shard_id`, `runtime_worker_id`, and `runtime_owned_ids`
- active run-setting surfaces should reject retired pipeline ids instead of silently normalizing them
- current code landed shard ownership, validation, promotion, and worker/shard observability, but the transport still rides CodexFarm `process`, so true multi-shard live session reuse remains incomplete

Anti-loop note:
- if a future change claims shard agents are "done," verify whether it changed only RecipeImport-side runtime structure or the underlying CodexFarm runner semantics too

## 2026-03-17 remaining legacy weight after shard-v1 cutover

Problem captured:
- once active pipeline ids and live shard-worker paths were cleaned up, "legacy" still looked larger than it really was because read-side helpers and retired modules were mixed together with live runtime code

Durable decisions:
- active run-setting surfaces are already strict; old recipe, knowledge, and line-role ids now fail instead of silently normalizing
- the main remaining compatibility seams are:
  - runner support for older codex-farm stderr progress lines and flag sets
  - compatibility `knowledge/out/` copies for prompt/debug readers
  - archived artifact readers in benchmark / analytics / external-review tooling
- the clearest dead weight is still the retired local-LLM stack:
  - `cookimport/llm/client.py`
  - `cookimport/llm/prompts.py`
  - `cookimport/llm/repair.py`
  - `cookimport/llm/codex_exec.py`

Anti-loop note:
- if a cleanup sweep needs to choose what to delete next, distinguish read-side historical readers from dead runtime modules instead of treating every `legacy`-shaped file as equally coupled to the live pipeline

## 2026-03-17 benchmark-root shard preview and zero-token runtime rehearsal

Problem captured:
- `cf-debug preview-prompts` on benchmark roots could be misread as limited to the original run settings, even when the real goal was projecting shard-v1 costs over saved staged outputs
- `--codex-execution-policy plan` looked like a possible zero-token runtime test, but it exits before the real worker sandbox / runner / proposal-promotion choreography runs

Durable decisions:
- benchmark-root preview should resolve `run_manifest.json.artifacts.{processed_output_run_dir,stage_run_dir}` until it finds the processed stage run with the staged outputs it needs
- preview remains a heuristic planning surface: it can project shard-v1 worker/shard budgets over deterministic-only benchmark outputs because it defaults to the shard-v1 surfaces unless explicitly overridden
- plan mode is not a true runtime rehearsal; if you need zero-token validation of live shard-runtime handoffs, redirect `SubprocessCodexFarmRunner` through a fake `codex-farm` executable via `--codex-farm-cmd` and run the execute path

Anti-loop note:
- if someone wants to test worker sandboxes, per-shard in/out folders, or proposal promotion without spending tokens, do not point them at plan mode alone; use a fake subprocess on the real runner seam

## 2026-03-17 prompt-preview contract reset: predictive only

Problem captured:
- prompt preview started drifting toward retrospective reporting and second-source-of-truth behavior:
  - reusing exact live telemetry from completed runs
  - reusing stale `raw/llm/.../{recipe_correction,knowledge}/in/*.json`
  - falling back to guessed chars-based token math when the real structure was unknown

Durable decisions:
- prompt preview is predictive-only; retrospective cost reporting belongs to `prompt_budget_summary.json` and the separate `actual-costs` surface
- predictive preview accepts only deterministic or `vanilla` processed inputs and must refuse Codex-backed or ambiguous sources
- preview must rebuild recipe and knowledge shard payloads locally from that one predictive-safe source of truth
- predictive cost estimation should come from tokenizing or structurally estimating the locally rebuilt prompt/task payloads plus fake-runner output builders, not from live telemetry reuse or one global chars-per-token multiplier
- if preview cannot produce a safe structural estimate, it should report that the token estimate is unavailable

Anti-loop note:
- older notes that suggested "reuse exact saved payloads when available" or "print a heuristic budget anyway" were superseded by this predictive-only split

## 2026-03-17 prompt-target defaults, worker defaults, and classic runtime truth

Problem captured:
- shard-v1 planning had already moved to prompt-target counts, but older runs and some defaults still behaved like the legacy shard-size world

Durable decisions:
- missing saved `*_prompt_target_count` fields now default to the current shard-v1 target of `5` per enabled phase during preview/planning
- when explicit prompt-target counts are driving the plan, knowledge bundling should not re-split on the older char-cap rule
- unset recipe / knowledge / line-role worker counts should default to planned shard/job count for that one book+phase, capped at `20`
- RecipeImport's shard-v1 subprocess transport must explicitly request CodexFarm's classic one-shot runtime and the namespaced RecipeImport benchmark flag:
  - `--runtime-mode classic_task_farm_v1`
  - `--recipeimport-benchmark-mode line_label_v1`

Anti-loop note:
- if prompt-target counts or shard counts look honest in preview but not in live execution, verify the real subprocess flags before changing planners again

## 2026-03-17 classic path handoff is still transport-dominated

Problem captured:
- after prompt-shape trims landed, line-role token totals could still look absurdly high compared with the visible prompt text

Durable decisions:
- classic path handoff is not opaque workspace context; Codex can reread deposited shard files through shell subturns, and those outputs become part of the counted thread
- line-role is the clearest current example: most remaining live input inflation comes from repeated file reads and cached thread replay, not from the compact visible prompt text
- treat `prompt_budget_summary.json` and finished-run telemetry as the truth for actual costs; prompt preview is still the predictive payload estimate

Evidence worth keeping:
- on the 2026-03-17 `saltfatacidheatcutdown` run, visible line-role prompt text was only modestly larger than the source book, but live line-role input was still about `17.8x` larger because the classic runtime kept replaying shard-file reads
- earlier March 17 runs also showed recipe correction behaving close to one read per shard while knowledge and especially line-role accumulated extra shell-driven context inside one task

Anti-loop note:
- if live token totals are still huge after prompt-shape cuts, inspect trace-level file-read behavior before squeezing row serialization again

## 2026-03-17 knowledge direct-exec transport cutover

Problem captured:
- knowledge was still paying path-mode shell replay costs even though its planner, validator, and writer contracts were already good enough

Durable decisions:
- keep `build_knowledge_jobs(...)`, proposal validation, and writer promotion exactly as they were
- replace the live knowledge transport with one direct `codex exec --json --output-schema ... -` call per shard using an inline prompt built from the existing compact instructions plus the owned shard JSON
- keep the shard-owned manifest / proposal / promotion contract so prompt preview and live knowledge execution still describe the same work units

Anti-loop note:
- if knowledge token costs or behavior drift again, check transport first; the safe cut here was dropping path-mode shell replay without inventing a second planner or validator

## 2026-03-17 shard-runtime documentation consolidation

Problem captured:
- the March 17 shard-runtime work had been spread across many temporary task files, which made the durable current contract harder to recover than the code itself.

Durable decisions:
- keep the lasting runtime story in this section log/readme: shard-runtime foundation plus recipe/knowledge/line-role cutovers, prompt-target defaults, structural predictive preview, concurrent worker launch, and the burn-the-boats legacy cleanup
- treat deleted task files as implementation scaffolding, not a second permanent source of truth

Anti-loop note:
- if a future refactor needs the current shard-runtime contract, start here and the section README rather than reviving `docs/tasks`

## 2026-03-17 line-role direct exec, preview/cost truth, and scope narrowing

Problem captured:
- line-role moved onto direct `codex exec`, but several follow-up questions kept looping:
  - whether line-role needed its own subprocess runner
  - whether prompt preview or dashboard token cells were the truth for finished runs
  - whether the line-role task itself was too broad for prose-heavy books

Durable decisions:
- line-role should reuse the shared direct runner in `codex_exec_runner.py`; the line-role-specific seam is telemetry shaping, because prompt exports and actual-cost readers still need shard-facing metadata such as prompt index, shard id, owned `atomic_index` coverage, and per-attempt summaries
- prompt preview is forward-looking and predictive-only; finished-run truth is `prompt_budget_summary.json`
- old saved preview artifacts can overstate cost relative to a freshly regenerated preview because current preview rebuilds the current planner/runtime shape instead of replaying older assumptions
- direct-exec token gaps are usually transport/runtime effects such as cached-input replay, file reads, or bigger real outputs than the preview schema guess, not hidden extra turns
- the mixed line-role task was the deeper product problem on prose-heavy books: one global label prompt was being asked to both recover recipe structure and judge outside-recipe semantics, which helped recipe-local books and hurt prose-heavy ones

Evidence worth keeping:
- `saltfatacidheatcutdown` showed the warning-sign split clearly:
  - recipe-local slices were strong
  - `KNOWLEDGE` vs `OTHER` stayed weak
- older saved previews on the same roots could still show hundreds of calls even after the live/current preview contract had moved to `5 / 5 / 5`

Anti-loop note:
- if someone is comparing preview, dashboard, and live telemetry, settle "predictive vs actual" first before changing prompt builders or scorer math
- if line-role helps a recipe-dense book and hurts a prose-heavy book, do not assume the model is uniformly bad; inspect whether the task scope is still mixing recipe-boundary work with outside-recipe semantics

## 2026-03-17 knowledge direct exec cutover and repo-wide cost-honesty pass

Problem captured:
- knowledge still paid path-mode shell replay costs after line-role and preview cleanup had already made the overhead obvious
- at the repo level, preview and live runtime could agree on call count but still diverge badly on billed tokens because recipe was still on classic transport and the visible-vs-billed vocabulary was inconsistent across stages

Durable decisions:
- keep the knowledge planner, validator, and writer intact; replace only the live transport with one direct structured `codex exec` call per shard using an inline prompt built from the existing compact knowledge instructions plus the owned shard JSON
- treat recipe transport as the highest-value remaining runtime cleanup once line-role and knowledge direct exec were in place
- the repo-level optimization target is not "teach preview to imitate hidden waste"; it is "make live runtime honor the simple one-shard / one-call operator model, then let preview describe that honest runtime"
- standardize cost reporting across direct phases around:
  - `visible_input_tokens`
  - `cached_input_tokens`
  - `visible_output_tokens`
  - `wrapper_overhead_tokens`

Evidence worth keeping:
- on the motivating benchmark root, preview and actual agreed on `15` total calls while actual billed tokens were still far higher, proving the main remaining problem was per-call size/overhead rather than hidden extra calls
- knowledge was already structurally clean enough that the safe cut was to drop transport replay without rewriting job planning or promotion

Anti-loop note:
- if preview and live disagree after call counts match, debug transport shape, cached replay, and output schema width before changing planners again

## 2026-03-17 recipe direct-exec cleanup and legacy mirror removal

Problem captured:
- recipe live execution had already moved to direct structured shard calls, but compatibility mirrors and a few readers still advertised `recipe_correction/{in,out}` as if that were the active contract

Durable decisions:
- the live recipe contract is:
  - immutable shard inputs under `recipe_phase_runtime/inputs/*.json`
  - validated proposals under `recipe_phase_runtime/proposals/*.json`
  - human/debug summaries under `recipe_correction_audit/*.json`
- delete the old `recipe_correction/{in,out}` write path instead of preserving it as a fake second truth
- move CLI debug-status checks and prompt-artifact discovery onto manifest keys and `recipe_phase_runtime/{inputs,proposals}` fallbacks so local tooling teaches the same contract as the runtime
- recipe direct-exec should use the same operator model as knowledge and line-role: one shard equals one structured Codex call, plus visible-vs-billed cost breakdown artifacts

Anti-loop note:
- if a tool claims recipe debug artifacts are missing, check whether it is still probing `recipe_correction/{in,out}` before touching the live writer

## 2026-03-18 line-role file-backed transport landed, two-phase prototype was retired, and cleanup had to be repo-wide

Problem captured:
- large inline line-role prompts still hit context limits on big books, so the model-facing seam had to move from giant inline prompt bodies to worker input files
- during that work, the repo briefly carried three competing stories:
  - old inline single-phase transport
  - a two-phase `recipe_region_gate` plus `recipe_structure_label` prototype
  - the final single-pass file-backed `line_role` runtime

Durable decisions:
- current live line-role truth is one file-backed `line_role` phase writing under `line-role-pipeline/runtime/line_role/`
- the worker `in/*.json` file is the authoritative model payload; wrapper prompts are intentionally short and must report `prompt_input_mode=path` plus `request_input_file`
- the two-phase prototype was useful only as a transport experiment; it was retired because rereading the same rows twice cost too much on books like `thefoodlabcutdown`
- finishing the cleanup required more than changing the runtime:
  - fake exec had to read the deposited task file for dry runs
  - fake-runner tests had to follow the new `runtime/line_role/` layout and `line-role-canonical-*` shard ids
  - prompt export had to stop globbing `line_role_prompt_response_*.txt` as if they were fresh input prompts
  - abandoned gate assets and compatibility branches had to be deleted so the repo stopped teaching the retired split

Evidence worth keeping:
- on `thefoodlabcutdown`, removing the live `recipe_region_gate` pass cut predictive line-role cost from about `10` calls / `1.30M` estimated tokens to about `5` calls / `636.9k`
- after wrapper bloat was removed, the dominant remaining line-role costs were:
  - duplicated neighbor context
  - repeated metadata / JSON framing
  - the raw row text itself

Anti-loop note:
- if line-role looks "wrong" because a test or preview still shows the older two-phase or inline layout, verify whether the bug is in runtime code, fake-runner/test expectations, or prompt-artifact discovery before reopening the transport design itself

## 2026-03-18 split recipe-region gate prototype was intentionally abandoned

Problem captured:
- prose-heavy books showed that one mixed line-role prompt was doing two jobs at once, so a two-phase `recipe_region_gate` plus `recipe_structure_label` split looked attractive

Durable decisions:
- the prototype was useful as a design probe and proved that preview, tests, and runtime artifacts could support multiple internal line-role phases
- it was intentionally backed out after user review because the extra internal phases increased effective prompt/fresh-agent count beyond the desired public `5 + 5 + 5` shape
- the active product shape is therefore:
  - one file-backed `line_role` phase
  - deterministic grouping afterward
  - continued work inside the existing stage boundary rather than multiplying line-role passes

Evidence worth keeping:
- the prototype succeeded technically, then was removed on product-shape grounds, not because the implementation was impossible

Anti-loop note:
- if someone proposes reviving `recipe_region_gate`, first justify why the gain is worth violating the current single-surface prompt-count mental model

## 2026-03-18 immutable input -> owned proposal -> deterministic promotion is the seam to keep

Problem captured:
- docs and helper surfaces could still make current Codex phases look more compatibility-heavy than they really were

Durable decisions:
- keep the durable LLM seam as:
  - program-written immutable input payload
  - model-owned structured proposal for exact owned ids
  - deterministic ownership validation
  - deterministic promotion into durable outputs
- recipe, knowledge, and line-role all already follow that contract closely enough that the next cleanup should remove misleading compatibility surfaces, not add new ones

Anti-loop note:
- if a future change wants the model to free-edit shared output files in place, it is probably moving away from the clean contract that made the current shard runtimes debuggable

## 2026-03-18 Stage 7 clarity was mostly naming plus one richer review summary

Problem captured:
- after the knowledge-stage runtime contract had settled, the remaining confusion was operator-facing wording and summary visibility, not artifact ownership or shard-runtime mechanics

Durable decisions:
- keep the live Stage 7 mechanics as they were:
  - deterministic seed non-recipe spans
  - parser-owned chunk pruning
  - immutable `knowledge/in/*.json`
  - validated `knowledge/proposals/*.json`
  - deterministic promotion into final authority plus reviewer snippets
- align remaining labels toward `non-recipe knowledge review`
- add one richer `review_summary` block in `knowledge_manifest.json` so operators can see seed-span count, chunk pruning totals, reviewed shard count, promoted useful chunks/snippets, and direct pointers back to `08_nonrecipe_spans.json` plus `09_knowledge_outputs.json`

Anti-loop note:
- if Stage 7 docs feel right but the surface still feels vague, check labels and manifest/report summaries before redesigning the runtime

## 2026-03-18 line-role transport compaction moved cost work onto the real billed seam

Problem captured:
- the first file-backed line-role cut removed wrapper bloat, but the worker task file still repeated too much metadata and hidden neighbor context
- there was a real risk of cutting billed payloads so aggressively that local debugging would get worse

Durable decisions:
- keep the billed model payload minimal and separate from the local debug view:
  - `workers/*/in/*.json` is the compact tuple transport
  - `workers/*/debug/*.json` is the rich local copy
- `prev_text` and `next_text` no longer belong on `AtomicLineCandidate`; prompt-local adjacency should come from explicit ordered lookup helpers instead
- line-role prompt semantics now need to stay aligned across three layers:
  - checked-in prompt assets
  - Python fallback strings
  - the file-backed wrapper prompt that explains the tuple contract

Evidence worth keeping:
- Food Lab preview work cut line-role cost in stages without changing call count:
  - dropping repeated neighbor fields cut about `43%` of estimated line-role tokens on one apples-to-apples `5`-shard preview
  - moving to need-to-know tuple payloads cut the same stage again from about `361,968` total tokens to about `181,980`
- the saved lesson was that the remaining cost after wrapper cleanup lived mostly in repeated row metadata, not in output schema size

Anti-loop note:
- if line-role cost spikes again, inspect tuple payload size, neighbor-window reconstruction, and wrapper semantics before widening schemas or reintroducing rich row objects into the billed transport

## 2026-03-18 recipe and knowledge prompt contracts were compacted instead of loosened

Problem captured:
- recipe and knowledge direct-exec prompts still carried stale transport wording, schema-shaped helper dumps, and metadata that cost tokens without improving grounded review

Durable decisions:
- knowledge direct prompts must teach inline JSON only; `{{INPUT_PATH}}` belongs to file-backed line-role, not knowledge
- knowledge payloads should stay compact and skeptical:
  - short aliases
  - raw block text remains authoritative
  - `semantic_hint` removed
  - `suggested_lane` only when deterministic evidence is strong
- recipe payloads should stay compact without dropping grounded evidence rows:
  - minified shard JSON
  - compact hint object
  - compact tagging guide
  - first-class bad-candidate triage surface (`fragmentary`, `not_a_recipe`, `repaired`)

Evidence worth keeping:
- Food Lab zero-token previews showed:
  - knowledge stage total tokens down about `36%` after compact payload work
  - full 3-stage preview total down about `19.6%` from the knowledge compaction alone
  - recipe-stage input down by about one third across Dinner for 2, Salt Fat Acid Heat, and The Food Lab without changing call counts
- fresh Food Lab / Salt Fat previews also confirmed the reviewer-facing knowledge prompt now teaches skepticism toward praise blurbs, signup copy, menus, and similar junk families instead of biasing toward `knowledge`

Anti-loop note:
- if future prompt work starts adding schema-shaped helper dumps, semantic priors, or duplicated metadata back into recipe/knowledge payloads, require new benchmark evidence first; the March 18 cuts already proved those fields were expensive and not structurally necessary

## 2026-03-18 knowledge integrity required stricter safety caps, less deterministic trust, and bounded repair

Problem captured:
- the live knowledge schema had one strict-JSON incompatibility
- a later broad shard-count override reopened the earlier giant-bundle risk for knowledge
- some invalid knowledge responses returned outer JSON but omitted owned chunks or wasted output on whitespace, and deterministic low-signal pruning was still deciding too much before review

Durable decisions:
- keep strict schema-pack regression coverage for nested required fields; the `rc` omission bug was a real live structured-output failure, not a test-only nit
- knowledge planning is fixed to one deterministic chunk per shard; only worker count remains operator-tunable there
- keep hard knowledge bundle safety caps for chunk count, char count, locality, and table isolation
- remove the low-signal deterministic prefilter and keep chunk-level semantic hints out of the billed payload
- use bounded recovery instead of validator leniency:
  - one repair pass for near-miss invalid outputs
  - same-stage re-sharding for pathological missing-row responses

Evidence worth keeping:
- the failing benchmark pattern that motivated this work was mostly `missing_owned_chunk_results`, not transport crashes
- focused tests now guard:
  - empty or missing chunk coverage
  - synthetic fallback chunk ids
  - out-of-surface evidence
  - long-book knowledge plans that must exceed the requested prompt target to stay within hard caps

Anti-loop note:
- if knowledge reliability regresses, do not respond by weakening ownership validation or restoring deterministic pruning. Re-check schema strictness, safety-cap obedience, and the repair/re-shard path first.

## 2026-03-18 direct-exec hardening centered on worker isolation and pathological-spend observability

Problem captured:
- direct shard workers could still inherit too much repo context, and March 18-style token blowups were hard to diagnose from summary artifacts alone

Durable decisions:
- direct recipe / knowledge / line-role workers run from sterile mirrored workspaces under `~/.codex-recipe/recipeimport-direct-exec-workspaces/`
- mirrored workspaces get shard-scoped `AGENTS.md` guidance and rewritten local paths so worker instructions stay task-local
- prompt and telemetry surfaces should expose pathological spend directly:
  - invalid-output spend
  - repaired-shard counts
  - command-executing shard counts
  - reasoning-heavy shard counts
  - merged pathology flags

Evidence worth keeping:
- this hardening pass intentionally shipped without a live benchmark rerun; the completed proof was focused local tests plus richer prompt-budget / telemetry artifacts
- a stale variable in the recipe execution-plan helper surfaced during worker-isolation verification, which is a reminder that these runtime seams need focused regression anchors even for "docs-adjacent" hardening

Anti-loop note:
- if a future token blowup review starts from raw `events.jsonl`, you are already too low-level. Start from `prompt_budget_summary.json`, worker status payloads, and the direct-exec pathology counters first.
