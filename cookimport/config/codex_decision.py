from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

TopTierProfileKind = Literal["codexfarm", "vanilla"]
BenchmarkVariantKind = Literal["vanilla", "codexfarm"]
CodexExecutionPolicyMode = Literal["execute", "plan"]

RECIPE_CODEX_PIPELINE = "codex-farm-3pass-v1"
LINE_ROLE_CODEX_PIPELINE = "codex-line-role-v1"
LINE_ROLE_DETERMINISTIC_PIPELINE = "deterministic-v1"
KNOWLEDGE_CODEX_PIPELINE = "codex-farm-knowledge-v1"
TAGS_CODEX_PIPELINE = "codex-farm-tags-v1"
PRELABEL_CODEX_PROVIDER = "codex-cli"
COMPACT_PASS2_PIPELINE = "recipe.schemaorg.compact.v1"
COMPACT_PASS3_PIPELINE = "recipe.final.compact.v1"

_TOP_TIER_PARSER_STACK_PATCH: dict[str, Any] = {
    "epub_extractor": "unstructured",
    "epub_unstructured_html_parser_version": "v1",
    "epub_unstructured_preprocess_mode": "semantic_v1",
    "epub_unstructured_skip_headers_footers": True,
    "section_detector_backend": "shared_v1",
    "multi_recipe_splitter": "rules_v1",
    "instruction_step_segmentation_policy": "always",
    "instruction_step_segmenter": "heuristic_v1",
    "pdf_ocr_policy": "off",
    "codex_farm_pass1_pattern_hints_enabled": False,
    "codex_farm_pass3_skip_pass2_ok": True,
    "codex_farm_pipeline_pass2": COMPACT_PASS2_PIPELINE,
    "codex_farm_pipeline_pass3": COMPACT_PASS3_PIPELINE,
}
_TOP_TIER_CODEXFARM_PATCH: dict[str, Any] = {
    **_TOP_TIER_PARSER_STACK_PATCH,
    "llm_recipe_pipeline": RECIPE_CODEX_PIPELINE,
    "llm_knowledge_pipeline": KNOWLEDGE_CODEX_PIPELINE,
    "line_role_pipeline": LINE_ROLE_CODEX_PIPELINE,
    "atomic_block_splitter": "atomic-v1",
}
_TOP_TIER_VANILLA_PATCH: dict[str, Any] = {
    **_TOP_TIER_PARSER_STACK_PATCH,
    "llm_recipe_pipeline": "off",
    "llm_knowledge_pipeline": "off",
    "llm_tags_pipeline": "off",
    "line_role_pipeline": LINE_ROLE_DETERMINISTIC_PIPELINE,
    "atomic_block_splitter": "atomic-v1",
}
_BENCHMARK_BASELINE_PATCH: dict[str, Any] = dict(_TOP_TIER_VANILLA_PATCH)
_BENCHMARK_CODEXFARM_PATCH: dict[str, Any] = {
    "llm_recipe_pipeline": RECIPE_CODEX_PIPELINE,
    "llm_knowledge_pipeline": KNOWLEDGE_CODEX_PIPELINE,
    "line_role_pipeline": LINE_ROLE_CODEX_PIPELINE,
    "atomic_block_splitter": "atomic-v1",
    "codex_farm_pass1_pattern_hints_enabled": False,
    "codex_farm_pass3_skip_pass2_ok": True,
    "codex_farm_pipeline_pass2": COMPACT_PASS2_PIPELINE,
    "codex_farm_pipeline_pass3": COMPACT_PASS3_PIPELINE,
}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _surface_list(*pairs: tuple[bool, str]) -> tuple[str, ...]:
    return tuple(name for enabled, name in pairs if enabled)


@dataclass(frozen=True)
class CodexSurfaceDecision:
    recipe_pipeline: str
    line_role_pipeline: str
    knowledge_pipeline: str
    tags_pipeline: str
    prelabel_provider: str
    recipe_codex_enabled: bool
    line_role_codex_enabled: bool
    deterministic_line_role_enabled: bool
    knowledge_codex_enabled: bool
    tags_codex_enabled: bool
    prelabel_codex_enabled: bool
    any_codex_enabled: bool
    codex_surfaces: tuple[str, ...]
    deterministic_surfaces: tuple[str, ...]
    ai_assistance_profile: str


@dataclass(frozen=True)
class CodexCommandDecision:
    context: str
    surface: CodexSurfaceDecision
    codex_requested: bool
    explicit_activation_required: bool
    explicit_activation_granted: bool
    activation_mode: str
    benchmark_variant: str | None = None

    @property
    def allowed(self) -> bool:
        return (not self.explicit_activation_required) or self.explicit_activation_granted


@dataclass(frozen=True)
class CodexExecutionPolicy:
    command_decision: CodexCommandDecision
    requested_mode: CodexExecutionPolicyMode
    resolved_mode: str
    plan_only: bool
    live_llm_allowed: bool

    @property
    def surface(self) -> CodexSurfaceDecision:
        return self.command_decision.surface

    @property
    def codex_requested(self) -> bool:
        return self.command_decision.codex_requested

    @property
    def blocked(self) -> bool:
        return self.requested_mode == "execute" and not self.command_decision.allowed

    @property
    def allowed(self) -> bool:
        return not self.blocked


def classify_codex_surfaces(payload: Mapping[str, Any] | None) -> CodexSurfaceDecision:
    normalized_payload = payload or {}
    recipe_pipeline = _normalize_text(normalized_payload.get("llm_recipe_pipeline") or "off")
    line_role_pipeline = _normalize_text(normalized_payload.get("line_role_pipeline") or "off")
    knowledge_pipeline = _normalize_text(
        normalized_payload.get("llm_knowledge_pipeline") or "off"
    )
    tags_pipeline = _normalize_text(normalized_payload.get("llm_tags_pipeline") or "off")
    prelabel_provider = _normalize_text(
        normalized_payload.get("prelabel_provider")
        or (
            PRELABEL_CODEX_PROVIDER
            if bool(
                normalized_payload.get("prelabel")
                or normalized_payload.get("prelabel_enabled")
            )
            else "off"
        )
    )

    recipe_codex_enabled = recipe_pipeline == RECIPE_CODEX_PIPELINE
    line_role_codex_enabled = line_role_pipeline == LINE_ROLE_CODEX_PIPELINE
    deterministic_line_role_enabled = line_role_pipeline == LINE_ROLE_DETERMINISTIC_PIPELINE
    knowledge_codex_enabled = knowledge_pipeline == KNOWLEDGE_CODEX_PIPELINE
    tags_codex_enabled = tags_pipeline == TAGS_CODEX_PIPELINE
    prelabel_codex_enabled = bool(
        normalized_payload.get("prelabel") or normalized_payload.get("prelabel_enabled")
    ) and prelabel_provider in {"", PRELABEL_CODEX_PROVIDER}
    any_codex_enabled = any(
        (
            recipe_codex_enabled,
            line_role_codex_enabled,
            knowledge_codex_enabled,
            tags_codex_enabled,
            prelabel_codex_enabled,
        )
    )
    codex_surfaces = _surface_list(
        (recipe_codex_enabled, "recipe"),
        (line_role_codex_enabled, "line_role"),
        (knowledge_codex_enabled, "knowledge"),
        (tags_codex_enabled, "tags"),
        (prelabel_codex_enabled, "prelabel"),
    )
    deterministic_surfaces = _surface_list(
        (deterministic_line_role_enabled, "line_role"),
    )
    recipe_family_codex_enabled = any(
        (
            recipe_codex_enabled,
            knowledge_codex_enabled,
            tags_codex_enabled,
        )
    )
    if recipe_family_codex_enabled and line_role_codex_enabled:
        ai_assistance_profile = "full_stack"
    elif recipe_family_codex_enabled:
        ai_assistance_profile = "recipe_only"
    elif line_role_codex_enabled:
        ai_assistance_profile = "line_role_only"
    elif any(
        key in normalized_payload
        for key in (
            "llm_recipe_pipeline",
            "line_role_pipeline",
            "llm_knowledge_pipeline",
            "llm_tags_pipeline",
        )
    ):
        ai_assistance_profile = "deterministic"
    else:
        ai_assistance_profile = "other"

    return CodexSurfaceDecision(
        recipe_pipeline=recipe_pipeline,
        line_role_pipeline=line_role_pipeline,
        knowledge_pipeline=knowledge_pipeline,
        tags_pipeline=tags_pipeline,
        prelabel_provider=prelabel_provider,
        recipe_codex_enabled=recipe_codex_enabled,
        line_role_codex_enabled=line_role_codex_enabled,
        deterministic_line_role_enabled=deterministic_line_role_enabled,
        knowledge_codex_enabled=knowledge_codex_enabled,
        tags_codex_enabled=tags_codex_enabled,
        prelabel_codex_enabled=prelabel_codex_enabled,
        any_codex_enabled=any_codex_enabled,
        codex_surfaces=codex_surfaces,
        deterministic_surfaces=deterministic_surfaces,
        ai_assistance_profile=ai_assistance_profile,
    )


def codex_surfaces_enabled(payload: Mapping[str, Any] | None) -> bool:
    return classify_codex_surfaces(payload).any_codex_enabled


def apply_top_tier_profile_contract(
    payload: Mapping[str, Any],
    profile: TopTierProfileKind,
) -> dict[str, Any]:
    normalized = dict(payload)
    if profile == "vanilla":
        normalized.update(_TOP_TIER_VANILLA_PATCH)
    else:
        normalized.update(_TOP_TIER_CODEXFARM_PATCH)
    return normalized


def apply_benchmark_baseline_contract(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized.update(_BENCHMARK_BASELINE_PATCH)
    return normalized


def apply_benchmark_codex_contract_from_baseline(
    baseline_payload: Mapping[str, Any],
) -> dict[str, Any]:
    codex_payload = dict(baseline_payload)
    codex_payload.update(_BENCHMARK_CODEXFARM_PATCH)
    return codex_payload


def apply_benchmark_variant_contract(
    payload: Mapping[str, Any],
    variant: BenchmarkVariantKind,
) -> dict[str, Any]:
    baseline_payload = apply_benchmark_baseline_contract(payload)
    if variant == "vanilla":
        return baseline_payload
    return apply_benchmark_codex_contract_from_baseline(baseline_payload)


def resolve_codex_command_decision(
    context: str,
    payload: Mapping[str, Any] | None = None,
    *,
    allow_codex: bool = False,
    include_codex_farm_requested: bool = False,
    explicit_confirmation_granted: bool = False,
    benchmark_variant: str | None = None,
) -> CodexCommandDecision:
    surface = classify_codex_surfaces(payload)
    if context in {"stage", "labelstudio_import", "labelstudio_benchmark", "entrypoint_stage"}:
        codex_requested = surface.any_codex_enabled
        explicit_required = codex_requested
        activation_granted = allow_codex if explicit_required else False
        if explicit_required:
            activation_mode = "allow_codex" if allow_codex else "missing_allow_codex"
        else:
            activation_mode = "not_required"
    elif context in {"bench_speed_run", "bench_quality_run"}:
        codex_requested = bool(include_codex_farm_requested)
        explicit_required = codex_requested
        activation_granted = (
            explicit_confirmation_granted if explicit_required else False
        )
        if explicit_required:
            activation_mode = (
                "benchmark_confirmation"
                if explicit_confirmation_granted
                else "missing_benchmark_confirmation"
            )
        else:
            activation_mode = "not_required"
    else:
        raise ValueError(f"Unsupported Codex decision context: {context}")

    return CodexCommandDecision(
        context=context,
        surface=surface,
        codex_requested=codex_requested,
        explicit_activation_required=explicit_required,
        explicit_activation_granted=activation_granted,
        activation_mode=activation_mode,
        benchmark_variant=benchmark_variant,
    )


def normalize_codex_execution_policy_mode(
    value: Any,
) -> CodexExecutionPolicyMode:
    raw = _normalize_text(value)
    if raw in {"", "execute", "run", "live"}:
        return "execute"
    if raw in {"plan", "preview", "dry-run", "dryrun"}:
        return "plan"
    raise ValueError(
        "Invalid codex execution policy. Expected one of: execute, plan."
    )


def resolve_codex_execution_policy(
    context: str,
    payload: Mapping[str, Any] | None = None,
    *,
    execution_policy_mode: Any = "execute",
    allow_codex: bool = False,
    include_codex_farm_requested: bool = False,
    explicit_confirmation_granted: bool = False,
    benchmark_variant: str | None = None,
) -> CodexExecutionPolicy:
    requested_mode = normalize_codex_execution_policy_mode(execution_policy_mode)
    command_decision = resolve_codex_command_decision(
        context,
        payload,
        allow_codex=allow_codex,
        include_codex_farm_requested=include_codex_farm_requested,
        explicit_confirmation_granted=explicit_confirmation_granted,
        benchmark_variant=benchmark_variant,
    )
    if requested_mode == "plan" and command_decision.surface.any_codex_enabled:
        return CodexExecutionPolicy(
            command_decision=command_decision,
            requested_mode=requested_mode,
            resolved_mode="plan",
            plan_only=True,
            live_llm_allowed=False,
        )
    if requested_mode == "execute" and command_decision.surface.any_codex_enabled:
        return CodexExecutionPolicy(
            command_decision=command_decision,
            requested_mode=requested_mode,
            resolved_mode="execute" if command_decision.allowed else "blocked",
            plan_only=False,
            live_llm_allowed=command_decision.allowed,
        )
    return CodexExecutionPolicy(
        command_decision=command_decision,
        requested_mode=requested_mode,
        resolved_mode="not_required",
        plan_only=False,
        live_llm_allowed=False,
    )


def format_codex_surface_summary(surface: CodexSurfaceDecision) -> str:
    if surface.codex_surfaces:
        return ", ".join(surface.codex_surfaces)
    if surface.deterministic_surfaces:
        return "deterministic " + ", ".join(surface.deterministic_surfaces)
    return "none"


def format_codex_command_summary(decision: CodexCommandDecision) -> str:
    if decision.explicit_activation_required and decision.allowed:
        if decision.context in {"bench_speed_run", "bench_quality_run"}:
            return (
                "Codex decision: benchmark confirmation accepted; planned Codex-backed "
                "variants enabled."
            )
        return (
            "Codex decision: explicit approval accepted; Codex-backed surfaces: "
            f"{format_codex_surface_summary(decision.surface)}."
        )
    if decision.surface.codex_surfaces:
        return (
            "Codex decision: blocked pending explicit approval for "
            f"{format_codex_surface_summary(decision.surface)}."
        )
    if decision.surface.deterministic_surfaces:
        return (
            "Codex decision: deterministic helper surfaces only "
            f"({format_codex_surface_summary(decision.surface)})."
        )
    return "Codex decision: no Codex-backed surfaces enabled."


def format_codex_execution_policy_summary(policy: CodexExecutionPolicy) -> str:
    if policy.plan_only:
        return (
            "Codex execution policy: plan only; live Codex disabled; planned surfaces: "
            f"{format_codex_surface_summary(policy.surface)}."
        )
    return format_codex_command_summary(policy.command_decision)


def codex_decision_metadata(decision: CodexCommandDecision) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "ai_assistance_profile": decision.surface.ai_assistance_profile,
        "codex_decision_context": decision.context,
        "codex_decision_mode": decision.activation_mode,
        "codex_decision_allowed": decision.allowed,
        "codex_decision_explicit_activation_required": (
            decision.explicit_activation_required
        ),
        "codex_decision_explicit_activation_granted": (
            decision.explicit_activation_granted
        ),
        "codex_decision_codex_requested": decision.codex_requested,
        "codex_decision_codex_enabled": decision.surface.any_codex_enabled,
        "codex_decision_codex_surfaces": list(decision.surface.codex_surfaces),
        "codex_decision_deterministic_surfaces": list(
            decision.surface.deterministic_surfaces
        ),
        "codex_decision_summary": format_codex_command_summary(decision),
    }
    if decision.benchmark_variant:
        metadata["benchmark_variant"] = decision.benchmark_variant
    return metadata


def apply_codex_decision_metadata(
    payload: Mapping[str, Any],
    decision: CodexCommandDecision,
) -> dict[str, Any]:
    annotated = dict(payload)
    annotated.update(codex_decision_metadata(decision))
    return annotated


def codex_execution_policy_metadata(policy: CodexExecutionPolicy) -> dict[str, Any]:
    metadata = codex_decision_metadata(policy.command_decision)
    metadata.update(
        {
            "codex_execution_policy_requested_mode": policy.requested_mode,
            "codex_execution_policy_resolved_mode": policy.resolved_mode,
            "codex_execution_plan_only": policy.plan_only,
            "codex_execution_live_llm_allowed": policy.live_llm_allowed,
            "codex_execution_summary": format_codex_execution_policy_summary(policy),
        }
    )
    return metadata


def apply_codex_execution_policy_metadata(
    payload: Mapping[str, Any],
    policy: CodexExecutionPolicy,
) -> dict[str, Any]:
    annotated = dict(payload)
    annotated.update(codex_execution_policy_metadata(policy))
    return annotated


def write_codex_execution_plan(
    *,
    run_root: Path,
    policy: CodexExecutionPolicy,
    run_config: Mapping[str, Any],
    planned_work: Mapping[str, Any] | None = None,
    source_path: str | None = None,
    source_hash: str | None = None,
    importer_name: str | None = None,
    notes: str | None = None,
) -> Path:
    canonical_run_config = json.dumps(
        dict(run_config),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    payload: dict[str, Any] = {
        "schema_version": "codex_execution_plan.v1",
        "created_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(timespec="seconds"),
        "context": policy.command_decision.context,
        "requested_mode": policy.requested_mode,
        "resolved_mode": policy.resolved_mode,
        "plan_only": policy.plan_only,
        "live_llm_allowed": policy.live_llm_allowed,
        "summary": format_codex_execution_policy_summary(policy),
        "ai_assistance_profile": policy.surface.ai_assistance_profile,
        "codex_surfaces": list(policy.surface.codex_surfaces),
        "deterministic_surfaces": list(policy.surface.deterministic_surfaces),
        "run_config_hash": hashlib.sha256(
            canonical_run_config.encode("utf-8")
        ).hexdigest(),
        "run_config": dict(run_config),
    }
    if source_path or source_hash or importer_name:
        payload["source"] = {
            "path": source_path,
            "source_hash": source_hash,
            "importer_name": importer_name,
        }
    if planned_work:
        payload["planned_work"] = dict(planned_work)
    if notes:
        payload["notes"] = str(notes).strip()
    plan_path = run_root / "codex_execution_plan.json"
    plan_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return plan_path
