from __future__ import annotations

from cookimport.bench.qualitysuite.shared import *  # noqa: F401,F403
from cookimport.bench.qualitysuite import shared as _shared

globals().update(
    {name: getattr(_shared, name) for name in dir(_shared) if not name.startswith("__")}
)


def _read_json_object(path: Path, *, context: str) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise ValueError(f"{context} not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Failed to parse {context}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{context} must contain a JSON object.")
    return dict(payload)


class QualityExperiment(BaseModel):
    """One quality experiment definition row."""

    model_config = ConfigDict(extra="forbid")

    id: str
    run_settings_patch: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("id is required")
        if not _EXPERIMENT_ID_PATTERN.match(cleaned):
            raise ValueError(
                "id must be slug-safe: lowercase letters, digits, '_' or '-'"
            )
        return cleaned

class QualityExperimentV2(QualityExperiment):
    """Schema-v2 experiment row with optional all-method runtime knob patching."""

    all_method_runtime_patch: dict[str, Any] = Field(default_factory=dict)

class QualityLever(BaseModel):
    """Schema-v2 lever: a toggleable patch that becomes its own experiment."""

    model_config = ConfigDict(extra="forbid")

    id: str
    enabled: bool = True
    run_settings_patch: dict[str, Any] = Field(default_factory=dict)
    all_method_runtime_patch: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("id is required")
        if not _EXPERIMENT_ID_PATTERN.match(cleaned):
            raise ValueError(
                "id must be slug-safe: lowercase letters, digits, '_' or '-'"
            )
        return cleaned

class _ExperimentFileV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    base_run_settings_file: str | None = None
    experiments: list[QualityExperiment]

    @model_validator(mode="after")
    def _validate_payload(self) -> "_ExperimentFileV1":
        seen_ids: set[str] = set()
        for experiment in self.experiments:
            if experiment.id in seen_ids:
                raise ValueError(f"Duplicate experiment id: {experiment.id}")
            seen_ids.add(experiment.id)
            _validate_patch_keys(
                experiment_id=experiment.id,
                patch=experiment.run_settings_patch,
            )
        if not self.experiments:
            raise ValueError("At least one experiment is required.")
        return self

class _ExperimentFileV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 2
    base_run_settings_file: str | None = None
    include_baseline: bool = True
    baseline_id: str = "baseline"
    include_all_on: bool = False
    all_on_id: str = "all_on"
    all_method_runtime: dict[str, Any] = Field(default_factory=dict)
    experiments: list[QualityExperimentV2] = Field(default_factory=list)
    levers: list[QualityLever] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_payload(self) -> "_ExperimentFileV2":
        for key in ("baseline_id", "all_on_id"):
            value = str(getattr(self, key) or "").strip()
            if not value:
                raise ValueError(f"{key} is required")
            if not _EXPERIMENT_ID_PATTERN.match(value):
                raise ValueError(
                    f"{key} must be slug-safe: lowercase letters, digits, '_' or '-'"
                )

        if self.all_method_runtime:
            _validate_all_method_runtime_patch_keys(
                context_id="all_method_runtime",
                patch=self.all_method_runtime,
            )

        for experiment in self.experiments:
            _validate_patch_keys(
                experiment_id=experiment.id,
                patch=experiment.run_settings_patch,
            )
            if experiment.all_method_runtime_patch:
                _validate_all_method_runtime_patch_keys(
                    context_id=f"experiment '{experiment.id}'",
                    patch=experiment.all_method_runtime_patch,
                )

        for lever in self.levers:
            _validate_patch_keys(
                experiment_id=lever.id,
                patch=lever.run_settings_patch,
            )
            if lever.all_method_runtime_patch:
                _validate_all_method_runtime_patch_keys(
                    context_id=f"lever '{lever.id}'",
                    patch=lever.all_method_runtime_patch,
                )

        if not self.experiments and not self.levers and not self.include_baseline:
            raise ValueError(
                "Schema v2 experiments file must include at least one of: "
                "experiments[], levers[], or include_baseline=true."
            )
        return self

@dataclass(frozen=True)
class _ResolvedExperiment:
    id: str
    run_settings_patch: dict[str, Any]
    requested_run_settings_payload: dict[str, Any]
    requested_run_settings: RunSettings
    run_settings_payload: dict[str, Any]
    run_settings: RunSettings
    all_method_runtime_patch: dict[str, Any]
    all_method_runtime: dict[str, Any]

def _load_experiment_file(path: Path) -> _ExperimentFileV1 | _ExperimentFileV2:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Failed to read experiments file: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Experiments file must contain a JSON object.")
    schema_version = payload.get("schema_version", 1)
    try:
        schema_version_int = int(schema_version)
    except (TypeError, ValueError):
        raise ValueError("schema_version must be an integer.") from None
    if schema_version_int not in _SUPPORTED_EXPERIMENT_SCHEMA_VERSIONS:
        supported = ", ".join(str(v) for v in sorted(_SUPPORTED_EXPERIMENT_SCHEMA_VERSIONS))
        raise ValueError(
            f"Unsupported schema_version {schema_version_int}. Supported: {supported}."
        )
    if schema_version_int == 1:
        return _ExperimentFileV1.model_validate(payload)
    return _ExperimentFileV2.model_validate(payload)

def _resolve_base_run_settings_payload(
    *,
    experiments_file: Path,
    experiment_payload: _ExperimentFileV1 | _ExperimentFileV2,
    base_run_settings_file: Path | None,
) -> dict[str, Any]:
    if base_run_settings_file is not None:
        return _read_json_object(
            base_run_settings_file,
            context="--base-run-settings-file",
        )

    embedded_path = str(experiment_payload.base_run_settings_file or "").strip()
    if embedded_path:
        embedded_candidate = Path(embedded_path)
        if not embedded_candidate.is_absolute():
            embedded_candidate = (experiments_file.parent / embedded_candidate).resolve()
        return _read_json_object(
            embedded_candidate,
            context="experiments.base_run_settings_file",
        )

    default_config = REPO_ROOT / "cookimport.json"
    if not default_config.exists() or not default_config.is_file():
        return {}
    return _read_json_object(default_config, context="cookimport.json")

def _derive_all_method_runtime_base(base_payload: dict[str, Any]) -> dict[str, Any]:
    """Map cookimport.json-style all_method_* keys into all-method runtime kwargs."""
    mapped: dict[str, Any] = {"smart_scheduler": True}
    mapping = {
        "all_method_max_parallel_sources": "max_parallel_sources",
        "all_method_max_inflight_pipelines": "max_inflight_pipelines",
        "all_method_max_split_phase_slots": "max_concurrent_split_phases",
        "all_method_max_eval_tail_pipelines": "max_eval_tail_pipelines",
        "all_method_config_timeout_seconds": "config_timeout_seconds",
        "all_method_retry_failed_configs": "retry_failed_configs",
        "all_method_scheduler_scope": "scheduler_scope",
        "all_method_source_scheduling": "source_scheduling",
        "all_method_source_shard_threshold_seconds": "source_shard_threshold_seconds",
        "all_method_source_shard_max_parts": "source_shard_max_parts",
        "all_method_source_shard_min_variants": "source_shard_min_variants",
        "all_method_wing_backlog_target": "wing_backlog_target",
        "all_method_smart_scheduler": "smart_scheduler",
    }
    for src_key, dst_key in mapping.items():
        if src_key not in base_payload:
            continue
        mapped[dst_key] = base_payload.get(src_key)
    return mapped

def _validate_all_method_runtime_patch_keys(*, context_id: str, patch: dict[str, Any]) -> None:
    unknown_keys = sorted(set(patch) - _ALL_METHOD_RUNTIME_ALLOWED_KEYS)
    if unknown_keys:
        joined = ", ".join(unknown_keys)
        raise ValueError(
            f"{context_id} has unknown all_method_runtime_patch key(s): {joined}"
        )

def _merge_patches_strict(
    *,
    patches: list[tuple[str, dict[str, Any]]],
    kind: str,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    seen: dict[str, tuple[str, Any]] = {}
    for patch_id, patch in patches:
        for key, value in patch.items():
            if key in seen:
                prior_id, prior_value = seen[key]
                if prior_value != value:
                    raise ValueError(
                        f"Conflicting {kind} key {key!r}: {prior_id}={prior_value!r} vs {patch_id}={value!r}"
                    )
                continue
            seen[key] = (patch_id, value)
            merged[key] = value
    return merged

def _validate_qualitysuite_requested_settings_disallow_codex_farm(
    *,
    experiment_id: str,
    payload: dict[str, Any],
) -> None:
    surface = classify_codex_surfaces(payload)
    disallowed_surfaces = [
        name
        for enabled, name in (
            (surface.recipe_codex_enabled, "recipe"),
            (surface.knowledge_codex_enabled, "knowledge"),
        )
        if enabled
    ]
    if disallowed_surfaces:
        joined = ", ".join(disallowed_surfaces)
        raise ValueError(
            "QualitySuite forbids Codex Farm-enabled requested settings. "
            f"Experiment '{experiment_id}' enabled: {joined}."
        )

def _expand_experiments(
    payload: _ExperimentFileV1 | _ExperimentFileV2,
) -> list[QualityExperimentV2]:
    if isinstance(payload, _ExperimentFileV1):
        return [
            QualityExperimentV2(
                id=exp.id,
                run_settings_patch=dict(exp.run_settings_patch),
                all_method_runtime_patch={},
            )
            for exp in payload.experiments
        ]

    experiments: list[QualityExperimentV2] = []
    if payload.include_baseline:
        experiments.append(QualityExperimentV2(id=payload.baseline_id))

    experiments.extend(payload.experiments)

    enabled_levers = [lever for lever in payload.levers if lever.enabled]
    for lever in enabled_levers:
        experiments.append(
            QualityExperimentV2(
                id=lever.id,
                run_settings_patch=dict(lever.run_settings_patch),
                all_method_runtime_patch=dict(lever.all_method_runtime_patch),
            )
        )

    if payload.include_all_on:
        if not enabled_levers:
            raise ValueError("include_all_on=true requires at least one enabled lever.")
        run_settings_patch = _merge_patches_strict(
            patches=[
                (lever.id, dict(lever.run_settings_patch))
                for lever in enabled_levers
                if lever.run_settings_patch
            ],
            kind="run_settings_patch",
        )
        runtime_patch = _merge_patches_strict(
            patches=[
                (lever.id, dict(lever.all_method_runtime_patch))
                for lever in enabled_levers
                if lever.all_method_runtime_patch
            ],
            kind="all_method_runtime_patch",
        )
        experiments.append(
            QualityExperimentV2(
                id=payload.all_on_id,
                run_settings_patch=run_settings_patch,
                all_method_runtime_patch=runtime_patch,
            )
        )

    seen_ids: set[str] = set()
    duplicates: list[str] = []
    for exp in experiments:
        if exp.id in seen_ids:
            duplicates.append(exp.id)
            continue
        seen_ids.add(exp.id)
    if duplicates:
        joined = ", ".join(sorted(set(duplicates)))
        raise ValueError(f"Duplicate experiment id(s) after lever expansion: {joined}")

    if not experiments:
        raise ValueError("No experiments were generated from this experiments file.")
    return experiments

def _resolve_experiments(
    *,
    experiments: list[QualityExperimentV2],
    base_payload: dict[str, Any],
    all_method_runtime_base: dict[str, Any],
) -> list[_ResolvedExperiment]:
    benchmark_base_payload = apply_benchmark_baseline_contract(base_payload)
    resolved: list[_ResolvedExperiment] = []
    for experiment in experiments:
        requested_payload = dict(base_payload)
        requested_payload.update(dict(experiment.run_settings_patch))
        # Reject Codex-enabled requests before benchmark baseline coercion can mask them.
        _validate_qualitysuite_requested_settings_disallow_codex_farm(
            experiment_id=experiment.id,
            payload=requested_payload,
        )
        merged_payload = dict(benchmark_base_payload)
        merged_payload.update(dict(experiment.run_settings_patch))
        requested_run_settings = RunSettings.from_dict(
            project_run_config_payload(
                merged_payload,
                contract=RUN_SETTING_CONTRACT_FULL,
            ),
            warn_context=f"quality-run experiment {experiment.id}",
        )
        requested_run_settings_payload = requested_run_settings.to_run_config_dict()
        run_settings_payload = dict(requested_run_settings_payload)
        run_settings = RunSettings.from_dict(
            project_run_config_payload(
                run_settings_payload,
                contract=RUN_SETTING_CONTRACT_FULL,
            ),
            warn_context=f"quality-run experiment {experiment.id} benchmark baseline",
        )
        runtime_payload = dict(all_method_runtime_base)
        runtime_payload.update(dict(experiment.all_method_runtime_patch))
        resolved.append(
            _ResolvedExperiment(
                id=experiment.id,
                run_settings_patch=dict(experiment.run_settings_patch),
                requested_run_settings_payload=requested_run_settings_payload,
                requested_run_settings=requested_run_settings,
                run_settings_payload=run_settings_payload,
                run_settings=run_settings,
                all_method_runtime_patch=dict(experiment.all_method_runtime_patch),
                all_method_runtime=runtime_payload,
            )
        )
    return resolved

def _validate_patch_keys(*, experiment_id: str, patch: dict[str, Any]) -> None:
    known_fields = set(RunSettings.model_fields) | _RUN_SETTINGS_PATCH_COMPAT_KEYS
    unknown_keys = sorted(set(patch) - known_fields)
    if unknown_keys:
        joined = ", ".join(unknown_keys)
        raise ValueError(
            f"Experiment '{experiment_id}' has unknown run_settings_patch key(s): {joined}"
        )
