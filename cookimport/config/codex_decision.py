from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from cookimport.config.run_settings import (
    KNOWLEDGE_CODEX_PIPELINE_SHARD_V1,
    LINE_ROLE_PIPELINE_SHARD_V1,
    RECIPE_CODEX_FARM_EXECUTION_PIPELINES,
    RECIPE_CODEX_FARM_PIPELINE_SHARD_V1,
)

TopTierProfileKind = Literal["codexfarm", "vanilla"]
BenchmarkVariantKind = Literal["vanilla", "codexfarm"]
CodexExecutionPolicyMode = Literal["execute"]

RECIPE_CODEX_PIPELINE = RECIPE_CODEX_FARM_PIPELINE_SHARD_V1
RECIPE_CODEX_PIPELINES = frozenset(RECIPE_CODEX_FARM_EXECUTION_PIPELINES)
LINE_ROLE_CODEX_PIPELINE = LINE_ROLE_PIPELINE_SHARD_V1
LINE_ROLE_DETERMINISTIC_PIPELINE = "deterministic-v1"
KNOWLEDGE_CODEX_PIPELINE = KNOWLEDGE_CODEX_PIPELINE_SHARD_V1
PRELABEL_CODEX_PROVIDER = "codex-farm"
BUCKET1_FIXED_BEHAVIOR_VERSION = "bucket1-fixed-v1"
SECTION_DETECTOR_SHARED_V1 = "shared_v1"
INSTRUCTION_STEP_SEGMENTATION_ALWAYS = "always"
INSTRUCTION_STEP_SEGMENTER_HEURISTIC_V1 = "heuristic_v1"
BENCHMARK_SEQUENCE_MATCHER_DMP = "dmp"
COMPACT_KNOWLEDGE_PIPELINE = "recipe.knowledge.compact.v1"


@dataclass(frozen=True)
class Bucket1FixedBehavior:
    version: str = BUCKET1_FIXED_BEHAVIOR_VERSION
    section_detector_backend: str = SECTION_DETECTOR_SHARED_V1
    instruction_step_segmentation_policy: str = INSTRUCTION_STEP_SEGMENTATION_ALWAYS
    instruction_step_segmenter: str = INSTRUCTION_STEP_SEGMENTER_HEURISTIC_V1
    benchmark_sequence_matcher: str = BENCHMARK_SEQUENCE_MATCHER_DMP
    multi_recipe_trace: bool = False
    p6_emit_metadata_debug: bool = False
    codex_farm_pipeline_knowledge: str = COMPACT_KNOWLEDGE_PIPELINE

    def manifest_metadata(self) -> dict[str, Any]:
        return {
            "bucket1_fixed_behavior_version": self.version,
        }


_BUCKET1_FIXED_BEHAVIOR = Bucket1FixedBehavior()


def bucket1_fixed_behavior() -> Bucket1FixedBehavior:
    return _BUCKET1_FIXED_BEHAVIOR


def apply_bucket1_fixed_behavior_metadata(
    payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    normalized = dict(payload or {})
    normalized.update(bucket1_fixed_behavior().manifest_metadata())
    return normalized

_TOP_TIER_PARSER_STACK_PATCH: dict[str, Any] = {
    "epub_extractor": "unstructured",
    "epub_unstructured_html_parser_version": "v1",
    "epub_unstructured_preprocess_mode": "semantic_v1",
    "epub_unstructured_skip_headers_footers": True,
    "multi_recipe_splitter": "rules_v1",
    "pdf_ocr_policy": "off",
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
    "line_role_pipeline": "off",
    "atomic_block_splitter": "off",
}
_BENCHMARK_BASELINE_PATCH: dict[str, Any] = dict(_TOP_TIER_VANILLA_PATCH)
_BENCHMARK_CODEXFARM_PATCH: dict[str, Any] = {
    "llm_recipe_pipeline": RECIPE_CODEX_PIPELINE,
    "llm_knowledge_pipeline": KNOWLEDGE_CODEX_PIPELINE,
    "line_role_pipeline": LINE_ROLE_CODEX_PIPELINE,
    "atomic_block_splitter": "atomic-v1",
}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_prelabel_provider(value: Any) -> str:
    normalized = _normalize_text(value)
    if normalized == "codex_farm":
        return PRELABEL_CODEX_PROVIDER
    return normalized


def _surface_list(*pairs: tuple[bool, str]) -> tuple[str, ...]:
    return tuple(name for enabled, name in pairs if enabled)


@dataclass(frozen=True)
class CodexSurfaceDecision:
    recipe_pipeline: str
    line_role_pipeline: str
    knowledge_pipeline: str
    prelabel_provider: str
    recipe_codex_enabled: bool
    line_role_codex_enabled: bool
    deterministic_line_role_enabled: bool
    knowledge_codex_enabled: bool
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
    prelabel_requested = bool(
        normalized_payload.get("prelabel") or normalized_payload.get("prelabel_enabled")
    )
    recipe_pipeline = _normalize_text(normalized_payload.get("llm_recipe_pipeline") or "off")
    line_role_pipeline = _normalize_text(normalized_payload.get("line_role_pipeline") or "off")
    knowledge_pipeline = _normalize_text(
        normalized_payload.get("llm_knowledge_pipeline") or "off"
    )
    prelabel_provider = _normalize_prelabel_provider(
        normalized_payload.get("prelabel_provider")
        or (PRELABEL_CODEX_PROVIDER if prelabel_requested else "off")
    )
    if prelabel_requested and prelabel_provider in {"", "off"}:
        prelabel_provider = PRELABEL_CODEX_PROVIDER

    recipe_codex_enabled = recipe_pipeline in RECIPE_CODEX_PIPELINES
    line_role_codex_enabled = line_role_pipeline == LINE_ROLE_CODEX_PIPELINE
    deterministic_line_role_enabled = line_role_pipeline == LINE_ROLE_DETERMINISTIC_PIPELINE
    knowledge_codex_enabled = knowledge_pipeline == KNOWLEDGE_CODEX_PIPELINE
    prelabel_codex_enabled = prelabel_requested
    any_codex_enabled = any(
        (
            recipe_codex_enabled,
            line_role_codex_enabled,
            knowledge_codex_enabled,
            prelabel_codex_enabled,
        )
    )
    codex_surfaces = _surface_list(
        (recipe_codex_enabled, "recipe"),
        (line_role_codex_enabled, "line_role"),
        (knowledge_codex_enabled, "knowledge"),
        (prelabel_codex_enabled, "prelabel"),
    )
    deterministic_surfaces = _surface_list(
        (deterministic_line_role_enabled, "line_role"),
    )
    recipe_family_codex_enabled = any(
        (
            recipe_codex_enabled,
            knowledge_codex_enabled,
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
        )
    ):
        ai_assistance_profile = "deterministic"
    else:
        ai_assistance_profile = "other"

    return CodexSurfaceDecision(
        recipe_pipeline=recipe_pipeline,
        line_role_pipeline=line_role_pipeline,
        knowledge_pipeline=knowledge_pipeline,
        prelabel_provider=prelabel_provider,
        recipe_codex_enabled=recipe_codex_enabled,
        line_role_codex_enabled=line_role_codex_enabled,
        deterministic_line_role_enabled=deterministic_line_role_enabled,
        knowledge_codex_enabled=knowledge_codex_enabled,
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
    raise ValueError(
        "Invalid codex execution policy. Only 'execute' is supported; plan mode was removed."
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
    if requested_mode == "execute" and command_decision.surface.any_codex_enabled:
        return CodexExecutionPolicy(
            command_decision=command_decision,
            requested_mode=requested_mode,
            resolved_mode="execute" if command_decision.allowed else "blocked",
            live_llm_allowed=command_decision.allowed,
        )
    return CodexExecutionPolicy(
        command_decision=command_decision,
        requested_mode=requested_mode,
        resolved_mode="not_required",
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
    return format_codex_command_summary(policy.command_decision)


def codex_backend_for_surface(surface: CodexSurfaceDecision) -> str | None:
    if surface.any_codex_enabled:
        return "codexfarm"
    return None


def codex_decision_metadata(decision: CodexCommandDecision) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "ai_assistance_profile": decision.surface.ai_assistance_profile,
        "codex_backend": codex_backend_for_surface(decision.surface),
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
