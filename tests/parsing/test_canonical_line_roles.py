from __future__ import annotations

import tests.parsing.canonical_line_role_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_label_atomic_lines_requires_explicit_live_llm_approval_for_shard_runtime() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:ambiguous:1",
            block_index=1,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]
    blocked_predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        codex_runner=_line_role_runner({0: "NONRECIPE_CANDIDATE"}),
    )
    assert blocked_predictions[0].decided_by == "fallback"

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        codex_runner=_line_role_runner({0: "NONRECIPE_CANDIDATE"}),
        live_llm_allowed=True,
    )
    assert predictions[0].decided_by == "codex"


def test_pre_grouping_candidate_sanitizer_strips_recipe_span_hints() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:stale",
            block_id="block:stale:1",
            block_index=1,
            atomic_index=0,
            text="SERVES 4",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback", "yield_like"],
        )
    ]

    sanitized = canonical_line_roles_module.sanitize_pre_grouping_line_role_candidates(
        candidates
    )

    assert sanitized[0].recipe_id is None
    assert sanitized[0].within_recipe_span is None
    assert sanitized[0].rule_tags == ["yield_like"]


def test_label_atomic_lines_outside_recipe_knowledge_like_prose_stays_reviewable_other() -> None:
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
    assert predictions[0].label == "NONRECIPE_CANDIDATE"
    assert predictions[0].within_recipe_span is False


def test_label_atomic_lines_outside_recipe_saltfat_science_prose_stays_reviewable_other() -> None:
    blocks = [
        {
            "block_id": "block:knowledge:science",
            "block_index": 1,
            "text": (
                "Salt also reduces our perception of bitterness, with the secondary "
                "effect of emphasizing other flavors present in bitter dishes. Salt "
                "enhances sweetness while reducing bitterness in foods that are both "
                "bitter and sweet, such as bittersweet chocolate, coffee ice cream, "
                "or burnt caramels."
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
    assert predictions[0].label == "NONRECIPE_CANDIDATE"


def test_label_atomic_lines_outside_recipe_knowledge_heading_uses_neighbor_context_for_reviewable_other() -> None:
    blocks = [
        {
            "block_id": "block:knowledge:prev",
            "block_index": 1,
            "text": (
                "As with salt, the best way to correct overly fatty food is to "
                "rebalance the dish."
            ),
        },
        {
            "block_id": "block:knowledge:heading",
            "block_index": 2,
            "text": "Balancing Fat",
        },
        {
            "block_id": "block:knowledge:next",
            "block_index": 3,
            "text": (
                "Foods that are too dry can be corrected with a bit more fat."
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
    assert by_text["Balancing Fat"].label == "NONRECIPE_CANDIDATE"
    assert (
        by_text[
            "As with salt, the best way to correct overly fatty food is to rebalance the dish."
        ].label
        == "NONRECIPE_CANDIDATE"
    )
    assert (
        by_text["Foods that are too dry can be corrected with a bit more fat."].label
        == "NONRECIPE_CANDIDATE"
    )


def test_label_atomic_lines_outside_recipe_first_person_learning_prose_stays_reviewable_other() -> None:
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
        == "NONRECIPE_CANDIDATE"
    )


def test_label_atomic_lines_outside_recipe_saltfat_question_heading_stays_other() -> None:
    blocks = [
        {
            "block_id": "block:knowledge:question-heading",
            "block_index": 1,
            "text": "What is Heat?",
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "NONRECIPE_CANDIDATE"


def test_label_atomic_lines_outside_recipe_saltfat_citrus_lesson_stays_reviewable_other() -> None:
    blocks = [
        {
            "block_id": "block:knowledge:citrus",
            "block_index": 1,
            "text": (
                "When it comes to citrus, lemon trees are well suited to the "
                "coastal climates in Mediterranean countries, so choose lemon to "
                "squeeze into tabbouleh and hummus, and over grilled octopus, "
                "Nicoise salad, or Sicilian fennel and orange salad. Lime trees, "
                "on the other hand, grow more readily in tropical climates, so "
                "limes are the preferred citrus everywhere from Mexico and Cuba to "
                "India, Vietnam, and Thailand. Use limes in guacamole, pho ga, "
                "green papaya salad, and kachumbar, the Indian answer to pico de "
                "gallo. One form of citrus you should never use, though, is "
                "bottled citrus juice. Made from concentrate and doctored with "
                "preservatives and citrus oils, it tastes bitter and doesn't offer "
                "any of the clean, bright flavor of fresh-squeezed juice."
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
    assert predictions[0].label == "NONRECIPE_CANDIDATE"


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


def test_label_atomic_lines_outside_recipe_variant_heading_can_stay_structured() -> None:
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


def test_label_atomic_lines_outside_recipe_structured_cluster_can_stay_structured() -> None:
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
    assert predictions[0].label == "INGREDIENT_LINE"
    assert predictions[1].label == "INSTRUCTION_LINE"


def test_label_atomic_lines_unknown_pre_grouping_cluster_stays_structured() -> None:
    blocks = [
        {
            "block_id": "block:ingredient:unknown:1",
            "block_index": 41,
            "text": "2 tablespoons olive oil",
        },
        {
            "block_id": "block:instruction:unknown:1",
            "block_index": 42,
            "text": "Whisk until smooth.",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=None,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 2
    assert predictions[0].within_recipe_span is None
    assert predictions[1].within_recipe_span is None
    assert predictions[0].label == "INGREDIENT_LINE"
    assert predictions[1].label == "INSTRUCTION_LINE"


def test_label_atomic_lines_unknown_pre_grouping_science_prose_stays_reviewable_other() -> None:
    blocks = [
        {
            "block_id": "block:knowledge:science:unknown",
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
        within_recipe_span=None,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].within_recipe_span is None
    assert predictions[0].label == "NONRECIPE_CANDIDATE"


def test_label_atomic_lines_unknown_pre_grouping_knowledge_heading_uses_neighbor_context_for_reviewable_other() -> None:
    blocks = [
        {
            "block_id": "block:knowledge:prev:unknown",
            "block_index": 1,
            "text": (
                "Salt affects texture and flavor because it changes how food "
                "absorbs moisture during cooking."
            ),
        },
        {
            "block_id": "block:knowledge:heading:unknown",
            "block_index": 2,
            "text": "SALT AND FLAVOR",
        },
        {
            "block_id": "block:knowledge:next:unknown",
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
        within_recipe_span=None,
    )
    predictions = label_atomic_lines(candidates, _settings())
    by_text = {prediction.text: prediction for prediction in predictions}
    assert by_text["SALT AND FLAVOR"].label == "NONRECIPE_CANDIDATE"
    assert (
        by_text[
            "Salt affects texture and flavor because it changes how food absorbs moisture during cooking."
        ].label
        == "NONRECIPE_CANDIDATE"
    )
    assert (
        by_text[
            "The relationship between salt and flavor is multidimensional, and even small changes can improve aroma and balance bitterness."
        ].label
        == "NONRECIPE_CANDIDATE"
    )


def test_label_atomic_lines_outside_recipe_saltfat_heading_stays_reviewable_other() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:knowledge:coddling:0",
            block_index=0,
            atomic_index=0,
            text="Coddling and Poaching",
            within_recipe_span=False,
            rule_tags=["title_like"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:knowledge:coddling:1",
            block_index=1,
            atomic_index=1,
            text=(
                "Gentle cooking in water just below a simmer keeps delicate "
                "proteins tender and protects them from overcooking."
            ),
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        ),
    ]

    predictions = label_atomic_lines(candidates, _settings())

    assert [prediction.label for prediction in predictions] == [
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
    ]


def test_label_atomic_lines_outside_recipe_saltfat_crouton_storage_step_stays_instruction_line() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:croutons",
            block_id="block:croutons:title",
            block_index=0,
            atomic_index=0,
            text="Torn Croutons",
            within_recipe_span=False,
            rule_tags=["title_like"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:croutons",
            block_id="block:croutons:ingredient",
            block_index=1,
            atomic_index=1,
            text="1 loaf country bread",
            within_recipe_span=False,
            rule_tags=["ingredient_like"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:croutons",
            block_id="block:croutons:instruction",
            block_index=2,
            atomic_index=2,
            text=(
                "When done, let the croutons cool in a single layer on the baking "
                "sheet. Use immediately or keep in an airtight container for up to "
                "2 days. To refresh stale croutons, bake for 3 to 4 minutes at "
                "400°F."
            ),
            within_recipe_span=False,
            rule_tags=["instruction_like"],
        ),
    ]

    predictions = label_atomic_lines(candidates, _settings())

    assert [prediction.label for prediction in predictions] == [
        "RECIPE_TITLE",
        "INGREDIENT_LINE",
        "INSTRUCTION_LINE",
    ]


def test_label_atomic_lines_outside_recipe_tail_step_with_instruction_neighbor_stays_instruction_line() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:croutons",
            block_id="block:croutons:toast",
            block_index=0,
            atomic_index=0,
            text=(
                "Toast the croutons for about 18 to 22 minutes, checking them "
                "after 8 minutes. Rotate the pans and continue baking until "
                "golden brown."
            ),
            within_recipe_span=False,
            rule_tags=["instruction_with_time"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:croutons",
            block_id="block:croutons:cool",
            block_index=1,
            atomic_index=1,
            text=(
                "When done, let the croutons cool in a single layer on the "
                "baking sheet. Use immediately or keep in an airtight "
                "container for up to 2 days. To refresh stale croutons, bake "
                "for 3 to 4 minutes at 400°F."
            ),
            within_recipe_span=False,
            rule_tags=["instruction_with_time"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:croutons",
            block_id="block:croutons:freeze",
            block_index=2,
            atomic_index=2,
            text="Freeze leftover croutons for up to 2 months and use in Ribollita.",
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        ),
    ]

    predictions = label_atomic_lines(candidates, _settings())

    assert [prediction.label for prediction in predictions] == [
        "INSTRUCTION_LINE",
        "INSTRUCTION_LINE",
        "RECIPE_NOTES",
    ]


def test_label_atomic_lines_outside_recipe_instruction_like_endorsement_cluster_stays_other() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:endorsement:1",
            block_index=1,
            atomic_index=0,
            text=(
                "\"Like the amazing meals that come out of Samin Nosrat's kitchen, "
                "Salt, Fat, Acid, Heat is the perfect mixture of highest-quality "
                "ingredients: beautiful storytelling, clear science, and "
                "illustrations that make the book joyful to read.\""
            ),
            within_recipe_span=False,
            rule_tags=["instruction_like"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:endorsement:2",
            block_index=2,
            atomic_index=1,
            text=(
                "\"Salt, Fat, Acid, Heat is a wildly informative culinary "
                "resource whose prose and illustrations guide readers through "
                "the science of cooking.\""
            ),
            within_recipe_span=False,
            rule_tags=["instruction_like"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:endorsement:3",
            block_index=3,
            atomic_index=2,
            text="-A chef who admires the book",
            within_recipe_span=False,
            rule_tags=[],
        ),
    ]

    predictions = label_atomic_lines(candidates, _settings())

    assert [prediction.label for prediction in predictions] == [
        "NONRECIPE_EXCLUDE",
        "NONRECIPE_EXCLUDE",
        "NONRECIPE_EXCLUDE",
    ]
    assert all(
        "rescued_other_to_instruction" not in prediction.reason_tags
        for prediction in predictions
    )


def test_label_atomic_lines_outside_recipe_publisher_signup_cluster_is_excluded() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:promo:1",
            block_index=1,
            atomic_index=0,
            text="Thank you for downloading this Simon & Schuster ebook.",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:promo:2",
            block_index=2,
            atomic_index=1,
            text=(
                "Get a FREE ebook when you join our mailing list. Plus, get "
                "updates on new releases, deals, recommended reads, and more "
                "from Simon & Schuster. Click below to sign up and see terms "
                "and conditions."
            ),
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:promo:3",
            block_index=3,
            atomic_index=2,
            text=(
                "Already a subscriber? Provide your email again so we can "
                "register this ebook and send you more of what you like to "
                "read. You will continue to receive exclusive offers in your "
                "inbox."
            ),
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:promo:4",
            block_index=4,
            atomic_index=3,
            text="CLICK HERE TO SIGN UP",
            within_recipe_span=False,
            rule_tags=[],
        ),
    ]

    predictions = label_atomic_lines(candidates, _settings())

    assert [prediction.label for prediction in predictions] == [
        "NONRECIPE_EXCLUDE",
        "NONRECIPE_EXCLUDE",
        "NONRECIPE_EXCLUDE",
        "NONRECIPE_EXCLUDE",
    ]


def test_label_atomic_lines_outside_recipe_isolated_howto_heading_defaults_away_from_structure() -> None:
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
    assert predictions[0].label == "NONRECIPE_CANDIDATE"


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
    assert predictions[0].label == "NONRECIPE_CANDIDATE"


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
    assert predictions[0].label == "NONRECIPE_CANDIDATE"


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


def test_label_atomic_lines_unknown_pre_grouping_storage_note_is_recipe_notes() -> None:
    blocks = [
        {
            "block_id": "block:note:storage:1",
            "block_index": 1,
            "text": "Store leftover slaw covered, in the fridge, for up to two days.",
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=None,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_NOTES"


def test_label_atomic_lines_unknown_pre_grouping_refrigerate_leftovers_is_recipe_notes() -> None:
    blocks = [
        {
            "block_id": "block:note:storage:2",
            "block_index": 1,
            "text": "Refrigerate leftovers, covered, for up to 3 days.",
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=None,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_NOTES"


def test_label_atomic_lines_unknown_pre_grouping_ideal_for_serving_suggestion_is_recipe_notes() -> None:
    blocks = [
        {
            "block_id": "block:note:serving:1",
            "block_index": 1,
            "text": (
                "Ideal for garden lettuces, arugula, chicories, Belgian endive, "
                "Little Gem and romaine lettuce, beets, tomatoes, blanched, "
                "grilled, or roasted vegetables of any kind."
            ),
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=None,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_NOTES"


def test_label_atomic_lines_unknown_pre_grouping_serve_with_suggestion_is_recipe_notes() -> None:
    blocks = [
        {
            "block_id": "block:note:serving:2",
            "block_index": 1,
            "text": "Serve with grilled fish, roast chicken, or ripe tomatoes.",
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=None,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_NOTES"


def test_label_atomic_lines_science_prose_with_internal_ideal_for_is_not_recipe_notes() -> None:
    blocks = [
        {
            "block_id": "block:knowledge:ideal-for:1",
            "block_index": 1,
            "text": (
                "Fine or medium-size crystals of this type are ideal for everyday "
                "cooking. Use this type of sea salt to season foods from within."
            ),
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=None,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label != "RECIPE_NOTES"


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
    assert predictions[0].label == "NONRECIPE_CANDIDATE"


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
    assert predictions[0].label == "NONRECIPE_EXCLUDE"


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


def test_label_atomic_lines_long_to_make_variant_paragraph_is_not_howto_heading() -> None:
    blocks = [
        {
            "block_id": "block:variant:long:1",
            "block_index": 1,
            "text": (
                "To make Caprese Salad, alternate heirloom tomato slices with 1/2-inch "
                "slices of fresh mozzarella or burrata cheese before seasoning and "
                "dressing. Skip the herb salad. Instead, when seasoning the cherry "
                "tomatoes in a separate bowl, add 12 torn basil leaves."
            ),
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id="recipe:variant",
        within_recipe_span=True,
    )
    assert "howto_heading" not in candidates[0].rule_tags
    predictions = label_atomic_lines(candidates, _settings())
    assert predictions[0].label == "RECIPE_VARIANT"


def test_label_atomic_lines_variations_heading_can_anchor_outside_recipe_variant_run() -> None:
    blocks = [
        {
            "block_id": "block:variant:heading:1",
            "block_index": 1,
            "text": "Variations",
        },
        {
            "block_id": "block:variant:heading:2",
            "block_index": 2,
            "text": (
                "If you don't have cabbage on hand, or simply want to try something "
                "new, make an Alterna-slaw, using 1 large bunch raw kale, 1 1/2 "
                "pounds raw Brussels sprouts, or 1 1/2 pounds raw kohlrabi instead."
            ),
        },
        {
            "block_id": "block:variant:heading:3",
            "block_index": 3,
            "text": (
                "For Mexi-Slaw, substitute a neutral-tasting oil for the olive oil, "
                "lime juice for the lemon juice, and cilantro for the parsley."
            ),
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )

    predictions = label_atomic_lines(candidates, _settings())

    assert [prediction.label for prediction in predictions] == [
        "RECIPE_VARIANT",
        "RECIPE_VARIANT",
        "RECIPE_VARIANT",
    ]


def test_label_atomic_lines_lead_variant_paragraph_keeps_explicit_following_rows_in_variant_run() -> None:
    blocks = [
        {
            "block_id": "block:variant:run:1",
            "block_index": 1,
            "text": (
                "To make Caprese Salad, alternate heirloom tomato slices with 1/2-inch "
                "slices of fresh mozzarella or burrata cheese before seasoning and "
                "dressing."
            ),
        },
        {
            "block_id": "block:variant:run:2",
            "block_index": 2,
            "text": "12 torn basil leaves",
        },
        {
            "block_id": "block:variant:run:3",
            "block_index": 3,
            "text": "Instead, mound the cherry tomatoes over the tomato slices and serve.",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id="recipe:variant",
        within_recipe_span=True,
    )

    predictions = label_atomic_lines(candidates, _settings())

    assert [prediction.label for prediction in predictions] == [
        "RECIPE_VARIANT",
        "RECIPE_VARIANT",
        "RECIPE_VARIANT",
    ]


def test_label_atomic_lines_variant_run_plain_instruction_needs_variant_cues() -> None:
    blocks = [
        {
            "block_id": "block:variant:run:plain:1",
            "block_index": 1,
            "text": (
                "To make Caprese Salad, alternate heirloom tomato slices with 1/2-inch "
                "slices of fresh mozzarella or burrata cheese before seasoning and "
                "dressing."
            ),
        },
        {
            "block_id": "block:variant:run:plain:2",
            "block_index": 2,
            "text": "12 torn basil leaves",
        },
        {
            "block_id": "block:variant:run:plain:3",
            "block_index": 3,
            "text": "Mound the cherry tomatoes over the tomato slices and serve.",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id="recipe:variant",
        within_recipe_span=True,
    )

    predictions = label_atomic_lines(candidates, _settings())

    assert [prediction.label for prediction in predictions] == [
        "RECIPE_VARIANT",
        "RECIPE_VARIANT",
        "INSTRUCTION_LINE",
    ]


def test_label_atomic_lines_generic_to_make_step_stays_instruction_not_variant() -> None:
    blocks = [
        {
            "block_id": "block:variant:false-positive:generic-make:1",
            "block_index": 1,
            "text": (
                "To make the salad, use your hands to toss the greens and Torn "
                "Croutons with an abundant amount of dressing in a large bowl to coat "
                "evenly."
            ),
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id="recipe:caesar",
        within_recipe_span=True,
    )

    predictions = label_atomic_lines(candidates, _settings())

    assert predictions[0].label == "INSTRUCTION_LINE"


def test_label_atomic_lines_exact_caesar_outside_span_make_step_stays_instruction() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:1397",
            block_index=1397,
            atomic_index=1397,
            text=(
                "Coarsely chop the anchovies and then pound them into a fine paste "
                "in a mortar and pestle. The more you break them down, the better "
                "the dressing will be."
            ),
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:1398",
            block_index=1398,
            atomic_index=1398,
            text=(
                "In a medium bowl, stir together the anchovies, mayonnaise, garlic, "
                "lemon juice, vinegar, Parmesan, Worcestershire sauce, and pepper. "
                "Taste with a leaf of lettuce, then add salt and adjust acid as "
                "needed. Or, practicing what you learned about Layering Salt , add "
                "a little bit of each salty ingredient to the mayonnaise, bit by "
                "bit. Adjust the acid, then taste and adjust the salty ingredients "
                "until you reach the ideal balance of Salt, Fat, and Acid. Has "
                "putting a lesson you read in a book into practice ever been this "
                "delicious? I doubt it."
            ),
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:1399",
            block_index=1399,
            atomic_index=1399,
            text=(
                "To make the salad, use your hands to toss the greens and Torn "
                "Croutons with an abundant amount of dressing in a large bowl to "
                "coat evenly. Garnish with Parmesan and freshly ground black pepper "
                "and serve immediately."
            ),
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:1400",
            block_index=1400,
            atomic_index=1400,
            text="Refrigerate leftover dressing, covered, for up to 3 days.",
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:1401",
            block_index=1401,
            atomic_index=1401,
            text=(
                "Ideal for romaine and Little Gem lettuce, chicories, raw or "
                "blanched Kale, shaved Brussels sprouts, Belgian endive."
            ),
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        ),
    ]

    predictions = label_atomic_lines(candidates, _settings())

    by_atomic_index = {prediction.atomic_index: prediction for prediction in predictions}

    assert by_atomic_index[1399].label == "INSTRUCTION_LINE"
    assert by_atomic_index[1400].label == "RECIPE_NOTES"
    assert by_atomic_index[1401].label == "RECIPE_NOTES"


def test_label_atomic_lines_exact_lesson_prose_recover_knowledge_rows() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:230",
            block_index=230,
            atomic_index=230,
            text=(
                "I asked questions of everyone, every day. I read, cooked, tasted, "
                "and also wrote about food, all in an effort to deepen my "
                "understanding. I visited farms and farmers' markets and learned my "
                "way around their wares. Gradually the chefs gave me more "
                "responsibility, from frying tiny, gleaming anchovies for the first "
                "course to folding perfect little ravioli for the second to "
                "butchering beef for the third. These thrills sustained me as I "
                "made innumerable mistakes-some small, such as being sent to "
                "retrieve cilantro and returning with parsley because I couldn't "
                "tell the difference, and some large, like the time I burned the "
                "rich beef sauce for a dinner we hosted for the First Lady."
            ),
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:231",
            block_index=231,
            atomic_index=231,
            text=(
                "As I improved, I began to detect the nuances that distinguish good "
                "food from great. I started to discern individual components in a "
                "dish, understanding when the pasta water and not the sauce needed "
                "more salt, or when an herb salsa needed more vinegar to balance a "
                "rich, sweet lamb stew. I started to see some basic patterns in the "
                "seemingly impenetrable maze of daily-changing, seasonal menus. "
                "Tough cuts of meat were salted the night before, while delicate "
                "fish filets were seasoned at the time of cooking. Oil for frying "
                "had to be hot-otherwise the food would end up soggy-while butter "
                "for tart dough had to remain cold, so that the crust would crisp "
                "up and become flaky. A squeeze of lemon or splash of vinegar could "
                "improve almost every salad, soup, and braise. Certain cuts of meat "
                "were always grilled, while others were always braised."
            ),
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:232",
            block_index=232,
            atomic_index=232,
            text=(
                "Salt, Fat, Acid, and Heat were the four elements that guided basic "
                "decision making in every single dish, no matter what. The rest was "
                "just a combination of cultural, seasonal, or technical details, "
                "for which we could consult cookbooks and experts, histories, and "
                "maps. It was a revelation."
            ),
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:233",
            block_index=233,
            atomic_index=233,
            text=(
                "The idea of making consistently great food had seemed like some "
                "inscrutable mystery, but now I had a little mental checklist to "
                "think about every time I set foot in a kitchen: Salt, Fat, Acid, "
                "Heat. I mentioned the theory to one of the chefs. He smiled at me, "
                "as if to say, \"Duh. Everyone knows that.\""
            ),
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        ),
    ]

    predictions = label_atomic_lines(candidates, _settings())

    assert [prediction.label for prediction in predictions] == [
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
    ]


def test_label_atomic_lines_front_matter_heading_and_title_list_stay_other() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:16",
            block_index=16,
            atomic_index=16,
            text="How to Use This Book",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:17",
            block_index=17,
            atomic_index=17,
            text="PART ONE",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:18",
            block_index=18,
            atomic_index=18,
            text="The Four Elements of Good Cooking",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:19",
            block_index=19,
            atomic_index=19,
            text="SALT",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:20",
            block_index=20,
            atomic_index=20,
            text="What is Salt?",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:58",
            block_index=58,
            atomic_index=58,
            text="Summer: Tomato, Basil, and Cucumber",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:59",
            block_index=59,
            atomic_index=59,
            text="Autumn: Roasted Squash, Sage, and Hazelnut",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:60",
            block_index=60,
            atomic_index=60,
            text="Winter: Roasted Radicchio and Roquefort",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:61",
            block_index=61,
            atomic_index=61,
            text="Spring: Asparagus and Feta with Mint",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:62",
            block_index=62,
            atomic_index=62,
            text="Torn Croutons",
            within_recipe_span=False,
            rule_tags=[],
        ),
    ]

    predictions = label_atomic_lines(candidates, _settings())
    by_atomic_index = {prediction.atomic_index: prediction for prediction in predictions}

    assert by_atomic_index[18].label == "NONRECIPE_EXCLUDE"
    assert by_atomic_index[60].label == "NONRECIPE_EXCLUDE"
    assert by_atomic_index[61].label == "NONRECIPE_EXCLUDE"
    assert by_atomic_index[62].label == "NONRECIPE_EXCLUDE"


def test_label_atomic_lines_front_matter_chapter_taxonomy_cluster_is_excluded() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:17",
            block_index=17,
            atomic_index=17,
            text="PART ONE",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:18",
            block_index=18,
            atomic_index=18,
            text="The Four Elements of Good Cooking",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:19",
            block_index=19,
            atomic_index=19,
            text="SALT",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:20",
            block_index=20,
            atomic_index=20,
            text="What is Salt?",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:21",
            block_index=21,
            atomic_index=21,
            text="Salt and Flavor",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:22",
            block_index=22,
            atomic_index=22,
            text="How Salt Works",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:23",
            block_index=23,
            atomic_index=23,
            text="Diffusion Calculus",
            within_recipe_span=False,
            rule_tags=[],
        ),
    ]

    predictions = label_atomic_lines(candidates, _settings())
    by_text = {prediction.text: prediction for prediction in predictions}

    assert all(prediction.label == "NONRECIPE_EXCLUDE" for prediction in predictions)
    assert by_text["PART ONE"].label == "NONRECIPE_EXCLUDE"
    assert by_text["The Four Elements of Good Cooking"].label == "NONRECIPE_EXCLUDE"
    assert by_text["SALT"].label == "NONRECIPE_EXCLUDE"
    assert by_text["What is Salt?"].label == "NONRECIPE_EXCLUDE"
    assert by_text["Salt and Flavor"].label == "NONRECIPE_EXCLUDE"
    assert by_text["How Salt Works"].label == "NONRECIPE_EXCLUDE"
    assert by_text["Diffusion Calculus"].label == "NONRECIPE_EXCLUDE"


def test_label_atomic_lines_atomized_chapter_taxonomy_heading_trio_stays_other() -> None:
    candidates = atomize_blocks(
        [
            {
                "block_id": "block:18",
                "block_index": 18,
                "text": "The Four Elements of Good Cooking",
            },
            {
                "block_id": "block:19",
                "block_index": 19,
                "text": "SALT",
            },
            {
                "block_id": "block:20",
                "block_index": 20,
                "text": "What is Salt?",
            },
            {
                "block_id": "block:21",
                "block_index": 21,
                "text": "Salt enhances flavor.",
            },
        ],
        recipe_id=None,
        within_recipe_span=False,
    )

    predictions = label_atomic_lines(candidates, _settings())

    assert [prediction.label for prediction in predictions] == [
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
    ]


def test_label_atomic_lines_exact_variations_block_stays_variant() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:1378",
            block_index=1378,
            atomic_index=1378,
            text="Variations",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:1379",
            block_index=1379,
            atomic_index=1379,
            text="To add a little heat, add 1 teaspoon minced jalapeño.",
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:1380",
            block_index=1380,
            atomic_index=1380,
            text=(
                "To evoke the flavors of Korea or Japan, add a few drops of "
                "toasted sesame oil."
            ),
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        ),
    ]

    predictions = label_atomic_lines(candidates, _settings())

    assert [prediction.label for prediction in predictions] == [
        "RECIPE_VARIANT",
        "RECIPE_VARIANT",
        "RECIPE_VARIANT",
    ]


def test_label_atomic_lines_variant_run_does_not_pull_following_notes_into_variant() -> None:
    blocks = [
        {
            "block_id": "block:variant:notes:1",
            "block_index": 1,
            "text": "Variation",
        },
        {
            "block_id": "block:variant:notes:2",
            "block_index": 2,
            "text": (
                "To make Goma-Ae dressing, substitute 1/4 cup seasoned rice wine "
                "vinegar for the lemon juice and omit the cumin."
            ),
        },
        {
            "block_id": "block:variant:notes:3",
            "block_index": 3,
            "text": "Ideal for drizzling over roasted vegetables or grilled fish.",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )

    predictions = label_atomic_lines(candidates, _settings())

    assert [prediction.label for prediction in predictions] == [
        "RECIPE_VARIANT",
        "RECIPE_VARIANT",
        "RECIPE_NOTES",
    ]


def test_label_atomic_lines_bare_variations_heading_without_variant_body_stays_other() -> None:
    blocks = [
        {
            "block_id": "block:variant:false-positive:1",
            "block_index": 1,
            "text": "Variations",
        },
        {
            "block_id": "block:variant:false-positive:2",
            "block_index": 2,
            "text": (
                "Different acids behave differently in emulsions, and each one changes "
                "flavor in its own way."
            ),
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )

    predictions = label_atomic_lines(candidates, _settings())

    assert predictions[0].label == "NONRECIPE_CANDIDATE"
    assert predictions[1].label == "NONRECIPE_CANDIDATE"


def test_label_atomic_lines_long_to_serve_sentence_defaults_away_from_howto_section() -> None:
    blocks = [
        {
            "block_id": "block:serve:outside:1",
            "block_index": 1,
            "text": (
                "To serve, arrange the wedges on the platter-the rule when plating "
                "beets is: put them down confidently, and do not move them or they "
                "will stain, leaving a messy trail in their wake."
            ),
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    assert "howto_heading" not in candidates[0].rule_tags
    predictions = label_atomic_lines(candidates, _settings())
    assert predictions[0].label == "NONRECIPE_CANDIDATE"


def test_label_atomic_lines_short_to_serve_heading_stays_howto_section() -> None:
    blocks = [
        {
            "block_id": "block:serve:heading:1",
            "block_index": 1,
            "text": "TO SERVE",
        },
        {
            "block_id": "block:serve:heading:2",
            "block_index": 2,
            "text": "1 bunch watercress",
        },
        {
            "block_id": "block:serve:heading:3",
            "block_index": 3,
            "text": "Arrange the duck on a platter and scatter with watercress.",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id="recipe:duck",
        within_recipe_span=True,
    )
    assert "howto_heading" in candidates[0].rule_tags
    predictions = label_atomic_lines(candidates, _settings())
    assert predictions[0].label == "HOWTO_SECTION"


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
    assert predictions[0].label == "NONRECIPE_CANDIDATE"


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


def test_label_atomic_lines_routes_outside_recipe_knowledge_headings_and_fragments_to_other() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:knowledge:1",
            block_index=1,
            atomic_index=0,
            text="How Salt Works",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:knowledge:2",
            block_index=2,
            atomic_index=1,
            text="FAT",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:knowledge:3",
            block_index=3,
            atomic_index=2,
            text="acid, which brightens and balances",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:knowledge:4",
            block_index=4,
            atomic_index=3,
            text="and heat, which ultimately determines the texture of food",
            within_recipe_span=False,
            rule_tags=[],
        ),
    ]

    predictions = label_atomic_lines(candidates, _settings())
    assert [prediction.label for prediction in predictions] == [
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
    ]


def test_label_atomic_lines_outside_recipe_useful_prose_stays_reviewable_other() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:knowledge:5",
            block_index=5,
            atomic_index=0,
            text=(
                "Salt also reduces our perception of bitterness, with the secondary "
                "effect of emphasizing other flavors present in bitter dishes."
            ),
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:knowledge:6",
            block_index=6,
            atomic_index=1,
            text="-Alice Waters , New York Times bestselling author of The Art of Simple Food",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:knowledge:7",
            block_index=7,
            atomic_index=2,
            text=(
                "Let Salt, Fat, and Acid work together in concert to improve "
                "anything you eat, whether you cooked it or not."
            ),
            within_recipe_span=False,
            rule_tags=[],
        ),
    ]

    predictions = label_atomic_lines(candidates, _settings())
    assert [prediction.label for prediction in predictions] == [
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_EXCLUDE",
        "NONRECIPE_CANDIDATE",
    ]


def test_label_atomic_lines_outside_recipe_generic_heading_stays_other() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:outside-title:1",
            block_index=1,
            atomic_index=0,
            text="A Panzanella for Every Season",
            within_recipe_span=False,
            rule_tags=[],
        )
    ]

    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "NONRECIPE_CANDIDATE"
