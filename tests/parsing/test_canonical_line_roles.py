from __future__ import annotations

import json
import re
import time

from cookimport.config.run_settings import RunSettings
from cookimport.llm.canonical_line_role_prompt import (
    build_canonical_line_role_prompt,
    serialize_line_role_targets,
)
from cookimport.parsing import canonical_line_roles as canonical_line_roles_module
from cookimport.parsing.canonical_line_roles import label_atomic_lines
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate, atomize_blocks
from tests.paths import FIXTURES_DIR


def _load_fixture(name: str) -> dict[str, object]:
    fixture_path = FIXTURES_DIR / "canonical_labeling" / name
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def _settings(mode: str = "deterministic-v1", **kwargs):
    return RunSettings(line_role_pipeline=mode, **kwargs)


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
        "cookimport.parsing.canonical_line_roles._run_line_role_prompt_via_codex_farm",
        _fake_codex_call,
    )
    predictions = label_atomic_lines(candidates, _settings("codex-line-role-v1"))
    assert len(predictions) == 1
    assert predictions[0].label == "INSTRUCTION_LINE"
    assert predictions[0].decided_by == "fallback"
    assert "sanitized_time_to_instruction" in predictions[0].reason_tags


def test_label_atomic_lines_passes_explicit_live_llm_approval_to_codex_calls(
    monkeypatch,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:ambiguous:1",
            block_index=1,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            prev_text=None,
            next_text=None,
            rule_tags=["recipe_span_fallback"],
        )
    ]
    observed_allow_llm: list[bool] = []

    def _fake_codex_call(**kwargs):
        observed_allow_llm.append(bool(kwargs.get("allow_llm")))
        return {
            "response": json.dumps([{"atomic_index": 0, "label": "OTHER"}]),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "usage": None,
            "turn_failed_message": None,
        }

    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles._run_line_role_prompt_via_codex_farm",
        _fake_codex_call,
    )
    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-v1"),
        live_llm_allowed=True,
    )
    assert observed_allow_llm == [True]
    assert predictions[0].decided_by == "codex"


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


def test_label_atomic_lines_outside_recipe_science_prose_is_knowledge() -> None:
    blocks = [
        {
            "block_id": "block:knowledge:science",
            "block_index": 1,
            "text": (
                "The primary role that salt plays in cooking is to amplify flavor. "
                "Though salt also affects texture, nearly every decision you make "
                "about salt will involve enhancing and deepening flavor."
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


def test_label_atomic_lines_outside_recipe_knowledge_heading_uses_neighbor_context() -> None:
    blocks = [
        {
            "block_id": "block:knowledge:prev",
            "block_index": 1,
            "text": (
                "Salt affects texture and flavor because it changes how food "
                "absorbs moisture during cooking."
            ),
        },
        {
            "block_id": "block:knowledge:heading",
            "block_index": 2,
            "text": "SALT AND FLAVOR",
        },
        {
            "block_id": "block:knowledge:next",
            "block_index": 3,
            "text": (
                "The relationship between salt and flavor is multidimensional, "
                "and even small changes can improve aroma and balance bitterness."
            ),
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    by_text = {prediction.text: prediction for prediction in predictions}
    assert by_text["SALT AND FLAVOR"].label == "KNOWLEDGE"


def test_label_atomic_lines_outside_recipe_first_person_learning_prose_is_not_recipe_notes() -> None:
    blocks = [
        {
            "block_id": "block:knowledge:first-person",
            "block_index": 1,
            "text": (
                "As I improved, I began to detect the nuances that distinguish good "
                "food from great, understanding when pasta water needed more salt "
                "and when vinegar was needed to balance a rich stew."
            ),
        },
        {
            "block_id": "block:knowledge:neighbor",
            "block_index": 2,
            "text": (
                "Salt, fat, acid, and heat guided those decisions because each one "
                "changed flavor, texture, and temperature in predictable ways."
            ),
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    by_text = {prediction.text: prediction for prediction in predictions}
    assert (
        by_text[
            "As I improved, I began to detect the nuances that distinguish good "
            "food from great, understanding when pasta water needed more salt "
            "and when vinegar was needed to balance a rich stew."
        ].label
        == "KNOWLEDGE"
    )


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


def test_label_atomic_lines_outside_recipe_variant_heading_without_context_is_downgraded() -> None:
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
    assert predictions[0].label in {"OTHER", "KNOWLEDGE"}


def test_label_atomic_lines_outside_recipe_structured_cluster_needs_anchor_evidence() -> None:
    blocks = [
        {
            "block_id": "block:ingredient:1",
            "block_index": 1,
            "text": "1 tablespoon kosher salt",
        },
        {
            "block_id": "block:instruction:2",
            "block_index": 2,
            "text": "Stir to combine.",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 2
    assert predictions[0].label in {"OTHER", "KNOWLEDGE"}
    assert predictions[1].label in {"OTHER", "KNOWLEDGE"}


def test_label_atomic_lines_outside_recipe_howto_heading_is_hard_denied() -> None:
    blocks = [
        {
            "block_id": "block:howto:outside:1",
            "block_index": 1,
            "text": "FOR THE SAUCE",
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label != "HOWTO_SECTION"


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


def test_label_atomic_lines_heading_like_line_without_neighboring_evidence_is_not_title() -> None:
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
    assert predictions[0].label in {"OTHER", "KNOWLEDGE"}


def test_label_atomic_lines_heading_like_line_with_neighboring_structure_can_be_title() -> None:
    blocks = [
        {
            "block_id": "block:title:with-context:1",
            "block_index": 1,
            "text": "POACHED EGGS",
        },
        {
            "block_id": "block:title:with-context:2",
            "block_index": 2,
            "text": "2 large eggs",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 2
    assert predictions[0].label == "RECIPE_TITLE"


def test_label_atomic_lines_outside_recipe_long_mixed_case_title_with_yield_is_title() -> None:
    blocks = [
        {
            "block_id": "block:title:long:1",
            "block_index": 1,
            "text": "Pan-Roasted Filets Mignons with Asparagus and Garlic-Herb Butter",
        },
        {
            "block_id": "block:title:long:2",
            "block_index": 2,
            "text": "serves 2",
        },
        {
            "block_id": "block:title:long:3",
            "block_index": 3,
            "text": "total time: 45 minutes",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert predictions[0].label == "RECIPE_TITLE"


def test_label_atomic_lines_outside_recipe_all_caps_verb_heading_can_be_title() -> None:
    blocks = [
        {
            "block_id": "block:title:verb:1",
            "block_index": 1,
            "text": "ROAST GROUSE WITH BREAD SAUCE AND GAME CRUMBS",
        },
        {
            "block_id": "block:title:verb:2",
            "block_index": 2,
            "text": "NOTE: Keep the birds cool before cooking.",
        },
        {
            "block_id": "block:title:verb:3",
            "block_index": 3,
            "text": "serves 4",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert predictions[0].label == "RECIPE_TITLE"


def test_label_atomic_lines_outside_recipe_title_can_look_past_note_line() -> None:
    blocks = [
        {
            "block_id": "block:title:note:1",
            "block_index": 1,
            "text": "FOOLPROOF SOFT-BOILED EGGS",
        },
        {
            "block_id": "block:title:note:2",
            "block_index": 2,
            "text": "NOTE: Practice once if needed.",
        },
        {
            "block_id": "block:title:note:3",
            "block_index": 3,
            "text": "1 quart water",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert predictions[0].label == "RECIPE_TITLE"


def test_label_atomic_lines_outside_recipe_toc_heading_is_not_recipe_title() -> None:
    blocks = [
        {
            "block_id": "block:title:toc:1",
            "block_index": 1,
            "text": "THE BASIC PANTRY",
        },
        {
            "block_id": "block:title:toc:2",
            "block_index": 2,
            "text": "1 EGGS, DAIRY, and the Science of Breakfast",
        },
        {
            "block_id": "block:title:toc:3",
            "block_index": 3,
            "text": "2 SOUPS, STEWS, and the Science of Stock",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert predictions[0].label == "OTHER"


def test_label_atomic_lines_outside_recipe_how_to_heading_is_not_recipe_title() -> None:
    blocks = [
        {
            "block_id": "block:title:howto:1",
            "block_index": 1,
            "text": "How to Cut a Bell Pepper",
        },
        {
            "block_id": "block:title:howto:2",
            "block_index": 2,
            "text": "There are two camps when it comes to cutting peppers.",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert predictions[0].label != "RECIPE_TITLE"


def test_codex_neighbor_ingredient_fragment_rescued_to_ingredient(monkeypatch) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:ingredient:0",
            block_index=0,
            atomic_index=0,
            text="1 cup",
            within_recipe_span=True,
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
        "cookimport.parsing.canonical_line_roles._run_line_role_prompt_via_codex_farm",
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


def test_label_atomic_lines_recipe_title_with_immediate_note_prose_stays_recipe_title() -> None:
    blocks = [
        {
            "block_id": "block:title:note-prose:1",
            "block_index": 1,
            "text": "LEEKS VINAIGRETTE",
        },
        {
            "block_id": "block:title:note-prose:2",
            "block_index": 2,
            "text": (
                "I like this best when the leeks are barely warm and the dressing "
                "has had a minute to soak in."
            ),
        },
        {
            "block_id": "block:title:note-prose:3",
            "block_index": 3,
            "text": "2 large leeks",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id="recipe:0",
        within_recipe_span=True,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert predictions[0].label == "RECIPE_TITLE"


def test_label_atomic_lines_non_header_yield_phrase_demotes_to_instruction() -> None:
    blocks = [
        {
            "block_id": "block:yield:1",
            "block_index": 1,
            "text": "SERVES with crusty bread and lemon wedges.",
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id="recipe:0",
        within_recipe_span=True,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "INSTRUCTION_LINE"
    assert "sanitized_yield_to_instruction" in predictions[0].reason_tags


def test_label_atomic_lines_title_like_line_without_supportive_next_line_is_not_title() -> None:
    blocks = [
        {
            "block_id": "block:title:outside:1",
            "block_index": 1,
            "text": "PAN-SEARED SALMON",
        },
        {
            "block_id": "block:title:outside:2",
            "block_index": 2,
            "text": (
                "I learned this on a rainy night, and this paragraph is narrative "
                "context rather than an ingredient list or recipe boundary line."
            ),
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 2
    assert predictions[0].label == "OTHER"


def test_title_like_line_stays_resolved_when_full_book_codex_reviews_it(
    monkeypatch,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:title:1",
            block_index=1,
            atomic_index=0,
            text="A PORRIDGE OF LOVAGE STEMS",
            within_recipe_span=True,
            prev_text=None,
            next_text=None,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    observed_prompts: list[str] = []

    def _fake_codex_call(**kwargs):
        observed_prompts.append(str(kwargs.get("prompt") or ""))
        return {
            "response": json.dumps([{"atomic_index": 0, "label": "OTHER"}]),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "usage": None,
            "turn_failed_message": None,
        }

    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles._run_line_role_prompt_via_codex_farm",
        _fake_codex_call,
    )
    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-v1"),
    )
    assert len(observed_prompts) == 1
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_TITLE"
    assert predictions[0].decided_by in {"rule", "fallback"}


def test_codex_mode_accepts_global_label_not_present_in_old_shortlist(monkeypatch) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:title:global",
            block_index=1,
            atomic_index=0,
            text="Shaved Carrot Salad with Ginger and Lime",
            within_recipe_span=True,
            prev_text=None,
            next_text="1 large jalapeño, seeds and veins removed if desired, thinly sliced",
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
        "cookimport.parsing.canonical_line_roles._run_line_role_prompt_via_codex_farm",
        _fake_codex_call,
    )
    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-v1"),
    )
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_TITLE"
    assert predictions[0].decided_by == "codex"


def test_label_ownership_vetoes_codex_override_of_strong_recipe_note() -> None:
    candidate = AtomicLineCandidate(
        recipe_id="recipe:0",
        block_id="block:note:0",
        block_index=0,
        atomic_index=0,
        text="NOTE: Keep blender cup warm.",
        within_recipe_span=True,
        prev_text=None,
        next_text="Whisk in the butter.",
        rule_tags=["note_prefix"],
    )
    accepted = canonical_line_roles_module._apply_label_ownership_arbitration(
        prediction=canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id="recipe:0",
            block_id="block:note:0",
            block_index=0,
            atomic_index=0,
            text="NOTE: Keep blender cup warm.",
            within_recipe_span=True,
            label="OTHER",
            decided_by="codex",
            reason_tags=["codex_line_role"],
        ),
        baseline_prediction=canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id="recipe:0",
            block_id="block:note:0",
            block_index=0,
            atomic_index=0,
            text="NOTE: Keep blender cup warm.",
            within_recipe_span=True,
            label="RECIPE_NOTES",
            decided_by="rule",
            reason_tags=["note_prefix"],
        ),
        candidate=candidate,
        by_atomic_index={0: candidate},
    )

    assert accepted.label == "RECIPE_NOTES"
    assert accepted.decided_by == "fallback"
    assert "ownership_veto_recipe_notes" in accepted.reason_tags


def test_label_ownership_rejects_codex_time_line_without_strong_local_evidence() -> None:
    candidate = AtomicLineCandidate(
        recipe_id="recipe:0",
        block_id="block:time:0",
        block_index=0,
        atomic_index=0,
        text="Stir well and taste for seasoning.",
        within_recipe_span=True,
        prev_text="1 cup stock",
        next_text="Serve warm.",
        rule_tags=["instruction_like"],
    )
    accepted = canonical_line_roles_module._apply_label_ownership_arbitration(
        prediction=canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id="recipe:0",
            block_id="block:time:0",
            block_index=0,
            atomic_index=0,
            text="Stir well and taste for seasoning.",
            within_recipe_span=True,
            label="TIME_LINE",
            decided_by="codex",
            reason_tags=["codex_line_role"],
        ),
        baseline_prediction=canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id="recipe:0",
            block_id="block:time:0",
            block_index=0,
            atomic_index=0,
            text="Stir well and taste for seasoning.",
            within_recipe_span=True,
            label="INSTRUCTION_LINE",
            decided_by="rule",
            reason_tags=["instruction_like"],
        ),
        candidate=candidate,
        by_atomic_index={0: candidate},
    )

    assert accepted.label == "INSTRUCTION_LINE"
    assert accepted.decided_by == "fallback"
    assert "ownership_veto_time_line_needs_strong_evidence" in accepted.reason_tags


def test_codex_mode_preserves_deterministic_recipe_title_without_score_escalation(monkeypatch) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:title:2",
            block_index=2,
            atomic_index=0,
            text="A PORRIDGE OF LOVAGE STEMS",
            within_recipe_span=False,
            prev_text=None,
            next_text="2 tablespoons olive oil",
            rule_tags=["outside_recipe_span"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:title:3",
            block_index=3,
            atomic_index=1,
            text="2 tablespoons olive oil",
            within_recipe_span=False,
            prev_text="A PORRIDGE OF LOVAGE STEMS",
            next_text=None,
            rule_tags=["ingredient_like", "outside_recipe_span"],
        )
    ]

    def _codex_should_not_run(**_kwargs):
        raise AssertionError("codex runner should not execute for deterministic title hold")

    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles._run_line_role_prompt_via_codex_farm",
        _codex_should_not_run,
    )
    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-v1"),
    )
    assert len(predictions) == 2
    assert predictions[0].label == "RECIPE_TITLE"
    assert predictions[0].decided_by == "rule"
    assert predictions[0].escalation_reasons == ["outside_span_structured_label"]


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
        "cookimport.parsing.canonical_line_roles._run_line_role_prompt_via_codex_farm",
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
    do_no_harm_path = tmp_path / "line-role-pipeline" / "do_no_harm_diagnostics.json"
    assert do_no_harm_path.exists()


def test_canonical_line_role_prompt_includes_required_contract_text() -> None:
    candidate = AtomicLineCandidate(
        recipe_id="r1",
        block_id="block:1",
        block_index=1,
        atomic_index=0,
        text="SERVES 4",
        within_recipe_span=True,
        prev_text="",
        next_text="2 tablespoons olive oil",
        rule_tags=["yield_prefix"],
    )
    prompt = build_canonical_line_role_prompt(
        [candidate],
        allowed_labels=["OTHER", "YIELD_LINE", "INGREDIENT_LINE"],
        escalation_reasons_by_atomic_index={0: ["deterministic_unresolved"]},
    )
    assert "schema.org extraction" in prompt
    assert "RECIPE_TITLE > RECIPE_VARIANT > YIELD_LINE > HOWTO_SECTION >" in prompt
    assert "Never label a quantity/unit ingredient line as `KNOWLEDGE`." in prompt
    assert "Label codes: L0=OTHER, L1=YIELD_LINE, L2=INGREDIENT_LINE" in prompt
    assert "Escalation reason codes: R0=deterministic_unresolved" in prompt
    assert "Recipe atomic index ranges for this batch: 0" in prompt
    assert '[0, "L0", "R0", "SERVES 4", ["", "2 tablespoons olive oil"]]' in prompt


def test_canonical_line_role_prompt_compact_format_defines_row_schema_once() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="r1",
            block_id="block:1",
            block_index=1,
            atomic_index=0,
            text="SERVES 4",
            within_recipe_span=True,
            prev_text="",
            next_text="2 tablespoons olive oil",
            rule_tags=["yield_prefix"],
        ),
        AtomicLineCandidate(
            recipe_id="r1",
            block_id="block:2",
            block_index=2,
            atomic_index=1,
            text="2 tablespoons olive oil",
            within_recipe_span=True,
            prev_text="SERVES 4",
            next_text="Whisk and serve.",
            rule_tags=["ingredient_like"],
        ),
    ]

    prompt = build_canonical_line_role_prompt(
        candidates,
        prompt_format="compact_v1",
        allowed_labels=["YIELD_LINE", "OTHER", "INGREDIENT_LINE"],
    )
    assert "[atomic_index, label_code, reason_codes, current_line]" in prompt
    assert prompt.count("[atomic_index, label_code, reason_codes, current_line]") == 1
    assert "Recipe atomic index ranges for this batch: 0-1" in prompt
    assert '[0, "L1", "-", "SERVES 4"]' in prompt
    assert '[1, "L1", "-", "2 tablespoons olive oil"]' in prompt

    compact_rows = serialize_line_role_targets(
        candidates,
        allowed_labels=["YIELD_LINE", "OTHER", "INGREDIENT_LINE"],
    )
    assert compact_rows.splitlines() == [
        '[0, "L1", "-", "SERVES 4"]',
        '[1, "L1", "-", "2 tablespoons olive oil"]',
    ]


def test_canonical_line_role_prompt_blanks_neighbors_outside_recipe_rows() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:1",
            block_index=1,
            atomic_index=0,
            text="Praise for SALT FAT ACID HEAT",
            within_recipe_span=False,
            prev_text="Front matter",
            next_text="Quote paragraph",
            rule_tags=["outside_recipe"],
        ),
        AtomicLineCandidate(
            recipe_id="r1",
            block_id="block:2",
            block_index=2,
            atomic_index=1,
            text="SERVES 4",
            within_recipe_span=True,
            prev_text="",
            next_text="2 tablespoons olive oil",
            rule_tags=["yield_prefix"],
        ),
    ]

    compact_rows = serialize_line_role_targets(
        candidates,
        allowed_labels=["YIELD_LINE", "OTHER", "INGREDIENT_LINE"],
        escalation_reasons_by_atomic_index={
            0: ["outside_span_structured_label"],
            1: ["deterministic_unresolved"],
        },
    ).splitlines()

    compact_outside = json.loads(compact_rows[0])
    assert compact_outside == [0, "L1", "R0", "Praise for SALT FAT ACID HEAT"]

    compact_inside = json.loads(compact_rows[1])
    assert compact_inside == [
        1,
        "L1",
        "R1",
        "SERVES 4",
        ["", "2 tablespoons olive oil"],
    ]


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
        "cookimport.parsing.canonical_line_roles._run_line_role_prompt_via_codex_farm",
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
        "cookimport.parsing.canonical_line_roles._run_line_role_prompt_via_codex_farm",
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


def test_codex_mode_does_not_escalate_outside_recipe_span_candidates_without_reasons(
    monkeypatch,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:1",
            block_index=1,
            atomic_index=0,
            text="CONTENTS",
            within_recipe_span=False,
            prev_text=None,
            next_text=None,
            rule_tags=["outside_recipe_span"],
        )
    ]

    def _should_not_call_codex(**_kwargs):
        raise AssertionError("outside-span score-based escalation should be gone")

    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles._run_line_role_prompt_via_codex_farm",
        _should_not_call_codex,
    )
    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-v1"),
    )
    assert len(predictions) == 1
    assert predictions[0].label == "OTHER"
    assert predictions[0].decided_by in {"rule", "fallback"}
    assert predictions[0].escalation_reasons == []


def test_do_no_harm_arbitration_partially_downgrades_outside_promotions() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id=f"block:{index}",
            block_index=index,
            atomic_index=index,
            text=f"candidate {index}",
            within_recipe_span=False,
            prev_text=None,
            next_text=None,
            rule_tags=["outside_recipe_span"],
        )
        for index in range(2)
    ]
    candidates.extend(
        [
            AtomicLineCandidate(
                recipe_id=f"recipe:{index}",
                block_id=f"block:inside:{index}",
                block_index=index + 2,
                atomic_index=index + 2,
                text=f"inside {index}",
                within_recipe_span=True,
                prev_text=None,
                next_text=None,
                rule_tags=["instruction_like"],
            )
            for index in range(8)
        ]
    )
    candidate_predictions = {
        0: canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id=None,
            block_id="block:0",
            block_index=0,
            atomic_index=0,
            text="candidate 0",
            within_recipe_span=False,
            label="RECIPE_TITLE",
            decided_by="codex",
            reason_tags=["codex_line_role"],
        ),
        1: canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id=None,
            block_id="block:1",
            block_index=1,
            atomic_index=1,
            text="candidate 1",
            within_recipe_span=False,
            label="RECIPE_VARIANT",
            decided_by="codex",
            reason_tags=["codex_line_role"],
        ),
    }
    for index in range(2, 10):
        candidate_predictions[index] = canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id=f"recipe:{index}",
            block_id=f"block:inside:{index}",
            block_index=index,
            atomic_index=index,
            text=f"inside {index}",
            within_recipe_span=True,
            label="INSTRUCTION_LINE",
            decided_by="rule",
            reason_tags=["instruction_like"],
        )
    baseline_predictions = {
        index: canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id=None,
            block_id=f"block:{index}",
            block_index=index,
            atomic_index=index,
            text=f"candidate {index}",
            within_recipe_span=False,
            label="OTHER",
            decided_by="rule",
            reason_tags=["outside_recipe_span"],
        )
        for index in range(2)
    }
    for index in range(2, 10):
        baseline_predictions[index] = canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id=f"recipe:{index}",
            block_id=f"block:inside:{index}",
            block_index=index,
            atomic_index=index,
            text=f"inside {index}",
            within_recipe_span=True,
            label="INSTRUCTION_LINE",
            decided_by="rule",
            reason_tags=["instruction_like"],
        )

    accepted, diagnostics, changed_rows = (
        canonical_line_roles_module._apply_do_no_harm_arbitration(
            ordered_candidates=candidates,
            candidate_predictions=candidate_predictions,
            baseline_predictions=baseline_predictions,
        )
    )

    assert diagnostics["decision"]["scope"] == "partial_outside_downgrade"
    assert diagnostics["outside_title_variant_promotions"] == 2
    assert all(accepted[index].label == "OTHER" for index in range(2))
    assert len(changed_rows) == 2


def test_do_no_harm_arbitration_full_fallback_reverts_all_rows() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id=f"block:{index}",
            block_index=index,
            atomic_index=index,
            text=f"candidate {index}",
            within_recipe_span=(index >= 8),
            prev_text=None,
            next_text=None,
            rule_tags=["outside_recipe_span"],
        )
        for index in range(10)
    ]
    candidate_predictions: dict[int, canonical_line_roles_module.CanonicalLineRolePrediction] = {}
    baseline_predictions: dict[int, canonical_line_roles_module.CanonicalLineRolePrediction] = {}
    for index in range(10):
        candidate_predictions[index] = canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id=None,
            block_id=f"block:{index}",
            block_index=index,
            atomic_index=index,
            text=f"candidate {index}",
            within_recipe_span=(index >= 8),
            label="RECIPE_TITLE" if index < 8 else "INSTRUCTION_LINE",
            decided_by="codex",
            reason_tags=["codex_line_role"],
        )
        baseline_predictions[index] = canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id=None,
            block_id=f"block:{index}",
            block_index=index,
            atomic_index=index,
            text=f"candidate {index}",
            within_recipe_span=(index >= 8),
            label="OTHER",
            decided_by="rule",
            reason_tags=["baseline"],
        )

    accepted, diagnostics, changed_rows = (
        canonical_line_roles_module._apply_do_no_harm_arbitration(
            ordered_candidates=candidates,
            candidate_predictions=candidate_predictions,
            baseline_predictions=baseline_predictions,
        )
    )

    assert diagnostics["decision"]["scope"] == "full_source_fallback"
    assert diagnostics["outside_recipeish_promotions"] == 8
    assert all(accepted[index].label == "OTHER" for index in range(10))
    assert len(changed_rows) == 10


def test_line_role_guardrail_preview_report_writes_non_mutating_artifacts(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:preview:0",
            block_index=0,
            atomic_index=0,
            text="candidate 0",
            within_recipe_span=False,
            prev_text=None,
            next_text=None,
            rule_tags=["outside_recipe_span"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:preview:1",
            block_index=1,
            atomic_index=1,
            text="candidate 1",
            within_recipe_span=False,
            prev_text=None,
            next_text=None,
            rule_tags=["outside_recipe_span"],
        ),
    ]
    candidates.extend(
        [
            AtomicLineCandidate(
                recipe_id=f"recipe:{index}",
                block_id=f"block:inside:{index}",
                block_index=index + 2,
                atomic_index=index + 2,
                text=f"inside {index}",
                within_recipe_span=True,
                prev_text=None,
                next_text=None,
                rule_tags=["instruction_like"],
            )
            for index in range(8)
        ]
    )
    candidate_predictions = {
        0: canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id=None,
            block_id="block:preview:0",
            block_index=0,
            atomic_index=0,
            text="candidate 0",
            within_recipe_span=False,
            label="RECIPE_TITLE",
            decided_by="codex",
            reason_tags=["codex_line_role"],
        ),
        1: canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id=None,
            block_id="block:preview:1",
            block_index=1,
            atomic_index=1,
            text="candidate 1",
            within_recipe_span=False,
            label="RECIPE_VARIANT",
            decided_by="codex",
            reason_tags=["codex_line_role"],
        ),
    }
    baseline_predictions = {
        0: canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id=None,
            block_id="block:preview:0",
            block_index=0,
            atomic_index=0,
            text="candidate 0",
            within_recipe_span=False,
            label="OTHER",
            decided_by="rule",
            reason_tags=["outside_recipe_span"],
        ),
        1: canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id=None,
            block_id="block:preview:1",
            block_index=1,
            atomic_index=1,
            text="candidate 1",
            within_recipe_span=False,
            label="OTHER",
            decided_by="rule",
            reason_tags=["outside_recipe_span"],
        ),
    }
    for index in range(2, 10):
        candidate_predictions[index] = canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id=f"recipe:{index}",
            block_id=f"block:inside:{index}",
            block_index=index,
            atomic_index=index,
            text=f"inside {index}",
            within_recipe_span=True,
            label="INSTRUCTION_LINE",
            decided_by="rule",
            reason_tags=["instruction_like"],
        )
        baseline_predictions[index] = canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id=f"recipe:{index}",
            block_id=f"block:inside:{index}",
            block_index=index,
            atomic_index=index,
            text=f"inside {index}",
            within_recipe_span=True,
            label="INSTRUCTION_LINE",
            decided_by="rule",
            reason_tags=["instruction_like"],
        )

    _accepted, diagnostics, changed_rows = canonical_line_roles_module._apply_do_no_harm_arbitration(
        ordered_candidates=candidates,
        candidate_predictions=candidate_predictions,
        baseline_predictions=baseline_predictions,
    )
    report = canonical_line_roles_module._build_line_role_guardrail_report(
        guardrail_mode="preview",
        diagnostics=diagnostics,
        changed_rows=changed_rows,
    )
    canonical_line_roles_module._write_line_role_guardrail_artifacts(
        artifact_root=tmp_path,
        report=report,
        diagnostics=diagnostics,
        changed_rows=changed_rows,
    )

    guardrail_report = json.loads(
        (tmp_path / "line-role-pipeline" / "guardrail_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert guardrail_report["mode"] == "preview"
    assert guardrail_report["applied"] is False
    assert guardrail_report["would_change_rows"] == 2
    assert (tmp_path / "line-role-pipeline" / "guardrail_changed_rows.jsonl").exists()
    assert (tmp_path / "line-role-pipeline" / "do_no_harm_diagnostics.json").exists()


def test_line_role_guardrail_off_report_disables_arbitration_artifacts(
    tmp_path,
) -> None:
    report = canonical_line_roles_module._build_line_role_guardrail_report(
        guardrail_mode="off",
        diagnostics=None,
        changed_rows=[],
    )
    canonical_line_roles_module._write_line_role_guardrail_artifacts(
        artifact_root=tmp_path,
        report=report,
        diagnostics=None,
        changed_rows=[],
    )

    guardrail_report = json.loads(
        (tmp_path / "line-role-pipeline" / "guardrail_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert guardrail_report["mode"] == "off"
    assert guardrail_report["decision"]["scope"] == "disabled"
    assert not (tmp_path / "line-role-pipeline" / "do_no_harm_diagnostics.json").exists()


def test_build_line_role_codex_execution_plan_covers_all_rows_in_codex_mode() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous title-ish line",
            within_recipe_span=True,
            prev_text=None,
            next_text="1 cup flour",
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:1",
            block_index=1,
            atomic_index=1,
            text="1 cup flour",
            within_recipe_span=True,
            prev_text="Ambiguous title-ish line",
            next_text=None,
            rule_tags=["ingredient_like"],
        ),
    ]

    plan = canonical_line_roles_module.build_line_role_codex_execution_plan(
        candidates,
        _settings("codex-line-role-v1"),
        codex_batch_size=10,
    )

    assert plan["enabled"] is True
    assert plan["planned_batch_count"] == 1
    assert plan["planned_candidate_count"] == 2
    assert plan["batches"][0]["atomic_indices"] == [0, 1]
    assert plan["batches"][0]["rows"][0]["deterministic_label"] == "OTHER"
    assert plan["batches"][0]["rows"][1]["deterministic_label"] == "INGREDIENT_LINE"
    assert plan["batches"][0]["rows"][0]["escalation_reasons"] == [
        "deterministic_unresolved",
        "fallback_decision",
    ]


def test_build_line_role_codex_execution_plan_uses_shared_default_batch_size() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:{index}",
            block_index=index,
            atomic_index=index,
            text=f"Line {index}",
            within_recipe_span=False,
            prev_text=None,
            next_text=None,
            rule_tags=[],
        )
        for index in range(canonical_line_roles_module.LINE_ROLE_CODEX_BATCH_SIZE_DEFAULT + 1)
    ]

    plan = canonical_line_roles_module.build_line_role_codex_execution_plan(
        candidates,
        _settings("codex-line-role-v1"),
    )

    assert plan["codex_batch_size"] == canonical_line_roles_module.LINE_ROLE_CODEX_BATCH_SIZE_DEFAULT
    assert plan["planned_candidate_count"] == len(candidates)
    assert plan["planned_batch_count"] == 2
    assert plan["batches"][0]["candidate_count"] == canonical_line_roles_module.LINE_ROLE_CODEX_BATCH_SIZE_DEFAULT
    assert plan["batches"][1]["candidate_count"] == 1


def test_label_atomic_lines_codex_retries_transient_failures(monkeypatch) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:retry:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            prev_text=None,
            next_text=None,
            rule_tags=["recipe_span_fallback"],
        )
    ]
    call_count = {"value": 0}
    observed_sleeps: list[float] = []

    def _fake_sleep(seconds: float) -> None:
        observed_sleeps.append(float(seconds))

    def _fake_codex_call(**_kwargs):
        call_count["value"] += 1
        if call_count["value"] < 3:
            return {
                "response": "",
                "returncode": 1,
                "stdout": "",
                "stderr": "temporary service unavailable",
                "usage": None,
                "turn_failed_message": "transient",
            }
        return {
            "response": json.dumps([{"atomic_index": 0, "label": "OTHER"}]),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "usage": None,
            "turn_failed_message": None,
        }

    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles.time.sleep",
        _fake_sleep,
    )
    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles._run_line_role_prompt_via_codex_farm",
        _fake_codex_call,
    )
    predictions = label_atomic_lines(candidates, _settings("codex-line-role-v1"))
    assert len(predictions) == 1
    assert predictions[0].label == "OTHER"
    assert predictions[0].decided_by == "codex"
    assert call_count["value"] == 3
    assert observed_sleeps == [1.5, 3.0]


def test_label_atomic_lines_codex_cache_hit_skips_runner(
    monkeypatch,
    tmp_path,
) -> None:
    settings = _settings("codex-line-role-v1")
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:cache:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            prev_text=None,
            next_text=None,
            rule_tags=["recipe_span_fallback"],
        )
    ]
    call_count = {"value": 0}

    def _fake_codex_call(**_kwargs):
        call_count["value"] += 1
        return {
            "response": json.dumps([{"atomic_index": 0, "label": "OTHER"}]),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "usage": None,
            "turn_failed_message": None,
        }

    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles._run_line_role_prompt_via_codex_farm",
        _fake_codex_call,
    )
    first = label_atomic_lines(
        candidates,
        settings,
        artifact_root=tmp_path / "artifacts",
        source_hash="source-hash-1",
        cache_root=tmp_path / "line-role-cache",
    )
    assert call_count["value"] == 1
    assert first[0].decided_by == "codex"

    def _runner_should_not_execute(**_kwargs):
        raise AssertionError("cache hit should skip codex call")

    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles._run_line_role_prompt_via_codex_farm",
        _runner_should_not_execute,
    )
    second = label_atomic_lines(
        candidates,
        settings,
        artifact_root=tmp_path / "artifacts",
        source_hash="source-hash-1",
        cache_root=tmp_path / "line-role-cache",
    )
    assert second[0].label == first[0].label
    assert second[0].decided_by == first[0].decided_by
    cache_files = list((tmp_path / "line-role-cache").rglob("*.json"))
    assert cache_files


def test_label_atomic_lines_writes_line_role_telemetry_summary_with_retry_usage(
    monkeypatch,
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
            prev_text=None,
            next_text=None,
            rule_tags=["recipe_span_fallback"],
        )
    ]
    responses = iter(
        [
            {
                "response": "",
                "returncode": 1,
                "stdout": "",
                "stderr": "transient",
                "usage": {
                    "input_tokens": 10,
                    "cached_input_tokens": 2,
                    "output_tokens": 3,
                    "reasoning_tokens": 1,
                },
                "turn_failed_message": "retry me",
            },
            {
                "response": json.dumps([{"atomic_index": 0, "label": "OTHER"}]),
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "usage": {
                    "input_tokens": 20,
                    "cached_input_tokens": 4,
                    "output_tokens": 5,
                    "reasoning_tokens": 2,
                },
                "turn_failed_message": None,
            },
        ]
    )

    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles._run_line_role_prompt_via_codex_farm",
        lambda **_kwargs: next(responses),
    )

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-v1"),
        artifact_root=tmp_path,
    )

    assert len(predictions) == 1
    assert predictions[0].label == "OTHER"
    telemetry_payload = json.loads(
        (tmp_path / "line-role-pipeline" / "telemetry_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert telemetry_payload["summary"]["batch_count"] == 1
    assert telemetry_payload["summary"]["attempt_count"] == 2
    assert telemetry_payload["summary"]["attempts_with_usage"] == 2
    assert telemetry_payload["summary"]["tokens_input"] == 30
    assert telemetry_payload["summary"]["tokens_cached_input"] == 6
    assert telemetry_payload["summary"]["tokens_output"] == 8
    assert telemetry_payload["summary"]["tokens_reasoning"] == 3
    assert telemetry_payload["summary"]["tokens_total"] == 38
    assert telemetry_payload["batches"][0]["attempt_count"] == 2


def test_label_atomic_lines_codex_cache_reuses_across_runtime_only_setting_changes(
    monkeypatch,
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:cache:runtime",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            prev_text=None,
            next_text=None,
            rule_tags=["recipe_span_fallback"],
        )
    ]
    call_count = {"value": 0}

    def _fake_codex_call(**_kwargs):
        call_count["value"] += 1
        return {
            "response": json.dumps([{"atomic_index": 0, "label": "OTHER"}]),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "usage": None,
            "turn_failed_message": None,
        }

    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles._run_line_role_prompt_via_codex_farm",
        _fake_codex_call,
    )
    first = label_atomic_lines(
        candidates,
        _settings("codex-line-role-v1", workers=1, codex_farm_cmd="codex-a"),
        artifact_root=tmp_path / "artifacts",
        source_hash="source-hash-runtime",
        cache_root=tmp_path / "line-role-cache",
    )
    assert call_count["value"] == 1
    assert first[0].decided_by == "codex"

    def _runner_should_not_execute(**_kwargs):
        raise AssertionError("cache hit should skip codex call")

    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles._run_line_role_prompt_via_codex_farm",
        _runner_should_not_execute,
    )
    second = label_atomic_lines(
        candidates,
        _settings("codex-line-role-v1", workers=9, codex_farm_cmd="codex-b"),
        artifact_root=tmp_path / "artifacts",
        source_hash="source-hash-runtime",
        cache_root=tmp_path / "line-role-cache",
    )
    assert second[0].label == first[0].label


def test_line_role_cache_path_changes_when_line_role_pipeline_changes(tmp_path) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:cache:path",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            prev_text=None,
            next_text=None,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    off_path = canonical_line_roles_module._resolve_line_role_cache_path(
        source_hash="source-hash-path",
        settings=_settings("off"),
        ordered_candidates=candidates,
        artifact_root=tmp_path / "artifacts",
        cache_root=tmp_path / "line-role-cache",
        codex_timeout_seconds=30,
        codex_batch_size=8,
    )
    codex_path = canonical_line_roles_module._resolve_line_role_cache_path(
        source_hash="source-hash-path",
        settings=_settings("codex-line-role-v1"),
        ordered_candidates=candidates,
        artifact_root=tmp_path / "artifacts",
        cache_root=tmp_path / "line-role-cache",
        codex_timeout_seconds=30,
        codex_batch_size=8,
    )

    assert off_path is not None
    assert codex_path is not None
    assert off_path != codex_path


def test_label_atomic_lines_codex_parallel_batches_keep_deterministic_outputs(
    monkeypatch,
    tmp_path,
) -> None:
    candidates: list[AtomicLineCandidate] = []
    for atomic_index in range(4):
        candidates.append(
            AtomicLineCandidate(
                recipe_id="recipe:0",
                block_id=f"block:parallel:{atomic_index}",
                block_index=atomic_index,
                atomic_index=atomic_index,
                text=f"Ambiguous line {atomic_index}",
                within_recipe_span=True,
                prev_text=None,
                next_text=None,
                rule_tags=["recipe_span_fallback"],
            )
        )

    delay_by_atomic_index = {
        0: 0.20,
        1: 0.05,
        2: 0.15,
        3: 0.01,
    }
    call_order: list[int] = []

    def _fake_codex_call(**kwargs):
        prompt_text = str(kwargs.get("prompt") or "")
        match = re.search(r'"atomic_index"\\s*:\\s*(\\d+)', prompt_text)
        assert match is not None
        atomic_index = int(match.group(1))
        time.sleep(delay_by_atomic_index.get(atomic_index, 0.0))
        call_order.append(atomic_index)
        return {
            "response": json.dumps(
                [{"atomic_index": atomic_index, "label": "OTHER"}]
            ),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "usage": None,
            "turn_failed_message": None,
        }

    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles._run_line_role_prompt_via_codex_farm",
        _fake_codex_call,
    )
    monkeypatch.setattr(
        canonical_line_roles_module,
        "_resolve_line_role_codex_max_inflight",
        lambda: 4,
    )
    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-v1"),
        artifact_root=tmp_path,
        codex_batch_size=1,
    )
    assert call_order != [0, 1, 2, 3]
    assert [row.atomic_index for row in predictions] == [0, 1, 2, 3]
    assert all(row.label == "OTHER" for row in predictions)

    prompt_dir = tmp_path / "line-role-pipeline" / "prompts"
    dedup_lines = (
        prompt_dir / "codex_prompt_log.dedup.txt"
    ).read_text(encoding="utf-8").splitlines()
    assert len(dedup_lines) == 4
    assert all("\tprompt_" in line for line in dedup_lines)


def test_label_atomic_lines_uses_compact_prompt_format_when_env_enabled(
    monkeypatch,
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:compact:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous line 0",
            within_recipe_span=True,
            prev_text="Before",
            next_text="After",
            rule_tags=["recipe_span_fallback"],
        )
    ]

    def _fake_codex_call(**_kwargs):
        return {
            "response": json.dumps([{"atomic_index": 0, "label": "OTHER"}]),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "usage": None,
            "turn_failed_message": None,
        }

    monkeypatch.setenv("COOKIMPORT_LINE_ROLE_PROMPT_FORMAT", "compact_v1")
    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles._run_line_role_prompt_via_codex_farm",
        _fake_codex_call,
    )

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-v1"),
        artifact_root=tmp_path,
        codex_batch_size=1,
    )

    assert predictions[0].label == "OTHER"
    prompt_text = (tmp_path / "line-role-pipeline" / "prompts" / "prompt_0001.txt").read_text(
        encoding="utf-8"
    )
    assert "[atomic_index, label_code, reason_codes, current_line]" in prompt_text
    assert "Label codes:" in prompt_text
    assert "Recipe atomic index ranges for this batch: 0" in prompt_text
    assert '["Before", "After"]' in prompt_text
    assert "Ambiguous line 0" in prompt_text


def test_line_role_prompt_format_defaults_to_compact_when_env_unset(
    monkeypatch,
) -> None:
    monkeypatch.delenv("COOKIMPORT_LINE_ROLE_PROMPT_FORMAT", raising=False)

    assert canonical_line_roles_module._resolve_line_role_prompt_format() == "compact_v1"


def test_label_atomic_lines_codex_progress_callback_reports_batch_counts(
    monkeypatch,
) -> None:
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
                prev_text=None,
                next_text=None,
                rule_tags=["recipe_span_fallback"],
            )
        )

    def _fake_codex_call(**kwargs):
        prompt_text = str(kwargs.get("prompt") or "")
        match = re.search(r'"atomic_index"\\s*:\\s*(\\d+)', prompt_text)
        assert match is not None
        atomic_index = int(match.group(1))
        return {
            "response": json.dumps(
                [{"atomic_index": atomic_index, "label": "OTHER"}]
            ),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "usage": None,
            "turn_failed_message": None,
        }

    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles._run_line_role_prompt_via_codex_farm",
        _fake_codex_call,
    )
    monkeypatch.setattr(
        canonical_line_roles_module,
        "_resolve_line_role_codex_max_inflight",
        lambda: 2,
    )
    progress_messages: list[str] = []
    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-v1"),
        codex_batch_size=1,
        progress_callback=progress_messages.append,
    )

    assert [row.atomic_index for row in predictions] == [0, 1, 2]
    assert progress_messages[0] == (
        "Running canonical line-role pipeline... task 0/3"
    )
    assert (
        "Running canonical line-role pipeline... task 3/3" in progress_messages
    )
    assert (
        "Running canonical line-role pipeline... task 0/3 | running 2"
        in progress_messages
    )
    assert progress_messages[-1] == (
        "Running canonical line-role pipeline... task 3/3 | running 0"
    )
    assert any("task 1/3 | running 2" in message for message in progress_messages)
    assert any("task 2/3 | running 1" in message for message in progress_messages)


def test_label_atomic_lines_codex_max_inflight_override_takes_precedence(
    monkeypatch,
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
                prev_text=None,
                next_text=None,
                rule_tags=["recipe_span_fallback"],
            )
        )

    def _fake_codex_call(**kwargs):
        prompt_text = str(kwargs.get("prompt") or "")
        match = re.search(r'"atomic_index"\\s*:\\s*(\\d+)', prompt_text)
        assert match is not None
        atomic_index = int(match.group(1))
        return {
            "response": json.dumps(
                [{"atomic_index": atomic_index, "label": "OTHER"}]
            ),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "usage": None,
            "turn_failed_message": None,
        }

    monkeypatch.setattr(
        "cookimport.parsing.canonical_line_roles._run_line_role_prompt_via_codex_farm",
        _fake_codex_call,
    )
    monkeypatch.setattr(
        canonical_line_roles_module,
        "_resolve_line_role_codex_max_inflight",
        lambda: 1,
    )
    progress_messages: list[str] = []
    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-v1"),
        codex_batch_size=1,
        codex_max_inflight=3,
        progress_callback=progress_messages.append,
    )

    assert [row.atomic_index for row in predictions] == [0, 1, 2]
    assert (
        "Running canonical line-role pipeline... task 0/3 | running 3"
        in progress_messages
    )


def test_label_atomic_lines_deterministic_progress_callback_reports_task_counts() -> None:
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
        _settings("deterministic-v1"),
        progress_callback=progress_messages.append,
    )
    assert len(predictions) == 2
    assert progress_messages[0] == "Running canonical line-role pipeline... task 0/2"
    assert progress_messages[-1] == "Running canonical line-role pipeline... task 2/2"
    assert all("| running " not in message for message in progress_messages)
