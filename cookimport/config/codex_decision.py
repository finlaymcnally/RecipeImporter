from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

TopTierProfileKind = Literal["codexfarm", "vanilla"]
BenchmarkVariantKind = Literal["vanilla", "codexfarm"]

RECIPE_CODEX_PIPELINE = "codex-farm-3pass-v1"
LINE_ROLE_CODEX_PIPELINE = "codex-line-role-v1"
LINE_ROLE_DETERMINISTIC_PIPELINE = "deterministic-v1"
KNOWLEDGE_CODEX_PIPELINE = "codex-farm-knowledge-v1"
TAGS_CODEX_PIPELINE = "codex-farm-tags-v1"

_TOP_TIER_CODEXFARM_PATCH: dict[str, Any] = {
    "llm_recipe_pipeline": RECIPE_CODEX_PIPELINE,
    "line_role_pipeline": LINE_ROLE_CODEX_PIPELINE,
    "atomic_block_splitter": "atomic-v1",
    "codex_farm_pass1_pattern_hints_enabled": False,
    "codex_farm_pass3_skip_pass2_ok": True,
}
_TOP_TIER_VANILLA_PATCH: dict[str, Any] = {
    "llm_recipe_pipeline": "off",
    "llm_knowledge_pipeline": "off",
    "llm_tags_pipeline": "off",
    "line_role_pipeline": LINE_ROLE_DETERMINISTIC_PIPELINE,
    "atomic_block_splitter": "atomic-v1",
    "codex_farm_pass1_pattern_hints_enabled": False,
    "codex_farm_pass3_skip_pass2_ok": True,
    "epub_extractor": "unstructured",
    "epub_unstructured_html_parser_version": "v1",
    "epub_unstructured_preprocess_mode": "br_split_v1",
    "epub_unstructured_skip_headers_footers": False,
}
_BENCHMARK_BASELINE_PATCH: dict[str, Any] = {
    "llm_recipe_pipeline": "off",
    "llm_knowledge_pipeline": "off",
    "llm_tags_pipeline": "off",
    "line_role_pipeline": "off",
    "atomic_block_splitter": "off",
}
_BENCHMARK_CODEXFARM_PATCH: dict[str, Any] = {
    "llm_recipe_pipeline": RECIPE_CODEX_PIPELINE,
    "line_role_pipeline": LINE_ROLE_CODEX_PIPELINE,
    "atomic_block_splitter": "atomic-v1",
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
    recipe_codex_enabled: bool
    line_role_codex_enabled: bool
    deterministic_line_role_enabled: bool
    knowledge_codex_enabled: bool
    tags_codex_enabled: bool
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


def classify_codex_surfaces(payload: Mapping[str, Any] | None) -> CodexSurfaceDecision:
    normalized_payload = payload or {}
    recipe_pipeline = _normalize_text(normalized_payload.get("llm_recipe_pipeline") or "off")
    line_role_pipeline = _normalize_text(normalized_payload.get("line_role_pipeline") or "off")
    knowledge_pipeline = _normalize_text(
        normalized_payload.get("llm_knowledge_pipeline") or "off"
    )
    tags_pipeline = _normalize_text(normalized_payload.get("llm_tags_pipeline") or "off")

    recipe_codex_enabled = recipe_pipeline == RECIPE_CODEX_PIPELINE
    line_role_codex_enabled = line_role_pipeline == LINE_ROLE_CODEX_PIPELINE
    deterministic_line_role_enabled = line_role_pipeline == LINE_ROLE_DETERMINISTIC_PIPELINE
    knowledge_codex_enabled = knowledge_pipeline == KNOWLEDGE_CODEX_PIPELINE
    tags_codex_enabled = tags_pipeline == TAGS_CODEX_PIPELINE
    any_codex_enabled = any(
        (
            recipe_codex_enabled,
            line_role_codex_enabled,
            knowledge_codex_enabled,
            tags_codex_enabled,
        )
    )
    codex_surfaces = _surface_list(
        (recipe_codex_enabled, "recipe"),
        (line_role_codex_enabled, "line_role"),
        (knowledge_codex_enabled, "knowledge"),
        (tags_codex_enabled, "tags"),
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
        recipe_codex_enabled=recipe_codex_enabled,
        line_role_codex_enabled=line_role_codex_enabled,
        deterministic_line_role_enabled=deterministic_line_role_enabled,
        knowledge_codex_enabled=knowledge_codex_enabled,
        tags_codex_enabled=tags_codex_enabled,
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
