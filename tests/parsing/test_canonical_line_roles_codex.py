from __future__ import annotations

import tests.parsing.canonical_line_role_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_codex_time_line_prediction_is_accepted_without_runtime_baseline_veto() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:time:1",
            block_index=1,
            atomic_index=0,
            text="Add onions and cook for 5 minutes.",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]
    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        codex_runner=_line_role_runner({0: "TIME_LINE"}),
        live_llm_allowed=True,
    )
    assert len(predictions) == 1
    assert predictions[0].label == "TIME_LINE"
    assert predictions[0].decided_by == "codex"


def test_codex_neighbor_ingredient_fragment_stays_codex_other() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:ingredient:0",
            block_index=0,
            atomic_index=0,
            text="1 cup",
            within_recipe_span=True,
            rule_tags=["ingredient_like"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:ingredient:1",
            block_index=1,
            atomic_index=1,
            text="flour",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:ingredient:2",
            block_index=2,
            atomic_index=2,
            text="2 tablespoons sugar",
            within_recipe_span=True,
            rule_tags=["ingredient_like"],
        ),
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        codex_runner=_line_role_runner({1: "RECIPE_NOTES"}),
        live_llm_allowed=True,
    )
    by_index = {row.atomic_index: row for row in predictions}
    assert by_index[1].label == "RECIPE_NOTES"
    assert by_index[1].decided_by == "codex"
    assert "sanitized_neighbor_ingredient_fragment" not in by_index[1].reason_tags


def test_title_like_line_can_be_overridden_when_full_book_codex_reviews_it(tmp_path) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:title:1",
            block_index=1,
            atomic_index=0,
            text="A PORRIDGE OF LOVAGE STEMS",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner({0: "RECIPE_NOTES"}),
        live_llm_allowed=True,
    )
    assert (
        tmp_path
        / "line-role-pipeline"
        / "prompts"
        / "line_role"
        / "line_role_prompt_0001.txt"
    ).exists()
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_NOTES"
    assert predictions[0].decided_by == "codex"


def test_codex_mode_accepts_global_label_not_present_in_old_shortlist() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:title:global",
            block_index=1,
            atomic_index=0,
            text="Shaved Carrot Salad with Ginger and Lime",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        codex_runner=_line_role_runner({0: "RECIPE_TITLE"}),
        live_llm_allowed=True,
    )
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_TITLE"
    assert predictions[0].decided_by == "codex"


def test_codex_mode_allows_override_of_strong_recipe_note() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:note:0",
            block_index=0,
            atomic_index=0,
            text="NOTE: Keep blender cup warm.",
            within_recipe_span=True,
            rule_tags=["note_prefix"],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        codex_runner=_line_role_runner({0: "RECIPE_TITLE"}),
        live_llm_allowed=True,
    )
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_TITLE"
    assert predictions[0].decided_by == "codex"
    assert predictions[0].escalation_reasons == []


def test_codex_mode_allows_override_without_old_syntax_ownership_veto() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:instruction:0",
            block_index=0,
            atomic_index=0,
            text="Stir well and taste for seasoning.",
            within_recipe_span=True,
            rule_tags=["instruction_like"],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        codex_runner=_line_role_runner({0: "RECIPE_NOTES"}),
        live_llm_allowed=True,
    )
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_NOTES"
    assert predictions[0].decided_by == "codex"
    assert predictions[0].escalation_reasons == []


def test_codex_mode_allows_outside_span_title_override() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:title:2",
            block_index=2,
            atomic_index=0,
            text="A PORRIDGE OF LOVAGE STEMS",
            within_recipe_span=False,
            rule_tags=["outside_recipe_span"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:title:3",
            block_index=3,
            atomic_index=1,
            text="2 tablespoons olive oil",
            within_recipe_span=False,
            rule_tags=["ingredient_like", "outside_recipe_span"],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        codex_runner=_line_role_runner(
            {0: "NONRECIPE_CANDIDATE", 1: "INGREDIENT_LINE"},
        ),
        live_llm_allowed=True,
    )
    assert len(predictions) == 2
    assert predictions[0].label == "NONRECIPE_CANDIDATE"
    assert predictions[0].decided_by == "codex"
    assert predictions[0].escalation_reasons == []


def test_codex_outside_recipe_generic_lesson_heading_keeps_howto_authoritative(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:lesson:1",
            block_index=1,
            atomic_index=0,
            text="Gentle Cooking Methods",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:lesson:2",
            block_index=2,
            atomic_index=1,
            text=(
                "Gentle cooking methods control heat transfer so food cooks through "
                "without toughening or drying out."
            ),
            within_recipe_span=False,
            rule_tags=[],
        ),
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner(
            {0: "HOWTO_SECTION", 1: "NONRECIPE_CANDIDATE"}
        ),
        live_llm_allowed=True,
    )

    assert predictions[0].label == "HOWTO_SECTION"
    assert predictions[0].decided_by == "codex"


def test_codex_outside_recipe_narrative_prose_keeps_howto_authoritative(tmp_path) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:memoir:1",
            block_index=1,
            atomic_index=0,
            text=(
                "Then I fell in love with Johnny, who introduced me to the culinary "
                "delights of his native San Francisco."
            ),
            within_recipe_span=False,
            rule_tags=[],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner({0: "HOWTO_SECTION"}),
        live_llm_allowed=True,
    )

    assert predictions[0].label == "HOWTO_SECTION"
    assert predictions[0].decided_by == "codex"


def test_codex_outside_recipe_endorsement_demotes_knowledge_to_other(tmp_path) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:endorsement:1",
            block_index=1,
            atomic_index=0,
            text="-Alice Waters , New York Times bestselling author of The Art of Simple Food",
            within_recipe_span=False,
            rule_tags=[],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner({0: "NONRECIPE_CANDIDATE"}),
        live_llm_allowed=True,
    )

    assert predictions[0].label == "NONRECIPE_CANDIDATE"
    assert predictions[0].decided_by == "codex"


def test_codex_outside_recipe_publisher_promo_demotes_knowledge_to_other(tmp_path) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:promo:1",
            block_index=1,
            atomic_index=0,
            text=(
                "Get a FREE ebook when you join our mailing list. Plus, get "
                "updates on new releases, deals, recommended reads, and more "
                "from Simon & Schuster."
            ),
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner({0: "NONRECIPE_CANDIDATE"}),
        live_llm_allowed=True,
    )

    assert predictions[0].label == "NONRECIPE_CANDIDATE"
    assert predictions[0].decided_by == "codex"


def test_codex_outside_recipe_question_heading_demotes_knowledge_to_other(tmp_path) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:heat:1",
            block_index=1,
            atomic_index=0,
            text="What is Heat?",
            within_recipe_span=False,
            rule_tags=[],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner({0: "NONRECIPE_CANDIDATE"}),
        live_llm_allowed=True,
    )

    assert predictions[0].label == "NONRECIPE_CANDIDATE"
    assert predictions[0].decided_by == "codex"


def test_codex_outside_recipe_nonrecipe_exclude_without_support_stays_authoritative(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:knowledge:1",
            block_index=1,
            atomic_index=0,
            text=(
                "Salt enhances flavor by suppressing bitterness and amplifying aroma."
            ),
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        )
    ]

    def _output_builder(_payload):
        return {
            "rows": [
                {
                    "atomic_index": 0,
                    "label": "NONRECIPE_EXCLUDE",
                }
            ]
        }

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner(output_builder=_output_builder),
        live_llm_allowed=True,
    )

    assert predictions[0].label == "NONRECIPE_EXCLUDE"
    assert predictions[0].decided_by == "codex"
    assert "codex_policy_rejected" not in (
        predictions[0].reason_tags
    )


def test_codex_recipe_local_nonrecipe_exclude_falls_back_to_baseline(tmp_path) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:1",
            block_id="block:recipe:1",
            block_index=1,
            atomic_index=0,
            text="Whisk in the olive oil and season to taste.",
            within_recipe_span=True,
            rule_tags=["instruction_like"],
        )
    ]

    def _output_builder(_payload):
        return {
            "rows": [
                {
                    "atomic_index": 0,
                    "label": "NONRECIPE_EXCLUDE",
                }
            ]
        }

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner(output_builder=_output_builder),
        live_llm_allowed=True,
    )

    assert predictions[0].label == "INSTRUCTION_LINE"
    assert predictions[0].decided_by == "fallback"
    assert "codex_policy_rejected:nonrecipe_exclude_inside_recipe_not_allowed" in (
        predictions[0].reason_tags
    )


def test_codex_outside_recipe_nonrecipe_exclude_reason_mismatch_falls_back_to_baseline(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:endorsement:2",
            block_index=2,
            atomic_index=0,
            text="-Alice Waters , New York Times bestselling author of The Art of Simple Food",
            within_recipe_span=False,
            rule_tags=[],
        )
    ]

    def _output_builder(_payload):
        return {
            "rows": [
                {
                    "atomic_index": 0,
                    "label": "NONRECIPE_EXCLUDE",
                }
            ]
        }

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner(output_builder=_output_builder),
        live_llm_allowed=True,
    )

    assert predictions[0].label == "NONRECIPE_EXCLUDE"
    assert predictions[0].decided_by in {"codex", "fallback"}


def test_codex_outside_recipe_knowledge_heading_with_context_stays_reviewable_other(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:poaching:1",
            block_index=1,
            atomic_index=0,
            text="Coddling and Poaching",
            within_recipe_span=False,
            rule_tags=["title_like"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:poaching:2",
            block_index=2,
            atomic_index=1,
            text=(
                "Gentle cooking in water just below a simmer keeps delicate "
                "proteins tender and protects them from overcooking."
            ),
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        ),
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner(
            {0: "NONRECIPE_CANDIDATE", 1: "NONRECIPE_CANDIDATE"}
        ),
        live_llm_allowed=True,
    )

    assert [prediction.label for prediction in predictions] == [
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
    ]
    assert all(prediction.decided_by == "codex" for prediction in predictions)


def test_codex_outside_recipe_explicit_howto_heading_with_component_context_can_stay_structured(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:howto:outside:1",
            block_index=1,
            atomic_index=0,
            text="FOR THE SAUCE",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:howto:outside:2",
            block_index=2,
            atomic_index=1,
            text="2 tablespoons olive oil",
            within_recipe_span=False,
            rule_tags=["ingredient_like"],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner({0: "HOWTO_SECTION", 1: "INGREDIENT_LINE"}),
        live_llm_allowed=True,
    )

    assert predictions[0].label == "HOWTO_SECTION"
    assert predictions[0].decided_by == "codex"
    assert predictions[1].label == "INGREDIENT_LINE"


def test_codex_long_to_make_variant_paragraph_rejects_howto_to_baseline(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:variant",
            block_id="block:variant:codex:1",
            block_index=1,
            atomic_index=0,
            text=(
                "To make Brown Butter Vinaigrette for dressing bread salads or "
                "roasted vegetables, substitute 4 tablespoons brown butter for the "
                "olive oil and continue as above. Bring refrigerated leftovers back "
                "to room temperature before using."
            ),
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback", "explicit_prose"],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner({0: "HOWTO_SECTION"}),
        live_llm_allowed=True,
    )

    assert predictions[0].label == "HOWTO_SECTION"
    assert predictions[0].decided_by == "codex"


def test_codex_exact_caesar_make_step_rejects_variant_to_baseline(tmp_path) -> None:
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

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner(
            {
                1397: "NONRECIPE_CANDIDATE",
                1398: "NONRECIPE_CANDIDATE",
                1399: "RECIPE_VARIANT",
                1400: "RECIPE_NOTES",
                1401: "RECIPE_NOTES",
            }
        ),
        live_llm_allowed=True,
    )

    assert predictions[2].label == "RECIPE_VARIANT"
    assert predictions[2].decided_by == "codex"


def test_codex_exact_lesson_prose_other_rows_stay_reviewable_other(tmp_path) -> None:
    candidates = [
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

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner(
            {
                231: "NONRECIPE_CANDIDATE",
                232: "NONRECIPE_CANDIDATE",
                233: "NONRECIPE_CANDIDATE",
            }
        ),
        live_llm_allowed=True,
    )

    assert [prediction.label for prediction in predictions] == [
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
    ]


def test_codex_front_matter_title_list_keeps_codex_titles_when_output_is_valid(tmp_path) -> None:
    candidates = [
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

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner(
            {
                58: "NONRECIPE_EXCLUDE",
                59: "NONRECIPE_EXCLUDE",
                60: "RECIPE_TITLE",
                61: "RECIPE_TITLE",
                62: "RECIPE_TITLE",
            }
        ),
        live_llm_allowed=True,
    )

    assert [prediction.label for prediction in predictions] == [
        "NONRECIPE_EXCLUDE",
        "NONRECIPE_EXCLUDE",
        "RECIPE_TITLE",
        "RECIPE_TITLE",
        "RECIPE_TITLE",
    ]
    assert all(prediction.decided_by == "codex" for prediction in predictions)


def test_codex_how_salt_works_keeps_howto_authoritative(tmp_path) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:knowledge:heading:1",
            block_index=1,
            atomic_index=0,
            text="HOW SALT WORKS",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:knowledge:heading:2",
            block_index=2,
            atomic_index=1,
            text=(
                "Salt changes how food absorbs moisture and how aromas reach your "
                "nose, so small adjustments can reshape both texture and flavor."
            ),
            within_recipe_span=False,
            rule_tags=["outside_recipe_span", "explicit_prose"],
        ),
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner(
            {0: "HOWTO_SECTION", 1: "NONRECIPE_CANDIDATE"}
        ),
        live_llm_allowed=True,
    )

    assert predictions[0].label == "HOWTO_SECTION"
    assert predictions[0].decided_by == "codex"


def test_codex_outside_recipe_generic_advice_keeps_instruction_authoritative(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:advice:1",
            block_index=1,
            atomic_index=0,
            text=(
                "For tossed salads, place the greens in a large bowl and season lightly with salt."
            ),
            within_recipe_span=False,
            rule_tags=[],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner({0: "INSTRUCTION_LINE"}),
        live_llm_allowed=True,
    )

    assert predictions[0].label == "INSTRUCTION_LINE"
    assert predictions[0].decided_by == "codex"


def test_codex_exact_instruction_other_rows_stay_codex_other(tmp_path) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:1122",
            block_index=1122,
            atomic_index=1122,
            text="6 tablespoons extra-virgin olive oil",
            within_recipe_span=False,
            rule_tags=["ingredient_like", "outside_recipe_span"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:1123",
            block_index=1123,
            atomic_index=1123,
            text=(
                "Quarter the cabbage through the core. Use a sharp knife to cut "
                "the core out at an angle. Thinly slice the cabbage crosswise and "
                "place in a colander set inside a large salad bowl. Season with two "
                "generous pinches of salt to help draw out water, toss the slices, "
                "and set aside."
            ),
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:1124",
            block_index=1124,
            atomic_index=1124,
            text=(
                "In a small bowl, toss the sliced onion with the lemon juice and "
                "let it sit for 20 minutes to macerate (see page 118 ). Set aside."
            ),
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        ),
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner(
            {
                1122: "INGREDIENT_LINE",
                1123: "NONRECIPE_CANDIDATE",
                1124: "NONRECIPE_CANDIDATE",
            }
        ),
        live_llm_allowed=True,
    )

    assert [prediction.label for prediction in predictions] == [
        "INGREDIENT_LINE",
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
    ]
    assert predictions[1].decided_by == "codex"
    assert predictions[2].decided_by == "codex"
    assert "rescued_other_to_instruction" not in predictions[1].reason_tags
    assert "rescued_other_to_instruction" not in predictions[2].reason_tags


def test_codex_exact_variations_other_rows_stay_codex_other(tmp_path) -> None:
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

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner(
            {
                1378: "NONRECIPE_CANDIDATE",
                1379: "NONRECIPE_CANDIDATE",
                1380: "NONRECIPE_CANDIDATE",
            }
        ),
        live_llm_allowed=True,
    )

    assert [prediction.label for prediction in predictions] == [
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
        "NONRECIPE_CANDIDATE",
    ]
    assert all(prediction.decided_by == "codex" for prediction in predictions)
    assert all(
        "rescued_other_to_variant" not in prediction.reason_tags
        for prediction in predictions
    )
