---
summary: "ExecPlan for Phase 1 of Refactor.md: make stage observability the new source of truth and delete legacy pass-slot taxonomy, compatibility renderings, and fallback readers."
read_when:
  - "When implementing Phase 1 under Recommended Migration Strategy in docs/reports/Refactor.md"
  - "When changing stage naming, run summaries, run manifests, prompt artifacts, or benchmark bundle stage reporting"
  - "When deleting pass-slot naming such as pass2_schemaorg, pass3_stage, or other legacy stage compatibility seams"
---

# Fix Observability By Deleting Legacy Stage Taxonomy

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `docs/PLANS.md`.

This plan implements only `Phase 1 — Fix observability first` from `docs/reports/Refactor.md`. It is still pre-label-first and pre-recipe-architecture-change work, but it is not a compatibility-preserving migration. Phase 1 is the point where the repo stops speaking in pass-slot language. Delete the old observability paradigm outright. Do not preserve `pass1` through `pass5` naming, compatibility aliases, benchmark compatibility families, or historical fallback readers inside the new observability contract. There is no dual taxonomy period in this plan.

## Purpose / Big Picture

After this change, a person inspecting any new stage run or benchmark prediction run should see only one stage language: the new semantic stage language owned by `stage_observability.json`. They should be able to answer three questions without reading code: what stages existed in this run, what each stage was actually called, and which files belong to each stage. They should not have to mentally translate `pass2_schemaorg`, `pass3_stage`, or any other dead naming seam.

The user-visible result should be one shared run-level artifact, `stage_observability.json`, that becomes the canonical description of observed stages for the run. `run_summary.json`, `run_summary.md`, `run_manifest.json`, prompt artifact exports, and benchmark upload-bundle rendering should all read from that same stage description instead of maintaining local maps. The old pass-slot worldview is not retained as a parallel surface. If a merged-repair run is the real recipe stage, the run should present `Merged Repair` and only `Merged Repair`. If a classic three-pass recipe run is the real topology, the run should present `Chunking`, `Schema.org Extraction`, and `Final Draft`. A deterministic run should not invent absent LLM stages.

This phase also establishes the cross-phase contract for the rest of the refactor. Later phases may add new semantic stage keys and new stage-owned artifacts, but they must register those changes through the shared stage-observability layer first and then let summaries, manifests, prompt exports, and benchmark renderers consume that shared truth. The point of Phase 1 is not only to clean up current naming. It is to kill the old stage taxonomy so the later phases cannot drift back into it.

For the rest of this phase series, treat the following semantic keys from `docs/reports/Refactor.md` as the naming backbone for the final architecture rather than as optional prose: `label_det`, `label_llm_correct`, `group_recipe_spans`, `build_intermediate_det`, `recipe_llm_correct_and_link`, `build_final_recipe`, `classify_nonrecipe`, `extract_knowledge_optional`, and `write_outputs`. Phase 1 does not need to fabricate stages that do not yet exist, but once a later phase lands it must teach only these semantic keys through `stage_observability.json`. Old pass-slot names do not get grandfathered in.

## Progress

- [x] (2026-03-15_22.20.44) Re-read `docs/PLANS.md` before drafting this ExecPlan.
- [x] (2026-03-15_22.20.44) Re-read the relevant section of `docs/reports/Refactor.md`, especially `Recommended Migration Strategy` and `Phase 1 — Fix observability first`.
- [x] (2026-03-15_22.20.44) Read current staging and LLM references in `docs/05-staging/05-staging_readme.md` and `docs/10-llm/10-llm_README.md`.
- [x] (2026-03-15_22.20.44) Surveyed the concrete observability seams in `cookimport/staging/import_session.py`, `cookimport/staging/writer.py`, `cookimport/cli.py`, `cookimport/runs/manifest.py`, `cookimport/llm/prompt_artifacts.py`, and `cookimport/bench/upload_bundle_v1_render.py`.
- [x] (2026-03-15_22.20.44) Recorded the discovery summary in `docs/understandings/2026-03-15_22.20.44-phase1-observability-surface-map.md`.
- [x] (2026-03-15_22.20.44) Wrote this ExecPlan.
- [x] (2026-03-15_23.07.00) Revised the ExecPlan to reflect the destructive-migration philosophy: Phase 1 now deletes legacy pass-slot naming and compatibility readers instead of preserving them.
- [ ] Implement shared stage observability models and run-level writer under `cookimport/runs/`.
- [ ] Rename raw stage-owned storage and run-level reporting so pass-slot names disappear from new outputs.
- [ ] Remove compatibility fields and fallback readers from `run_summary`, `run_manifest`, prompt artifact export, and benchmark upload-bundle rendering.
- [ ] Update or regenerate benchmark/test fixtures that still assert pass-slot compatibility output.
- [ ] Add focused tests for deterministic, three-pass, merged-repair, and pass4 knowledge cases under the new semantic-only naming.
- [ ] Update short folder notes and current docs so future reviewers can understand the new observability contract from checked-in documentation alone.

## Surprises & Discoveries

- Observation: the repo already has one useful stage-descriptor seam, but it was written as a local repair rather than the repo-wide source of truth.
  Evidence: `cookimport/llm/prompt_artifacts.py` defines `PromptStageDescriptor` and already derives human-facing stage labels from observed pipeline ids.

- Observation: benchmark upload-bundle rendering was already compensating for stage drift, which made it tempting to keep compatibility families around.
  Evidence: `cookimport/bench/upload_bundle_v1_render.py` still knows about `pass2_*` and `pass3_*`, while `cookimport/cli.py` writes run summaries from a different coarse stage surface.

- Observation: the biggest source of confusion is not a missing label string; it is the existence of multiple overlapping stage taxonomies.
  Evidence: `cookimport/staging/import_session.py` knows what actually ran, but `run_manifest.json`, prompt export, and benchmark bundle rendering each rediscover stage truth independently and in different vocabularies.

- Observation: the old plan language still assumed historical-root support and additive fallback logic, which conflicts directly with the user’s refactor philosophy.
  Evidence: the prior revision explicitly preserved `pass2_stage` and historical reconstruction paths. That language has to be removed for the plan to match the intended “burn the boats” migration.

## Decision Log

- Decision: Phase 1 is the destructive migration point for stage observability.
  Rationale: preserving the old stage taxonomy during a major refactor would keep the repo mentally and structurally split across two paradigms. The point of this phase is to establish one truthful stage language, not two.
  Date/Author: 2026-03-15 / Codex

- Decision: `stage_observability.json` is the only canonical run-level stage description for new runs.
  Rationale: today no single file answers “what stages happened here?” for a novice. The new artifact must replace older naming surfaces rather than coexist with them.
  Date/Author: 2026-03-15 / Codex

- Decision: raw stage-owned storage for new runs must be renamed to semantic paths during Phase 1 instead of keeping `pass1` through `pass5` path names alive.
  Rationale: if raw storage still uses pass-slot names, every downstream tool will keep relearning the old worldview. Renaming storage is part of deleting the old paradigm.
  Date/Author: 2026-03-15 / Codex

- Decision: benchmark upload-bundle rendering and prompt artifact export must delete compatibility-only stage views instead of preserving them.
  Rationale: these surfaces are user-facing. Leaving `pass2_stage`, `pass3_stage`, or similar outputs in place would undermine the whole refactor by teaching reviewers the dead taxonomy.
  Date/Author: 2026-03-15 / Codex

- Decision: historical roots that cannot satisfy the new contract do not drive this plan.
  Rationale: this is a major refactor with no rollback posture. Old fixture roots can be regenerated or rewritten. The code should target the new model cleanly instead of carrying historical fallback readers forever.
  Date/Author: 2026-03-15 / Codex

- Decision: this plan still does not change recipe extraction logic, grouping logic, or knowledge-mining scope.
  Rationale: `Refactor.md` separates observability-first work from the later label-first and recipe-stage redesign. The destructive part of this plan is about naming, artifacts, and ownership boundaries, not about pulling Phase 2 or Phase 3 logic forward.
  Date/Author: 2026-03-15 / Codex

## Outcomes & Retrospective

Planning outcome only so far: the highest-leverage seam is still a shared stage description written once per run and consumed everywhere else, but the plan is no longer additive. The key implementation risk is now broader churn: renaming raw stage storage, deleting compatibility renderings, and refreshing fixtures in one sweep. That is acceptable because the user’s stated goal is a hard cut to the new paradigm rather than a reversible migration.

## Context and Orientation

In the current repository, the main single-file stage flow runs through `cookimport/staging/import_session.py::execute_stage_import_session_from_result(...)`. That function applies the optional recipe Codex pipeline, then deterministic table and chunk work, then optional knowledge harvest, then the writers in `cookimport/staging/writer.py`, then stage-block prediction writing, and finally the report. This is the most truthful place to think about “what stages actually happened.”

After the per-book work finishes, `cookimport/cli.py` writes run-level artifacts such as `run_summary.json`, `run_summary.md`, and `run_manifest.json`. Those files are stable and widely reused, but right now they do not expose one ordered source of truth for observed stages.

The LLM side adds another layer. `cookimport/llm/codex_farm_orchestrator.py` writes recipe raw data and `llm_manifest.json`. `cookimport/llm/codex_farm_knowledge_orchestrator.py` writes knowledge raw data and `pass4_knowledge_manifest.json`. `cookimport/llm/prompt_artifacts.py` already contains a semantic rendering seam, but it still lives beside other naming systems instead of owning the repo-wide truth.

Benchmarking adds a fourth surface. `cookimport/bench/upload_bundle_v1_render.py` currently contains independent stage-normalization logic. In the new plan, that duplication is not tolerated. It must read the same shared stage truth as every other reporting surface.

For this plan, define the key terms plainly:

A “legacy pass slot” means the old numbered storage or report position such as `pass1`, `pass2`, `pass3`, `pass4`, or `pass5`, including names like `pass2_schemaorg` and fields like `pass2_stage`.

A “semantic stage” means the job that actually ran, such as `chunking`, `schemaorg`, `final`, `merged_repair`, `knowledge`, `tags`, or `write_outputs` for the current implementation, and the more final keys such as `label_det` or `build_final_recipe` once later phases land.

A “stage index” means the new run-level JSON artifact that lists observed stages in execution order, their human-facing labels, status, timing, and the files or directories that belong to each stage.

This plan touches these main paths:

- `cookimport/runs/manifest.py` and a new helper module under `cookimport/runs/` for the shared stage observability contract.
- `cookimport/cli.py` for run summary and manifest writing.
- `cookimport/staging/import_session.py` and `cookimport/staging/writer.py` as the canonical stage flow and stage-owned output writers.
- `cookimport/llm/codex_farm_orchestrator.py` and `cookimport/llm/codex_farm_knowledge_orchestrator.py` for semantic raw stage storage names.
- `cookimport/llm/prompt_artifacts.py` so prompt exports consume shared stage semantics.
- `cookimport/bench/upload_bundle_v1_render.py` and related bundle code so benchmark reporting consumes the same semantics and deletes pass-slot views.
- `docs/05-staging/05-staging_readme.md`, `docs/10-llm/10-llm_README.md`, and `cookimport/runs/README.md` so the new contract is documented where future work will look for it.

## Milestones

### Milestone 1: Introduce a shared stage observability contract

At the end of this milestone, the repo will have one module under `cookimport/runs/` that can describe the observed stage topology of a run without depending on any one output surface. A novice should be able to read this module and understand how stage truth is represented in this repo.

Create `cookimport/runs/stage_observability.py`. Use explicit models, preferably mirroring the repo’s existing style in `cookimport/runs/manifest.py`. The artifact written by this module should be `stage_observability.json` under the run root and should use a stable schema version such as `stage_observability.v1`.

The payload must include an ordered `stages` list. Each stage row must carry, at minimum, a stable `stage_key`, a human-facing `stage_label`, a `status`, a `stage_group`, an optional timing summary, and artifact references. Those artifact references should point to existing files and directories rather than inventing new duplicate payloads. The stage index is supposed to explain what already exists, not copy it. The schema must not include `legacy_slot`, `compatibility_aliases`, or any equivalent field that preserves the old taxonomy.

Design the module for runtime truth only. New runs should register the stages they observed and then serialize that truth into `stage_observability.json`. Do not build a historical reconstruction path around old pass-slot directories. If fixtures or benchmark roots need the new file, regenerate those roots in the new format instead of teaching the code to reverse-engineer the dead format.

Acceptance for this milestone is a focused test file, such as `tests/staging/test_stage_observability.py`, that can build stage-observability payloads for at least these cases: deterministic-only run, classic three-pass recipe run, merged-repair recipe run, and knowledge-enabled run.

### Milestone 2: Emit the stage index from real run roots and rename raw stage storage

At the end of this milestone, real stage runs and prediction-run-style outputs will write `stage_observability.json`, `run_manifest.json` will point to it directly, and raw stage-owned output paths for new runs will use semantic stage names instead of pass-slot names.

Implement a runtime stage recorder that collects observed stages during execution and passes them to the new writer. Update the raw output writers so stage-owned directories and artifact groupings are keyed by semantic stage names. This includes recipe-stage raw outputs and knowledge-stage raw outputs. The repo should stop writing new roots that contain storage names such as `pass2_schemaorg` when a semantic name such as `merged_repair` or `schemaorg` is the real stage.

Update `cookimport/cli.py` so `stage_observability.json` is written before `run_manifest.json` and `run_summary.json` are finalized. `run_manifest.json` must gain a stable artifact key such as `stage_observability_json`. At the same time, remove old stage-taxonomy fields that no longer belong in the manifest. Do not keep old artifact keys solely for compatibility.

Acceptance for this milestone is that new tests verify the new manifest artifact key, the presence of `stage_observability.json` in newly written run roots, and the absence of pass-slot directory names in new raw stage output paths.

### Milestone 3: Make summaries and prompt exports consume the shared stage description and delete local maps

At the end of this milestone, the main human-facing stage summaries inside stage runs will no longer rely on their own separate stage maps, and prompt artifacts will stop exporting pass-slot-derived labels.

Update `cookimport/cli.py::_build_stage_run_summary_payload(...)` and `_write_stage_run_summary(...)` so the summary includes an ordered view of observed stages derived from `stage_observability.json`. Remove stale or duplicative stage-naming fields that teach the old model. The human-facing labels in this section must come from the stage index, not from local string heuristics.

Then update `cookimport/llm/prompt_artifacts.py` to consume shared stage metadata instead of owning a separate stage taxonomy. Keep prompt-export-specific rendering helpers only if they are presentation adapters over shared stage semantics. Delete any prompt-export logic that exists only to map semantic stages back onto pass-slot folder names.

Acceptance for this milestone is that the prompt-artifact regression slice still passes after fixtures are updated to the new semantic-only naming and that a merged-repair fixture renders `Merged Repair` with no pass-slot synonyms anywhere in the exported payload.

### Milestone 4: Route benchmark upload-bundle rendering through the same stage truth and delete compatibility views

At the end of this milestone, benchmark bundle rendering will consume the same stage truth as the rest of the repo and will no longer emit compatibility fields such as `pass2_stage` or `pass3_stage`.

Use the shared stage builder inside the bundle flow. The renderer should read `stage_observability.json` and stage-owned semantic artifact paths, then render reviewer output from that information alone. Remove the old normalized compatibility model. If benchmark fixtures in `data/golden/` still depend on pass-slot naming, regenerate them or replace them with new semantic fixtures rather than keeping fallback logic in production code.

Acceptance for this milestone is that `tests/bench/test_upload_bundle_v1_existing_output.py` and `tests/bench/test_benchmark_cutdown_for_external_ai.py` pass after their fixture expectations are rewritten around semantic stage names only.

### Milestone 5: Document the contract and prove it on real runs

At the end of this milestone, a future contributor can inspect the docs and one real run root and understand the new observability boundary without reading this plan first.

Update `docs/05-staging/05-staging_readme.md` to describe the new `stage_observability.json` artifact and the semantic stage-owned output paths. Update `docs/10-llm/10-llm_README.md` to explain that recipe and knowledge manifests are stage-local artifacts beneath the new stage taxonomy, not owners of an alternate naming scheme. Update `cookimport/runs/README.md` with a short note describing `run_manifest.json` plus `stage_observability.json` as the paired run-level observability contract.

Then run at least one real stage import and inspect the output. Prefer `data/input/saltfatacidheatCUTDOWN.epub` because it already exists in the repo and exercises real stage output paths. If live Codex execution is available, run both a deterministic baseline and a merged-repair recipe pipeline case. If live Codex execution is not available, keep the proof limited to deterministic execution plus the targeted test slices and record that limitation in this plan.

Acceptance for this milestone is that a real run root contains `stage_observability.json`, `run_summary.json`, `run_summary.md`, and `run_manifest.json` that all agree on the stage topology, and that the run root contains no pass-slot-named stage directories or observability fields.

## Plan of Work

Start by introducing the shared stage description as the replacement observability contract, not as an additive sidecar. The simplest durable move is to define one explicit model and writer under `cookimport/runs/`, then route every reporting surface through that model and delete their local stage maps. This includes prompt export and benchmark upload-bundle rendering.

At the same time, rename raw stage-owned storage so the repo stops producing new paths that preserve the dead pass-slot worldview. This is a bigger sweep than a pure metadata change, but it is the only way to make the new paradigm real. If the filesystem still says `pass2_schemaorg`, the codebase will keep thinking in that language.

Keep the first version truthful rather than speculative. The stage index does not need to pretend that label-first stages already exist. It needs to describe the current implementation accurately, using semantic names for the current topology and leaving room for the later phase keys from `docs/reports/Refactor.md`. The destructive part is about deleting the old vocabulary, not about inventing future stages early.

Once the new artifact exists, reroute `run_summary` and `run_manifest`, then prompt artifact export, then benchmark bundle rendering. As each surface is migrated, delete the replaced code immediately. Do not leave dormant compatibility adapters in the tree. If tests or fixtures rely on the old model, rewrite them to the new one instead of preserving an adapter path.

## Concrete Steps

Work from `/home/mcnal/projects/recipeimport`.

Prepare the environment:

    source .venv/bin/activate
    pip install -e .[dev]

Before implementation, run the current cross-surface regression slice to establish the baseline that will intentionally change:

    source .venv/bin/activate
    pytest tests/staging/test_run_manifest_parity.py tests/labelstudio/test_labelstudio_benchmark_helpers_artifacts.py tests/bench/test_upload_bundle_v1_existing_output.py tests/bench/test_benchmark_cutdown_for_external_ai.py -q

Expected baseline outcome:

    compact pytest output; command exits 0

After introducing the new shared module and renaming raw storage, add and run a focused test file for the new contract:

    source .venv/bin/activate
    pytest tests/staging/test_stage_observability.py -q

Expected outcome after Milestone 1:

    compact pytest output; command exits 0

After routing manifests and summaries and deleting compatibility fields:

    source .venv/bin/activate
    pytest tests/staging/test_run_manifest_parity.py -q

After routing prompt artifacts and deleting pass-slot mappings:

    source .venv/bin/activate
    pytest tests/labelstudio/test_labelstudio_benchmark_helpers_artifacts.py -q

After routing upload-bundle rendering and deleting compatibility views:

    source .venv/bin/activate
    pytest tests/bench/test_upload_bundle_v1_existing_output.py tests/bench/test_benchmark_cutdown_for_external_ai.py -q

Then run one real deterministic stage import:

    source .venv/bin/activate
    cookimport stage data/input/saltfatacidheatCUTDOWN.epub --out /tmp/phase1-observability-det

Expected outcome:

    a new timestamped run root under /tmp/phase1-observability-det containing run_manifest.json, run_summary.json, run_summary.md, and stage_observability.json, with semantic stage-owned directories only

If live Codex execution is available, also run a merged-repair example:

    source .venv/bin/activate
    cookimport stage data/input/saltfatacidheatCUTDOWN.epub --out /tmp/phase1-observability-merged --llm-recipe-pipeline codex-farm-2stage-repair-v1 --llm-knowledge-pipeline codex-farm-knowledge-v1 --codex-execution-policy execute

Expected outcome:

    the run root contains stage_observability.json, and the primary recipe stage label is Merged Repair with no pass-slot synonym fields or directories

Inspect the new artifact directly:

    source .venv/bin/activate
    python - <<'PY'
    from pathlib import Path
    import json

    run_root = max(Path("/tmp/phase1-observability-det").glob("*/"), key=lambda p: p.name)
    payload = json.loads((run_root / "stage_observability.json").read_text(encoding="utf-8"))
    print(payload["schema_version"])
    for stage in payload.get("stages", []):
        print(stage["stage_key"], "=>", stage["stage_label"])
    PY

Expected transcript shape:

    stage_observability.v1
    ...
    write_outputs => Write Outputs

Prove the old taxonomy is gone from the new run root:

    source .venv/bin/activate
    run_root="$(ls -1 /tmp/phase1-observability-det | tail -n 1)"
    rg -n "pass[1-5]|pass2_schemaorg|pass3_stage|compatibility_alias|legacy_slot" "/tmp/phase1-observability-det/$run_root"

Expected outcome:

    command exits 1 with no matches

## Validation and Acceptance

The change is accepted only if the same semantic stage naming is visible across every major reporting surface for the same run root and the old pass-slot naming is absent from new outputs.

For a deterministic stage run, `stage_observability.json` must exist and must not claim absent recipe LLM stages. `run_summary.json` and `run_summary.md` must include an ordered observed-stage view derived from that file. `run_manifest.json` must point to `stage_observability.json`. None of those files may contain `pass1`, `pass2`, `pass3`, `pass4`, `pass5`, `legacy_slot`, or `compatibility_aliases`.

For a classic three-pass recipe run, the stage index must include semantic recipe stages for `chunking`, `schemaorg`, and `final`, plus any optional knowledge or tags stages that actually ran. Prompt artifact outputs must use those semantic labels as their display names and must not include pass-slot synonyms.

For a merged-repair recipe run, the stage index must show `merged_repair` as the recipe correction stage and must not fabricate a `final` LLM stage that did not run. No run-level or prompt-artifact surface may mention `pass2` or `pass2_schemaorg`.

For benchmark upload-bundle rendering, reviewer-facing output must derive only from the shared stage semantics. Fields such as `pass2_stage` and `pass3_stage` must be removed. Updated benchmark fixtures must prove that the bundle still renders correctly under the new naming.

## Idempotence and Recovery

Writing `stage_observability.json`, `run_summary.json`, and `run_summary.md` must be safe to repeat. If a run root already contains those files, the writer should overwrite them deterministically from the current runtime observations.

This plan is intentionally destructive. Old benchmark roots, fixture outputs, or ad hoc run folders that still depend on pass-slot naming are not protected by fallback code. Recovery means regenerating those artifacts under the new semantic naming, not keeping compatibility readers alive in the codebase.

If a downstream surface such as prompt export or upload-bundle rendering still depends on deleted fields during implementation, fix that surface immediately and rerun the targeted tests. Do not restore the deleted compatibility field as a temporary crutch.

## Artifacts and Notes

The new run-level artifact should look roughly like this for a merged-repair run:

    {
      "schema_version": "stage_observability.v1",
      "run_kind": "stage",
      "run_id": "2026-03-15_12.34.56",
      "stages": [
        {
          "stage_key": "merged_repair",
          "stage_label": "Merged Repair",
          "stage_group": "recipe_llm",
          "status": "completed"
        }
      ]
    }

The important thing is not the exact JSON formatting. The important thing is that the artifact names only the semantic stage and contains no legacy pass-slot metadata.

## Interfaces and Dependencies

In `cookimport/runs/stage_observability.py`, define explicit models and helpers for the new artifact. Keep the surface small and stable. A good minimum interface is:

    class StageArtifactRef(BaseModel):
        path: str
        kind: str
        role: str | None = None

    class ObservedStage(BaseModel):
        stage_key: str
        stage_label: str
        stage_group: str
        status: str
        artifacts: list[StageArtifactRef] = Field(default_factory=list)
        timing_seconds: float | None = None
        notes: list[str] = Field(default_factory=list)

    class StageObservabilityReport(BaseModel):
        schema_version: str
        run_kind: str
        run_id: str
        stages: list[ObservedStage]

    def build_stage_observability_report(
        *,
        run_root: Path,
        run_kind: str,
        run_config: Mapping[str, Any],
        observed_stages: Sequence[ObservedStage],
    ) -> StageObservabilityReport:
        ...

    def write_stage_observability_report(
        run_root: Path,
        report: StageObservabilityReport,
    ) -> Path:
        ...

In `cookimport/cli.py`, call this writer before `_write_stage_run_manifest(...)` and `_write_stage_run_summary(...)` so both surfaces consume the new artifact. Remove the replaced local stage summary maps once this call path exists.

In `cookimport/staging/writer.py` and the LLM orchestrators, rename stage-owned raw output directories so semantic stage names become the only directory vocabulary produced for new runs.

In `cookimport/llm/prompt_artifacts.py`, keep prompt-export-specific rendering helpers only as adapters over shared stage data. Delete any helper whose only purpose is to translate semantic stages back into pass-slot names.

In benchmark bundle code, read `stage_observability.json` and semantic stage-owned artifacts directly. Delete compatibility fields and delete the code that computes them.

2026-03-15_22.20.44 / Codex: created this ExecPlan from `docs/reports/Refactor.md` Phase 1 after surveying the current stage, manifest, prompt-artifact, and upload-bundle observability seams. The first draft chose a shared run-level stage index as the minimal truthful seam that could land before any label-first pipeline rewrite.

2026-03-15_22.30.53 / Codex: revised the plan to make the cross-phase contract explicit. Reason: later phase plans need a clear rule that new stage topology and richer runtime statuses flow through `stage_observability.json`.

2026-03-15_22.42.10 / Codex: harmonized the concrete commands with the repo's current CLI surface by using `cookimport stage --out ...` consistently. Reason: the later phase plans already use `--out`, and the observability plan should not teach a different flag while serving as the cross-phase reference.

2026-03-15_22.52.33 / Codex: revised the plan to name the full cross-phase semantic-stage set explicitly. Reason: Phases 2 through 4 now agree on their handoff contracts, and Phase 1 should be the place that states once, clearly, that those stage keys become product truth only through `stage_observability.json`.

2026-03-15_23.07.00 / Codex: rewrote the plan around a destructive migration philosophy after user clarification. Reason: the earlier draft preserved legacy pass-slot paths, compatibility aliases, and historical fallback readers, which contradicted the intended major-refactor posture of deleting old code and shipping only the new paradigm.
