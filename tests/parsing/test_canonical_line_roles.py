from __future__ import annotations

import json

from cookimport.config.run_settings import RunSettings
from cookimport.llm.canonical_line_role_prompt import build_canonical_line_role_prompt
from cookimport.parsing.canonical_line_roles import label_atomic_lines
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate, atomize_blocks
from tests.paths import FIXTURES_DIR


def _load_fixture(name: str) -> dict[str, object]:
    fixture_path = FIXTURES_DIR / "canonical_labeling" / name
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def _settings(mode: str = "deterministic-v1"):
    return RunSettings(line_role_pipeline=mode)


def test_label_atomic_lines_hollandaise_note_and_howto_rules() -> None:
    payload = _load_fixture("hollandaise_merged_block.json")
    blocks = payload.get("blocks")
    assert isinstance(blocks, list)
    candidates = atomize_blocks(
        blocks,
        recipe_id=str(payload.get("recipe_id") or ""),
        within_recipe_span=True,
    )
    predictions = label_atomic_lines(candidates, _settings())
    by_text = {prediction.text: prediction for prediction in predictions}
    assert by_text["NOTE: Keep blender cup warm."].label == "RECIPE_NOTES"
    assert (
        by_text["TO MAKE HOLLANDAISE WITH AN IMMERSION BLENDER"].label
        == "HOWTO_SECTION"
    )
    assert by_text["NOTE: Keep blender cup warm."].decided_by == "rule"
    assert all(prediction.within_recipe_span is True for prediction in predictions)


def test_label_atomic_lines_ingredient_range_never_yield() -> None:
    payload = _load_fixture("ingredient_vs_yield_ranges.json")
    blocks = payload.get("blocks")
    assert isinstance(blocks, list)
    candidates = atomize_blocks(
        blocks,
        recipe_id=str(payload.get("recipe_id") or ""),
        within_recipe_span=True,
    )
    predictions = label_atomic_lines(candidates, _settings())
    by_text = {prediction.text: prediction for prediction in predictions}
    assert by_text["SERVES 4"].label == "YIELD_LINE"
    assert by_text["4 to 6 chicken leg quarters"].label == "INGREDIENT_LINE"
    assert by_text["2 tablespoons olive oil"].label == "INGREDIENT_LINE"


def test_label_atomic_lines_omelet_variant_and_ingredient_rules() -> None:
    payload = _load_fixture("omelet_variant_lines.json")
    blocks = payload.get("blocks")
    assert isinstance(blocks, list)
    candidates = atomize_blocks(
        blocks,
        recipe_id=str(payload.get("recipe_id") or ""),
        within_recipe_span=True,
    )
    predictions = label_atomic_lines(candidates, _settings())
    by_text = {prediction.text: prediction for prediction in predictions}
    assert (
        by_text["DINER-STYLE MUSHROOM, PEPPER, AND ONION OMELET"].label
        == "RECIPE_VARIANT"
    )
    assert by_text["3 tablespoons whole milk"].label == "INGREDIENT_LINE"


def test_label_atomic_lines_instruction_with_time_stays_instruction() -> None:
    payload = _load_fixture("braised_chicken_tail_steps.json")
    blocks = payload.get("blocks")
    assert isinstance(blocks, list)
    candidates = atomize_blocks(
        blocks,
        recipe_id=str(payload.get("recipe_id") or ""),
        within_recipe_span=True,
    )
    predictions = label_atomic_lines(candidates, _settings())
    by_text = {prediction.text: prediction for prediction in predictions}
    assert by_text["3. Cover and braise for 45 minutes."].label == "INSTRUCTION_LINE"


def test_codex_time_line_prediction_demotes_to_instruction_when_not_primary_time(
    monkeypatch,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:time:1",
            block_index=1,
            atomic_index=0,
            text="Add onions and cook for 5 minutes.",
            within_recipe_span=True,
            candidate_labels=["TIME_LINE", "INSTRUCTION_LINE", "OTHER"],
            prev_text=None,
            next_text=None,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    def _fake_codex_call(**_kwargs):
        return {
            "response": json.dumps([{"atomic_index": 0, "label": "TIME_LINE"}]),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "usage": None,
            "turn_failed_message": None,
        }

    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles.run_codex_json_prompt",
        _fake_codex_call,
    )
    predictions = label_atomic_lines(candidates, _settings("codex-line-role-v1"))
    assert len(predictions) == 1
    assert predictions[0].label == "INSTRUCTION_LINE"
    assert predictions[0].decided_by == "fallback"
    assert "sanitized_time_to_instruction" in predictions[0].reason_tags


def test_label_atomic_lines_outside_recipe_can_be_knowledge() -> None:
    blocks = [
        {
            "block_id": "block:knowledge:1",
            "block_index": 1,
            "text": (
                "Copper pans conduct heat quickly and evenly, so even small burner "
                "changes show up immediately across the pan."
            ),
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "KNOWLEDGE"
    assert predictions[0].within_recipe_span is False


def test_label_atomic_lines_outside_recipe_note_prefix_is_recipe_notes() -> None:
    blocks = [
        {
            "block_id": "block:note:1",
            "block_index": 1,
            "text": "NOTE: Keep the soup warm while you prep garnish.",
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_NOTES"


def test_label_atomic_lines_outside_recipe_variant_heading_is_recipe_variant() -> None:
    blocks = [
        {
            "block_id": "block:variant:1",
            "block_index": 1,
            "text": "FOR A CROWD",
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_VARIANT"


def test_label_atomic_lines_outside_recipe_first_person_prose_is_not_recipe_notes() -> None:
    blocks = [
        {
            "block_id": "block:preface:1",
            "block_index": 1,
            "text": (
                "I spent years testing this in my home kitchen, but this paragraph "
                "is narrative preface prose and not an inline recipe note."
            ),
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "OTHER"


def test_label_atomic_lines_outside_recipe_prose_defaults_to_other_without_knowledge_cue() -> None:
    blocks = [
        {
            "block_id": "block:narrative:1",
            "block_index": 1,
            "text": (
                "The chapter opens with a short story about market mornings, and "
                "the prose lingers on scene-setting details before any recipe starts."
            ),
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "OTHER"


def test_label_atomic_lines_outside_recipe_food_note_prose_is_recipe_notes() -> None:
    blocks = [
        {
            "block_id": "block:tip:1",
            "block_index": 1,
            "text": (
                "I like mine extra peppery, and you can spoon it over biscuits "
                "while the gravy is still hot."
            ),
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_NOTES"


def test_label_atomic_lines_outside_recipe_contents_heading_is_not_recipe_variant() -> None:
    blocks = [
        {
            "block_id": "block:heading:1",
            "block_index": 1,
            "text": "CONTENTS",
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label != "RECIPE_VARIANT"


def test_label_atomic_lines_heading_like_ingredient_promotes_recipe_title() -> None:
    blocks = [
        {
            "block_id": "block:title:1",
            "block_index": 1,
            "text": "POACHED EGGS",
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_TITLE"


def test_codex_neighbor_ingredient_fragment_rescued_to_ingredient(monkeypatch) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:ingredient:0",
            block_index=0,
            atomic_index=0,
            text="1 cup",
            within_recipe_span=True,
            candidate_labels=["INGREDIENT_LINE", "YIELD_LINE", "OTHER"],
            prev_text=None,
            next_text="flour",
            rule_tags=["ingredient_like"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:ingredient:1",
            block_index=1,
            atomic_index=1,
            text="flour",
            within_recipe_span=True,
            candidate_labels=["OTHER", "INGREDIENT_LINE"],
            prev_text="1 cup",
            next_text="2 tablespoons sugar",
            rule_tags=["recipe_span_fallback"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:ingredient:2",
            block_index=2,
            atomic_index=2,
            text="2 tablespoons sugar",
            within_recipe_span=True,
            candidate_labels=["INGREDIENT_LINE", "YIELD_LINE", "OTHER"],
            prev_text="flour",
            next_text=None,
            rule_tags=["ingredient_like"],
        ),
    ]

    def _fake_codex_call(**_kwargs):
        return {
            "response": json.dumps([{"atomic_index": 1, "label": "OTHER"}]),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "usage": None,
            "turn_failed_message": None,
        }

    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles.run_codex_json_prompt",
        _fake_codex_call,
    )
    predictions = label_atomic_lines(candidates, _settings("codex-line-role-v1"))
    by_index = {row.atomic_index: row for row in predictions}
    assert by_index[1].label == "INGREDIENT_LINE"
    assert by_index[1].decided_by == "fallback"
    assert "sanitized_neighbor_ingredient_fragment" in by_index[1].reason_tags


def test_label_atomic_lines_component_heading_prefers_howto_section() -> None:
    blocks = [
        {
            "block_id": "block:ingredient:1",
            "block_index": 1,
            "text": "4 Hakurei turnip leaves, about 8 to 10 inches long",
        },
        {
            "block_id": "block:heading:1",
            "block_index": 2,
            "text": "AGING THE DUCK",
        },
        {
            "block_id": "block:instruction:1",
            "block_index": 3,
            "text": (
                "Trim any excess fat from around the neck and abdominal cavity of "
                "the duck."
            ),
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id="recipe:0",
        within_recipe_span=True,
    )
    predictions = label_atomic_lines(candidates, _settings())
    by_text = {prediction.text: prediction for prediction in predictions}
    assert by_text["AGING THE DUCK"].label == "HOWTO_SECTION"
    assert by_text["AGING THE DUCK"].decided_by == "rule"


def test_label_atomic_lines_recipe_title_with_immediate_yield_stays_recipe_title() -> None:
    blocks = [
        {
            "block_id": "block:title:yield:1",
            "block_index": 1,
            "text": "CHICKEN DRIPPINGS",
        },
        {
            "block_id": "block:title:yield:2",
            "block_index": 2,
            "text": "YIELDS ABOUT 2 CUPS/400 G",
        },
        {
            "block_id": "block:title:yield:3",
            "block_index": 3,
            "text": "4 whole chickens",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id="recipe:0",
        within_recipe_span=True,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert predictions[0].text == "CHICKEN DRIPPINGS"
    assert predictions[0].label == "RECIPE_TITLE"


def test_codex_mode_title_like_candidate_allowlist_includes_recipe_title(monkeypatch) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:title:1",
            block_index=1,
            atomic_index=0,
            text="A PORRIDGE OF LOVAGE STEMS",
            within_recipe_span=True,
            candidate_labels=["OTHER", "KNOWLEDGE"],
            prev_text=None,
            next_text=None,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    def _fake_codex_call(**_kwargs):
        return {
            "response": json.dumps([{"atomic_index": 0, "label": "RECIPE_TITLE"}]),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "usage": None,
            "turn_failed_message": None,
        }

    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles.run_codex_json_prompt",
        _fake_codex_call,
    )
    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-v1"),
    )
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_TITLE"
    assert predictions[0].decided_by == "codex"
    assert "RECIPE_TITLE" in predictions[0].candidate_labels


def test_codex_mode_preserves_low_confidence_deterministic_recipe_title(monkeypatch) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:title:2",
            block_index=2,
            atomic_index=0,
            text="A PORRIDGE OF LOVAGE STEMS",
            within_recipe_span=False,
            candidate_labels=["OTHER", "KNOWLEDGE"],
            prev_text=None,
            next_text=None,
            rule_tags=["outside_recipe_span"],
        )
    ]

    def _codex_should_not_run(**_kwargs):
        raise AssertionError("codex runner should not execute for deterministic title hold")

    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles.run_codex_json_prompt",
        _codex_should_not_run,
    )
    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-v1"),
    )
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_TITLE"
    assert predictions[0].decided_by == "rule"
    assert "RECIPE_TITLE" in predictions[0].candidate_labels


def test_label_atomic_lines_note_like_prose_prefers_recipe_notes() -> None:
    blocks = [
        {
            "block_id": "block:note-prose:1",
            "block_index": 1,
            "text": (
                "If you like a thinner finish, you can whisk in a splash of stock "
                "right before serving to loosen the texture."
            ),
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id="recipe:0",
        within_recipe_span=True,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_NOTES"
    assert predictions[0].decided_by == "rule"


def test_label_atomic_lines_codex_parse_error_falls_back_and_writes_flag(
    monkeypatch,
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
            candidate_labels=["OTHER", "KNOWLEDGE"],
            prev_text="1. Heat a heavy skillet over medium-high heat.",
            next_text="2. Add the steak and sear until browned.",
            rule_tags=["recipe_span_fallback"],
        )
    ]

    def _fake_codex_call(**_kwargs):
        return {
            "response": "not-json",
            "returncode": 0,
            "stdout": "not-json",
            "stderr": "",
            "usage": None,
            "turn_failed_message": None,
        }

    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles.run_codex_json_prompt",
        _fake_codex_call,
    )
    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-v1"),
        artifact_root=tmp_path,
    )
    assert predictions[0].label == "OTHER"
    assert predictions[0].decided_by == "fallback"
    assert "deterministic_unavailable" in predictions[0].reason_tags
    parse_errors_path = tmp_path / "line-role-pipeline" / "prompts" / "parse_errors.json"
    payload = json.loads(parse_errors_path.read_text(encoding="utf-8"))
    assert payload["parse_error_count"] == 1
    assert payload["parse_error_present"] is True


def test_canonical_line_role_prompt_includes_required_contract_text() -> None:
    candidate = AtomicLineCandidate(
        recipe_id="r1",
        block_id="block:1",
        block_index=1,
        atomic_index=0,
        text="SERVES 4",
        within_recipe_span=True,
        candidate_labels=["YIELD_LINE", "OTHER"],
        prev_text="",
        next_text="2 tablespoons olive oil",
        rule_tags=["yield_prefix"],
    )
    prompt = build_canonical_line_role_prompt([candidate])
    assert "schema.org extraction" in prompt
    assert "RECIPE_TITLE > RECIPE_VARIANT > YIELD_LINE > HOWTO_SECTION >" in prompt
    assert "Never label a quantity/unit ingredient line as `KNOWLEDGE`." in prompt
    assert '"atomic_index": 0' in prompt
    assert '"candidate_labels": ["YIELD_LINE", "OTHER"]' in prompt


def test_codex_knowledge_inside_recipe_requires_explicit_prose_tags(
    monkeypatch,
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
            candidate_labels=["OTHER", "KNOWLEDGE"],
            prev_text=None,
            next_text="middle",
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
            candidate_labels=["OTHER", "KNOWLEDGE"],
            prev_text="prev",
            next_text="next",
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
            candidate_labels=["OTHER", "KNOWLEDGE"],
            prev_text="middle",
            next_text=None,
            rule_tags=["recipe_span_fallback", "explicit_prose"],
        ),
    ]

    def _fake_codex_call(**_kwargs):
        return {
            "response": json.dumps(
                [
                    {"atomic_index": 0, "label": "OTHER"},
                    {"atomic_index": 1, "label": "KNOWLEDGE"},
                    {"atomic_index": 2, "label": "OTHER"},
                ]
            ),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "usage": None,
            "turn_failed_message": None,
        }

    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles.run_codex_json_prompt",
        _fake_codex_call,
    )
    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-v1"),
        artifact_root=tmp_path,
    )
    by_index = {row.atomic_index: row for row in predictions}
    assert by_index[1].label == "KNOWLEDGE"
    assert by_index[1].decided_by == "codex"


def test_codex_knowledge_inside_recipe_rejected_without_explicit_prose_tag(
    monkeypatch,
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
            candidate_labels=["OTHER", "KNOWLEDGE"],
            prev_text=None,
            next_text="middle",
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
            candidate_labels=["OTHER", "KNOWLEDGE"],
            prev_text="prev",
            next_text="next",
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
            candidate_labels=["OTHER", "KNOWLEDGE"],
            prev_text="middle",
            next_text=None,
            rule_tags=["recipe_span_fallback", "explicit_prose"],
        ),
    ]

    def _fake_codex_call(**_kwargs):
        return {
            "response": json.dumps(
                [
                    {"atomic_index": 0, "label": "OTHER"},
                    {"atomic_index": 1, "label": "KNOWLEDGE"},
                    {"atomic_index": 2, "label": "OTHER"},
                ]
            ),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "usage": None,
            "turn_failed_message": None,
        }

    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles.run_codex_json_prompt",
        _fake_codex_call,
    )
    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-v1"),
        artifact_root=tmp_path,
    )
    by_index = {row.atomic_index: row for row in predictions}
    assert by_index[1].label == "OTHER"
    assert by_index[1].decided_by == "fallback"


def test_codex_mode_escalates_low_confidence_deterministic_candidates(monkeypatch) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:1",
            block_index=1,
            atomic_index=0,
            text="CONTENTS",
            within_recipe_span=False,
            candidate_labels=["OTHER", "KNOWLEDGE"],
            prev_text=None,
            next_text=None,
            rule_tags=["outside_recipe_span"],
        )
    ]

    def _fake_codex_call(**_kwargs):
        return {
            "response": json.dumps([{"atomic_index": 0, "label": "KNOWLEDGE"}]),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "usage": None,
            "turn_failed_message": None,
        }

    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles.run_codex_json_prompt",
        _fake_codex_call,
    )
    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-v1"),
    )
    assert len(predictions) == 1
    assert predictions[0].label == "KNOWLEDGE"
    assert predictions[0].decided_by == "codex"
