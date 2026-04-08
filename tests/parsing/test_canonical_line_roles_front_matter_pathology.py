from __future__ import annotations

import tests.parsing.canonical_line_role_support as _support

globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def _front_matter_fixture() -> dict[str, object]:
    return _load_fixture("front_matter_pathology_shard.json")


def _front_matter_candidates() -> list[AtomicLineCandidate]:
    fixture = _front_matter_fixture()
    candidates: list[AtomicLineCandidate] = []
    for atomic_index, text in fixture["rows"]:
        candidates.append(
            AtomicLineCandidate(
                recipe_id=None,
                block_id=f"block:{atomic_index}",
                block_index=int(atomic_index),
                atomic_index=int(atomic_index),
                text=str(text),
                within_recipe_span=False,
                rule_tags=[],
            )
        )
    return candidates


def _front_matter_shard() -> ShardManifestEntryV1:
    fixture = _front_matter_fixture()
    rows = [list(row) for row in fixture["rows"]]
    context_after_rows = [list(row) for row in fixture["context_after_rows"]]
    return ShardManifestEntryV1(
        shard_id=str(fixture["shard_id"]),
        owned_ids=tuple(str(row[0]) for row in rows),
        input_payload={
            "rows": rows,
            "context_after_rows": context_after_rows,
        },
    )


def _front_matter_baseline() -> dict[int, CanonicalLineRolePrediction]:
    return canonical_line_roles_module._build_line_role_deterministic_baseline(  # noqa: SLF001
        ordered_candidates=_front_matter_candidates()
    )


def test_line_role_inline_prompt_includes_front_matter_profile_guidance() -> None:
    shard = _front_matter_shard()
    baseline = _front_matter_baseline()

    packet = canonical_line_roles_module._build_line_role_structured_packet(  # noqa: SLF001
        shard=shard,
        packet_kind="initial",
        deterministic_baseline_by_atomic_index=baseline,
    )
    prompt = canonical_line_roles_module._build_line_role_structured_prompt(  # noqa: SLF001
        packet=packet,
    )

    assert packet["shard_profile"]["summary"] == (
        "This shard reads like front matter and contents navigation, not one live recipe."
    )
    assert "Shared labeling contract:" in prompt
    assert "Contents-style title lists, endorsements, intro framing" in prompt
    assert "Shard profile evidence:" in prompt
    assert "`CONTENTS`" in prompt
    assert "`Epigraph`" in prompt
    assert "`What is Salt?`" in prompt


def test_line_role_semantic_guard_rejects_saved_front_matter_pathology() -> None:
    from cookimport.parsing.canonical_line_roles import runtime_workers as runtime_workers_module

    fixture = _front_matter_fixture()
    shard = _front_matter_shard()
    baseline = _front_matter_baseline()

    _payload, validation_errors, validation_metadata, proposal_status = (
        runtime_workers_module._evaluate_line_role_structured_response(  # noqa: SLF001
            shard=shard,
            response_text=json.dumps(fixture["bad_repair_response"], sort_keys=True),
            deterministic_baseline_by_atomic_index=baseline,
            validator=canonical_line_roles_module._validate_line_role_shard_proposal,  # noqa: SLF001
        )
    )

    assert proposal_status == "invalid"
    assert "semantic_pathology_rejected" in validation_errors
    assert validation_metadata["semantic_rejected"] is True
    assert any(
        "front matter" in diagnostic or "contents" in diagnostic
        for diagnostic in validation_metadata["semantic_diagnostics"]
    )
    row_resolution_payload, row_resolution_metadata = (
        canonical_line_roles_module._build_line_role_row_resolution(  # noqa: SLF001
            shard=shard,
            validation_metadata=validation_metadata,
        )
    )
    assert row_resolution_payload is not None
    assert row_resolution_metadata["semantic_containment_applied"] is True
    assert row_resolution_metadata["accepted_row_count"] == 0
    assert row_resolution_metadata["semantic_containment_row_count"] == len(
        fixture["rows"]
    )
    labels = {row["label"] for row in row_resolution_payload["rows"]}
    assert labels <= {"NONRECIPE_CANDIDATE", "NONRECIPE_EXCLUDE"}
    assert "RECIPE_TITLE" not in labels
    assert "HOWTO_SECTION" not in labels


def test_line_role_semantic_guard_allows_real_knowledge_heading_cluster() -> None:
    from cookimport.parsing.canonical_line_roles import runtime_workers as runtime_workers_module

    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:0",
            block_index=0,
            atomic_index=0,
            text="Gentle Cooking Methods",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:1",
            block_index=1,
            atomic_index=1,
            text=(
                "Gentle cooking methods control heat transfer so food cooks through "
                "without toughening or drying out."
            ),
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:2",
            block_index=2,
            atomic_index=2,
            text="Moist heat protects delicate proteins from drying out.",
            within_recipe_span=False,
            rule_tags=[],
        ),
    ]
    baseline = canonical_line_roles_module._build_line_role_deterministic_baseline(  # noqa: SLF001
        ordered_candidates=candidates
    )
    shard = ShardManifestEntryV1(
        shard_id="knowledge-heading-cluster",
        owned_ids=("0", "1", "2"),
        input_payload={
            "rows": [[0, candidates[0].text], [1, candidates[1].text], [2, candidates[2].text]],
        },
    )

    _payload, validation_errors, validation_metadata, proposal_status = (
        runtime_workers_module._evaluate_line_role_structured_response(  # noqa: SLF001
            shard=shard,
            response_text=json.dumps(
                {
                    "rows": [
                        {"row_id": "r01", "label": "NONRECIPE_CANDIDATE"},
                        {"row_id": "r02", "label": "NONRECIPE_CANDIDATE"},
                        {"row_id": "r03", "label": "NONRECIPE_CANDIDATE"},
                    ]
                },
                sort_keys=True,
            ),
            deterministic_baseline_by_atomic_index=baseline,
            validator=canonical_line_roles_module._validate_line_role_shard_proposal,  # noqa: SLF001
        )
    )

    assert proposal_status == "validated"
    assert "semantic_pathology_rejected" not in validation_errors
    assert validation_metadata.get("semantic_rejected") is not True


def test_label_atomic_lines_contains_front_matter_pathology_fixture(tmp_path) -> None:
    from cookimport.runs.stage_observability import build_line_role_stage_summary

    fixture = _front_matter_fixture()
    candidates = _front_matter_candidates()
    runner = FakeCodexExecRunner(
        output_builder=lambda _payload: fixture["bad_repair_response"]
    )

    predictions = label_atomic_lines(
        candidates,
        _settings(
            "codex-line-role-route-v2",
            line_role_codex_exec_style="inline-json-v1",
            line_role_prompt_target_count=1,
            line_role_worker_count=1,
        ),
        artifact_root=tmp_path,
        codex_runner=runner,
        live_llm_allowed=True,
    )

    assert len(predictions) == len(candidates)
    assert {prediction.label for prediction in predictions} <= {
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_EXCLUDE",
    }
    assert any("semantic_pathology_contained" in prediction.reason_tags for prediction in predictions)
    assert all(
        prediction.label not in {"RECIPE_TITLE", "HOWTO_SECTION"}
        for prediction in predictions
    )
    assert any(
        prediction.label == "NONRECIPE_EXCLUDE" for prediction in predictions
    )

    summary = build_line_role_stage_summary(
        tmp_path / "line-role-pipeline" / "runtime" / "line_role"
    )
    assert summary["repair_recovery_policy"]["transport"] == "inline-json-v1"
    assert summary["shards"]["suspicious_shard_count"] == 1
    assert summary["attention_summary"]["needs_attention"] is True
