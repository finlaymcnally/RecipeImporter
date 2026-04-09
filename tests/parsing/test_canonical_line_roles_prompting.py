from __future__ import annotations

from types import SimpleNamespace

import tests.parsing.canonical_line_role_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_label_atomic_lines_invalid_task_file_answer_fails_closed_without_parse_error_flag(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="r1",
            block_id="block:1",
            block_index=1,
            atomic_index=0,
            text=(
                "This paragraph explains why pan temperature matters for crust "
                "development and how airflow changes moisture retention."
            ),
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    def _invalid_task_file_builder(payload):
        edited = dict(payload or {})
        units = edited.get("units") or []
        if units and isinstance(units[0], dict):
            first_unit = dict(units[0])
            first_unit["answer"] = {"label": "NOT_A_LABEL"}
            units = [first_unit, *units[1:]]
        edited["units"] = units
        return edited

    with pytest.raises(
        canonical_line_roles_module.LineRoleRepairFailureError,
        match="failed closed",
    ):
        label_atomic_lines(
            candidates,
            _settings("codex-line-role-route-v2"),
            artifact_root=tmp_path,
            codex_runner=FakeCodexExecRunner(output_builder=_invalid_task_file_builder),
            live_llm_allowed=True,
        )
    parse_errors_path = (
        tmp_path
        / "line-role-pipeline"
        / "prompts"
        / "line_role"
        / "parse_errors.json"
    )
    payload = json.loads(parse_errors_path.read_text(encoding="utf-8"))
    assert payload["parse_error_count"] == 1
    assert payload["parse_error_present"] is True
    assert not (tmp_path / "line-role-pipeline" / "guardrail_report.json").exists()
    assert not (tmp_path / "line-role-pipeline" / "do_no_harm_diagnostics.json").exists()
    proposal_payload = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "proposals"
            / "line-role-canonical-0001-a000000-a000000.json"
        ).read_text(encoding="utf-8")
    )
    assert proposal_payload["validation_errors"] == ["invalid_label:0:NOT_A_LABEL"]
    assert proposal_payload["payload"] is None
    assert proposal_payload["repair_attempted"] is True
    assert proposal_payload["repair_status"] == "failed"
    assert proposal_payload["validation_metadata"]["row_resolution"]["unresolved_atomic_indices"] == [0]
    shard_status_rows = [
        json.loads(line)
        for line in (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "shard_status.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert shard_status_rows[0]["state"] == "repair_failed"


def test_line_role_shared_contract_block_includes_required_contract_text() -> None:
    contract = build_line_role_shared_contract_block()

    assert "`INSTRUCTION_LINE` means a recipe-local procedural step" in contract
    assert "`HOWTO_SECTION` is recipe-internal only." in contract
    assert "`HOWTO_SECTION` is book-optional." in contract
    assert (
        "Variant context is local, not sticky. End a nearby `Variations` run"
        in contract
    )
    assert (
        "Do not let nearby `Variations` prose swallow a fresh recipe start such as `Bright Cabbage Slaw`"
        in contract
    )
    assert (
        "If a short title-like line is immediately followed by a strict yield line or ingredient rows"
        in contract
    )
    assert "reset to a new recipe: prefer `RECIPE_TITLE`" in contract
    assert (
        "A strict yield header such as `SERVES 4`, `Makes about 1/2 cup`, or `Yield: 6 servings` stays `YIELD_LINE`"
        in contract
    )
    assert "Line: `Bright Cabbage Slaw`" in contract
    assert "Label: `RECIPE_TITLE`" in contract
    assert "Line: `Serves 4 generously`" in contract
    assert "Label: `YIELD_LINE`" in contract
    assert "Line: `1/2 medium red onion, sliced thinly`" in contract
    assert "Label: `INGREDIENT_LINE`" in contract
    assert "Cooking Acids" in contract
    assert "Use limes in guacamole" in contract
    assert "Obvious praise blurbs, foreword or preface setup" in contract
    assert "This book will teach you the four elements of good cooking." in contract
    assert "Label: `NONRECIPE_EXCLUDE`" in contract


def test_line_role_taskfile_worker_prompt_includes_title_yield_reset_contract() -> None:
    from cookimport.parsing.canonical_line_roles.planning import (
        _build_line_role_taskfile_prompt,
    )
    from cookimport.llm.canonical_line_role_prompt import (
        build_line_role_shared_contract_block,
    )

    prompt = _build_line_role_taskfile_prompt(
        shards=[SimpleNamespace(shard_id="line-role-canonical-0001-a000000-a000002")]
    )
    shared_contract = build_line_role_shared_contract_block()

    assert "Shared labeling contract:" in prompt
    for line in (
        "`INSTRUCTION_LINE` means a recipe-local procedural step",
        "Contents-style title lists, endorsements, intro framing, and isolated topic headings default to `NONRECIPE_EXCLUDE`",
        "This book will teach you the four elements of good cooking.",
    ):
        assert line in shared_contract
        assert line in prompt
    assert "Title, variant, yield, and section calls are sequence-sensitive." in prompt
    assert "read the nearby rows directly in the ordered `task.json` ledger" in prompt


def test_line_role_inline_packet_uses_ordered_rows_and_neighbor_context() -> None:
    shard = ShardManifestEntryV1(
        shard_id="line-role-canonical-0001-a000010-a000011",
        owned_ids=("10", "11"),
        input_payload={
            "rows": [[10, "Bright Cabbage Slaw"], [11, "Serves 4 generously"]],
            "context_before_rows": [[9, "Variations"]],
            "context_after_rows": [[12, "1/2 medium red onion, sliced thinly"]],
        },
    )

    packet = canonical_line_roles_module._build_line_role_structured_packet(  # noqa: SLF001
        shard=shard,
        packet_kind="initial",
    )
    prompt = canonical_line_roles_module._build_line_role_structured_prompt(  # noqa: SLF001
        packet=packet,
    )

    assert packet["rows"] == [{"text": "Bright Cabbage Slaw"}, {"text": "Serves 4 generously"}]
    assert packet["context_before_rows"] == [{"text": "Variations"}]
    assert packet["context_after_rows"] == [
        {"text": "1/2 medium red onion, sliced thinly"}
    ]
    assert "owned_ids" not in packet
    assert '{"labels":["<ALLOWED_LABEL>","<ALLOWED_LABEL>"]}' in prompt
    assert "This packet has 2 owned row(s)" in prompt
    assert "Return exactly 2 label(s): one for each owned row shown in `rows`." in prompt
    assert "Keep label order exactly aligned with the packet `rows` order." in prompt
    assert "Finish the full owned-row list; do not stop early." in prompt
    assert "Do not copy the placeholder schema literally" in prompt
    assert "nearby context rows are shown" in prompt


def test_shared_line_role_contract_block_appears_in_file_prompt() -> None:
    shared_contract = build_line_role_shared_contract_block()
    file_prompt = build_canonical_line_role_file_prompt(
        input_path=Path("/tmp/line_role_input_0001.json"),
        input_payload={
            "v": 2,
            "shard_id": "line-role-canonical-0001-a000123-a000456",
            "rows": [[123, "1 cup flour"]],
        },
    )

    assert shared_contract in file_prompt


def test_canonical_candidate_fingerprint_changes_when_neighbor_text_changes() -> None:
    baseline = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:0",
            block_index=0,
            atomic_index=0,
            text="Before",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:1",
            block_index=1,
            atomic_index=1,
            text="Ambiguous line",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:2",
            block_index=2,
            atomic_index=2,
            text="After",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        ),
    ]
    updated = [
        baseline[0],
        baseline[1],
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:2",
            block_index=2,
            atomic_index=2,
            text="Changed after",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        ),
    ]

    assert canonical_line_roles_module._canonical_candidate_fingerprint(
        baseline
    ) != canonical_line_roles_module._canonical_candidate_fingerprint(updated)


def test_canonical_candidate_fingerprint_ignores_pre_grouping_recipe_span_hints() -> None:
    baseline = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous line",
            within_recipe_span=None,
            rule_tags=["yield_like"],
        )
    ]
    stale_hints = [
        AtomicLineCandidate(
            recipe_id="recipe:stale",
            block_id="block:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous line",
            within_recipe_span=True,
            rule_tags=["yield_like", "recipe_span_fallback"],
        )
    ]

    assert canonical_line_roles_module._canonical_candidate_fingerprint(
        baseline
    ) == canonical_line_roles_module._canonical_candidate_fingerprint(stale_hints)


def test_line_role_shard_plans_keep_owned_rows_without_hidden_task_splits() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:{index}",
            block_index=index,
            atomic_index=index,
            text=f"Line {index}",
            within_recipe_span=True,
            rule_tags=[],
        )
        for index in range(8)
    ]
    deterministic_baseline = {
        index: canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id=candidate.recipe_id,
            block_id=str(candidate.block_id),
            block_index=int(candidate.block_index),
            atomic_index=int(candidate.atomic_index),
            text=str(candidate.text),
            within_recipe_span=candidate.within_recipe_span,
            label="OTHER",
            decided_by="rule",
            reason_tags=[],
        )
        for index, candidate in enumerate(candidates)
    }

    plans = canonical_line_roles_module._build_line_role_canonical_plans(  # noqa: SLF001
        ordered_candidates=candidates,
        deterministic_baseline=deterministic_baseline,
        settings=_settings(
            "codex-line-role-route-v2",
            line_role_shard_target_lines=8,
        ),
        codex_batch_size=8,
    )

    assert len(plans) == 1
    shard_plan = plans[0]
    assert [candidate.atomic_index for candidate in shard_plan.candidates] == list(range(8))
    assert set(shard_plan.manifest_entry.input_payload) == {"v", "shard_id", "rows"}
    assert set(shard_plan.debug_input_payload) == {"shard_id", "phase_key", "rows"}
    assert "context_before_rows" not in shard_plan.manifest_entry.input_payload
    assert "context_after_rows" not in shard_plan.manifest_entry.input_payload
    assert "context_before_rows" not in shard_plan.debug_input_payload
    assert "context_after_rows" not in shard_plan.debug_input_payload
    assert shard_plan.manifest_entry.owned_ids == tuple(str(index) for index in range(8))
    assert [row[0] for row in shard_plan.manifest_entry.input_payload["rows"]] == list(range(8))
    assert "recipe_id" not in shard_plan.debug_input_payload["rows"][0]
    assert "within_recipe_span" not in shard_plan.debug_input_payload["rows"][0]


def test_line_role_shard_plans_include_boundary_neighbor_context_when_neighbors_exist() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:{index}",
            block_index=index,
            atomic_index=index,
            text=f"Line {index}",
            within_recipe_span=True,
            rule_tags=[],
        )
        for index in range(9)
    ]
    deterministic_baseline = {
        index: canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id=candidate.recipe_id,
            block_id=str(candidate.block_id),
            block_index=int(candidate.block_index),
            atomic_index=int(candidate.atomic_index),
            text=str(candidate.text),
            within_recipe_span=candidate.within_recipe_span,
            label="OTHER",
            decided_by="rule",
            reason_tags=[],
        )
        for index, candidate in enumerate(candidates)
    }

    plans = canonical_line_roles_module._build_line_role_canonical_plans(  # noqa: SLF001
        ordered_candidates=candidates,
        deterministic_baseline=deterministic_baseline,
        settings=_settings(
            "codex-line-role-route-v2",
            line_role_shard_target_lines=3,
        ),
        codex_batch_size=3,
    )

    assert len(plans) == 3

    first_plan = plans[0]
    assert "context_before_rows" not in first_plan.manifest_entry.input_payload
    assert first_plan.manifest_entry.input_payload["context_after_rows"] == [[3, "Line 3"]]
    assert "context_before_rows" not in first_plan.debug_input_payload
    assert first_plan.debug_input_payload["context_after_rows"] == [
        {"atomic_index": 3, "current_line": "Line 3"}
    ]

    middle_plan = plans[1]
    assert middle_plan.manifest_entry.input_payload["context_before_rows"] == [[2, "Line 2"]]
    assert middle_plan.manifest_entry.input_payload["context_after_rows"] == [[6, "Line 6"]]
    assert middle_plan.debug_input_payload["context_before_rows"] == [
        {"atomic_index": 2, "current_line": "Line 2"}
    ]
    assert middle_plan.debug_input_payload["context_after_rows"] == [
        {"atomic_index": 6, "current_line": "Line 6"}
    ]

    last_plan = plans[2]
    assert last_plan.manifest_entry.input_payload["context_before_rows"] == [[5, "Line 5"]]
    assert "context_after_rows" not in last_plan.manifest_entry.input_payload
    assert last_plan.debug_input_payload["context_before_rows"] == [
        {"atomic_index": 5, "current_line": "Line 5"}
    ]
    assert "context_after_rows" not in last_plan.debug_input_payload


def test_canonical_line_role_file_prompt_describes_compact_tuple_payload() -> None:
    prompt = build_canonical_line_role_file_prompt(
        input_path=Path("/tmp/line_role_input_0001.json"),
        input_payload={
            "v": 2,
            "shard_id": "line-role-canonical-0001-a000123-a000456",
            "context_before_rows": [[122, "Earlier context"]],
            "context_after_rows": [[124, "Later context"]],
            "rows": [[123, "1 cup flour"]],
        },
    )

    assert (
        '{"labels":["<ALLOWED_LABEL>","<ALLOWED_LABEL>"]}'
        in prompt
    )
    assert "line-role-canonical-0001-a000123-a000456" in prompt
    assert "context_before_rows" in prompt
    assert "context_after_rows" in prompt
    assert '{"text": "1 cup flour"}' in prompt
    assert "The authoritative owned shard rows are embedded below." in prompt
    assert "Reference-only neighboring context may also be embedded below" in prompt
    assert "do not open it or inspect the workspace to answer" in prompt
    assert "Do not run shell commands, Python, or any other tools." in prompt
    assert "Do not describe your plan, reasoning, or heuristics." in prompt
    assert "Your first response must be the final JSON object." in prompt
    assert "Use only the top-level key `labels`." in prompt
    assert "Each owned row object contains only `text`." in prompt
    assert "Return exactly one label for every owned input row in `rows`." in prompt
    assert "Finish the full owned-row list; do not stop early." in prompt
    assert "Use the `text` field as the line to label." in prompt
    assert "Never label reference-only neighboring rows" in prompt
    assert "Do not label `context_before_rows` or `context_after_rows`; they are for interpretation only." in prompt
    assert "Use `context_before_rows` and `context_after_rows` only for context around the owned rows in `rows`." in prompt
    assert "If the shard rows are outside recipe context, default to `NONRECIPE_CANDIDATE`" in prompt
    assert (
        "Variant context is local, not sticky. End a nearby `Variations` run"
        in prompt
    )
    assert (
        "Do not let nearby `Variations` prose swallow a fresh recipe start such as `Bright Cabbage Slaw`"
        in prompt
    )
    assert (
        "If a short title-like line is immediately followed by a strict yield line or ingredient rows"
        in prompt
    )
    assert "reset to a new recipe: prefer `RECIPE_TITLE`" in prompt
    assert (
        "A strict yield header such as `SERVES 4`, `Makes about 1/2 cup`, or `Yield: 6 servings` stays `YIELD_LINE`"
        in prompt
    )
    assert "Bright Cabbage Slaw" in prompt
    assert "Serves 4 generously" in prompt
    assert "1/2 medium red onion, sliced thinly" in prompt
    assert (
        "Contents-style title lists, endorsements, intro framing, and isolated topic headings default to `NONRECIPE_EXCLUDE`"
        in prompt
    )
    assert (
        "Obvious praise blurbs, foreword or preface setup, book-thesis or manifesto framing"
        in prompt
    )
    assert "This book will teach you the four elements of good cooking." in prompt
    assert "Keep label order exactly aligned with the task file's `rows` array." in prompt
    assert "A single outside-recipe heading by itself is not enough" in prompt
    assert "Reference-only neighboring context:" in prompt
    assert "These neighboring rows are for context only. Do not label them." in prompt
    assert '<BEGIN_CONTEXT_BEFORE_ROWS>\n{"text": "Earlier context"}\n<END_CONTEXT_BEFORE_ROWS>' in prompt
    assert '<BEGIN_CONTEXT_AFTER_ROWS>\n{"text": "Later context"}\n<END_CONTEXT_AFTER_ROWS>' in prompt
    assert '<BEGIN_AUTHORITATIVE_ROWS>\n{"text": "1 cup flour"}\n<END_AUTHORITATIVE_ROWS>' in prompt


def test_canonical_line_role_file_prompt_ignores_removed_shard_context_fields() -> None:
    prompt = build_canonical_line_role_file_prompt(
        input_path=Path("/tmp/line_role_input_0002.json"),
        input_payload={
            "v": 2,
            "shard_id": "line-role-canonical-0001-a000080-a000147",
            "shard_mode": "front_matter_navigation",
            "context_confidence": "high",
            "shard_summary": "This shard reads like front matter.",
            "default_posture": "Default to `OTHER`.",
            "flip_policy": ["Do not over-structure recipe-name lists."],
            "howto_section_availability": "absent_or_unproven",
            "howto_section_evidence_count": 0,
            "howto_section_policy": "This book may legitimately use zero `HOWTO_SECTION` labels.",
            "example_files": ["01-lesson-prose-vs-howto.md"],
            "rows": [[80, "Blue Cheese Dressing"]],
        },
    )

    assert "Shard-local guidance:" not in prompt
    assert "Shard mode:" not in prompt
    assert "HOWTO_SECTION availability:" not in prompt
    assert "HOWTO_SECTION policy:" not in prompt
    assert "Repo-written contrast examples:" not in prompt


def test_line_role_shared_contract_fallback_stays_routing_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        canonical_line_role_prompt_module,
        "_SHARED_CONTRACT_TEMPLATE_PATH",
        Path("/tmp/does-not-exist-line-role-shared-contract.md"),
    )
    contract = build_line_role_shared_contract_block()

    assert "If a line discusses what cooks generally should do" in contract
    assert (
        "Lesson headings such as `Balancing Fat` or `WHAT IS ACID?` stay `NONRECIPE_CANDIDATE` only when surrounding rows clearly carry reusable explanatory prose."
        in contract
    )
    assert "Line: `Gentle Cooking Methods`\n    Label: `NONRECIPE_CANDIDATE`" in contract
    assert (
        "Line: `Foods that are too dry can be corrected with a bit more fat.`\n    Label: `NONRECIPE_CANDIDATE`"
        in contract
    )
    assert (
        "Variant context is local, not sticky. End a nearby `Variations` run"
        in contract
    )
    assert (
        "Do not let nearby `Variations` prose swallow a fresh recipe start such as `Bright Cabbage Slaw`"
        in contract
    )
    assert "Line: `Bright Cabbage Slaw`\n    Label: `RECIPE_TITLE`" in contract
    assert "Line: `Serves 4 generously`\n    Label: `YIELD_LINE`" in contract
    assert (
        "Line: `1/2 medium red onion, sliced thinly`\n    Label: `INGREDIENT_LINE`"
        in contract
    )
    assert (
        "Line: `Then I fell in love with Johnny, who introduced me to San Francisco.`\n    Label: `NONRECIPE_EXCLUDE`"
        in contract
    )
    assert (
        "Line: `This book will teach you the four elements of good cooking.`\n    Label: `NONRECIPE_EXCLUDE`"
        in contract
    )
    assert (
        "Line: `What is Heat?`\n    Label: `NONRECIPE_EXCLUDE`"
        in contract
    )


def test_repo_gold_exposes_no_subsection_and_real_subsection_books() -> None:
    saltfat_counts = _gold_label_counts_for_book("saltfatacidheatcutdown")
    sea_and_smoke_counts = _gold_label_counts_for_book("seaandsmokecutdown")

    assert saltfat_counts.get("HOWTO_SECTION", 0) == 0
    assert sea_and_smoke_counts.get("HOWTO_SECTION", 0) >= 100


def test_codex_knowledge_inside_recipe_requires_explicit_prose_tags(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:0",
            block_index=0,
            atomic_index=0,
            text=(
                "This paragraph gives narrative context about pan construction, and "
                "it includes multiple clauses to remain prose-like."
            ),
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback", "explicit_prose"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:1",
            block_index=1,
            atomic_index=1,
            text=(
                "Another prose paragraph discusses heat retention, moisture movement, "
                "and texture outcomes in complete sentences."
            ),
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback", "explicit_prose"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:2",
            block_index=2,
            atomic_index=2,
            text=(
                "A final prose paragraph closes the section, with punctuation and "
                "long-form explanation rather than imperative action."
            ),
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback", "explicit_prose"],
        ),
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner(
            {0: "RECIPE_NOTES", 1: "RECIPE_NOTES", 2: "RECIPE_NOTES"}
        ),
        live_llm_allowed=True,
    )
    by_index = {row.atomic_index: row for row in predictions}
    assert by_index[1].label == "RECIPE_NOTES"
    assert by_index[1].decided_by == "codex"


def test_codex_knowledge_inside_recipe_rejected_without_explicit_prose_tag(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:0",
            block_index=0,
            atomic_index=0,
            text=(
                "This paragraph gives narrative context about pan construction, and "
                "it includes multiple clauses to remain prose-like."
            ),
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback", "explicit_prose"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:1",
            block_index=1,
            atomic_index=1,
            text=(
                "Another prose paragraph discusses heat retention, moisture movement, "
                "and texture outcomes in complete sentences."
            ),
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:2",
            block_index=2,
            atomic_index=2,
            text=(
                "A final prose paragraph closes the section, with punctuation and "
                "long-form explanation rather than imperative action."
            ),
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback", "explicit_prose"],
        ),
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner(
            {0: "RECIPE_NOTES", 1: "RECIPE_NOTES", 2: "RECIPE_NOTES"}
        ),
        live_llm_allowed=True,
    )
    by_index = {row.atomic_index: row for row in predictions}
    assert by_index[1].label == "RECIPE_NOTES"
    assert by_index[1].decided_by == "codex"


def test_codex_mode_keeps_coarse_nonrecipe_exclude_without_subtype_metadata() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:1",
            block_index=1,
            atomic_index=0,
            text="CONTENTS",
            within_recipe_span=False,
            rule_tags=["outside_recipe_span"],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        codex_runner=_line_role_runner({0: "NONRECIPE_EXCLUDE"}),
        live_llm_allowed=True,
    )
    assert len(predictions) == 1
    assert predictions[0].label == "NONRECIPE_EXCLUDE"
    assert "nonrecipe_excluded" in predictions[0].escalation_reasons


def test_label_atomic_lines_codex_cache_hit_skips_runner(tmp_path) -> None:
    settings = _settings("codex-line-role-route-v2")
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:cache:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]
    runner = _line_role_runner({0: "RECIPE_NOTES"})
    first = label_atomic_lines(
        candidates,
        settings,
        artifact_root=tmp_path / "artifacts",
        source_hash="source-hash-1",
        cache_root=tmp_path / "line-role-cache",
        codex_runner=runner,
        live_llm_allowed=True,
    )
    assert len(runner.calls) == 1
    assert runner.calls[0]["mode"] == "taskfile"
    assert runner.calls[0]["output_schema_path"] is None
    assert first[0].decided_by == "codex"
    second = label_atomic_lines(
        candidates,
        settings,
        artifact_root=tmp_path / "artifacts",
        source_hash="source-hash-1",
        cache_root=tmp_path / "line-role-cache",
        codex_runner=_line_role_runner({0: "RECIPE_TITLE"}),
        live_llm_allowed=True,
    )
    assert second[0].label == first[0].label
    assert second[0].decided_by == first[0].decided_by
    cache_files = list((tmp_path / "line-role-cache").rglob("*.json"))
    assert cache_files


def test_label_atomic_lines_writes_line_role_telemetry_summary_from_runtime_rows(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:telemetry:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    class _TelemetryRunner(FakeCodexExecRunner):
        @staticmethod
        def _with_usage(result):  # noqa: ANN001
            return result.__class__(
                command=result.command,
                subprocess_exit_code=result.subprocess_exit_code,
                output_schema_path=result.output_schema_path,
                prompt_text=result.prompt_text,
                response_text=result.response_text,
                turn_failed_message=result.turn_failed_message,
                events=result.events,
                usage={
                    "input_tokens": 20,
                    "cached_input_tokens": 4,
                    "output_tokens": 5,
                    "reasoning_tokens": 2,
                },
                stderr_text=result.stderr_text,
                stdout_text=result.stdout_text,
            )

        def run_packet_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_packet_worker(*args, **kwargs)
            return self._with_usage(result)

        def run_taskfile_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_taskfile_worker(*args, **kwargs)
            return self._with_usage(result)

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_TelemetryRunner(
            output_builder=_line_role_runner({0: "RECIPE_NOTES"}).output_builder
        ),
        live_llm_allowed=True,
    )

    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_NOTES"
    telemetry_payload = json.loads(
        (tmp_path / "line-role-pipeline" / "telemetry_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert telemetry_payload["summary"]["batch_count"] == 1
    assert telemetry_payload["summary"]["attempt_count"] == 1
    assert telemetry_payload["summary"]["attempts_with_usage"] == 1
    assert telemetry_payload["summary"]["tokens_input"] == 20
    assert telemetry_payload["summary"]["tokens_cached_input"] == 4
    assert telemetry_payload["summary"]["tokens_output"] == 5
    assert telemetry_payload["summary"]["tokens_reasoning"] == 2
    assert telemetry_payload["summary"]["tokens_total"] == 31
    assert [phase["phase_key"] for phase in telemetry_payload["phases"]] == [
        "line_role",
    ]
    assert telemetry_payload["phases"][0]["batches"][0]["attempts"][0]["process_run"]["runtime_mode"] == "direct_codex_exec_v1"


def test_label_atomic_lines_leave_missing_line_role_usage_unavailable(tmp_path) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:telemetry:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    class _MissingUsageRunner(FakeCodexExecRunner):
        @staticmethod
        def _without_usage(result):  # noqa: ANN001
            return result.__class__(
                command=result.command,
                subprocess_exit_code=result.subprocess_exit_code,
                output_schema_path=result.output_schema_path,
                prompt_text=result.prompt_text,
                response_text=result.response_text,
                turn_failed_message=result.turn_failed_message,
                events=result.events,
                usage=None,
                stderr_text=result.stderr_text,
                stdout_text=result.stdout_text,
            )

        def run_packet_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_packet_worker(*args, **kwargs)
            return self._without_usage(result)

        def run_taskfile_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_taskfile_worker(*args, **kwargs)
            return self._without_usage(result)

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_MissingUsageRunner(
            output_builder=_line_role_runner({0: "RECIPE_NOTES"}).output_builder
        ),
        live_llm_allowed=True,
    )

    assert len(predictions) == 1
    telemetry_payload = json.loads(
        (tmp_path / "line-role-pipeline" / "telemetry_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert telemetry_payload["summary"]["attempt_count"] == 1
    assert telemetry_payload["summary"]["attempts_with_usage"] == 0
    assert telemetry_payload["summary"]["attempts_without_usage"] == 1
    assert telemetry_payload["summary"]["tokens_input"] is None
    assert telemetry_payload["summary"]["tokens_total"] is None
    batch_payload = telemetry_payload["phases"][0]["batches"][0]
    assert batch_payload["attempts_with_usage"] == 0
    assert batch_payload["attempts"][0]["usage"] is None

def test_label_atomic_lines_fails_closed_when_only_part_of_shard_validates(
    tmp_path: Path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:partial-fallback:{index}",
            block_index=index,
            atomic_index=index,
            text=f"Ambiguous line {index}",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
        for index in range(2)
    ]

    def _partially_valid_task_file_builder(payload):
        edited = dict(payload or {})
        units = []
        for unit in edited.get("units") or []:
            if not isinstance(unit, dict):
                continue
            unit_payload = dict(unit)
            evidence = dict(unit_payload.get("evidence") or {})
            unit_payload["answer"] = (
                {"label": "RECIPE_NOTES"}
                if str(evidence.get("row_id") or "").strip() == "r01"
                else {}
            )
            units.append(unit_payload)
        edited["units"] = units
        return edited

    try:
        label_atomic_lines(
            candidates,
            _settings(
                "codex-line-role-route-v2",
                line_role_worker_count=1,
                line_role_prompt_target_count=1,
            ),
            artifact_root=tmp_path,
            codex_batch_size=2,
            codex_runner=FakeCodexExecRunner(output_builder=_partially_valid_task_file_builder),
            live_llm_allowed=True,
        )
    except canonical_line_roles_module.LineRoleRepairFailureError as exc:
        message = str(exc)
        assert "failed closed" in message
        assert "Missing atomic indices: 0, 1" in message
        assert "repair_failed" in message
    else:
        pytest.fail("expected line-role partial shard validation to fail closed")
    proposal_payload = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "proposals"
            / "line-role-canonical-0001-a000000-a000001.json"
        ).read_text(encoding="utf-8")
    )
    assert proposal_payload["validation_metadata"]["row_resolution"] == {
        "accepted_atomic_indices": [],
        "accepted_row_count": 0,
        "all_rows_resolved": False,
        "semantic_containment_applied": False,
        "semantic_containment_row_count": 0,
        "semantic_rejected": False,
        "unresolved_atomic_indices": [0, 1],
        "unresolved_row_count": 2,
    }
    assert proposal_payload["validation_metadata"]["same_session_handoff_state"][
        "row_resolution_metadata"
    ] == {
        "accepted_atomic_indices": [0],
        "accepted_row_count": 1,
        "all_rows_resolved": False,
        "semantic_containment_applied": False,
        "semantic_containment_row_count": 0,
        "semantic_rejected": False,
        "unresolved_atomic_indices": [1],
        "unresolved_row_count": 1,
    }


def test_label_atomic_lines_codex_progress_callback_reports_shard_runtime_start_and_finish() -> None:
    candidates: list[AtomicLineCandidate] = []
    for atomic_index in range(3):
        candidates.append(
            AtomicLineCandidate(
                recipe_id="recipe:0",
                block_id=f"block:progress:{atomic_index}",
                block_index=atomic_index,
                atomic_index=atomic_index,
                text=f"Ambiguous line {atomic_index}",
                within_recipe_span=True,
                rule_tags=["recipe_span_fallback"],
            )
        )

    progress_messages: list[str] = []
    predictions = label_atomic_lines(
        candidates,
        _settings(
            "codex-line-role-route-v2",
            line_role_worker_count=2,
            line_role_prompt_target_count=None,
        ),
        codex_batch_size=1,
        codex_runner=_line_role_runner({0: "RECIPE_NOTES", 1: "RECIPE_NOTES", 2: "RECIPE_NOTES"}),
        live_llm_allowed=True,
        progress_callback=progress_messages.append,
    )

    progress_texts = _progress_messages_as_text(progress_messages)
    shard_progress_texts = [text for text in progress_texts if " shard " in text]
    assert [row.atomic_index for row in predictions] == [0, 1, 2]
    assert (
        "Running canonical line-role pipeline... shard 0/3 | running 2"
        in shard_progress_texts
    )
    assert shard_progress_texts[-1] == (
        "Running canonical line-role pipeline... shard 3/3 | running 0"
    )


def test_label_atomic_lines_codex_progress_callback_surfaces_worker_attention() -> None:
    class _WarningLineRoleRunner(FakeCodexExecRunner):
        def run_taskfile_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            supervision_callback = kwargs.get("supervision_callback")
            if callable(supervision_callback):
                supervision_callback(
                    CodexExecLiveSnapshot(
                        elapsed_seconds=82.0,
                        last_event_seconds_ago=58.0,
                        event_count=11,
                        command_execution_count=canonical_line_roles_module._LINE_ROLE_WORKSPACE_MAX_COMMAND_COUNT + 1,  # noqa: SLF001
                        reasoning_item_count=0,
                        last_command="python3 helper.py",
                        last_command_repeat_count=canonical_line_roles_module._LINE_ROLE_WORKSPACE_MAX_REPEAT_COUNT + 1,  # noqa: SLF001
                        has_final_agent_message=False,
                        timeout_seconds=None,
                    )
                )
                time.sleep(1.2)
            return super().run_taskfile_worker(*args, **kwargs)

    candidates: list[AtomicLineCandidate] = []
    for atomic_index in range(2):
        candidates.append(
            AtomicLineCandidate(
                recipe_id="recipe:0",
                block_id=f"block:attention:{atomic_index}",
                block_index=atomic_index,
                atomic_index=atomic_index,
                text=f"Ambiguous line {atomic_index}",
                within_recipe_span=True,
                rule_tags=["recipe_span_fallback"],
            )
        )

    progress_messages: list[str] = []
    label_atomic_lines(
        candidates,
        _settings(
            "codex-line-role-route-v2",
            line_role_worker_count=1,
            line_role_prompt_target_count=None,
        ),
        codex_batch_size=1,
        codex_runner=_WarningLineRoleRunner(
            output_builder=_line_role_runner(
                {0: "RECIPE_NOTES", 1: "RECIPE_NOTES"}
            ).output_builder
        ),
        live_llm_allowed=True,
        progress_callback=progress_messages.append,
    )

    payloads = [
        payload
        for message in progress_messages
        for payload in [parse_stage_progress(message)]
        if payload is not None
    ]
    assert any(
        payload.get("work_unit_label") == "shard"
        and payload.get("running_workers") == 1
        and any(
            "line-role-canonical-" in str(task)
            for task in (payload.get("active_tasks") or [])
        )
        for payload in payloads
    )
    assert any(payload.get("last_activity_at") for payload in payloads)


def test_label_atomic_lines_codex_max_inflight_override_takes_precedence(
    tmp_path,
) -> None:
    candidates: list[AtomicLineCandidate] = []
    for atomic_index in range(3):
        candidates.append(
            AtomicLineCandidate(
                recipe_id="recipe:0",
                block_id=f"block:override:{atomic_index}",
                block_index=atomic_index,
                atomic_index=atomic_index,
                text=f"Ambiguous line {atomic_index}",
                within_recipe_span=True,
                rule_tags=["recipe_span_fallback"],
            )
        )

    progress_messages: list[str] = []
    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2", line_role_prompt_target_count=None),
        artifact_root=tmp_path,
        codex_batch_size=1,
        codex_max_inflight=3,
        codex_runner=_line_role_runner({0: "RECIPE_NOTES", 1: "RECIPE_NOTES", 2: "RECIPE_NOTES"}),
        live_llm_allowed=True,
        progress_callback=progress_messages.append,
    )

    progress_texts = _progress_messages_as_text(progress_messages)
    assert [row.atomic_index for row in predictions] == [0, 1, 2]
    assert (
        "Running canonical line-role pipeline... shard 0/3 | running 3"
        in progress_texts
    )
    phase_manifest = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "phase_manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert phase_manifest["worker_count"] == 3


def test_label_atomic_lines_defaults_workers_to_shard_count_when_unspecified() -> None:
    candidates: list[AtomicLineCandidate] = []
    for atomic_index in range(5):
        candidates.append(
            AtomicLineCandidate(
                recipe_id="recipe:0",
                block_id=f"block:default-workers:{atomic_index}",
                block_index=atomic_index,
                atomic_index=atomic_index,
                text=f"Ambiguous line {atomic_index}",
                within_recipe_span=True,
                rule_tags=["recipe_span_fallback"],
            )
        )

    progress_messages: list[str] = []
    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2", line_role_prompt_target_count=None),
        codex_batch_size=1,
        codex_runner=_line_role_runner(
            {
                0: "RECIPE_NOTES",
                1: "RECIPE_NOTES",
                2: "RECIPE_NOTES",
                3: "RECIPE_NOTES",
                4: "RECIPE_NOTES",
            }
        ),
        live_llm_allowed=True,
        progress_callback=progress_messages.append,
    )

    progress_texts = _progress_messages_as_text(progress_messages)
    assert [row.atomic_index for row in predictions] == [0, 1, 2, 3, 4]
    assert (
        "Running canonical line-role pipeline... shard 0/5 | running 5"
        in progress_texts
    )


def test_label_atomic_lines_deterministic_progress_callback_reports_row_counts() -> None:
    blocks = [
        {
            "block_id": "block:det:0",
            "block_index": 0,
            "text": "SERVES 4",
        },
        {
            "block_id": "block:det:1",
            "block_index": 1,
            "text": "2 tablespoons olive oil",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id="recipe:det",
        within_recipe_span=True,
    )
    progress_messages: list[str] = []
    predictions = label_atomic_lines(
        candidates,
        _settings("off"),
        progress_callback=progress_messages.append,
    )
    progress_texts = _progress_messages_as_text(progress_messages)
    assert len(predictions) == 2
    assert progress_texts[0] == "Running canonical line-role pipeline... row 0/2"
    assert progress_texts[-1] == "Running canonical line-role pipeline... row 2/2"
    assert all("| running " not in message for message in progress_texts)
