---
summary: "ExecPlan for Phase 1 of Refactor.md: fix stage observability first by introducing a shared stage index and routing reporting surfaces through it before changing pipeline logic."
read_when:
  - "When implementing Phase 1 under Recommended Migration Strategy in docs/plans/Refactor.md"
  - "When changing stage naming, run summaries, run manifests, prompt artifacts, or benchmark bundle stage reporting"
  - "When a legacy pass slot such as pass2_schemaorg is reused by merged-repair or another future recipe stage"
---

# Fix Observability Before Pipeline Logic Changes

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `docs/PLANS.md`.

This plan implements only `Phase 1 — Fix observability first` from `docs/plans/Refactor.md`. It is intentionally pre-architecture-change work. Do not change recipe grouping, label-first behavior, or recipe reasoning boundaries in this plan. The purpose here is to make the current system describe itself truthfully before larger logic changes begin.

## Purpose / Big Picture

After this change, a person inspecting any stage run or benchmark prediction run should be able to answer three questions without reading code: what stages existed in this run, what each stage was actually called, and which files belong to each stage. Today those answers are spread across `run_summary.json`, `run_manifest.json`, prompt artifacts, `llm_manifest.json`, pass4 manifests, and benchmark bundle analysis, and some of those surfaces still talk in legacy pass-slot terms even when the live pipeline topology is different.

The user-visible result should be one shared run-level artifact, `stage_observability.json`, that becomes the canonical description of observed stages for the run. `run_summary.json`, `run_summary.md`, `run_manifest.json`, prompt artifact exports, and benchmark upload-bundle rendering should all read from that same stage description instead of maintaining separate hardcoded maps. A merged-repair run should present `Merged Repair` as the actual recipe stage while still exposing `pass2` and `pass2_schemaorg` only as compatibility aliases. A classic three-pass run should still show `Chunking`, `Schema.org Extraction`, and `Final Draft`. A deterministic run should not invent absent LLM stages.

## Progress

- [x] (2026-03-15_22.20.44) Re-read `docs/PLANS.md` before drafting this ExecPlan.
- [x] (2026-03-15_22.20.44) Re-read the relevant section of `docs/plans/Refactor.md`, especially `Recommended Migration Strategy` and `Phase 1 — Fix observability first`.
- [x] (2026-03-15_22.20.44) Read current staging and LLM references in `docs/05-staging/05-staging_readme.md` and `docs/10-llm/10-llm_README.md`.
- [x] (2026-03-15_22.20.44) Surveyed the concrete observability seams in `cookimport/staging/import_session.py`, `cookimport/staging/writer.py`, `cookimport/cli.py`, `cookimport/runs/manifest.py`, `cookimport/llm/prompt_artifacts.py`, and `cookimport/bench/upload_bundle_v1_render.py`.
- [x] (2026-03-15_22.20.44) Recorded the discovery summary in `docs/understandings/2026-03-15_22.20.44-phase1-observability-surface-map.md`.
- [x] (2026-03-15_22.20.44) Wrote this ExecPlan.
- [ ] Implement shared stage observability models and run-level writer under `cookimport/runs/`.
- [ ] Emit `stage_observability.json` for stage runs and prediction-run style outputs, then link it from `run_manifest.json`.
- [ ] Route `run_summary`, prompt artifact export, and upload-bundle stage rendering through the shared stage description instead of local hardcoded maps.
- [ ] Add focused tests for deterministic, three-pass, merged-repair, and pass4 knowledge cases.
- [ ] Update short folder notes and current docs so future reviewers can understand the new observability contract from checked-in documentation alone.

## Surprises & Discoveries

- Observation: the repo already has one good stage-descriptor seam, but it is not the shared source of truth.
  Evidence: `cookimport/llm/prompt_artifacts.py` defines `PromptStageDescriptor` and already derives human-facing stage labels from observed pipeline ids.

- Observation: benchmark upload-bundle rendering is already moving away from fixed pass-slot truth, but stage-run reporting is not yet using the same idea.
  Evidence: `cookimport/bench/upload_bundle_v1_render.py` keeps `pass2_*` and `pass3_*` as compatibility families, while `cookimport/cli.py` still writes run summaries from coarse `codex_farm.recipe_pipeline` / `knowledge_pipeline` / `tags_pipeline` fields.

- Observation: the main observability mismatch is not only prose; it is the absence of one canonical stage artifact.
  Evidence: `cookimport/staging/import_session.py` knows exactly which recipe, knowledge, and writer steps ran, but `run_manifest.json`, prompt export, and benchmark bundle surfaces each rediscover stage truth independently.

- Observation: raw LLM folder names are still legacy-slot names and should not be renamed as part of this first phase.
  Evidence: merged-repair still writes under `raw/llm/<workbook>/pass2_schemaorg/`, and recent prompt-artifact work explicitly treated that as a separate compatibility seam rather than renaming storage.

## Decision Log

- Decision: Phase 1 should add a shared run-level stage index instead of renaming raw `pass1` through `pass5` storage directories.
  Rationale: raw path renames would create broad churn before the larger label-first refactor lands. The observability problem can be solved first by adding truthful metadata and treating legacy path names as compatibility aliases.
  Date/Author: 2026-03-15 / Codex

- Decision: `stage_observability.json` should be the canonical run-level artifact for stage naming and artifact ownership.
  Rationale: today no single file answers “what stages happened here?” for a novice. A stable run-level artifact gives every downstream surface one thing to consume.
  Date/Author: 2026-03-15 / Codex

- Decision: prompt artifact export and upload-bundle rendering should be consumers of shared stage metadata, not owners of separate stage-taxonomy logic.
  Rationale: both surfaces already had to compensate for legacy pass-slot drift. Centralizing stage semantics avoids repeating that repair every time topology changes.
  Date/Author: 2026-03-15 / Codex

- Decision: benchmark and historical compatibility fields may remain, but they must be clearly marked as aliases rather than primary truth.
  Rationale: existing tooling still understands keys such as `pass2_stage` and `pass3_stage`. Keeping them as compatibility views is lower risk than deleting them in the same phase.
  Date/Author: 2026-03-15 / Codex

- Decision: this plan should not change recipe extraction logic, grouping logic, or knowledge-mining scope.
  Rationale: `Refactor.md` explicitly separates observability-first work from the later label-first and recipe-stage redesign. Mixing them would make validation ambiguous and raise regression risk.
  Date/Author: 2026-03-15 / Codex

## Outcomes & Retrospective

Planning outcome only so far: the highest-leverage seam is a shared stage description written once per run and consumed everywhere else. The main implementation risk is not the file write itself; it is keeping `run_summary`, prompt artifact rendering, and upload-bundle compatibility views aligned while preserving old paths and keys for historical runs. The plan below keeps that risk additive by introducing the new artifact first and only then rerouting existing reporting surfaces.

## Context and Orientation

In the current repository, the main single-file stage flow runs through `cookimport/staging/import_session.py::execute_stage_import_session_from_result(...)`. That function applies the optional recipe Codex pipeline, then deterministic table and chunk work, then optional pass4 knowledge harvest, then the writers in `cookimport/staging/writer.py`, then stage-block prediction writing, and finally the report. This is the most truthful place to think about “what stages actually happened,” even though it does not currently emit a dedicated stage topology artifact.

After the per-book work finishes, `cookimport/cli.py` writes run-level artifacts such as `run_summary.json`, `run_summary.md`, and `run_manifest.json`. Those files are stable and widely reused, but right now they are coarse summaries. They tell you which top-level pipeline ids were enabled, yet they do not provide one shared ordered list of observed stages with artifact ownership.

The LLM side adds another layer. `cookimport/llm/codex_farm_orchestrator.py` writes recipe-pass raw data and `llm_manifest.json`. `cookimport/llm/codex_farm_knowledge_orchestrator.py` writes pass4 knowledge raw data and `pass4_knowledge_manifest.json`. `cookimport/llm/prompt_artifacts.py` already understands that a legacy pass slot can be reused by a different semantic stage, which is why merged-repair prompt artifacts can now show `Merged Repair` even though the raw storage still lives under `pass2_schemaorg`.

Benchmarking adds a fourth surface. `cookimport/bench/upload_bundle_v1_render.py` already treats `pass2_*` and `pass3_*` as compatibility families for reviewer output. That was a necessary local fix, but it means benchmark bundles are solving the same naming problem independently from stage runs and prompt artifacts.

For this plan, define the key terms plainly:

A “legacy pass slot” means the old numbered storage or compatibility position such as `pass1`, `pass2`, `pass3`, `pass4`, or `pass5`, including folder names like `pass2_schemaorg`.

A “stage key” means the semantic job that actually ran, such as `chunking`, `schemaorg`, `final`, `merged_repair`, `knowledge`, `tags`, or `write_outputs`.

A “compatibility alias” means an older name that remains present for older files or tooling, but is no longer treated as the main truth shown to humans.

A “stage index” means the new run-level JSON artifact that lists observed stages in execution order, their human-facing labels, compatibility aliases, status, timing, and the files or directories that belong to each stage.

This plan touches these main paths:

- `cookimport/runs/manifest.py` and a new helper module under `cookimport/runs/` for the shared stage observability contract.
- `cookimport/cli.py` for run summary and manifest writing.
- `cookimport/staging/import_session.py` as the canonical stage flow to reflect in the new artifact.
- `cookimport/llm/prompt_artifacts.py` so prompt exports consume shared stage semantics.
- `cookimport/bench/upload_bundle_v1_render.py` and related bundle code so benchmark reporting consumes the same semantics.
- `docs/05-staging/05-staging_readme.md`, `docs/10-llm/10-llm_README.md`, and `cookimport/runs/README.md` so the new contract is documented where future work will look for it.

## Milestones

### Milestone 1: Introduce a shared stage observability contract

At the end of this milestone, the repo will have one module under `cookimport/runs/` that can describe the observed stage topology of a run without depending on any one output surface. A novice should be able to read this module and understand how stage truth is represented in this repo.

Create `cookimport/runs/stage_observability.py`. Use explicit models, preferably mirroring the repo’s existing style in `cookimport/runs/manifest.py`. The artifact written by this module should be `stage_observability.json` under the run root and should use a stable schema version such as `stage_observability.v1`.

The payload must include an ordered `stages` list. Each stage row must carry, at minimum, a stable `stage_key`, a human-facing `stage_label`, an optional `legacy_slot`, explicit `compatibility_aliases`, a `status`, a `stage_group`, an optional timing summary, and artifact references. Those artifact references should point to existing files and directories rather than inventing new duplicate payloads. The stage index is supposed to explain what already exists, not copy it.

For merged-repair and similar future cases, the model must support “semantic stage differs from legacy slot.” That means a row like `stage_key=merged_repair` can coexist with `legacy_slot=pass2` and `compatibility_aliases=["pass2", "pass2_schemaorg"]`.

Acceptance for this milestone is a focused test file, such as `tests/staging/test_stage_observability.py`, that can build stage-observability payloads for at least these cases: deterministic-only run, classic three-pass recipe run, merged-repair recipe run, and pass4 knowledge-enabled run.

### Milestone 2: Emit the stage index from real run roots and link it from manifests

At the end of this milestone, real stage runs and prediction-run-style outputs will write `stage_observability.json`, and `run_manifest.json` will point to it directly.

Implement a builder that works from the run root and existing manifests or reports instead of from ephemeral in-memory state only. That builder should discover current stage truth from artifacts already present in the run root: `llm_manifest.json`, pass4/pass5 manifests, prompt descriptors where helpful, stage reports, and the known staged output directories.

Update `cookimport/cli.py` so `stage_observability.json` is written before `run_manifest.json` and `run_summary.json` are finalized. `run_manifest.json` must gain a stable artifact key such as `stage_observability_json`. Do not remove existing artifact keys in this milestone. Add the new key and keep the old ones intact.

If prediction-run or eval-style roots already have enough information to write the same artifact, route them through the same helper. When a historical run root does not contain enough information, the helper must degrade gracefully and emit the best truthful subset instead of failing.

Acceptance for this milestone is that `tests/staging/test_run_manifest_parity.py` still passes and that new tests verify the new manifest artifact key and the presence of `stage_observability.json` in newly written run roots.

### Milestone 3: Make summaries and prompt exports consume the shared stage description

At the end of this milestone, the main human-facing stage summaries inside stage runs will no longer rely on their own separate hardcoded stage maps.

Update `cookimport/cli.py::_build_stage_run_summary_payload(...)` and `_write_stage_run_summary(...)` so the summary includes an ordered view of observed stages derived from `stage_observability.json`. Keep the existing coarse `codex_farm` block for backward readability, but add a new explicit `observed_stages` section in the JSON payload and a short “Observed stages” section in the markdown summary. The human-facing labels in this section must come from the stage index, not from local string heuristics.

Then update `cookimport/llm/prompt_artifacts.py` to consume shared stage metadata instead of owning a separate stage taxonomy. It is acceptable to keep prompt-export-specific rendering classes such as `PromptStageDescriptor`, but they should be built from shared stage semantics rather than from duplicate maps. The goal is that the logic that knows `merged_repair` is a semantic stage and `pass2_schemaorg` is a compatibility storage folder should exist in one place.

Acceptance for this milestone is that the existing prompt-artifact regression slice, especially `tests/labelstudio/test_labelstudio_benchmark_helpers_artifacts.py`, still passes and that a merged-repair fixture continues to render `Merged Repair` as the primary stage label.

### Milestone 4: Route benchmark upload-bundle rendering through the same stage truth

At the end of this milestone, benchmark bundle rendering will still expose compatibility families where needed, but it will no longer maintain an independent notion of what the run’s primary stage names are.

Use the same shared stage builder or a thin adapter over it inside the bundle flow. When an existing root contains `stage_observability.json`, prefer it. When it does not, fall back to the existing normalized model and compatibility logic. This fallback matters because historical benchmark roots already exist in the repository.

The existing compatibility views such as `analysis.stage_separated_comparison`, `pass2_stage`, and `pass3_stage` may remain, but they must be explicitly labeled as compatibility-only renderings when the semantic stage topology differs. Do not regress the recent upload-bundle flexibility work by reintroducing fixed-stage assumptions deeper in the renderer.

Acceptance for this milestone is that `tests/bench/test_upload_bundle_v1_existing_output.py` and `tests/bench/test_benchmark_cutdown_for_external_ai.py` still pass, including the merged-repair compatibility assertions already present there.

### Milestone 5: Document the contract and prove it on real runs

At the end of this milestone, a future contributor can inspect the docs and one real run root and understand the new observability boundary without reading this plan first.

Update `docs/05-staging/05-staging_readme.md` to describe the new `stage_observability.json` artifact and where it is written. Update `docs/10-llm/10-llm_README.md` to explain that recipe and knowledge manifests are inputs to the stage index rather than separate stage-taxonomy sources. Update `cookimport/runs/README.md` with a short note describing `run_manifest.json` plus `stage_observability.json` as the paired run-level observability contract.

Then run at least one real stage import and inspect the output. Prefer `data/input/saltfatacidheatCUTDOWN.epub` because it already exists in the repo and exercises real stage output paths. If live Codex execution is available, run both a deterministic baseline and a merged-repair recipe pipeline case. If live Codex execution is not available, keep the proof limited to deterministic execution plus the targeted test slices and record that limitation in this plan.

Acceptance for this milestone is that a real run root contains `stage_observability.json`, `run_summary.json`, `run_summary.md`, and `run_manifest.json` that all agree on the stage topology.

## Plan of Work

Start by introducing the shared stage description as an additive artifact, not as a rewrite of raw storage. The simplest durable move is to define one explicit model and writer under `cookimport/runs/` and then teach existing reporting surfaces to read that model. This follows the same pattern that already improved upload-bundle flexibility: create a normalized representation first, then render different compatibility views from it.

Use the current prompt-artifact stage descriptor work as seed material, but do not merely import that module everywhere. The prompt exporter is a consumer. The new run-level module should own the stage taxonomy and discovery rules; prompt export should adapt that shared data to its rendering-specific needs.

Keep the first version truthful rather than ambitious. The stage index does not need to predict future label-first stages yet. It needs to describe the current implementation accurately. That means it should represent the current extract-or-convert phase, optional recipe Codex stages, optional knowledge or tag stages, and the writer phase as they exist today. It should also say when a semantic stage reused a legacy pass slot.

Once the new artifact exists, reroute `run_summary` and `run_manifest` first. Those are the lowest-risk consumers and the easiest place to prove the contract is useful. Prompt artifact export and benchmark bundle rendering should come next because they already solve adjacent naming problems and can now delete duplicated stage-mapping logic.

Do not rename directories like `pass2_schemaorg` or remove compatibility fields like `pass2_stage` in this plan. Instead, preserve them under explicit compatibility metadata. The point is to make the system honest before making it cleaner.

## Concrete Steps

Work from `/home/mcnal/projects/recipeimport`.

Prepare the environment:

    source .venv/bin/activate
    pip install -e .[dev]

Before implementation, run the current cross-surface regression slice:

    source .venv/bin/activate
    pytest tests/staging/test_run_manifest_parity.py tests/labelstudio/test_labelstudio_benchmark_helpers_artifacts.py tests/bench/test_upload_bundle_v1_existing_output.py tests/bench/test_benchmark_cutdown_for_external_ai.py -q

Expected baseline outcome:

    compact pytest output; command exits 0

After introducing the new shared module, add and run a focused test file for the new contract:

    source .venv/bin/activate
    pytest tests/staging/test_stage_observability.py -q

Expected outcome after Milestone 1:

    compact pytest output; command exits 0

After routing manifests and summaries:

    source .venv/bin/activate
    pytest tests/staging/test_run_manifest_parity.py -q

After routing prompt artifacts:

    source .venv/bin/activate
    pytest tests/labelstudio/test_labelstudio_benchmark_helpers_artifacts.py -q

After routing upload-bundle rendering:

    source .venv/bin/activate
    pytest tests/bench/test_upload_bundle_v1_existing_output.py tests/bench/test_benchmark_cutdown_for_external_ai.py -q

Then run one real deterministic stage import:

    source .venv/bin/activate
    cookimport stage data/input/saltfatacidheatCUTDOWN.epub --output-root /tmp/phase1-observability-det

Expected outcome:

    a new timestamped run root under /tmp/phase1-observability-det containing run_manifest.json, run_summary.json, run_summary.md, and stage_observability.json

If live Codex execution is available, also run a merged-repair example:

    source .venv/bin/activate
    cookimport stage data/input/saltfatacidheatCUTDOWN.epub --output-root /tmp/phase1-observability-merged --llm-recipe-pipeline codex-farm-2stage-repair-v1 --llm-knowledge-pipeline codex-farm-knowledge-v1 --codex-execution-policy execute

Expected outcome:

    the run root still contains stage_observability.json, and the primary recipe stage label is Merged Repair rather than pass2 schemaorg

Inspect the new artifact directly:

    source .venv/bin/activate
    python - <<'PY'
    from pathlib import Path
    import json

    run_root = max(Path("/tmp/phase1-observability-det").glob("*/"), key=lambda p: p.name)
    payload = json.loads((run_root / "stage_observability.json").read_text(encoding="utf-8"))
    print(payload["schema_version"])
    for stage in payload.get("stages", []):
        print(stage["stage_key"], "=>", stage["stage_label"], stage.get("compatibility_aliases", []))
    PY

Expected transcript shape:

    stage_observability.v1
    ...
    write_outputs => Write Outputs [...]

## Validation and Acceptance

The change is accepted only if the same stage naming is visible across every major reporting surface for the same run root.

For a deterministic stage run, `stage_observability.json` must exist and must not claim absent recipe LLM stages. `run_summary.json` and `run_summary.md` must include an ordered observed-stage view derived from that file. `run_manifest.json` must point to `stage_observability.json`.

For a classic three-pass recipe run, the stage index must include semantic recipe stages for `chunking`, `schemaorg`, and `final`, plus any optional knowledge or tags stages that actually ran. Prompt artifact outputs must use those semantic labels as their main display names.

For a merged-repair recipe run, the stage index must show `merged_repair` as the primary recipe correction stage and must not fabricate a `final` LLM stage that did not run. If legacy names such as `pass2` or `pass2_schemaorg` are present, they must appear only as compatibility aliases.

For benchmark upload-bundle rendering, the compatibility views may still expose `pass2_stage` and `pass3_stage`, but the renderer must derive those from the shared stage semantics or from an equivalent compatibility adapter over the same model. Historical roots without `stage_observability.json` must still render successfully through fallback logic.

## Idempotence and Recovery

Writing `stage_observability.json`, `run_summary.json`, and `run_summary.md` must be safe to repeat. If a run root already contains those files, the writer should overwrite them deterministically from the current discovered artifacts.

If a run root lacks optional manifests such as `llm_manifest.json` or `pass4_knowledge_manifest.json`, stage-observability generation must degrade gracefully and emit only the stages that can be supported by evidence already on disk. Missing optional artifacts should produce absent stages or compatibility notes, not hard failures.

If a downstream surface such as prompt export or upload-bundle rendering has not yet been migrated, the new stage index must not block the old behavior. This plan is additive first. Routing changes can land surface by surface while keeping the repo usable.

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
          "legacy_slot": "pass2",
          "compatibility_aliases": ["pass2", "pass2_schemaorg"],
          "status": "completed"
        }
      ]
    }

The important thing is not the exact JSON formatting. The important thing is that the semantic stage and the compatibility alias are both visible and clearly separated.

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
        legacy_slot: str | None = None
        compatibility_aliases: list[str] = Field(default_factory=list)
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
    ) -> StageObservabilityReport:
        ...

    def write_stage_observability_report(
        run_root: Path,
        report: StageObservabilityReport,
    ) -> Path:
        ...

In `cookimport/cli.py`, call this writer before `_write_stage_run_manifest(...)` and `_write_stage_run_summary(...)` so both surfaces can consume the new artifact.

In `cookimport/llm/prompt_artifacts.py`, keep prompt-export-specific rendering helpers, but move stage taxonomy ownership out of local hardcoded maps and onto the shared stage-observability helpers or a shared stage-label registry extracted from them.

In benchmark bundle code, prefer `stage_observability.json` when present, but keep fallback compatibility inference for historical roots already checked into `data/golden/`.

2026-03-15_22.20.44 / Codex: created this ExecPlan from `docs/plans/Refactor.md` Phase 1 after surveying the current stage, manifest, prompt-artifact, and upload-bundle observability seams. The plan chooses a shared run-level stage index as the minimal truthful seam that can land before any label-first pipeline rewrite.
