from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from cookimport.llm.codex_farm_ids import sanitize_for_filename
from cookimport.llm.codex_farm_runner import (
    CodexFarmRunner,
    CodexFarmRunnerError,
    SubprocessCodexFarmRunner,
    ensure_codex_farm_pipelines_exist,
    resolve_codex_farm_output_schema_path,
)
from cookimport.tagging.catalog import TagCatalog
from cookimport.tagging.engine import TagSuggestion
from cookimport.tagging.signals import RecipeSignalPack

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TagCandidate:
    tag_key_norm: str
    display_name: str


@dataclass(frozen=True, slots=True)
class CodexFarmTagsJob:
    recipe_key: str
    recipe_id: str
    signals: RecipeSignalPack
    missing_categories: tuple[str, ...]
    candidates_by_category: dict[str, tuple[TagCandidate, ...]]


@dataclass(frozen=True, slots=True)
class CodexFarmTagsPassResult:
    suggestions_by_recipe: dict[str, list[TagSuggestion]]
    new_tag_proposals_by_recipe: dict[str, list[dict[str, str]]]
    llm_validation: dict[str, Any]
    llm_report: dict[str, Any]
    manifest_path: Path | None = None


class SelectedTagV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag_key_norm: str
    category_key_norm: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str

    @field_validator("tag_key_norm", "category_key_norm", "evidence", mode="before")
    @classmethod
    def _normalize_text(cls, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("text value must be non-empty")
        return text

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: object) -> float:
        return float(value)


class NewTagProposalV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposed_category: str
    display_name: str
    rationale: str

    @field_validator("proposed_category", "display_name", "rationale", mode="before")
    @classmethod
    def _normalize_text(cls, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("text value must be non-empty")
        return text


class Pass5TagsOutputV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_version: str
    recipe_id: str
    selected_tags: list[SelectedTagV1] = Field(default_factory=list)
    new_tag_proposals: list[NewTagProposalV1] = Field(default_factory=list)

    @field_validator("bundle_version", mode="before")
    @classmethod
    def _validate_bundle_version(cls, value: object) -> str:
        rendered = str(value or "").strip()
        if rendered != "1":
            raise ValueError("bundle_version must be '1'")
        return rendered

    @field_validator("recipe_id", mode="before")
    @classmethod
    def _normalize_recipe_id(cls, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("recipe_id must be non-empty")
        return text


def run_codex_farm_tags_pass(
    *,
    jobs: Sequence[CodexFarmTagsJob],
    catalog: TagCatalog,
    pipeline_id: str,
    codex_farm_cmd: str = "codex-farm",
    codex_farm_model: str | None = None,
    codex_farm_reasoning_effort: str | None = None,
    codex_farm_root: Path | str | None = None,
    codex_farm_workspace_root: Path | str | None = None,
    runner: CodexFarmRunner | None = None,
    raw_pass_dir: Path | None = None,
) -> CodexFarmTagsPassResult:
    if not jobs:
        return CodexFarmTagsPassResult(
            suggestions_by_recipe={},
            new_tag_proposals_by_recipe={},
            llm_validation={
                "jobs_requested": 0,
                "jobs_executed": 0,
                "outputs_read": 0,
                "missing_output_files": 0,
                "schema_invalid_outputs": 0,
                "selected_entries_seen": 0,
                "selected_entries_accepted": 0,
                "selected_entries_dropped": 0,
                "drop_reasons": {},
            },
            llm_report={"enabled": False, "pipeline_id": pipeline_id, "counts": {"jobs_written": 0}},
            manifest_path=None,
        )

    pipeline_root = _resolve_pipeline_root(codex_farm_root)
    workspace_root = _resolve_workspace_root(codex_farm_workspace_root)
    codex_runner = runner or SubprocessCodexFarmRunner(cmd=codex_farm_cmd)
    env = {"CODEX_FARM_ROOT": str(pipeline_root)}
    output_schema_path: str | None = None
    if runner is None:
        ensure_codex_farm_pipelines_exist(
            cmd=codex_farm_cmd,
            root_dir=pipeline_root,
            pipeline_ids=(pipeline_id,),
            env=env,
        )
        output_schema_path = str(
            resolve_codex_farm_output_schema_path(
                root_dir=pipeline_root,
                pipeline_id=pipeline_id,
            )
        )
    started = time.perf_counter()

    if raw_pass_dir is None:
        with TemporaryDirectory(prefix="cookimport-pass5-tags-") as temp_dir:
            temp_root = Path(temp_dir)
            return _run_with_dirs(
                jobs=jobs,
                catalog=catalog,
                pipeline_id=pipeline_id,
                codex_runner=codex_runner,
                env=env,
                in_dir=temp_root / "in",
                out_dir=temp_root / "out",
                pipeline_root=pipeline_root,
                workspace_root=workspace_root,
                codex_farm_model=codex_farm_model,
                codex_farm_reasoning_effort=codex_farm_reasoning_effort,
                started=started,
                manifest_path=None,
                output_schema_path=output_schema_path,
            )

    in_dir = raw_pass_dir / "in"
    out_dir = raw_pass_dir / "out"
    manifest_path = raw_pass_dir.parent / "pass5_tags_manifest.json"
    return _run_with_dirs(
        jobs=jobs,
        catalog=catalog,
        pipeline_id=pipeline_id,
        codex_runner=codex_runner,
        env=env,
        in_dir=in_dir,
        out_dir=out_dir,
        pipeline_root=pipeline_root,
        workspace_root=workspace_root,
        codex_farm_model=codex_farm_model,
        codex_farm_reasoning_effort=codex_farm_reasoning_effort,
        started=started,
        manifest_path=manifest_path,
        output_schema_path=output_schema_path,
    )


def _run_with_dirs(
    *,
    jobs: Sequence[CodexFarmTagsJob],
    catalog: TagCatalog,
    pipeline_id: str,
    codex_runner: CodexFarmRunner,
    env: Mapping[str, str],
    in_dir: Path,
    out_dir: Path,
    pipeline_root: Path,
    workspace_root: Path | None,
    codex_farm_model: str | None,
    codex_farm_reasoning_effort: str | None,
    started: float,
    manifest_path: Path | None,
    output_schema_path: str | None,
) -> CodexFarmTagsPassResult:
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    filenames_by_recipe_key: dict[str, str] = {}
    jobs_by_filename: dict[str, CodexFarmTagsJob] = {}
    for index, job in enumerate(jobs):
        filename = _job_filename(job, index=index)
        payload = _build_job_payload(job)
        _write_json(payload, in_dir / filename)
        filenames_by_recipe_key[job.recipe_key] = filename
        jobs_by_filename[filename] = job

    codex_runner.run_pipeline(
        pipeline_id,
        in_dir,
        out_dir,
        env,
        root_dir=pipeline_root,
        workspace_root=workspace_root,
        model=codex_farm_model,
        reasoning_effort=codex_farm_reasoning_effort,
    )

    suggestions_by_recipe: dict[str, list[TagSuggestion]] = {job.recipe_key: [] for job in jobs}
    proposals_by_recipe: dict[str, list[dict[str, str]]] = {job.recipe_key: [] for job in jobs}

    outputs_read = 0
    missing_output_files = 0
    schema_invalid_outputs = 0
    selected_entries_seen = 0
    selected_entries_accepted = 0
    selected_entries_dropped = 0
    drop_reasons: dict[str, int] = {}

    for filename, job in jobs_by_filename.items():
        out_path = out_dir / filename
        if not out_path.exists():
            missing_output_files += 1
            _increment(drop_reasons, "missing_output_file")
            continue

        try:
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            parsed = Pass5TagsOutputV1.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            schema_invalid_outputs += 1
            _increment(drop_reasons, "schema_validation_failed")
            logger.warning("Invalid pass5 tags output %s: %s", out_path, exc)
            continue

        outputs_read += 1
        if parsed.recipe_id != job.recipe_id:
            schema_invalid_outputs += 1
            _increment(drop_reasons, "recipe_id_mismatch")
            logger.warning(
                "Pass5 output recipe_id mismatch for %s: expected=%s got=%s",
                out_path,
                job.recipe_id,
                parsed.recipe_id,
            )
            continue

        allowed_by_category = {
            category_key: {candidate.tag_key_norm for candidate in candidates}
            for category_key, candidates in job.candidates_by_category.items()
        }

        for selected in parsed.selected_tags:
            selected_entries_seen += 1
            reason = _reject_reason_for_selected(
                selected=selected,
                job=job,
                catalog=catalog,
                allowed_by_category=allowed_by_category,
            )
            if reason is not None:
                selected_entries_dropped += 1
                _increment(drop_reasons, reason)
                continue

            selected_entries_accepted += 1
            evidence = selected.evidence.strip() or "LLM suggestion"
            suggestions_by_recipe[job.recipe_key].append(
                TagSuggestion(
                    tag_key=selected.tag_key_norm,
                    category_key=selected.category_key_norm,
                    confidence=float(selected.confidence),
                    evidence=[f"LLM: {evidence}"],
                    source="llm",
                    llm_pipeline_id=pipeline_id,
                )
            )

        proposals_by_recipe[job.recipe_key] = [
            {
                "proposed_category": proposal.proposed_category,
                "display_name": proposal.display_name,
                "rationale": proposal.rationale,
            }
            for proposal in parsed.new_tag_proposals
        ]

    elapsed_seconds = round(time.perf_counter() - started, 3)
    llm_validation: dict[str, Any] = {
        "jobs_requested": len(jobs),
        "jobs_executed": len(jobs),
        "outputs_read": outputs_read,
        "missing_output_files": missing_output_files,
        "schema_invalid_outputs": schema_invalid_outputs,
        "selected_entries_seen": selected_entries_seen,
        "selected_entries_accepted": selected_entries_accepted,
        "selected_entries_dropped": selected_entries_dropped,
        "drop_reasons": dict(sorted(drop_reasons.items())),
    }
    llm_report: dict[str, Any] = {
        "enabled": True,
        "pipeline_id": pipeline_id,
        "output_schema_path": output_schema_path,
        "counts": {
            "jobs_written": len(jobs),
            "outputs_read": outputs_read,
            "missing_output_files": missing_output_files,
            "schema_invalid_outputs": schema_invalid_outputs,
            "selected_entries_accepted": selected_entries_accepted,
            "selected_entries_dropped": selected_entries_dropped,
        },
        "timing": {"total_seconds": elapsed_seconds},
        "paths": {"in_dir": str(in_dir), "out_dir": str(out_dir)},
    }
    if manifest_path is not None:
        _write_json({"llm_report": llm_report, "llm_validation": llm_validation}, manifest_path)

    for recipe_key, suggestions in suggestions_by_recipe.items():
        suggestions.sort(key=lambda item: (item.category_key, -item.confidence, item.tag_key))
        if recipe_key not in proposals_by_recipe:
            proposals_by_recipe[recipe_key] = []

    return CodexFarmTagsPassResult(
        suggestions_by_recipe=suggestions_by_recipe,
        new_tag_proposals_by_recipe=proposals_by_recipe,
        llm_validation=llm_validation,
        llm_report=llm_report,
        manifest_path=manifest_path,
    )


def _build_job_payload(job: CodexFarmTagsJob) -> dict[str, Any]:
    return {
        "bundle_version": "1",
        "recipe_id": job.recipe_id,
        "title": job.signals.title,
        "description": job.signals.description or None,
        "notes": job.signals.notes or None,
        "ingredients": [str(line).strip() for line in job.signals.ingredients if str(line).strip()],
        "instructions": [str(line).strip() for line in job.signals.instructions if str(line).strip()],
        "missing_categories": list(job.missing_categories),
        "candidates_by_category": {
            category_key: [
                {"tag_key_norm": candidate.tag_key_norm, "display_name": candidate.display_name}
                for candidate in candidates
            ]
            for category_key, candidates in job.candidates_by_category.items()
        },
    }


def _job_filename(job: CodexFarmTagsJob, *, index: int) -> str:
    slug = sanitize_for_filename(job.recipe_key) or f"recipe_{index:04d}"
    return f"{index:04d}_{slug}.json"


def _reject_reason_for_selected(
    *,
    selected: SelectedTagV1,
    job: CodexFarmTagsJob,
    catalog: TagCatalog,
    allowed_by_category: Mapping[str, set[str]],
) -> str | None:
    if selected.category_key_norm not in set(job.missing_categories):
        return "category_not_requested"
    tag = catalog.tags_by_key.get(selected.tag_key_norm)
    if tag is None:
        return "unknown_tag_key_norm"
    actual_category = catalog.category_key_for_tag(selected.tag_key_norm)
    if actual_category != selected.category_key_norm:
        return "category_mismatch"
    allowed = allowed_by_category.get(selected.category_key_norm, set())
    if selected.tag_key_norm not in allowed:
        return "tag_not_in_shortlist"
    return None


def _resolve_pipeline_root(value: Path | str | None) -> Path:
    if value:
        root = Path(value).expanduser()
    else:
        root = Path(__file__).resolve().parents[2] / "llm_pipelines"
    required = ("pipelines", "prompts", "schemas")
    missing = [name for name in required if not (root / name).exists()]
    if missing:
        raise CodexFarmRunnerError(
            "Invalid codex-farm pipeline root "
            f"{root}: missing {', '.join(missing)}."
        )
    return root


def _resolve_workspace_root(value: Path | str | None) -> Path | None:
    if not value:
        return None
    root = Path(value).expanduser()
    if not root.exists() or not root.is_dir():
        raise CodexFarmRunnerError(
            f"Invalid codex-farm workspace root {root}: path does not exist or is not a directory."
        )
    return root


def _increment(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _write_json(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
