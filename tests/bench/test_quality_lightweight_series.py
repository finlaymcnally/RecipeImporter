from __future__ import annotations

import pytest

from cookimport.bench.quality_lightweight_series import (
    _CandidateMetrics,
    _build_combined_patch,
    _build_round_3_variants,
    _interaction_smoke_finding,
    _needs_confidence_guard,
    _score_categories,
    LightweightInteractionRiskProfile,
    LightweightSeriesProfile,
)


def _build_profile(
    *,
    categories: list[dict[str, object]],
) -> LightweightSeriesProfile:
    return LightweightSeriesProfile.model_validate(
        {
            "schema_version": 1,
            "baseline_experiment_id": "baseline",
            "categories": categories,
            "rounds": {
                "round_1_main_effects": {
                    "seed_count": 2,
                    "search_strategy": "exhaustive",
                    "include_deterministic_sweeps": False,
                    "race_probe_targets": 2,
                    "race_mid_targets": 4,
                    "race_keep_ratio": 0.35,
                    "race_finalists": 64,
                },
                "round_2_composition": {
                    "seed_count": 2,
                    "search_strategy": "exhaustive",
                    "include_deterministic_sweeps": False,
                    "race_probe_targets": 2,
                    "race_mid_targets": 4,
                    "race_keep_ratio": 0.35,
                    "race_finalists": 64,
                },
                "round_3_interaction_smoke": {
                    "seed_count": 2,
                    "search_strategy": "exhaustive",
                    "include_deterministic_sweeps": False,
                    "race_probe_targets": 2,
                    "race_mid_targets": 4,
                    "race_keep_ratio": 0.35,
                    "race_finalists": 64,
                },
            },
            "scoring": {
                "practical_epsilon": 0.001,
                "strict_epsilon": 0.001,
                "source_success_epsilon": 0.005,
                "confidence_guard": {
                    "enabled": True,
                    "practical_delta_diff_max": 0.0015,
                    "strict_delta_diff_max": 0.0015,
                },
                "combined_verdict": {
                    "practical_delta_min": -0.002,
                    "strict_delta_min": -0.002,
                    "source_success_delta_min": -0.01,
                },
            },
            "interaction_smoke": {
                "ablation_categories": ["parser", "structure", "instruction_segmentation"],
                "include_parser_runner_up_variant": True,
                "risk_thresholds": {
                    "practical_f1_gain_min": 0.003,
                    "strict_f1_gain_min": 0.003,
                    "source_success_rate_gain_min": 0.02,
                },
            },
        }
    )


def test_score_categories_tie_break_prefers_strict_delta_within_practical_epsilon() -> None:
    profile = _build_profile(
        categories=[
            {"id": "parser", "candidate_experiment_ids": ["alpha", "beta"]},
        ]
    )
    metrics = {
        "baseline": {
            "mean_practical_f1_macro": 0.7000,
            "mean_strict_f1_macro": 0.6000,
            "mean_source_success_rate": 1.0,
        },
        "alpha": {
            "mean_practical_f1_macro": 0.7050,
            "mean_strict_f1_macro": 0.6040,
            "mean_source_success_rate": 1.0,
        },
        "beta": {
            "mean_practical_f1_macro": 0.7054,
            "mean_strict_f1_macro": 0.6062,
            "mean_source_success_rate": 1.0,
        },
    }

    ranking = _score_categories(profile=profile, metrics_by_experiment=metrics)[0]
    assert ranking.winner_experiment_id == "beta"
    assert ranking.runner_up_experiment_id == "alpha"


def test_score_categories_chooses_baseline_for_non_improving_category() -> None:
    profile = _build_profile(
        categories=[
            {"id": "structure", "candidate_experiment_ids": ["candidate_a", "candidate_b"]},
        ]
    )
    metrics = {
        "baseline": {
            "mean_practical_f1_macro": 0.8000,
            "mean_strict_f1_macro": 0.8100,
            "mean_source_success_rate": 1.0,
        },
        "candidate_a": {
            "mean_practical_f1_macro": 0.7900,
            "mean_strict_f1_macro": 0.8050,
            "mean_source_success_rate": 0.99,
        },
        "candidate_b": {
            "mean_practical_f1_macro": 0.7880,
            "mean_strict_f1_macro": 0.8000,
            "mean_source_success_rate": 0.99,
        },
    }

    ranking = _score_categories(profile=profile, metrics_by_experiment=metrics)[0]
    assert ranking.winner_experiment_id == "baseline"
    assert ranking.runner_up_experiment_id == "candidate_a"


def test_needs_confidence_guard_triggers_only_for_near_tie() -> None:
    first = _CandidateMetrics(
        experiment_id="a",
        mean_practical_f1_macro=0.80,
        mean_strict_f1_macro=0.81,
        mean_source_success_rate=1.0,
        practical_delta=0.0100,
        strict_delta=0.0100,
        source_success_delta=0.0,
    )
    second = _CandidateMetrics(
        experiment_id="b",
        mean_practical_f1_macro=0.80,
        mean_strict_f1_macro=0.81,
        mean_source_success_rate=1.0,
        practical_delta=0.0090,
        strict_delta=0.0090,
        source_success_delta=0.0,
    )
    assert _needs_confidence_guard(
        first=first,
        second=second,
        config=_build_profile(categories=[{"id": "parser", "candidate_experiment_ids": ["a", "b"]}]).scoring.confidence_guard,
    )

    far_second = _CandidateMetrics(
        experiment_id="b",
        mean_practical_f1_macro=0.80,
        mean_strict_f1_macro=0.81,
        mean_source_success_rate=1.0,
        practical_delta=0.0050,
        strict_delta=0.0090,
        source_success_delta=0.0,
    )
    assert not _needs_confidence_guard(
        first=first,
        second=far_second,
        config=_build_profile(categories=[{"id": "parser", "candidate_experiment_ids": ["a", "b"]}]).scoring.confidence_guard,
    )


def test_build_combined_patch_raises_on_illegal_overlap() -> None:
    profile = _build_profile(
        categories=[
            {"id": "parser", "candidate_experiment_ids": ["parser_a"]},
            {"id": "structure", "candidate_experiment_ids": ["structure_b"]},
        ]
    )
    winner_ids = {"parser": "parser_a", "structure": "structure_b"}
    patches = {
        "baseline": {},
        "parser_a": {"epub_unstructured_preprocess_mode": "none"},
        "structure_b": {"epub_unstructured_preprocess_mode": "br_split_v1"},
    }

    with pytest.raises(ValueError, match="illegal_overlap"):
        _build_combined_patch(
            profile=profile,
            winner_ids_by_category=winner_ids,
            run_settings_patch_by_id=patches,
            baseline_experiment_id="baseline",
        )


def test_interaction_smoke_finding_classifies_risk() -> None:
    risk_thresholds = LightweightInteractionRiskProfile(
        practical_f1_gain_min=0.003,
        strict_f1_gain_min=0.003,
        source_success_rate_gain_min=0.02,
    )

    risk = _interaction_smoke_finding(
        variant_id="combined_minus_parser",
        gain_payload={
            "practical_delta": 0.0031,
            "strict_delta": 0.0001,
            "source_success_delta": 0.0,
        },
        risk_thresholds=risk_thresholds,
    )
    assert risk["verdict"] == "RISK"
    assert risk["triggered_thresholds"] == ["practical_f1_gain"]

    no_risk = _interaction_smoke_finding(
        variant_id="combined_minus_parser",
        gain_payload={
            "practical_delta": 0.0005,
            "strict_delta": 0.0004,
            "source_success_delta": 0.005,
        },
        risk_thresholds=risk_thresholds,
    )
    assert no_risk["verdict"] == "NO_OBVIOUS_RISK"
    assert no_risk["triggered_thresholds"] == []


def test_round_3_variants_skip_runner_up_variant_when_missing() -> None:
    profile = _build_profile(
        categories=[
            {"id": "parser", "candidate_experiment_ids": ["parser_a"]},
            {"id": "structure", "candidate_experiment_ids": ["structure_b"]},
            {
                "id": "instruction_segmentation",
                "candidate_experiment_ids": ["instruction_c"],
            },
        ]
    )
    winner_ids = {
        "parser": "parser_a",
        "structure": "structure_b",
        "instruction_segmentation": "instruction_c",
    }
    runner_up_ids = {
        "parser": None,
        "structure": None,
        "instruction_segmentation": None,
    }
    patches = {
        "baseline": {},
        "parser_a": {"epub_unstructured_preprocess_mode": "none"},
        "structure_b": {"section_detector_backend": "shared_v1"},
        "instruction_c": {"instruction_step_segmentation_policy": "always"},
    }

    variants = _build_round_3_variants(
        profile=profile,
        winner_ids_by_category=winner_ids,
        runner_up_ids_by_category=runner_up_ids,
        run_settings_patch_by_id=patches,
        baseline_experiment_id="baseline",
    )

    assert "combined_minus_parser" in variants
    assert "combined_minus_structure" in variants
    assert "combined_minus_instruction_segmentation" in variants
    assert "combined_plus_parser_runner_up" not in variants
